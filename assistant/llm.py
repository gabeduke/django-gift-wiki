"""The only module that knows which model vendor this is.

Everything else — the turn loop, the tools, the tests — talks to the generate()
protocol below and the neutral content shape it takes. That seam is what lets
the whole feature be tested without a network, and what would make swapping
vendors a one-file change.

Content shape, mirroring Gemini closely enough that the adapter is a 1:1
translation:

    {'role': 'user' | 'model', 'parts': [
        {'text': '...'},
        {'function_call': {'name': '...', 'args': {...}}},
        {'function_response': {'name': '...', 'response': {...}}},
    ]}
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

MODEL_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTurn:
    text: str = ''
    tool_calls: tuple = ()
    input_tokens: int = 0
    output_tokens: int = 0


class ModelUnavailable(RuntimeError):
    """The model could not be reached or refused to answer."""


class VertexModelClient:
    """Adapter over the Google Gen AI SDK, talking to Vertex AI.

    Authenticates with Application Default Credentials — on Cloud Run that is
    the compute service account, locally it is `gcloud auth application-default
    login`. No API key is managed anywhere.
    """

    def __init__(self, *, project, location, model_name, timeout_seconds=MODEL_TIMEOUT_SECONDS):
        self.project = project
        self.location = location
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def generate(self, *, system_instructions, contents, tool_declarations):
        from google import genai
        from google.genai import types

        try:
            client = genai.Client(vertexai=True, project=self.project, location=self.location)
            config = types.GenerateContentConfig(
                system_instruction=system_instructions,
                tools=[types.Tool(function_declarations=tool_declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                safety_settings=self._safety_settings(types),
                http_options=types.HttpOptions(timeout=self.timeout_seconds * 1000),
            )
            response = client.models.generate_content(
                model=self.model_name, contents=contents, config=config
            )
        except Exception as exc:
            # Log the exception's type only, never str(exc): a Vertex
            # validation error can echo the request content back in its
            # message, and that message is `contents` — conversation text,
            # which must never reach a log line. The full exception still
            # travels in ModelUnavailable's own argument, where nothing
            # persists it.
            logger.warning('Assistant model call failed', extra={'error_type': type(exc).__name__})
            raise ModelUnavailable(str(exc)) from exc

        return self._to_turn(response)

    def _safety_settings(self, types):
        """Set explicitly rather than left at defaults — the audience is children."""
        categories = (
            'HARM_CATEGORY_HATE_SPEECH',
            'HARM_CATEGORY_DANGEROUS_CONTENT',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT',
            'HARM_CATEGORY_HARASSMENT',
        )
        return [
            types.SafetySetting(category=category, threshold='BLOCK_MEDIUM_AND_ABOVE')
            for category in categories
        ]

    def _to_turn(self, response):
        text_parts = []
        tool_calls = []
        for candidate in response.candidates or []:
            for part in (candidate.content.parts or []) if candidate.content else []:
                if getattr(part, 'function_call', None):
                    tool_calls.append(
                        ToolCall(
                            name=part.function_call.name,
                            arguments=dict(part.function_call.args or {}),
                        )
                    )
                elif getattr(part, 'text', None):
                    text_parts.append(part.text)

        usage = getattr(response, 'usage_metadata', None)
        return ModelTurn(
            text=''.join(text_parts),
            tool_calls=tuple(tool_calls),
            input_tokens=getattr(usage, 'prompt_token_count', 0) or 0,
            output_tokens=getattr(usage, 'candidates_token_count', 0) or 0,
        )


def get_model_client():
    """The client the turn loop should use.

    `settings.ASSISTANT_MODEL_CLIENT` short-circuits this — tests set it to a
    FakeModelClient instance so nothing reaches a network.
    """
    override = getattr(django_settings, 'ASSISTANT_MODEL_CLIENT', None)
    if override is not None:
        return import_string(override)() if isinstance(override, str) else override

    from assistant.models import AssistantSettings

    return VertexModelClient(
        project=django_settings.ASSISTANT_VERTEX_PROJECT,
        location=django_settings.ASSISTANT_VERTEX_LOCATION,
        model_name=AssistantSettings.load().model_name,
    )
