"""Fixtures for the MCP server tests (gift_mcp)."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from mcp_helpers import authorize_params, connect_as, pkce_pair, query_of, register

from gift.models import AllowedEmail, Item
from gift_mcp.models import ApiToken
from gift_mcp.tokens import API_PREFIX, digest, make_secret

User = get_user_model()


@pytest.fixture
def mcp_on(monkeypatch):
    """The MCP_ENABLED flag, on. Off is the default, which is itself tested."""
    monkeypatch.setenv('MCP_ENABLED', 'TRUE')


@pytest.fixture
def make_api_token(db):
    """Make a personal token for `user` and return the secret (the only time it exists)."""

    def make(user, name='test token'):
        secret = make_secret(API_PREFIX)
        ApiToken.objects.create(
            user=user, name=name, token_hash=digest(secret), token_prefix=secret[:12]
        )
        return secret

    return make


@pytest.fixture
def rpc(mcp_on, db):
    """POST one JSON-RPC message to /mcp, optionally with a bearer token."""

    def call(token, method, params=None, id_=1, raw_body=None):
        body = {'jsonrpc': '2.0', 'id': id_, 'method': method}
        if params is not None:
            body['params'] = params
        extra = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return Client().post(
            '/mcp',
            data=raw_body if raw_body is not None else json.dumps(body),
            content_type='application/json',
            **extra,
        )

    return call


@pytest.fixture
def tool_http(rpc):
    """Call a tool over HTTP; returns (is_error, parsed value or error text)."""

    def run(token, tool, **arguments):
        result = rpc(token, 'tools/call', {'name': tool, 'arguments': arguments}).json()['result']
        text = result['content'][0]['text']
        if result.get('isError'):
            return True, text
        return False, json.loads(text)

    return run


@pytest.fixture
def make_user(db):
    """Make a person who is on the allowlist (the middleware's database allowlist)."""

    def make(username, email, **extra):
        AllowedEmail.objects.get_or_create(email=email)
        return User.objects.create_user(username=username, email=email, password='x', **extra)

    return make


@pytest.fixture
def giver(other_user):
    """A gift-giver on `wishlist` (owned by `user`): anyone who isn't owner-side."""
    return other_user


@pytest.fixture
def plain_item(wishlist):
    return Item.objects.create(wishlist=wishlist, name='Plain Mug', description='Blue one')


@pytest.fixture
def bought_item(wishlist, giver):
    return Item.objects.create(
        wishlist=wishlist, name='Bought Scarf', purchased=True, purchased_by=giver
    )


@pytest.fixture
def surprise_item(wishlist, giver):
    return Item.objects.create(
        wishlist=wishlist, name='Surprise Bike', is_sneaky=True, added_by=giver
    )


@pytest.fixture
def client_id(mcp_on, db):
    """A registered app (Claude)."""
    response = register()
    assert response.status_code == 201
    return response.json()['client_id']


@pytest.fixture
def approve(authenticated_user):
    """Approve as `user` in a signed-in browser; returns the authorization code."""

    def go(client_id, challenge, **override):
        params = authorize_params(client_id, challenge, **override)
        response = authenticated_user.post('/oauth/authorize', {**params, 'decision': 'approve'})
        assert response.status_code == 302, response.content
        return query_of(response)['code']

    return go


@pytest.fixture
def connect(client_id, authenticated_user):
    """Run the whole sign-in flow as `user`; returns the issued tokens."""
    return lambda: connect_as(authenticated_user, client_id)
