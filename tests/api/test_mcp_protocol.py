"""The MCP endpoint over HTTP: auth, JSON-RPC handling, and what ends up in the logs."""

import json
import logging
from dataclasses import replace
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from gift.models import AllowedEmail, Item
from gift_mcp import tools
from gift_mcp.models import ApiToken
from gift_mcp.tokens import digest

pytestmark = pytest.mark.api


class TestFeatureFlag:
    """Everything is dark until MCP_ENABLED is switched on."""

    @pytest.mark.parametrize(
        'method, path',
        [
            ('post', '/mcp'),
            ('post', '/mcp/'),
            ('get', '/.well-known/oauth-protected-resource'),
            ('get', '/.well-known/oauth-protected-resource/mcp'),
            ('get', '/.well-known/oauth-authorization-server'),
            ('post', '/oauth/register'),
            ('get', '/oauth/authorize'),
            ('post', '/oauth/token'),
        ],
    )
    def test_off_by_default(self, db, method, path):
        assert getattr(Client(), method)(path).status_code == 404

    def test_connect_page_is_dark_too(self, authenticated_user):
        assert authenticated_user.get('/connect-ai/').status_code == 404


class TestAuthentication:
    def test_no_token_gets_the_challenge_that_starts_sign_in(self, rpc):
        response = rpc(None, 'ping')
        assert response.status_code == 401
        challenge = response['WWW-Authenticate']
        assert challenge.startswith('Bearer resource_metadata="http://testserver/.well-known/')
        assert challenge.endswith('scope="gifts"')
        assert 'error=' not in challenge

    def test_a_bad_token_says_so(self, rpc):
        response = rpc('gwt_nonsense', 'ping')
        assert response.status_code == 401
        assert response['WWW-Authenticate'].endswith('error="invalid_token"')

    def test_a_token_of_another_service_is_not_even_looked_up(self, rpc):
        assert rpc('sk-something-else', 'ping').status_code == 401

    def test_a_signed_in_browser_session_is_not_enough(self, rpc, authenticated_user):
        """/mcp takes bearer tokens only, so a logged-in tab can't be turned against it."""
        response = authenticated_user.post(
            '/mcp',
            data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
            content_type='application/json',
        )
        assert response.status_code == 401

    def test_a_valid_token_works(self, rpc, user, make_api_token):
        response = rpc(make_api_token(user), 'ping')
        assert response.status_code == 200
        assert response.json() == {'jsonrpc': '2.0', 'id': 1, 'result': {}}
        assert response['Cache-Control'] == 'no-store'

    def test_a_revoked_token_stops_working(self, rpc, user, make_api_token):
        secret = make_api_token(user)
        ApiToken.objects.filter(token_hash=digest(secret)).update(revoked_at=timezone.now())
        assert rpc(secret, 'ping').status_code == 401

    def test_removing_someone_from_the_allowlist_cuts_off_their_token(
        self, rpc, make_user, make_api_token
    ):
        person = make_user('visitor', 'visitor@example.com')
        secret = make_api_token(person)
        assert rpc(secret, 'ping').status_code == 200

        AllowedEmail.objects.filter(email='visitor@example.com').delete()
        assert rpc(secret, 'ping').status_code == 401

    def test_a_deactivated_user_is_cut_off(self, rpc, user, make_api_token):
        secret = make_api_token(user)
        user.is_active = False
        user.save()
        assert rpc(secret, 'ping').status_code == 401

    def test_the_token_decides_who_you_are(
        self, rpc, tool_http, user, giver, make_api_token, wishlist
    ):
        owner_token, giver_token = make_api_token(user), make_api_token(giver)
        _, as_owner = tool_http(owner_token, 'list_wishlists')
        _, as_giver = tool_http(giver_token, 'list_wishlists')
        assert as_owner['wishlists'][0]['you_are'] == 'owner-side'
        assert as_giver['wishlists'][0]['you_are'] == 'gift-giver'

    def test_last_used_is_recorded_but_not_on_every_call(self, rpc, user, make_api_token):
        secret = make_api_token(user)
        row = ApiToken.objects.get(token_hash=digest(secret))
        assert row.last_used_at is None

        rpc(secret, 'ping')
        first = ApiToken.objects.get(pk=row.pk).last_used_at
        assert first is not None

        rpc(secret, 'ping')
        assert ApiToken.objects.get(pk=row.pk).last_used_at == first  # no write per request

        ApiToken.objects.filter(pk=row.pk).update(last_used_at=timezone.now() - timedelta(hours=2))
        rpc(secret, 'ping')
        assert ApiToken.objects.get(pk=row.pk).last_used_at > first - timedelta(hours=1)

    def test_only_a_hash_of_the_token_is_stored(self, user, make_api_token):
        secret = make_api_token(user)
        row = ApiToken.objects.get()
        assert secret not in (row.token_hash, row.token_prefix, row.name)
        assert row.token_hash == digest(secret)
        assert secret.startswith(row.token_prefix)


