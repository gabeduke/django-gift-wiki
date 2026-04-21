"""Tests for middleware that runs early in the request chain (no auth required)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.unit
class TestHealthCheckMiddleware:
    def test_health_endpoint_returns_200_unauthenticated(self, client, db):
        response = client.get('/health/')
        assert response.status_code == 200
        assert response.content == b'ok'


@pytest.mark.unit
class TestMetricsMiddleware:
    def test_metrics_endpoint_returns_200_unauthenticated(self, client):
        response = client.get('/metrics')
        assert response.status_code == 200
        assert 'text/plain' in response['Content-Type']

    def test_metrics_endpoint_with_trailing_slash_returns_200(self, client):
        response = client.get('/metrics/')
        assert response.status_code == 200
        assert 'text/plain' in response['Content-Type']


@pytest.mark.unit
class TestFirebaseAuthAllowlist:
    def test_disallowed_email_returns_403(self, client, db):
        """A successfully-authenticated user whose email is not in the allowlist gets 403."""
        denied_user = User.objects.create_user(username='denied', email='denied@example.com')

        with patch(
            'gift.middleware.firebase_auth.FirebaseAuthBackend.authenticate',
            return_value=denied_user,
        ):
            client.cookies['__session'] = 'fake-session-cookie'
            response = client.get('/')

        assert response.status_code == 403
        assert b'not authorized' in response.content
