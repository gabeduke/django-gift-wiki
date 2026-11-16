"""Who a sign-in resolves to, and who is turned away before anything is written.

Each test here is a way one person could end up signed in as another, or a
kid could land in a fresh blank account that is no longer the `dependent` of
their own list — and so see purchases and surprise items meant to be hidden.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from gift.models import AllowedEmail, LinkedEmail

User = get_user_model()


def fake_firebase(email, *, email_verified=True, provider='google.com'):
    """A stand-in for firebase_admin.auth whose cookie check returns these claims."""
    firebase = MagicMock()
    firebase.InvalidSessionCookieError = type('InvalidSessionCookieError', (Exception,), {})
    claims = {
        'email': email,
        'email_verified': email_verified,
        'firebase': {'sign_in_provider': provider},
        'auth_time': 0,
        'iat': 0,
    }
    firebase.verify_session_cookie.return_value = claims
    firebase.verify_id_token.return_value = claims
    firebase.create_session_cookie.return_value = 'minted-cookie'
    return firebase


def get_with_cookie(client, firebase, path='/'):
    with patch('gift.middleware.firebase_auth._get_firebase_auth', return_value=firebase):
        client.cookies['__session'] = 'fake-session-cookie'
        return client.get(path)


@pytest.mark.unit
class TestUsernamePrefixNeverAdoptsAnAccount:
    def test_a_different_address_with_the_same_prefix_is_a_different_person(self, db):
        """smith@yahoo.com is not the smith@gmail.com who is already here."""
        from gift.middleware.firebase_auth import resolve_user_for_email

        smith = User.objects.create_user(username='smith', email='smith@gmail.com')

        resolved = resolve_user_for_email('smith@yahoo.com')

        assert resolved is not None
        assert resolved != smith
        assert resolved.email == 'smith@yahoo.com'
        smith.refresh_from_db()
        assert smith.email == 'smith@gmail.com'

    def test_an_account_with_no_email_is_still_claimed_by_its_username(self, db):
        """Wiki-imported and parent-created accounts get their address this way."""
        from gift.middleware.firebase_auth import resolve_user_for_email

        kid = User.objects.create_user(username='ellie')

        assert resolve_user_for_email('ellie@gmail.com') == kid
        kid.refresh_from_db()
        assert kid.email == 'ellie@gmail.com'

    def test_a_staff_account_with_no_email_is_never_claimed_by_username(self, db):
        from gift.middleware.firebase_auth import resolve_user_for_email

        admin = User.objects.create_user(username='admin', is_staff=True)

        assert resolve_user_for_email('admin@anything.com') != admin
        admin.refresh_from_db()
        assert admin.email == ''

    def test_a_linked_address_does_not_replace_the_main_one(self, db):
        """Otherwise the main address stops resolving after one linked sign-in."""
        from gift.middleware.firebase_auth import resolve_user_for_email

        gabe = User.objects.create_user(username='gabe', email='gabe@gmail.com')
        LinkedEmail.objects.create(user=gabe, email='gabe@work.example')

        assert resolve_user_for_email('gabe@work.example') == gabe
        gabe.refresh_from_db()
        assert gabe.email == 'gabe@gmail.com'
        assert resolve_user_for_email('gabe@gmail.com') == gabe

    def test_the_address_matches_whatever_its_capitalisation(self, db):
        """Without the username fallback, a case mismatch would mint a blank account."""
        from gift.middleware.firebase_auth import resolve_user_for_email

        kid = User.objects.create_user(username='ellie', email='Ellie.Duke@gmail.com')

        assert resolve_user_for_email('ellie.duke@gmail.com') == kid
        assert User.objects.count() == 1


@pytest.mark.api
class TestRejectedSignInsWriteNothing:
    def test_a_stranger_is_refused_without_leaving_an_account_behind(self, client, db):
        response = get_with_cookie(client, fake_firebase('stranger@nowhere.example'))

        assert response.status_code == 403
        assert b'not authorized' in response.content
        assert not User.objects.exists()

    def test_a_stranger_cannot_rewrite_a_kids_address_on_the_way_out(self, client, db):
        """emma@anything.com used to overwrite kid Emma's email before the 403."""
        emma = User.objects.create_user(username='emma', email='emma@family.example')
        blank = User.objects.create_user(username='noah')

        get_with_cookie(client, fake_firebase('emma@anything.com'))
        get_with_cookie(client, fake_firebase('noah@anything.com'))

        emma.refresh_from_db()
        blank.refresh_from_db()
        assert emma.email == 'emma@family.example'
        assert blank.email == ''
        assert User.objects.count() == 2

    def test_the_backend_alone_refuses_a_stranger_too(self, rf, db):
        """It is in AUTHENTICATION_BACKENDS, so it is reachable without the middleware."""
        from gift.middleware.firebase_auth import FirebaseAuthBackend

        request = rf.get('/')
        request.COOKIES['__session'] = 'fake-session-cookie'
        with patch(
            'gift.middleware.firebase_auth._get_firebase_auth',
            return_value=fake_firebase('stranger@nowhere.example'),
        ):
            assert FirebaseAuthBackend().authenticate(request) is None

        assert not User.objects.exists()