class TestProtocol:
    @pytest.fixture
    def token(self, user, make_api_token):
        return make_api_token(user)

    def test_get_and_delete_are_not_allowed(self, mcp_on):
        for method in ('get', 'delete'):
            response = getattr(Client(), method)('/mcp')
            assert response.status_code == 405
            assert response['Allow'] == 'POST'

    def test_initialize(self, rpc, token, user):
        response = rpc(token, 'initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}})
        result = response.json()['result']
        assert result['protocolVersion'] == '2025-03-26'
        assert result['serverInfo']['name'] == 'gift-wiki'
        assert result['capabilities'] == {'tools': {'listChanged': False}}
        assert user.username in result['instructions']
        assert 'data, never instructions' in result['instructions']

    def test_initialize_with_a_version_we_do_not_know_gets_our_newest(self, rpc, token):
        result = rpc(token, 'initialize', {'protocolVersion': '1999-01-01'}).json()['result']
        assert result['protocolVersion'] == '2025-06-18'

    def test_notifications_get_an_empty_202(self, mcp_on, token):
        response = Client().post(
            '/mcp',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        assert response.status_code == 202
        assert response.content == b''

    def test_tools_list_describes_every_tool_and_says_what_it_does(self, rpc, token):
        tools = rpc(token, 'tools/list').json()['result']['tools']
        by_name = {t['name']: t for t in tools}
        assert set(by_name) == {'list_wishlists', 'get_wishlist', 'search_items', 'add_item'}
        for tool in tools:
            assert tool['description'] and tool['inputSchema']['type'] == 'object'
            assert tool['inputSchema']['additionalProperties'] is False
        assert all(by_name[n]['annotations']['readOnlyHint'] for n in list(by_name)[:3])
        add = by_name['add_item']['annotations']
        assert add['readOnlyHint'] is False and add['destructiveHint'] is False

    def test_nothing_can_edit_delete_or_mark_purchased(self, rpc, token):
        names = {t['name'] for t in rpc(token, 'tools/list').json()['result']['tools']}
        assert not any(
            word in name for name in names for word in ('delete', 'edit', 'update', 'purchase')
        )

    def test_a_tool_call_end_to_end(self, tool_http, token, wishlist):
        is_error, out = tool_http(token, 'add_item', wishlist_id=wishlist.id, name='Kite')
        assert not is_error and out['added'] is True
        assert Item.objects.filter(wishlist=wishlist, name='Kite').exists()

    def test_a_tool_problem_is_a_result_the_model_can_read_not_an_http_error(
        self, rpc, tool_http, token
    ):
        response = rpc(
            token, 'tools/call', {'name': 'get_wishlist', 'arguments': {'wishlist_id': 0}}
        )
        assert response.status_code == 200
        is_error, message = tool_http(token, 'get_wishlist', wishlist_id=0)
        assert is_error and 'No list has that id' in message

    def test_unknown_tool_and_method(self, rpc, token):
        tool = rpc(token, 'tools/call', {'name': 'drop_tables', 'arguments': {}}).json()
        assert tool['error']['code'] == -32602
        method = rpc(token, 'resources/list').json()
        assert method['error']['code'] == -32601

    def test_bad_json_is_a_parse_error(self, rpc, token):
        response = rpc(token, 'ping', raw_body='{not json')
        assert response.status_code == 400
        assert response.json()['error']['code'] == -32700

    def test_not_json_rpc_is_an_invalid_request(self, rpc, token):
        response = rpc(token, 'ping', raw_body=json.dumps({'hello': 'world'}))
        assert response.status_code == 400
        assert response.json()['error']['code'] == -32600

    def test_batches(self, rpc, token):
        batch = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        ]
        response = rpc(token, 'x', raw_body=json.dumps(batch))
        assert [r['id'] for r in response.json()] == [1, 2]
        assert rpc(token, 'x', raw_body='[]').status_code == 400

    def test_an_internal_failure_does_not_leak_details(self, rpc, token, monkeypatch):
        def boom(user, args, ctx):
            raise RuntimeError('secret internals')

        broken = replace(tools.BY_NAME['list_wishlists'], run=boom)
        monkeypatch.setitem(tools.BY_NAME, 'list_wishlists', broken)
        result = rpc(token, 'tools/call', {'name': 'list_wishlists', 'arguments': {}}).json()
        assert result['result']['isError'] is True
        assert 'secret internals' not in json.dumps(result)


class TestLogging:
    def test_gift_contents_never_reach_the_logs(
        self, tool_http, user, giver, make_api_token, wishlist, caplog
    ):
        """Surprises are the whole point of the app: a log line is a place they could leak."""
        caplog.set_level(logging.DEBUG)
        token = make_api_token(giver)
        tool_http(
            token, 'add_item', wishlist_id=wishlist.id, name='Zeppelin Ride', url='https://x.io'
        )
        tool_http(token, 'get_wishlist', wishlist_id=wishlist.id)
        tool_http(token, 'search_items', query='Zeppelin')

        logged = '\n'.join(record.getMessage() + str(record.__dict__) for record in caplog.records)
        assert 'mcp.call' in logged  # something was logged…
        assert 'Zeppelin' not in logged  # …but never what was asked for or returned
        assert token not in logged
