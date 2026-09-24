"""Tests for the assistant's turn loop, driven by a scripted model.

No network, no credentials, no tokens spent: FakeModelClient returns whatever
the test scripts, which is what makes the loop's guarantees — the cap, the
refund, the accounting, the permission binding — testable at all.
"""

import json

import pytest

from assistant.llm import ModelTurn, ToolCall, VertexModelClient
from assistant.models import AssistantSettings, AssistantUsage, current_period
from assistant.prompt import MAX_MESSAGE_CHARS
from assistant.quota import messages_used
from assistant.testing import FailingModelClient, FakeModelClient
from gift.models import FeatureFlag, Item
from giftwiki.feature_flags import _clear_cache

MESSAGE_URL = '/assistant/message/'


@pytest.fixture
def assistant_on(db):
    FeatureFlag.objects.update_or_create(name='ASSISTANT_ENABLED', defaults={'enabled': True})
    _clear_cache()
    yield
    _clear_cache()


def say(client, *texts):
    payload = {'messages': [{'role': 'user', 'text': text} for text in texts]}
    return client.post(MESSAGE_URL, data=json.dumps(payload), content_type='application/json')


@pytest.mark.unit
class TestTheGate:
    def test_anonymous_is_turned_away(self, client, db):
        response = say(client, 'hello')

        assert response.status_code in (302, 403)

    def test_closed_feature_returns_the_reason_and_spends_nothing(
        self, authenticated_user, user, db, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='should not run')])
        _clear_cache()

        response = say(authenticated_user, 'hello')

        assert response.status_code == 403
        assert response.json()['reason'] == 'disabled'
        assert settings.ASSISTANT_MODEL_CLIENT.calls == []
        assert messages_used(user) == 0

    def test_get_is_not_allowed(self, authenticated_user, assistant_on):
        assert authenticated_user.get(MESSAGE_URL).status_code == 405


