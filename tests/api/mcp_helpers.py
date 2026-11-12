"""Shared helpers for the MCP/OAuth tests. (tests/api is not a package, so test modules
and conftest import this as a top-level module.)"""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from django.test import Client

CALLBACK = 'https://claude.ai/api/mcp/auth_callback'


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    )
    return verifier, challenge


def register(**body):
    body.setdefault('client_name', 'Claude')
    body.setdefault('redirect_uris', [CALLBACK])
    return Client().post('/oauth/register', data=json.dumps(body), content_type='application/json')


def authorize_params(client_id, challenge, **override):
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': CALLBACK,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'state': 'xyz',
    }
    params.update(override)
    return params


def query_of(response):
    return {k: v[0] for k, v in parse_qs(urlsplit(response['Location']).query).items()}


def token_post(**form):
    return Client().post(
        '/oauth/token', data=urlencode(form), content_type='application/x-www-form-urlencoded'
    )


def mcp_status(access_token):
    """The HTTP status of an authenticated ping: 200 if the token works, 401 if not."""
    return (
        Client()
        .post(
            '/mcp',
            data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {access_token}',
        )
        .status_code
    )


def connect_as(browser, client_id):
    """Approve `client_id` in a signed-in `browser` and exchange the code. Returns the tokens."""
    verifier, challenge = pkce_pair()
    params = authorize_params(client_id, challenge)
    response = browser.post('/oauth/authorize', {**params, 'decision': 'approve'})
    assert response.status_code == 302, response.content
    token = token_post(
        grant_type='authorization_code',
        code=query_of(response)['code'],
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert token.status_code == 200, token.content
    return token.json()
