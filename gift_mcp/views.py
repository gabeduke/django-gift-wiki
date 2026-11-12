"""HTTP for the MCP server and its OAuth sign-in.

Everything is behind the MCP_ENABLED feature flag: with it off these paths 404, so
the feature can ship dark and be turned on from /admin/ without a deploy.

Only /oauth/authorize and /connect-ai/ use the browser session (Firebase cookie).
/mcp deliberately accepts bearer tokens and nothing else, so a signed-in browser
tab can't be turned against it.
"""

import json
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from giftwiki.feature_flags import get_mcp_enabled

from . import oauth
from .models import ApiToken, OAuthClient
from .server import handle_body
from .tokens import API_PREFIX, bearer_secret, digest, make_secret, user_for_bearer

logger = logging.getLogger(__name__)

MAX_ACTIVE_API_TOKENS = 10


def enabled_only(view):
    """404 unless the MCP_ENABLED flag is on."""

    def wrapper(request, *args, **kwargs):
        if not get_mcp_enabled():
            raise Http404('Not found')
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    response['Pragma'] = 'no-cache'
    return response


def _cors(response):
    """Open CORS for the discovery, registration and token endpoints (browser-based clients)."""
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


def _json(body, status=200):
    return _cors(_no_store(JsonResponse(body, status=status, safe=False)))


def _preflight():
    return _cors(HttpResponse(status=204))


# --- the MCP endpoint ---------------------------------------------------------


def _challenge(request, presented):
    """401 with the header that starts a client's sign-in (RFC 9728 / MCP authorization)."""
    header = oauth.www_authenticate(request)
    if presented:
        header += ', error="invalid_token"'
    response = JsonResponse(
        {
            'error': 'invalid_token' if presented else 'unauthorized',
            'error_description': (
                "This token isn't valid for the Gift Wiki."
                if presented
                else 'Sign in to the Gift Wiki.'
            ),
        },
        status=401,
    )
    response['WWW-Authenticate'] = header
    return _no_store(response)


@csrf_exempt
@enabled_only
def mcp_endpoint(request):
    """POST /mcp — JSON-RPC. Bearer tokens only; no cookies, no sessions."""
    if request.method != 'POST':
        response = HttpResponse('Method not allowed', status=405, content_type='text/plain')
        response['Allow'] = 'POST'
        return response

    header = request.headers.get('Authorization', '')
    user = user_for_bearer(header)
    if user is None:
        return _challenge(request, presented=bool(bearer_secret(header)))

    status, reply = handle_body(request.body, user, oauth.public_origin(request))
    if reply is None:
        return _no_store(HttpResponse(status=202))
    return _no_store(JsonResponse(reply, status=status, safe=False))


# --- discovery ----------------------------------------------------------------


@enabled_only
def protected_resource_metadata(request):
    if request.method == 'OPTIONS':
        return _preflight()
    response = JsonResponse(oauth.protected_resource_metadata(request))
    response['Cache-Control'] = 'public, max-age=300'
    return _cors(response)


@enabled_only
def authorization_server_metadata(request):
    if request.method == 'OPTIONS':
        return _preflight()
    response = JsonResponse(oauth.authorization_server_metadata(request))
    response['Cache-Control'] = 'public, max-age=300'
    return _cors(response)


# --- dynamic client registration ----------------------------------------------


@csrf_exempt
@enabled_only
def register(request):
    if request.method == 'OPTIONS':
        return _preflight()
    if request.method != 'POST':
        return _json({'error': 'invalid_request', 'error_description': 'POST only.'}, 405)
    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        return _json({'error': 'invalid_client_metadata', 'error_description': 'Send JSON.'}, 400)
    status, body = oauth.register_client(data)
    return _json(body, status)


# --- the sign-in and consent step ---------------------------------------------


def _redirect_back(redirect_uri, state, **params):
    """Send the person back to the app they came from, adding `params` to its return address."""
    if state:
        params['state'] = state
    parts = urlsplit(redirect_uri)
    query = urlencode(parse_qsl(parts.query) + list(params.items()))
    return HttpResponseRedirect(urlunsplit((parts.scheme, parts.netloc, parts.path, query, '')))


