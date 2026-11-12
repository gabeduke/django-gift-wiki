"""The page where a person makes personal tokens and manages the apps they've approved."""

import pytest
from django.test import Client
from mcp_helpers import connect_as, mcp_status

from gift_mcp.models import ApiToken, OAuthToken
from gift_mcp.tokens import digest

pytestmark = pytest.mark.api

URL = '/connect-ai/'


class TestConnectPage:
    def test_it_needs_a_signed_in_person(self, mcp_on, db):
        response = Client().get(URL)
        assert response.status_code == 302
        assert response['Location'].startswith('/auth.html')

    def test_it_shows_the_server_address(self, mcp_on, authenticated_user):
        page = authenticated_user.get(URL).content.decode()
        assert 'http://testserver/mcp' in page
        assert 'claude mcp add' in page

    def test_a_new_token_is_shown_once_stored_hashed_and_works(
        self, mcp_on, authenticated_user, user
    ):
        response = authenticated_user.post(URL, {'action': 'create_token', 'name': 'My laptop'})
        page = response.content.decode()
        secret = next(word for word in page.replace('"', ' ').split() if word.startswith('gwt_'))

        row = ApiToken.objects.get()
        assert row.user == user and row.name == 'My laptop'
        assert row.token_hash == digest(secret) and secret not in (row.token_hash, row.token_prefix)
        assert (
            response['Cache-Control'].startswith('max-age=0')
            or 'no-store' in response['Cache-Control']
        )
        assert mcp_status(secret) == 200

        # Reloading the page never shows it again, only the harmless prefix.
        again = authenticated_user.get(URL).content.decode()
        assert secret not in again and row.token_prefix in again

    def test_a_blank_name_gets_a_default(self, mcp_on, authenticated_user):
        authenticated_user.post(URL, {'action': 'create_token', 'name': '  '})
        assert ApiToken.objects.get().name == 'Untitled token'

    def test_there_is_a_limit(self, mcp_on, authenticated_user):
        for _ in range(10):
            authenticated_user.post(URL, {'action': 'create_token', 'name': 'x'})
        authenticated_user.post(URL, {'action': 'create_token', 'name': 'one too many'})
        assert ApiToken.objects.count() == 10

    def test_revoking_your_token(self, mcp_on, authenticated_user, user, make_api_token):
        secret = make_api_token(user)
        row = ApiToken.objects.get()
        authenticated_user.post(URL, {'action': 'revoke_token', 'id': row.pk})
        assert ApiToken.objects.get().revoked_at is not None
        assert mcp_status(secret) == 401

    def test_you_cannot_revoke_somebody_elses_token(
        self, mcp_on, authenticated_user, other_user, make_api_token
    ):
        secret = make_api_token(other_user)
        authenticated_user.post(URL, {'action': 'revoke_token', 'id': ApiToken.objects.get().pk})
        assert ApiToken.objects.get().revoked_at is None
        assert mcp_status(secret) == 200

    def test_each_person_sees_only_their_own_tokens(
        self, mcp_on, authenticated_user, other_user, make_api_token
    ):
        make_api_token(other_user, name='Somebody else laptop')
        assert 'Somebody else laptop' not in authenticated_user.get(URL).content.decode()


class TestConnectedApps:
    def test_approved_apps_are_listed_and_can_be_disconnected(self, authenticated_user, connect):
        tokens = connect()
        assert mcp_status(tokens['access_token']) == 200
        assert 'Claude' in authenticated_user.get(URL).content.decode()

        client_pk = OAuthToken.objects.first().client_id
        authenticated_user.post(URL, {'action': 'revoke_connection', 'id': client_pk})
        assert mcp_status(tokens['access_token']) == 401
        assert "Apps you've approved" in authenticated_user.get(URL).content.decode()
        assert 'Disconnect' not in authenticated_user.get(URL).content.decode()

    def test_disconnecting_only_cuts_off_your_own_access(
        self, authenticated_user, authenticated_other_user, client_id
    ):
        """Two people connect the same app; one disconnecting must not affect the other."""
        mine = connect_as(authenticated_user, client_id)
        theirs = connect_as(authenticated_other_user, client_id)
        assert mcp_status(mine['access_token']) == 200 and mcp_status(theirs['access_token']) == 200

        client_pk = OAuthToken.objects.first().client_id
        authenticated_user.post(URL, {'action': 'revoke_connection', 'id': client_pk})
        assert mcp_status(mine['access_token']) == 401
        assert mcp_status(theirs['access_token']) == 200


class TestProfileLink:
    def test_the_link_appears_only_when_the_feature_is_on(self, authenticated_user, monkeypatch):
        monkeypatch.delenv('MCP_ENABLED', raising=False)
        assert 'Connect an AI' not in authenticated_user.get('/profile/').content.decode()
        assert '/connect-ai/' not in authenticated_user.get('/profile/').content.decode()

        monkeypatch.setenv('MCP_ENABLED', 'TRUE')
        assert '/connect-ai/' in authenticated_user.get('/profile/').content.decode()