@pytest.mark.unit
class TestAPlainTurn:
    def test_returns_the_reply_and_what_is_left(
        self, authenticated_user, user, assistant_on, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient(
            [ModelTurn(text='You have one list.', input_tokens=30, output_tokens=6)]
        )
        AssistantSettings.objects.update_or_create(pk=1, defaults={'per_user_monthly_messages': 10})

        response = say(authenticated_user, 'what lists are there?')

        assert response.status_code == 200
        assert response.json()['reply'] == 'You have one list.'
        assert response.json()['messages_left'] == 9

    def test_tokens_are_recorded(self, authenticated_user, user, assistant_on, settings):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient(
            [ModelTurn(text='Hi', input_tokens=30, output_tokens=6)]
        )

        say(authenticated_user, 'hello')

        usage = AssistantUsage.objects.get(user=user, period=current_period())
        assert usage.message_count == 1
        assert usage.input_tokens == 30
        assert usage.output_tokens == 6

    def test_history_is_truncated_to_twenty_turns(
        self, authenticated_user, assistant_on, settings
    ):
        fake = FakeModelClient([ModelTurn(text='ok')])
        settings.ASSISTANT_MODEL_CLIENT = fake

        say(authenticated_user, *[f'message {n}' for n in range(30)])

        assert len(fake.calls[0]['contents']) == 20
        assert fake.calls[0]['contents'][0]['parts'][0]['text'] == 'message 10'

    def test_messages_are_truncated_to_the_character_cap(
        self, authenticated_user, assistant_on, settings
    ):
        """The other half of 'a forged history cannot replay something
        enormous': deleting the [:MAX_MESSAGE_CHARS] slice in build_contents
        wouldn't break the twenty-turn test above, so it needs its own."""
        fake = FakeModelClient([ModelTurn(text='ok')])
        settings.ASSISTANT_MODEL_CLIENT = fake

        say(authenticated_user, 'x' * (MAX_MESSAGE_CHARS + 500))

        assert len(fake.calls[0]['contents'][0]['parts'][0]['text']) == MAX_MESSAGE_CHARS

    def test_the_roster_is_in_the_system_instructions(
        self, authenticated_user, assistant_on, wishlist, settings
    ):
        fake = FakeModelClient([ModelTurn(text='ok')])
        settings.ASSISTANT_MODEL_CLIENT = fake

        say(authenticated_user, 'hello')

        assert 'Test Wishlist' in fake.calls[0]['system_instructions']

    def test_no_items_are_in_the_system_instructions(
        self, authenticated_user, assistant_on, wishlist, item, settings
    ):
        """The roster is names and people. Item detail stays behind the tools,
        where it is fresh and filtered."""
        fake = FakeModelClient([ModelTurn(text='ok')])
        settings.ASSISTANT_MODEL_CLIENT = fake

        say(authenticated_user, 'hello')

        assert 'Test Item' not in fake.calls[0]['system_instructions']


@pytest.mark.unit
class TestToolCycle:
    def test_a_tool_call_runs_and_the_result_comes_back(
        self, authenticated_user, user, wishlist, assistant_on, settings
    ):
        fake = FakeModelClient(
            [
                ModelTurn(tool_calls=(ToolCall('list_wishlists', {}),), input_tokens=20),
                ModelTurn(text='There is one list.', output_tokens=5),
            ]
        )
        settings.ASSISTANT_MODEL_CLIENT = fake

        response = say(authenticated_user, 'what lists are there?')

        assert response.json()['reply'] == 'There is one list.'
        second_call = fake.calls[1]['contents']
        assert second_call[-1]['parts'][0]['function_response']['name'] == 'list_wishlists'

    def test_tools_act_as_the_signed_in_user(
        self, authenticated_other_user, other_user, wishlist, assistant_on, settings
    ):
        """other_user is not owner-side on this list, so what they add is a
        surprise — decided from the session, never from anything the model said."""
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient(
            [
                ModelTurn(
                    tool_calls=(
                        ToolCall('add_item', {'wishlist_id': wishlist.id, 'name': 'Secret Kite'}),
                    )
                ),
                ModelTurn(text='Added it as a surprise.'),
            ]
        )

        say(authenticated_other_user, 'add a kite to that list')

        item = Item.objects.get(name='Secret Kite')
        assert item.is_sneaky is True
        assert item.added_by == other_user

    def test_tokens_accumulate_across_tool_iterations(
        self, authenticated_user, user, wishlist, assistant_on, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient(
            [
                ModelTurn(tool_calls=(ToolCall('list_wishlists', {}),), input_tokens=20, output_tokens=4),
                ModelTurn(text='Done.', input_tokens=35, output_tokens=7),
            ]
        )

        say(authenticated_user, 'hello')

        usage = AssistantUsage.objects.get(user=user, period=current_period())
        assert usage.input_tokens == 55
        assert usage.output_tokens == 11
        assert usage.message_count == 1, 'one user message is one message, however many calls'

    def test_the_iteration_cap_holds(self, authenticated_user, wishlist, assistant_on, settings):
        """Without a cap the cost of one 'message' is unbounded, which silently
        defeats the metering. The capped-out iteration also must not execute
        its tool call: there is no model call left to receive the result, so
        for a write like add_item that would be a real, unreported side
        effect — and asking again afterwards would risk a duplicate."""
        turns = [
            ModelTurn(text='thinking', tool_calls=(ToolCall('list_wishlists', {}),))
            for _ in range(4)
        ]
        turns.append(
            ModelTurn(
                text='thinking',
                tool_calls=(
                    ToolCall('add_item', {'wishlist_id': wishlist.id, 'name': 'Cap Kite'}),
                ),
            )
        )
        fake = FakeModelClient(turns)
        settings.ASSISTANT_MODEL_CLIENT = fake

        response = say(authenticated_user, 'loop forever')

        assert response.status_code == 200
        assert len(fake.calls) == 5
        assert response.json()['reply'] == 'thinking', 'return what it last said, not an error'
        assert not Item.objects.filter(name='Cap Kite').exists(), (
            'the call the cap cuts off must not run its tool'
        )

    def test_a_tool_error_is_fed_back_rather_than_ending_the_turn(
        self, authenticated_user, assistant_on, settings
    ):
        fake = FakeModelClient(
            [
                ModelTurn(tool_calls=(ToolCall('get_wishlist', {'wishlist_id': 999999}),)),
                ModelTurn(text="I couldn't find that list."),
            ]
        )
        settings.ASSISTANT_MODEL_CLIENT = fake

        response = say(authenticated_user, 'show me list 999999')

        assert response.status_code == 200
        assert 'error' in fake.calls[1]['contents'][-1]['parts'][0]['function_response']['response']

    def test_a_list_result_is_wrapped_in_a_dict_for_the_vendor_payload(
        self, authenticated_user, wishlist, assistant_on, settings
    ):
        """list_wishlists returns a bare list — the Vertex SDK types
        FunctionResponse.response as a dict, so a non-dict tool result must be
        wrapped before it goes into the part. Nothing else about the tool's
        Python-facing return value should change."""
        fake = FakeModelClient(
            [
                ModelTurn(tool_calls=(ToolCall('list_wishlists', {}),)),
                ModelTurn(text='There is one list.'),
            ]
        )
        settings.ASSISTANT_MODEL_CLIENT = fake

        say(authenticated_user, 'what lists are there?')

        response_payload = fake.calls[1]['contents'][-1]['parts'][0]['function_response']['response']
        assert isinstance(response_payload, dict)
        assert isinstance(response_payload['result'], list)
        assert response_payload['result'][0]['title'] == 'Test Wishlist'


@pytest.mark.unit
class TestFailureAndCaps:
    def test_a_failed_call_refunds_the_message(
        self, authenticated_user, user, assistant_on, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FailingModelClient()

        response = say(authenticated_user, 'hello')

        assert response.status_code == 503
        assert messages_used(user) == 0

    def test_a_vertex_client_construction_failure_becomes_a_friendly_503(
        self, authenticated_user, user, assistant_on, settings, monkeypatch
    ):
        """VertexModelClient.generate() used to build genai.Client(...) and
        GenerateContentConfig(...) *outside* its own try — only the
        generate_content() call itself was wrapped, so a credentials or
        configuration failure during construction propagated raw instead of
        becoming ModelUnavailable. This drives the real VertexModelClient
        (not a fake) with genai.Client() patched to blow up on construction,
        and pins that the endpoint still returns the spec's friendly 503
        with the reservation refunded — not a bare 500."""
        from google import genai

        def exploding_client(*args, **kwargs):
            raise RuntimeError('could not build a credentialed client')

        monkeypatch.setattr(genai, 'Client', exploding_client)
        settings.ASSISTANT_MODEL_CLIENT = VertexModelClient(
            project='test-project', location='us-central1', model_name='gemini-test'
        )

        response = say(authenticated_user, 'hello')

        assert response.status_code == 503
        assert messages_used(user) == 0

    def test_a_non_model_unavailable_failure_still_refunds_the_message(
        self, authenticated_user, user, assistant_on, settings
    ):
        """ModelUnavailable isn't the only way this can fail: VertexModelClient
        builds its genai.Client() outside its own try, and a tool's DB
        reconnect after connection.close() can raise OperationalError — this
        repo's documented failure mode (#12, #95). Neither is caught by the
        ModelUnavailable handler, so the refund can't depend on which
        exception it was."""

        class ExplodingModelClient:
            def generate(self, **kwargs):
                raise RuntimeError('credentials exploded')

        settings.ASSISTANT_MODEL_CLIENT = ExplodingModelClient()

        with pytest.raises(RuntimeError):
            say(authenticated_user, 'hello')

        assert messages_used(user) == 0

    def test_a_prompt_assembly_failure_still_refunds_the_message(
        self, authenticated_user, user, assistant_on, settings, monkeypatch
    ):
        """roster_for() queries the database before the model is ever called —
        it is exposed to the same reconnect failure as anything inside the
        loop, so it has to be inside the same guarded region. The reservation
        can't depend on which side of the model call the failure happened."""
        from assistant import views as assistant_views

        def exploding_roster_for(user):
            raise RuntimeError('reconnect exploded')

        monkeypatch.setattr(assistant_views, 'roster_for', exploding_roster_for)
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='should not run')])

        with pytest.raises(RuntimeError):
            say(authenticated_user, 'hello')

        assert messages_used(user) == 0

    def test_the_personal_cap_closes_the_door(
        self, authenticated_user, user, assistant_on, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='should not run')])
        AssistantSettings.objects.update_or_create(pk=1, defaults={'per_user_monthly_messages': 1})
        AssistantUsage.objects.create(user=user, period=current_period(), message_count=1)

        response = say(authenticated_user, 'one more')

        assert response.status_code == 403
        assert response.json()['reason'] == 'user_cap'
        assert settings.ASSISTANT_MODEL_CLIENT.calls == []

    def test_an_empty_conversation_is_rejected_without_spending(
        self, authenticated_user, user, assistant_on, settings
    ):
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='should not run')])

        response = authenticated_user.post(
            MESSAGE_URL, data=json.dumps({'messages': []}), content_type='application/json'
        )

        assert response.status_code == 400
        assert messages_used(user) == 0

    def test_malformed_json_is_rejected(self, authenticated_user, assistant_on):
        response = authenticated_user.post(
            MESSAGE_URL, data='{not json', content_type='application/json'
        )

        assert response.status_code == 400


