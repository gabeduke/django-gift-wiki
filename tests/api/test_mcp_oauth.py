"""OAuth 2.1 for the MCP endpoint: discovery, registration, sign-in and tokens.

This is the door a family member's AI assistant comes through, so the tests lean
on the ways it could be abused: an app that registers a return address it doesn't
own, a replayed code or refresh token, a missing or wrong PKCE verifier, and a
person who has since lost access.
"""

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client
from django.utils import timezone
from mcp_helpers import (
    CALLBACK,
    authorize_params,
    mcp_status,
    pkce_pair,
    query_of,
    register,
    token_post,
)

from gift.models import AllowedEmail
from gift_mcp import oauth
from gift_mcp.models import AuthorizationCode, OAuthClient, OAuthToken
from gift_mcp.tokens import digest

pytestmark = pytest.mark.api


class TestPkce:
    def test_the_rfc_7636_example(self):
        """RFC 7636 Appendix B: a published verifier/challenge pair."""
        assert oauth.pkce_matches(
            'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
            'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        )

    def test_a_wrong_or_malformed_verifier_fails(self):
        verifier, challenge = pkce_pair()
        assert not oauth.pkce_matches(verifier + 'x', challenge)
        assert not oauth.pkce_matches('short', challenge)
        assert not oauth.pkce_matches('', challenge)
        assert not oauth.pkce_matches(verifier, '')


class TestDiscovery:
    @pytest.mark.parametrize(
        'path',
        ['/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp'],
    )
    def test_protected_resource(self, mcp_on, db, path):
        response = Client().get(path)
        assert response.status_code == 200
        assert response.json() == {
            'resource': 'http://testserver/mcp',
            'authorization_servers': ['http://testserver'],
            'scopes_supported': ['gifts'],
            'bearer_methods_supported': ['header'],
            'resource_name': 'Gift Wiki',
        }
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_authorization_server(self, mcp_on, db):
        meta = Client().get('/.well-known/oauth-authorization-server').json()
        assert meta['issuer'] == 'http://testserver'
        assert meta['registration_endpoint'] == 'http://testserver/oauth/register'
        assert meta['code_challenge_methods_supported'] == ['S256']
        assert meta['token_endpoint_auth_methods_supported'] == ['none']
        assert meta['grant_types_supported'] == ['authorization_code', 'refresh_token']

    def test_the_scheme_is_the_requests_and_a_forged_proxy_header_is_ignored(self, mcp_on, db):
        """wsgi.py marks real requests https; a client-supplied X-Forwarded-Proto must not
        be able to change the (cacheable) documents we publish."""
        plain = Client().get('/.well-known/oauth-authorization-server').json()
        assert plain['issuer'] == 'http://testserver'
        forged = (
            Client()
            .get('/.well-known/oauth-authorization-server', HTTP_X_FORWARDED_PROTO='https')
            .json()
        )
        assert forged['issuer'] == 'http://testserver'
        secure = Client().get('/.well-known/oauth-authorization-server', secure=True).json()
        assert secure['issuer'] == 'https://testserver'

    def test_the_origin_can_be_pinned(self, mcp_on, db, settings):
        settings.MCP_PUBLIC_ORIGIN = 'https://giftwiki.example/'
        meta = Client().get('/.well-known/oauth-protected-resource').json()
        assert meta['resource'] == 'https://giftwiki.example/mcp'

    def test_cors_preflight(self, mcp_on, db):
        response = Client().options('/oauth/token')
        assert response.status_code == 204
        assert 'POST' in response['Access-Control-Allow-Methods']


class TestRegistration:
    def test_a_client_can_register(self, mcp_on, db):
        response = register()
        body = response.json()
        assert response.status_code == 201
        assert body['client_id'].startswith('gwc_')
        assert body['token_endpoint_auth_method'] == 'none'
        assert body['redirect_uris'] == [CALLBACK]
        assert OAuthClient.objects.get().client_name == 'Claude'

    @pytest.mark.parametrize(
        'uri',
        [
            'http://localhost:8123/callback',
            'http://127.0.0.1:9/cb',
            'http://[::1]:9/cb',
            'https://claude.com/api/mcp/auth_callback',
            'https://chatgpt.com/connector_platform_oauth_redirect',
        ],
    )
    def test_loopback_and_recognised_hosts_are_accepted(self, mcp_on, db, uri):
        assert register(redirect_uris=[uri]).status_code == 201

    @pytest.mark.parametrize(
        'uri',
        [
            'https://evil.example/cb',
            'https://claude.ai.evil.example/cb',
            'http://claude.ai/cb',
            'https://user:pw@claude.ai/cb',
            'https://claude.ai/cb#fragment',
            'javascript:alert(1)',
            'cursor://anysphere/cb',
            'http://localhost.evil.example/cb',
            'https://claude.ai/' + 'a' * 600,
            42,
        ],
    )
    def test_an_app_cannot_register_a_return_address_it_does_not_own(self, mcp_on, db, uri):
        response = register(redirect_uris=[uri])
        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_redirect_uri'
        assert OAuthClient.objects.count() == 0

    @pytest.mark.parametrize('uris', [[], None, 'https://claude.ai/cb', [CALLBACK] * 11])
    def test_redirect_uris_must_be_a_sensible_list(self, mcp_on, db, uris):
        assert register(redirect_uris=uris).status_code == 400

    def test_only_the_grants_we_support(self, mcp_on, db):
        assert register(grant_types=['implicit']).status_code == 400
        assert register(grant_types=['authorization_code', 'refresh_token']).status_code == 201

    def test_bad_bodies(self, mcp_on, db):
        client = Client()
        assert (
            client.post(
                '/oauth/register', data='{nope', content_type='application/json'
            ).status_code
            == 400
        )
        assert (
            client.post('/oauth/register', data='[]', content_type='application/json').status_code
            == 400
        )
        assert client.get('/oauth/register').status_code == 405

    def test_name_defaults_and_is_trimmed(self, mcp_on, db):
        assert register(client_name='   ').json()['client_name'] == 'MCP client'
        assert len(register(client_name='x' * 500).json()['client_name']) == 200

    def test_the_recognised_hosts_are_configurable(self, mcp_on, db, settings):
        settings.MCP_REDIRECT_HOSTS = ['assistant.example.org']
        assert register(redirect_uris=['https://assistant.example.org/cb']).status_code == 201
        assert register(redirect_uris=[CALLBACK]).status_code == 400

    def test_the_table_cannot_be_filled_by_strangers(self, mcp_on, db, monkeypatch):
        monkeypatch.setattr(oauth, 'MAX_CLIENTS', 2)
        assert register().status_code == 201
        assert register().status_code == 201
        assert register().status_code == 503

    def test_stale_unused_registrations_are_swept(self, mcp_on, db):
        stale = OAuthClient.objects.create(
            client_id='gwc_stale', client_name='Old', redirect_uris=[CALLBACK]
        )
        OAuthClient.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        register()
        assert not OAuthClient.objects.filter(client_id='gwc_stale').exists()


class TestAuthorize:
    def test_an_unknown_app_gets_an_error_page_not_a_redirect(self, mcp_on, db):
        _, challenge = pkce_pair()
        response = Client().get('/oauth/authorize', authorize_params('gwc_nope', challenge))
        assert response.status_code == 400
        assert 'Location' not in response

    def test_a_mismatched_return_address_is_never_redirected_to(self, client_id):
        _, challenge = pkce_pair()
        params = authorize_params(client_id, challenge, redirect_uri='https://evil.example/cb')
        response = Client().get('/oauth/authorize', params)
        assert response.status_code == 400
        assert 'Location' not in response

    @pytest.mark.parametrize(
        'override, error',
        [
            ({'code_challenge': ''}, 'invalid_request'),
            ({'code_challenge_method': 'plain'}, 'invalid_request'),
            ({'code_challenge_method': ''}, 'invalid_request'),
            ({'response_type': 'token'}, 'unsupported_response_type'),
            ({'resource': 'https://other.example/mcp'}, 'invalid_target'),
        ],
    )
    def test_other_problems_go_back_to_the_app(self, client_id, override, error):
        _, challenge = pkce_pair()
        response = Client().get(
            '/oauth/authorize', authorize_params(client_id, challenge, **override)
        )
        assert response.status_code == 302
        assert response['Location'].startswith(CALLBACK)
        assert query_of(response)['error'] == error
        assert query_of(response)['state'] == 'xyz'

    def test_signing_in_comes_first_and_returns_here(self, client_id):
        _, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        response = Client().get('/oauth/authorize', params)
        assert response.status_code == 302
        assert response['Location'].startswith('/auth.html?next=')
        next_path = parse_qs(urlsplit(response['Location']).query)['next'][0]
        assert next_path.startswith('/oauth/authorize?') and f'client_id={client_id}' in next_path

    def test_the_consent_page_says_who_is_asking_and_where_you_will_land(
        self, client_id, authenticated_user
    ):
        _, challenge = pkce_pair()
        response = authenticated_user.get(
            '/oauth/authorize', authorize_params(client_id, challenge)
        )
        page = response.content.decode()
        assert response.status_code == 200
        assert 'Connect Claude?' in page and 'claude.ai' in page
        assert 'csrfmiddlewaretoken' in page
        assert f'value="{challenge}"' in page
        assert response['X-Frame-Options'] == 'DENY'
        assert 'no-store' in response['Cache-Control'] or 'no-cache' in response['Cache-Control']

    def test_approving_returns_a_code_with_state_and_issuer(self, client_id, approve):
        _, challenge = pkce_pair()
        code = approve(client_id, challenge)
        assert code and AuthorizationCode.objects.count() == 1
        row = AuthorizationCode.objects.get()
        assert row.code_hash == digest(code) and code not in (row.code_hash, row.code_challenge)

    def test_the_redirect_carries_state_and_issuer(self, client_id, authenticated_user):
        _, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        response = authenticated_user.post('/oauth/authorize', {**params, 'decision': 'approve'})
        assert response['Location'].startswith(CALLBACK + '?')
        assert query_of(response)['state'] == 'xyz'
        assert query_of(response)['iss'] == 'http://testserver'

    def test_declining_says_so_and_issues_nothing(self, client_id, authenticated_user):
        _, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        response = authenticated_user.post('/oauth/authorize', {**params, 'decision': 'deny'})
        assert query_of(response)['error'] == 'access_denied'
        assert query_of(response)['state'] == 'xyz'
        assert AuthorizationCode.objects.count() == 0

    def test_anything_but_an_explicit_approval_is_a_no(self, client_id, authenticated_user):
        _, challenge = pkce_pair()
        response = authenticated_user.post(
            '/oauth/authorize', authorize_params(client_id, challenge)
        )
        assert query_of(response)['error'] == 'access_denied'
        assert AuthorizationCode.objects.count() == 0

    def test_a_loopback_client_may_change_its_port(self, mcp_on, db, authenticated_user):
        cid = register(redirect_uris=['http://localhost:1111/cb']).json()['client_id']
        _, challenge = pkce_pair()
        params = authorize_params(cid, challenge, redirect_uri='http://localhost:2222/cb')
        response = authenticated_user.post('/oauth/authorize', {**params, 'decision': 'approve'})
        assert response['Location'].startswith('http://localhost:2222/cb?')

    def test_a_loopback_client_may_not_change_the_path(self, mcp_on, db):
        cid = register(redirect_uris=['http://localhost:1111/cb']).json()['client_id']
        _, challenge = pkce_pair()
        params = authorize_params(cid, challenge, redirect_uri='http://localhost:1111/other')
        assert Client().get('/oauth/authorize', params).status_code == 400

    def test_the_return_address_can_be_left_out_when_there_is_only_one(
        self, client_id, authenticated_user
    ):
        _, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        del params['redirect_uri']
        response = authenticated_user.post('/oauth/authorize', {**params, 'decision': 'approve'})
        assert response['Location'].startswith(CALLBACK)


class TestTokenExchange:
    def test_the_whole_flow_and_the_token_works(self, connect, user, wishlist):
        tokens = connect()
        assert tokens['token_type'] == 'Bearer'
        assert tokens['expires_in'] == 3600
        assert tokens['scope'] == 'gifts'
        assert tokens['access_token'].startswith('gwa_')
        assert tokens['refresh_token'].startswith('gwr_')

        listing = (
            Client()
            .post(
                '/mcp',
                data=json.dumps(
                    {
                        'jsonrpc': '2.0',
                        'id': 1,
                        'method': 'tools/call',
                        'params': {'name': 'list_wishlists', 'arguments': {}},
                    }
                ),
                content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {tokens["access_token"]}',
            )
            .json()
        )
        rows = json.loads(listing['result']['content'][0]['text'])['wishlists']
        assert rows[0]['you_are'] == 'owner-side'  # it acted as the person who approved

    def test_only_hashes_are_stored(self, connect):
        tokens = connect()
        stored = list(OAuthToken.objects.values_list('token_hash', flat=True))
        assert digest(tokens['access_token']) in stored
        assert tokens['access_token'] not in stored and tokens['refresh_token'] not in stored

    def test_responses_are_not_cached(self, client_id, approve):
        verifier, challenge = pkce_pair()
        response = token_post(
            grant_type='authorization_code',
            code=approve(client_id, challenge),
            redirect_uri=CALLBACK,
            client_id=client_id,
            code_verifier=verifier,
        )
        assert response['Cache-Control'] == 'no-store'

    def test_a_code_works_once_and_replaying_it_revokes_what_it_bought(self, client_id, approve):
        verifier, challenge = pkce_pair()
        code = approve(client_id, challenge)
        form = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': CALLBACK,
            'client_id': client_id,
            'code_verifier': verifier,
        }
        first = token_post(**form)
        assert first.status_code == 200 and mcp_status(first.json()['access_token']) == 200

        replay = token_post(**form)
        assert replay.status_code == 400 and replay.json()['error'] == 'invalid_grant'
        assert mcp_status(first.json()['access_token']) == 401  # the leak is contained

    @pytest.mark.parametrize(
        'break_it',
        [
            {'code_verifier': 'x' * 50},
            {'redirect_uri': 'https://claude.ai/somewhere/else'},
            {'code': 'not-a-real-code'},
        ],
    )
    def test_a_wrong_verifier_address_or_code_is_refused(self, client_id, approve, break_it):
        verifier, challenge = pkce_pair()
        form = {
            'grant_type': 'authorization_code',
            'code': approve(client_id, challenge),
            'redirect_uri': CALLBACK,
            'client_id': client_id,
            'code_verifier': verifier,
        }
        response = token_post(**{**form, **break_it})
        assert response.status_code == 400 and response.json()['error'] == 'invalid_grant'
        assert OAuthToken.objects.count() == 0

    def test_a_code_expires(self, client_id, approve):
        verifier, challenge = pkce_pair()
        code = approve(client_id, challenge)
        AuthorizationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = token_post(
            grant_type='authorization_code',
            code=code,
            redirect_uri=CALLBACK,
            client_id=client_id,
            code_verifier=verifier,
        )
        assert response.json()['error'] == 'invalid_grant'

    def test_a_code_cannot_be_used_by_a_different_app(self, client_id, approve):
        verifier, challenge = pkce_pair()
        code = approve(client_id, challenge)
        other = register(client_name='Other').json()['client_id']
        response = token_post(
            grant_type='authorization_code',
            code=code,
            redirect_uri=CALLBACK,
            client_id=other,
            code_verifier=verifier,
        )
        assert response.json()['error'] == 'invalid_grant'

    def test_unknown_client_and_grant(self, client_id):
        unknown = token_post(grant_type='authorization_code', client_id='gwc_nope')
        assert unknown.status_code == 401 and unknown.json()['error'] == 'invalid_client'
        unsupported = token_post(grant_type='password', client_id=client_id)
        assert unsupported.json()['error'] == 'unsupported_grant_type'
        assert Client().get('/oauth/token').status_code == 405

    def test_someone_who_lost_access_before_the_exchange_gets_nothing(self, client_id, make_user):
        # Only on the database allowlist, so removing the row really removes access.
        visitor = make_user('visitor', 'visitor@example.com')
        browser = Client()
        browser.force_login(visitor)
        verifier, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        response = browser.post('/oauth/authorize', {**params, 'decision': 'approve'})
        code = query_of(response)['code']

        AllowedEmail.objects.filter(email='visitor@example.com').delete()
        response = token_post(
            grant_type='authorization_code',
            code=code,
            redirect_uri=CALLBACK,
            client_id=client_id,
            code_verifier=verifier,
        )
        assert response.status_code == 400 and response.json()['error'] == 'invalid_grant'
        assert OAuthToken.objects.count() == 0

    def test_losing_access_after_connecting_cuts_the_connector_off(self, client_id, make_user):
        visitor = make_user('visitor', 'visitor@example.com')
        browser = Client()
        browser.force_login(visitor)
        verifier, challenge = pkce_pair()
        params = authorize_params(client_id, challenge)
        code = query_of(browser.post('/oauth/authorize', {**params, 'decision': 'approve'}))['code']
        tokens = token_post(
            grant_type='authorization_code',
            code=code,
            redirect_uri=CALLBACK,
            client_id=client_id,
            code_verifier=verifier,
        ).json()
        assert mcp_status(tokens['access_token']) == 200

        AllowedEmail.objects.filter(email='visitor@example.com').delete()
        assert mcp_status(tokens['access_token']) == 401
        refresh = token_post(
            grant_type='refresh_token', refresh_token=tokens['refresh_token'], client_id=client_id
        )
        assert refresh.status_code == 400


