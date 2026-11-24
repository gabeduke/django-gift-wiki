"""Tests for middleware that runs early in the request chain (no auth required)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db.utils import OperationalError
from django.http import HttpResponseServerError

User = get_user_model()

OPS_TOKEN = 'test-ops-token'
GATED_PATHS = ['/health/db/', '/metrics', '/metrics/']


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.mark.unit
class TestHealthCheckMiddleware:
    def test_health_endpoint_returns_200_unauthenticated(self, client, db):
        response = client.get('/health/')
        assert response.status_code == 200
        assert response.content == b'ok'

    def test_health_endpoint_does_not_query_the_database(
        self, client, db, django_assert_num_queries
    ):
        """Liveness must not touch the DB.

        Every probe hit was running `SELECT 1`, which resets Neon's autosuspend
        timer and pins the compute awake 24/7.
        """
        with django_assert_num_queries(0):
            response = client.get('/health/')

        assert response.status_code == 200
        assert response.content == b'ok'

    def test_health_endpoint_stays_up_when_database_is_unreachable(self, client):
        """A dead DB means degraded, not dead. Liveness must still report ok."""
        with patch(
            'gift.middleware.healthcheck.connections.__getitem__',
            side_effect=OperationalError('could not connect to server'),
        ):
            response = client.get('/health/')

        assert response.status_code == 200
        assert response.content == b'ok'

    def test_health_endpoint_stays_public_when_an_ops_token_is_set(
        self, client, db, settings, django_assert_num_queries
    ):
        """Probes carry no token. Gating the DB check must not gate liveness."""
        settings.OPS_TOKEN = OPS_TOKEN

        with django_assert_num_queries(0):
            response = client.get('/health/')

        assert response.status_code == 200
        assert response.content == b'ok'


@pytest.mark.unit
class TestOperatorOnlyEndpoints:
    """`/health/db/` and `/metrics` are answered before authentication (#130).

    A public `/health/db/` lets anyone run a query and reset Neon's autosuspend
    timer, burning the free plan's compute allowance; `/metrics` leaks paths and
    usage patterns. Refusals must be a 404 that runs no query at all.
    """

    @pytest.mark.parametrize('path', GATED_PATHS)
    def test_anonymous_request_is_404_without_touching_the_database(
        self, client, db, settings, django_assert_num_queries, path
    ):
        settings.OPS_TOKEN = ''

        with django_assert_num_queries(0):
            response = client.get(path)

        assert response.status_code == 404

    @pytest.mark.parametrize('path', GATED_PATHS)
    def test_missing_token_is_404_without_touching_the_database(
        self, client, db, settings, django_assert_num_queries, path
    ):
        settings.OPS_TOKEN = OPS_TOKEN

        with django_assert_num_queries(0):
            response = client.get(path)

        assert response.status_code == 404

    @pytest.mark.parametrize('path', GATED_PATHS)
    @pytest.mark.parametrize(
        'authorization',
        [
            'Bearer wrong-token',
            f'Bearer {OPS_TOKEN}x',
            f'Basic {OPS_TOKEN}',
            OPS_TOKEN,
            'Bearer ',
        ],
    )
    def test_wrong_token_is_404_without_touching_the_database(
        self, client, db, settings, django_assert_num_queries, path, authorization
    ):
        settings.OPS_TOKEN = OPS_TOKEN

        with django_assert_num_queries(0):
            response = client.get(path, headers={'Authorization': authorization})

        assert response.status_code == 404

    @pytest.mark.parametrize('path', GATED_PATHS)
    def test_token_is_enforced_even_under_debug(self, client, db, settings, path):
        settings.DEBUG = True
        settings.OPS_TOKEN = OPS_TOKEN

        assert client.get(path).status_code == 404

    def test_db_check_with_the_token_runs_one_query(
        self, client, db, settings, django_assert_num_queries
    ):
        settings.OPS_TOKEN = OPS_TOKEN

        with django_assert_num_queries(1):
            response = client.get('/health/db/', headers=bearer(OPS_TOKEN))

        assert response.status_code == 200
        assert response.content == b'ok'

    def test_db_check_with_the_token_reports_an_unreachable_database(self, client, settings):
        settings.OPS_TOKEN = OPS_TOKEN

        with patch(
            'gift.middleware.healthcheck.connections.__getitem__',
            side_effect=OperationalError('could not connect to server'),
        ):
            response = client.get('/health/db/', headers=bearer(OPS_TOKEN))

        assert response.status_code == 500
        assert b'Database check failed' in response.content

    @pytest.mark.parametrize('path', ['/metrics', '/metrics/'])
    def test_metrics_with_the_token(self, client, settings, path):
        settings.OPS_TOKEN = OPS_TOKEN

        response = client.get(path, headers=bearer(OPS_TOKEN))

        assert response.status_code == 200
        assert 'text/plain' in response['Content-Type']

    def test_bearer_scheme_is_case_insensitive(self, client, settings):
        settings.OPS_TOKEN = OPS_TOKEN

        response = client.get('/metrics', headers={'Authorization': f'bearer {OPS_TOKEN}'})

        assert response.status_code == 200

    def test_open_under_debug_when_no_token_is_configured(self, client, db, settings):
        """Local development needs no token."""
        settings.DEBUG = True
        settings.OPS_TOKEN = ''

        assert client.get('/health/db/').status_code == 200
        assert client.get('/metrics').status_code == 200


@pytest.mark.unit
class TestFirebaseAuthAllowlist:
    def test_disallowed_email_returns_403(self, client, db):
        """A verified Firebase email that is not in the allowlist gets 403."""
        with patch(
            'gift.middleware.firebase_auth.FirebaseAuthBackend.verified_email',
            return_value='denied@example.com',
        ):
            client.cookies['__session'] = 'fake-session-cookie'
            response = client.get('/')

        assert response.status_code == 403
        assert b'not authorized' in response.content


@pytest.mark.unit
class TestFirebaseUserResolution:
    """Resolving a verified Firebase email onto a Django account.

    Matters for managed (child) accounts: a parent assigns `ellie` the address
    ellie.duke@gmail.com, and the derived username `ellie.duke` may already
    belong to somebody else.
    """

    def test_resolves_an_existing_account_by_email(self, db):
        from gift.middleware.firebase_auth import resolve_user_for_email

        kid = User.objects.create_user(username='ellie', email='ellie.duke@gmail.com')

        assert resolve_user_for_email('ellie.duke@gmail.com') == kid

    def test_keeps_the_username_when_the_email_prefix_belongs_to_someone_else(self, db):
        """Renaming into a taken username raised IntegrityError and killed the login."""
        from gift.middleware.firebase_auth import resolve_user_for_email

        User.objects.create_user(username='ellie.duke', email='mom@example.com')
        kid = User.objects.create_user(username='ellie', email='ellie.duke@gmail.com')

        resolved = resolve_user_for_email('ellie.duke@gmail.com')

        assert resolved == kid
        kid.refresh_from_db()
        assert kid.username == 'ellie'

    def test_still_freshens_the_username_when_the_prefix_is_free(self, db):
        from gift.middleware.firebase_auth import resolve_user_for_email

        user = User.objects.create_user(username='old-handle', email='ellie.duke@gmail.com')

        resolve_user_for_email('ellie.duke@gmail.com')

        user.refresh_from_db()
        assert user.username == 'ellie.duke'


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