@pytest.mark.unit
class TestGlobalBudgetAlert:
    """The passive 80%-of-ceiling alert: a warning the app logs on the way out
    of an ordinary turn, never a probe. terraform/monitoring.tf's log-based
    metric matches this exact message string, so the two must stay in sync —
    this pins the string the code actually emits."""

    def test_logs_a_warning_at_80_percent_of_the_global_ceiling(
        self, authenticated_user, user, other_user, assistant_on, settings, caplog
    ):
        AssistantSettings.objects.update_or_create(pk=1, defaults={'global_monthly_messages': 10})
        AssistantUsage.objects.create(user=other_user, period=current_period(), message_count=7)
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='ok')])

        with caplog.at_level('WARNING', logger='assistant.views'):
            say(authenticated_user, 'hello')

        assert 'Assistant global budget at 80%' in caplog.text

    def test_does_not_log_below_80_percent(
        self, authenticated_user, user, assistant_on, settings, caplog
    ):
        AssistantSettings.objects.update_or_create(
            pk=1, defaults={'global_monthly_messages': 100}
        )
        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([ModelTurn(text='ok')])

        with caplog.at_level('WARNING', logger='assistant.views'):
            say(authenticated_user, 'hello')

        assert 'Assistant global budget at 80%' not in caplog.text