class TestRefresh:
    def refresh(self, client_id, refresh_token):
        return token_post(
            grant_type='refresh_token', refresh_token=refresh_token, client_id=client_id
        )

    def test_refreshing_rotates_both_tokens(self, client_id, connect):
        tokens = connect()
        response = self.refresh(client_id, tokens['refresh_token'])
        fresh = response.json()
        assert response.status_code == 200
        assert fresh['access_token'] != tokens['access_token']
        assert fresh['refresh_token'] != tokens['refresh_token']
        assert mcp_status(fresh['access_token']) == 200

    def test_replaying_a_rotated_refresh_token_revokes_everything(self, client_id, connect):
        tokens = connect()
        fresh = self.refresh(client_id, tokens['refresh_token']).json()

        replay = self.refresh(client_id, tokens['refresh_token'])
        assert replay.status_code == 400 and replay.json()['error'] == 'invalid_grant'
        assert mcp_status(fresh['access_token']) == 401
        assert self.refresh(client_id, fresh['refresh_token']).status_code == 400

    def test_an_expired_access_token_is_refused(self, connect):
        tokens = connect()
        OAuthToken.objects.filter(kind=OAuthToken.ACCESS).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert mcp_status(tokens['access_token']) == 401

    def test_an_expired_refresh_token_is_refused(self, client_id, connect):
        tokens = connect()
        OAuthToken.objects.filter(kind=OAuthToken.REFRESH).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert self.refresh(client_id, tokens['refresh_token']).status_code == 400

    def test_a_refresh_token_is_not_an_access_token_or_the_other_way_round(
        self, client_id, connect
    ):
        tokens = connect()
        assert mcp_status(tokens['refresh_token']) == 401
        assert self.refresh(client_id, tokens['access_token']).status_code == 400

    def test_another_app_cannot_use_it(self, connect):
        tokens = connect()
        other = register(client_name='Other').json()['client_id']
        assert self.refresh(other, tokens['refresh_token']).status_code == 400


class TestHousekeeping:
    def test_long_dead_codes_and_tokens_are_swept_when_new_ones_are_issued(
        self, client_id, connect
    ):
        connect()
        long_ago = timezone.now() - timedelta(days=45)
        OAuthToken.objects.update(expires_at=long_ago)
        AuthorizationCode.objects.update(expires_at=long_ago)
        assert OAuthToken.objects.count() == 2 and AuthorizationCode.objects.count() == 1

        connect()  # issuing again sweeps the stale rows first
        assert OAuthToken.objects.filter(expires_at__lt=long_ago + timedelta(days=1)).count() == 0
        assert OAuthToken.objects.count() == 2
        assert (
            AuthorizationCode.objects.filter(expires_at__lt=long_ago + timedelta(days=1)).count()
            == 0
        )
