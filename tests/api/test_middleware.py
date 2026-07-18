"""Tests for middleware that runs early in the request chain (no auth required)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponseServerError

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


@pytest.mark.unit
class TestErrorLoggingMiddleware:
    """Tests for the error logging middleware."""

    def test_logs_unhandled_exception(self, client, settings):
        """The middleware logs unhandled exceptions with request context."""
        from gift.middleware.error_logging import ErrorLoggingMiddleware

        def exploding_view(request):
            raise RuntimeError('boom')

        middleware = ErrorLoggingMiddleware(lambda request: exploding_view(request))

        with patch(
            'gift.middleware.error_logging.logger'
        ) as mock_logger:
            with pytest.raises(RuntimeError):
                middleware(client.get('/').wsgi_request)

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        # args = (format_string, method, path, exc_type, exc_message)
        assert call_args.args[3] == 'RuntimeError'
        assert call_args.args[4] == 'boom'
        assert call_args.kwargs['exc_info'] is True
        assert call_args.kwargs['extra']['request_path'] == '/'

    def test_logs_explicit_500_response(self, client, settings):
        """The middleware logs 500 responses returned without an exception."""
        from gift.middleware.error_logging import ErrorLoggingMiddleware

        def failing_view(request):
            return HttpResponseServerError('server error')

        middleware = ErrorLoggingMiddleware(lambda request: failing_view(request))

        with patch(
            'gift.middleware.error_logging.logger'
        ) as mock_logger:
            response = middleware(client.get('/').wsgi_request)

        assert response.status_code == 500
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert call_args.kwargs['extra']['status_code'] == 500
        assert call_args.kwargs['extra']['request_path'] == '/'
