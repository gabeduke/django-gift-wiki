"""The bubble renders exactly when the gate says it should, and never otherwise.

Hiding the UI is not the security control — the endpoint checks again — but a
bubble that is present and dead is worse than no bubble.
"""

import json

import pytest
from django.test import Client

from assistant.models import AssistantSettings, AssistantUsage, current_period
from gift.models import FeatureFlag
from giftwiki.feature_flags import _clear_cache


@pytest.fixture
def assistant_on(db):
    FeatureFlag.objects.update_or_create(name='ASSISTANT_ENABLED', defaults={'enabled': True})
    _clear_cache()
    yield
    _clear_cache()


@pytest.mark.unit
class TestBubbleVisibility:
    def test_absent_when_the_feature_is_off(self, authenticated_user, db):
        _clear_cache()

        assert b'wl-assistant' not in authenticated_user.get('/').content

    def test_present_when_the_feature_is_on(self, authenticated_user, assistant_on):
        assert b'wl-assistant' in authenticated_user.get('/').content

    def test_absent_for_anonymous_visitors(self, client, assistant_on):
        assert b'wl-assistant' not in client.get('/').content

    def test_absent_once_the_personal_cap_is_reached(self, authenticated_user, user, assistant_on):
        AssistantSettings.objects.update_or_create(pk=1, defaults={'per_user_monthly_messages': 1})
        AssistantUsage.objects.create(user=user, period=current_period(), message_count=1)

        assert b'wl-assistant' not in authenticated_user.get('/').content

    def test_present_on_a_wishlist_page_too(self, authenticated_user, wishlist, assistant_on):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')

        assert b'wl-assistant' in response.content


@pytest.mark.unit
class TestEndpointRequiresCsrf:
    """The bubble's fetch sends X-CSRFToken, but nothing in the JS suite can
    prove that (there's no JS test runner here) — this only pins the
    endpoint's own protection: `POST /assistant/message/` has no
    `@csrf_exempt`, so a request without a token must be rejected. Django's
    default test client does not enforce CSRF, so this needs a client built
    with `enforce_csrf_checks=True` or the whole suite would stay green even
    if the endpoint were wide open.
    """

    def test_a_request_without_a_csrf_token_is_rejected(self, user, assistant_on):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(user)

        response = strict_client.post(
            '/assistant/message/',
            data=json.dumps({'messages': [{'role': 'user', 'text': 'hello'}]}),
            content_type='application/json',
        )

        assert response.status_code == 403