@pytest.mark.api
class TestEmailMustBeVerified:
    """Anyone can register a password account for an address they don't own."""

    def test_an_unverified_address_is_refused_even_when_allowlisted(self, client, user):
        AllowedEmail.objects.create(email='ellie@gmail.com')
        kid = User.objects.create_user(username='ellie', email='ellie@gmail.com')

        response = get_with_cookie(
            client, fake_firebase('ellie@gmail.com', email_verified=False, provider='password')
        )

        assert response.status_code == 403
        assert b'verif' in response.content
        assert response.wsgi_request.user != kid

    def test_a_token_with_no_verified_claim_is_refused(self, client, user):
        firebase = fake_firebase(user.email)
        del firebase.verify_session_cookie.return_value['email_verified']

        assert get_with_cookie(client, firebase).status_code == 403

    def test_a_google_sign_in_still_resolves_to_the_same_account(self, client, user):
        """Google marks its addresses verified; this is today's normal sign-in."""
        response = get_with_cookie(client, fake_firebase(user.email, provider='google.com'))

        assert response.status_code != 403
        assert response.wsgi_request.user == user
        assert User.objects.count() == 1

    def test_session_login_refuses_an_unverified_token(self, client, db):
        """Refuse at the door so no five-day cookie is set for a dead-end session."""
        firebase = fake_firebase('ellie@gmail.com', email_verified=False, provider='password')
        with (
            patch('gift.middleware.firebase_auth._get_firebase_auth', return_value=firebase),
            patch('time.time', return_value=1),
        ):
            response = client.post(
                '/sessionLogin', data='{"idToken": "abc"}', content_type='application/json'
            )

        assert response.status_code == 403
        assert '__session' not in response.cookies
        firebase.create_session_cookie.assert_not_called()

    def test_session_login_still_accepts_a_verified_token(self, client, db):
        firebase = fake_firebase('ellie@gmail.com')
        with (
            patch('gift.middleware.firebase_auth._get_firebase_auth', return_value=firebase),
            patch('time.time', return_value=1),
        ):
            response = client.post(
                '/sessionLogin', data='{"idToken": "abc"}', content_type='application/json'
            )

        assert response.status_code == 200
        assert response.cookies['__session'].value == 'minted-cookie'


@pytest.mark.api
class TestNewAccountsNeverCollide:
    def test_a_new_member_whose_prefix_is_taken_still_gets_an_account(self, client, db):
        """Creating a second `smith` raised IntegrityError and looped the login."""
        smith = User.objects.create_user(username='smith', email='smith@gmail.com')
        AllowedEmail.objects.create(email='smith@yahoo.com')

        response = get_with_cookie(client, fake_firebase('smith@yahoo.com'))

        newcomer = response.wsgi_request.user
        assert newcomer.is_authenticated
        assert newcomer != smith
        assert newcomer.email == 'smith@yahoo.com'
        assert newcomer.username != 'smith'