@enabled_only
@never_cache
def authorize(request):
    """GET: sign in if needed, then ask. POST: the person's answer."""
    if request.method not in ('GET', 'POST'):
        return HttpResponse('Method not allowed', status=405, content_type='text/plain')

    params = request.POST if request.method == 'POST' else request.GET
    origin = oauth.public_origin(request)
    try:
        auth = oauth.parse_authorize_request(params, request)
    except oauth.AuthorizeFatal as problem:
        return render(
            request, 'gift_mcp/authorize_error.html', {'message': str(problem)}, status=400
        )
    except oauth.AuthorizeRedirect as problem:
        return _redirect_back(
            problem.redirect_uri,
            problem.state,
            error=problem.error,
            error_description=problem.description,
            iss=origin,
        )

    if not request.user.is_authenticated:
        # The normal Google sign-in, then straight back here.
        return redirect_to_login(request.get_full_path())

    if request.method == 'POST':
        if request.POST.get('decision') == 'approve':
            code = oauth.issue_code(auth, request.user)
            logger.info(
                'mcp.authorized',
                extra={'user_id': request.user.pk, 'client': auth.client.client_name},
            )
            return _redirect_back(auth.redirect_uri, auth.state, code=code, iss=origin)
        return _redirect_back(
            auth.redirect_uri,
            auth.state,
            error='access_denied',
            error_description='The person said no.',
            iss=origin,
        )

    return render(
        request,
        'gift_mcp/consent.html',
        {
            'client_name': auth.client.client_name,
            'return_host': urlsplit(auth.redirect_uri).netloc,
            'fields': {
                key: params.get(key, '')
                for key in (
                    'response_type',
                    'client_id',
                    'redirect_uri',
                    'state',
                    'code_challenge',
                    'code_challenge_method',
                    'resource',
                )
            },
        },
    )


@csrf_exempt
@enabled_only
def token(request):
    if request.method == 'OPTIONS':
        return _preflight()
    if request.method != 'POST':
        return _json({'error': 'invalid_request', 'error_description': 'POST only.'}, 405)
    status, body = oauth.token_endpoint(request.POST)
    return _json(body, status)


# --- the person's own page ----------------------------------------------------


@login_required
@enabled_only
@never_cache
def connect(request):
    """Make and revoke personal tokens, and see (and cut off) the apps you've approved."""
    now = timezone.now()
    new_token = None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_token':
            active = ApiToken.objects.filter(user=request.user, revoked_at__isnull=True).count()
            if active >= MAX_ACTIVE_API_TOKENS:
                messages.error(request, "That's the most tokens you can have. Revoke one first.")
                return redirect('gift_mcp:connect_ai')
            name = (request.POST.get('name') or '').strip()[:80] or 'Untitled token'
            new_token = make_secret(API_PREFIX)
            ApiToken.objects.create(
                user=request.user,
                name=name,
                token_hash=digest(new_token),
                token_prefix=new_token[:12],
            )
            # Rendered straight away rather than redirected: this is the only time it is shown.
        elif action == 'revoke_token':
            ApiToken.objects.filter(
                user=request.user, pk=request.POST.get('id') or 0, revoked_at__isnull=True
            ).update(revoked_at=now)
            messages.success(request, 'Token revoked.')
            return redirect('gift_mcp:connect_ai')
        elif action == 'revoke_connection':
            client = OAuthClient.objects.filter(pk=request.POST.get('id') or 0).first()
            if client:
                oauth.revoke_connection(request.user, client)
                messages.success(request, f'{client.client_name} has been disconnected.')
            return redirect('gift_mcp:connect_ai')

    connections = (
        OAuthClient.objects.filter(
            tokens__user=request.user, tokens__revoked_at__isnull=True, tokens__expires_at__gt=now
        )
        .distinct()
        .order_by('client_name')
    )
    return render(
        request,
        'gift_mcp/connect.html',
        {
            'mcp_url': f'{oauth.public_origin(request)}/mcp',
            'tokens': ApiToken.objects.filter(user=request.user, revoked_at__isnull=True),
            'connections': connections,
            'new_token': new_token,
        },
    )
