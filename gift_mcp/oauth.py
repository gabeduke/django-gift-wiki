"""OAuth 2.1 for the MCP endpoint, so Claude (claude.ai connectors, mobile, Desktop,
Claude Code) can connect by signing in rather than pasting a token.

The app is its own authorization server. A person signs in with the app's normal
Google sign-in (the Firebase session cookie) and approves on /oauth/authorize;
the client then trades the code it receives for tokens. Modelled on FWP's
`lib/oauth.ts`, trimmed to what Claude's connector flow needs:

  * clients register themselves (RFC 7591), but only with redirect URIs on hosts
    we recognise or on the person's own computer — an unknown app can't ask a
    family member for access and send the result somewhere else;
  * PKCE with S256 is mandatory; there are no client secrets (public clients);
  * access tokens last an hour, refresh tokens thirty days and rotate on use,
    and replaying a used one revokes everything that client holds;
  * every MCP request re-checks the person is still on the allowlist, so
    removing someone cuts off their connectors immediately.

All functions here are plain: no HTTP objects except `request` where an origin is
needed. The views wrap them.
"""

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from gift.middleware.firebase_auth import is_email_allowed

from .models import AuthorizationCode, OAuthClient, OAuthToken
from .tokens import ACCESS_PREFIX, REFRESH_PREFIX, digest, make_secret

SCOPE = 'gifts'
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
# Expired codes and tokens are kept this long (for a replay to still be recognised) and then deleted.
STALE_AFTER = timedelta(days=30)

# Clients register themselves with no one watching, so keep the table from filling up.
CLIENT_UNUSED_TTL = timedelta(days=30)
MAX_CLIENTS = 500
MAX_REDIRECT_URIS = 10

LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}
_VERIFIER = re.compile(r'^[A-Za-z0-9\-._~]{43,128}$')
_CHALLENGE = re.compile(r'^[A-Za-z0-9_-]{43}$')  # base64url of a SHA-256: always 43 characters


# --- where we are -------------------------------------------------------------


def public_origin(request):
    """https://giftwiki.leetserve.com — set MCP_PUBLIC_ORIGIN, or it is read off the request.

    `giftwiki/wsgi.py` marks every request https (TLS ends at Cloud Run), so in
    production the scheme is right without trusting any header — a client-supplied
    X-Forwarded-Proto is deliberately ignored, since these documents are cacheable.
    A local server over plain http should set MCP_PUBLIC_ORIGIN=http://localhost:8000.
    get_host() only returns hosts in ALLOWED_HOSTS, so a forged Host header can't
    poison the URLs we publish either.
    """
    configured = getattr(settings, 'MCP_PUBLIC_ORIGIN', '')
    if configured:
        return configured.rstrip('/')
    return f'{request.scheme}://{request.get_host()}'


def resource_url(request):
    return f'{public_origin(request)}/mcp'


def www_authenticate(request):
    """The 401 challenge that starts a client's sign-in (RFC 9728)."""
    return (
        f'Bearer resource_metadata="{public_origin(request)}'
        f'/.well-known/oauth-protected-resource/mcp", scope="{SCOPE}"'
    )


def protected_resource_metadata(request):
    return {
        'resource': resource_url(request),
        'authorization_servers': [public_origin(request)],
        'scopes_supported': [SCOPE],
        'bearer_methods_supported': ['header'],
        'resource_name': 'Gift Wiki',
    }


