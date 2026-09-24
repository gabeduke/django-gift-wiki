"""The assistant's one endpoint: a synchronous turn on a WSGI worker.

Streaming would need ASGI, which is this project's biggest risk bought for its
smallest payoff on exchanges lasting about two seconds. So the worker is held
for the duration of the call — which is exactly why the DB connection is not.
"""

import json
import logging
import time

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from assistant.easter_eggs import detect, record_find
from assistant.gating import CAP_MESSAGE, assistant_available_for
from assistant.llm import ModelUnavailable, get_model_client
from assistant.models import AssistantSettings
from assistant.prompt import build_contents, celebration_for, roster_for, system_instructions
from assistant.quota import global_messages_used, record_tokens, refund_message, reserve_message
from assistant.tools import TOOL_DECLARATIONS, run_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
TURN_BUDGET_SECONDS = 60
BUSY_MESSAGE = "I couldn't reach my brain just then — try that again in a moment."
LOST_MESSAGE = 'I got a bit lost there. Ask me again?'


@require_POST
@login_required
def message(request):
    availability = assistant_available_for(request.user)
    if not availability.available:
        return JsonResponse(
            {
                'available': False,
                'reason': availability.reason,
                'message': availability.message,
            },
            status=403,
        )

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Malformed request.'}, status=400)
    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
        return JsonResponse({'error': 'Malformed request.'}, status=400)

    contents = build_contents(data['messages'])
    if not contents:
        return JsonResponse({'error': 'Say something first.'}, status=400)

    config = AssistantSettings.load()

    # Reserved before the call it pays for, with an atomic increment, so two
    # tabs can't both slip under the cap. Checked after, which is what makes it
    # race-free; refunded below if the call never happens.
    used = reserve_message(request.user)
    if (
        used > config.per_user_monthly_messages
        or global_messages_used() > config.global_monthly_messages
    ):
        refund_message(request.user)
        closed = assistant_available_for(request.user)
        return JsonResponse(
            {
                'available': False,
                'reason': closed.reason or 'user_cap',
                'message': closed.message or CAP_MESSAGE,
            },
            status=403,
        )

    deadline = time.monotonic() + TURN_BUDGET_SECONDS
    input_tokens = 0
    output_tokens = 0
    reply = ''

    try:
        # Assembling the prompt is not free: roster_for() queries the
        # database, and that query is exactly as exposed to a reconnect
        # failure as anything inside the loop below. It has to be inside the
        # same guarded region as the model call it precedes, or a failure
        # here leaks the reservation just as the loop's own failures would
        # without the handler below.
        # Detection runs beside the turn, never inside it: finding an egg changes
        # what the assistant *says*, and nothing at all about what the tools return.
        latest = next((part for part in reversed(contents) if part['role'] == 'user'), None)
        egg = detect(latest['parts'][0].get('text', '') if latest else '')
        celebration = None
        if egg is not None and record_find(request.user, egg):
            celebration = celebration_for(request.user, egg)
            logger.info(
                'Easter egg found', extra={'user': request.user.email, 'egg': egg.slug}
            )

        instructions = system_instructions(request.user, roster_for(request.user), celebration)
        client = get_model_client()

        for iteration in range(MAX_TOOL_ITERATIONS):
            # Never hold a Neon connection across the model call: this is the
            # longest thing the app ever does inside a request, and a held
            # connection across it is the shape that produces a mid-request SSL
            # drop (issues #12, #95). Django reopens lazily on the next query.
            connection.close()

            turn = client.generate(
                system_instructions=instructions,
                contents=contents,
                tool_declarations=TOOL_DECLARATIONS,
            )
            input_tokens += turn.input_tokens
            output_tokens += turn.output_tokens
            if turn.text:
                reply = turn.text
            if not turn.tool_calls:
                break
            if iteration == MAX_TOOL_ITERATIONS - 1:
                # This is the last call the cap allows, so there is no model
                # call left to receive a tool result. Running the tool here
                # anyway would be a side effect nobody is told about — for a
                # write like add_item, a real, silent database change.
                break

            contents.append(
                {
                    'role': 'model',
                    'parts': [
                        {'function_call': {'name': call.name, 'args': call.arguments}}
                        for call in turn.tool_calls
                    ],
                }
            )
            contents.append(
                {
                    'role': 'user',
                    'parts': [
                        {
                            'function_response': {
                                'name': call.name,
                                # user is bound here, from the session. Nothing
                                # the model said has any say in whose data this is.
                                'response': _as_response_payload(
                                    run_tool(request.user, call.name, call.arguments)
                                ),
                            }
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
            if time.monotonic() > deadline:
                logger.warning('Assistant turn exceeded its budget', extra={'user': request.user.email})
                break
    except ModelUnavailable:
        refund_message(request.user)
        return JsonResponse({'error': BUSY_MESSAGE}, status=503)
    except Exception:
        # Not every failure path raises ModelUnavailable: VertexModelClient
        # builds its genai.Client() outside its own try, and a tool's DB
        # reconnect after connection.close() above can raise OperationalError
        # (this repo's documented failure mode, #12 and #95) — neither is
        # caught by the handler above. The reservation must not survive any
        # failure that keeps the user from getting an answer, whichever
        # exception carries it.
        refund_message(request.user)
        raise

    record_tokens(request.user, input_tokens, output_tokens)
    return JsonResponse(
        {
            'reply': reply or LOST_MESSAGE,
            'messages_left': max(0, config.per_user_monthly_messages - used),
        }
    )


def _as_response_payload(result):
    """Shape a tool's return value for `function_response.response`.

    The Vertex SDK types that field as a dict, but tools stay Pythonic for
    their Python callers — `list_wishlists` returns a bare list. This is the
    vendor boundary, so the wrapping happens here rather than in tools.py.

    The wrap is visible on the wire: `list_wishlists` reaches the model as
    `{'result': [...]}`, while every other tool's own dict — including the
    `{'error': ...}` shape run_tool() returns on failure — passes through
    unchanged. That asymmetry is deliberate, not an inconsistency to fix.
    """
    if not isinstance(result, dict):
        return {'result': result}
    return result
