"""BDD step definitions for allowlist.feature.

The Firebase middleware decides allow/deny based on the email returned by
``FirebaseAuthBackend.authenticate``. These tests mock that method so we
don't need a real Firebase session cookie. The conftest-level
``DJANGO_ALLOWED_USERS`` = ``test@example.com,other@example.com`` is the
allowlist used by the already-initialized middleware instance.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from pytest_bdd import given, parsers, scenarios, then, when

pytestmark = pytest.mark.bdd

scenarios(str(Path(__file__).parent.parent / 'features' / 'allowlist.feature'))


@given(parsers.parse('a Firebase session for email "{email}"'), target_fixture='session_email')
def session_email(email):
    return email


@when('the user requests the home page', target_fixture='response')
def request_home(db, monkeypatch, session_email):
    mock_user = MagicMock()
    mock_user.email = session_email
    mock_user.username = session_email.split('@')[0]
    mock_user.is_authenticated = True

    from gift.middleware import firebase_auth

    monkeypatch.setattr(
        firebase_auth.FirebaseAuthBackend,
        'authenticate',
        lambda self, request: mock_user,
    )

    client = Client()
    client.cookies['__session'] = 'dummy-session-cookie'
    return client.get('/')


@then(parsers.parse('the response status is {status:d}'))
def assert_status(response, status):
    assert response.status_code == status


@given('DJANGO_ALLOWED_USERS is unset')
def unset_allowlist(monkeypatch):
    monkeypatch.setenv('DJANGO_ALLOWED_USERS', '')


@when('the Firebase auth middleware is constructed', target_fixture='construction_error')
def construct_middleware():
    from gift.middleware.firebase_auth import FirebaseAuthMiddleware

    try:
        FirebaseAuthMiddleware(lambda request: None)
    except ImproperlyConfigured as exc:
        return exc
    return None


@then('it raises ImproperlyConfigured')
def assert_improperly_configured(construction_error):
    assert isinstance(construction_error, ImproperlyConfigured)