def authorization_server_metadata(request):
    origin = public_origin(request)
    return {
        'issuer': origin,
        'authorization_endpoint': f'{origin}/oauth/authorize',
        'token_endpoint': f'{origin}/oauth/token',
        'registration_endpoint': f'{origin}/oauth/register',
        'scopes_supported': [SCOPE],
        'response_types_supported': ['code'],
        'response_modes_supported': ['query'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'],
        'code_challenge_methods_supported': ['S256'],
        'authorization_response_iss_parameter_supported': True,
    }


# --- PKCE and redirect URIs ---------------------------------------------------


def pkce_matches(verifier, challenge):
    """RFC 7636 S256: BASE64URL(SHA256(verifier)) == challenge."""
    if not verifier or not _VERIFIER.match(verifier):
        return False
    computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return hmac.compare_digest(computed.rstrip(b'=').decode(), challenge or '')


def is_loopback(uri):
    """http://localhost, 127.0.0.1 or [::1] (any port) — a client on the person's own computer."""
    parts = urlsplit(uri)
    return parts.scheme == 'http' and (parts.hostname or '') in LOOPBACK_HOSTS


def _redirect_hosts():
    return {
        host.strip().lower() for host in getattr(settings, 'MCP_REDIRECT_HOSTS', []) if host.strip()
    }


def redirect_uri_registrable(uri):
    """May a client register this redirect URI? Loopback, or https on a host we recognise."""
    if not isinstance(uri, str) or len(uri) > 500:
        return False
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.hostname or parts.username or parts.password:
        return False
    if is_loopback(uri):
        return True
    return parts.scheme == 'https' and parts.hostname.lower() in _redirect_hosts()


def redirect_uri_matches(registered, requested):
    """Exact match, except loopback URIs where only the port may differ (RFC 8252 §7.3)."""
    if requested in registered:
        return True
    if not is_loopback(requested):
        return False
    wanted = urlsplit(requested)
    for uri in registered:
        if not is_loopback(uri):
            continue
        have = urlsplit(uri)
        if (have.hostname, have.path, have.query) == (wanted.hostname, wanted.path, wanted.query):
            return True
    return False


# --- errors -------------------------------------------------------------------


def oauth_error(error, description, status=400):
    """An RFC 6749 error body and its HTTP status."""
    return status, {'error': error, 'error_description': description}


# --- dynamic client registration (RFC 7591) -----------------------------------


def register_client(data):
    """Create a client from registration metadata. Returns (status, body)."""
    if not isinstance(data, dict):
        return oauth_error('invalid_client_metadata', 'Send a JSON object.')

    uris = data.get('redirect_uris')
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECT_URIS:
        return oauth_error('invalid_redirect_uri', 'Send between 1 and 10 redirect_uris.')
    for uri in uris:
        if not redirect_uri_registrable(uri):
            return oauth_error(
                'invalid_redirect_uri',
                'Each redirect URI must be https on a host this server recognises, or http on '
                'localhost.',
            )

    grants = data.get('grant_types')
    if grants is not None:
        if not isinstance(grants, list) or not set(grants) <= {
            'authorization_code',
            'refresh_token',
        }:
            return oauth_error(
                'invalid_client_metadata',
                'Only the authorization_code and refresh_token grants are supported.',
            )

    name = data.get('client_name')
    name = name.strip()[:200] if isinstance(name, str) and name.strip() else 'MCP client'

    now = timezone.now()
    OAuthClient.objects.filter(
        created_at__lt=now - CLIENT_UNUSED_TTL, last_used_at__isnull=True
    ).delete()
    if OAuthClient.objects.count() >= MAX_CLIENTS:
        return oauth_error(
            'temporarily_unavailable', 'Too many registered apps; try again later.', 503
        )

    client = OAuthClient.objects.create(
        client_id='gwc_' + secrets.token_urlsafe(16), client_name=name, redirect_uris=list(uris)
    )
    return 201, {
        'client_id': client.client_id,
        'client_name': client.client_name,
        'redirect_uris': client.redirect_uris,
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'token_endpoint_auth_method': 'none',
        'scope': SCOPE,
    }


# --- authorization request ----------------------------------------------------


class AuthorizeFatal(Exception):
    """The request can't be trusted enough to send the person anywhere: show an error page."""


class AuthorizeRedirect(Exception):
    """The client is known, so the error goes back to it (RFC 6749 §4.1.2.1)."""

    def __init__(self, error, description, redirect_uri, state):
        super().__init__(description)
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state


@dataclass
class AuthorizeRequest:
    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    state: str


def parse_authorize_request(params, request):
    """Validate /oauth/authorize parameters (a dict-like of strings)."""
    client = OAuthClient.objects.filter(client_id=params.get('client_id', '')).first()
    if client is None:
        raise AuthorizeFatal('This app is not recognised. Start the connection again from the app.')

    redirect_uri = params.get('redirect_uri', '')
    if not redirect_uri and len(client.redirect_uris) == 1:
        redirect_uri = client.redirect_uris[0]
    if not redirect_uri or not redirect_uri_matches(client.redirect_uris, redirect_uri):
        raise AuthorizeFatal("This app's return address doesn't match what it registered.")

    state = params.get('state', '')

    def fail(error, description):
        raise AuthorizeRedirect(error, description, redirect_uri, state)

    if params.get('response_type') != 'code':
        fail('unsupported_response_type', 'Only response_type=code is supported.')
    challenge = params.get('code_challenge', '')
    if not _CHALLENGE.match(challenge) or params.get('code_challenge_method') != 'S256':
        fail('invalid_request', 'PKCE with code_challenge_method=S256 is required.')
    resource = params.get('resource')
    if resource and resource.rstrip('/') not in (resource_url(request), public_origin(request)):
        fail('invalid_target', 'That resource is not served here.')

    return AuthorizeRequest(
        client=client, redirect_uri=redirect_uri, code_challenge=challenge, state=state
    )


def issue_code(auth, user):
    """Record a person's approval and return the single-use code that stands for it."""
    code = secrets.token_urlsafe(32)
    AuthorizationCode.objects.create(
        code_hash=digest(code),
        client=auth.client,
        user=user,
        redirect_uri=auth.redirect_uri,
        code_challenge=auth.code_challenge,
        scope=SCOPE,
        expires_at=timezone.now() + CODE_TTL,
    )
    return code


# --- token endpoint -----------------------------------------------------------


def _user_may_hold_tokens(user):
    return user.is_active and is_email_allowed(user.email)


def revoke_connection(user, client):
    """Cut off every token `client` holds for `user`."""
    OAuthToken.objects.filter(user=user, client=client, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _sweep(now):
    """Drop long-dead rows so the tables don't grow forever. Done where we are already writing."""
    OAuthToken.objects.filter(expires_at__lt=now - STALE_AFTER).delete()
    AuthorizationCode.objects.filter(expires_at__lt=now - STALE_AFTER).delete()


def _issue_tokens(client, user):
    now = timezone.now()
    _sweep(now)
    access, refresh = make_secret(ACCESS_PREFIX), make_secret(REFRESH_PREFIX)
    OAuthToken.objects.create(
        token_hash=digest(access),
        kind=OAuthToken.ACCESS,
        client=client,
        user=user,
        scope=SCOPE,
        expires_at=now + ACCESS_TTL,
    )
    OAuthToken.objects.create(
        token_hash=digest(refresh),
        kind=OAuthToken.REFRESH,
        client=client,
        user=user,
        scope=SCOPE,
        expires_at=now + REFRESH_TTL,
    )
    OAuthClient.objects.filter(pk=client.pk).update(last_used_at=now)
    return {
        'access_token': access,
        'token_type': 'Bearer',
        'expires_in': int(ACCESS_TTL.total_seconds()),
        'refresh_token': refresh,
        'scope': SCOPE,
    }


def _exchange_code(client, params):
    code_row = (
        AuthorizationCode.objects.select_related('user')
        .filter(code_hash=digest(params.get('code', '')), client=client)
        .first()
    )
    if code_row is None:
        return oauth_error('invalid_grant', 'That code is not valid.')
    if code_row.used_at is not None:
        # A code is single-use. Seeing it again means it leaked, so undo what it bought.
        revoke_connection(code_row.user, client)
        return oauth_error('invalid_grant', 'That code has already been used.')
    if code_row.expires_at <= timezone.now():
        return oauth_error('invalid_grant', 'That code has expired.')
    if params.get('redirect_uri', '') != code_row.redirect_uri:
        return oauth_error(
            'invalid_grant', 'redirect_uri does not match the authorization request.'
        )
    if not pkce_matches(params.get('code_verifier', ''), code_row.code_challenge):
        return oauth_error('invalid_grant', 'The PKCE code_verifier does not match.')
    if not _user_may_hold_tokens(code_row.user):
        return oauth_error('invalid_grant', 'This person no longer has access.')

    with transaction.atomic():
        # Claim the code atomically so two simultaneous exchanges can't both win.
        claimed = AuthorizationCode.objects.filter(pk=code_row.pk, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        if not claimed:
            return oauth_error('invalid_grant', 'That code has already been used.')
        return 200, _issue_tokens(client, code_row.user)


def _exchange_refresh(client, params):
    row = (
        OAuthToken.objects.select_related('user')
        .filter(
            token_hash=digest(params.get('refresh_token', '')),
            kind=OAuthToken.REFRESH,
            client=client,
        )
        .first()
    )
    if row is None:
        return oauth_error('invalid_grant', 'That refresh token is not valid.')
    if row.revoked_at is not None:
        # Rotated away already. Whoever is holding it now is not who we gave it to.
        revoke_connection(row.user, client)
        return oauth_error('invalid_grant', 'That refresh token has already been used.')
    if row.expires_at <= timezone.now():
        return oauth_error('invalid_grant', 'That refresh token has expired.')
    if not _user_may_hold_tokens(row.user):
        return oauth_error('invalid_grant', 'This person no longer has access.')

    with transaction.atomic():
        rotated = OAuthToken.objects.filter(pk=row.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        if not rotated:
            return oauth_error('invalid_grant', 'That refresh token has already been used.')
        return 200, _issue_tokens(client, row.user)


def token_endpoint(params):
    """Handle a POST /oauth/token form (a dict-like of strings). Returns (status, body)."""
    client = OAuthClient.objects.filter(client_id=params.get('client_id', '')).first()
    if client is None:
        return oauth_error('invalid_client', 'Unknown client_id.', 401)

    grant = params.get('grant_type')
    if grant == 'authorization_code':
        return _exchange_code(client, params)
    if grant == 'refresh_token':
        return _exchange_refresh(client, params)
    return oauth_error('unsupported_grant_type', 'Use authorization_code or refresh_token.')
