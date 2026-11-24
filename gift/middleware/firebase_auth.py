"""
Firebase Authentication Middleware

This middleware handles authentication via Firebase Authentication.
It reads the Firebase ID token from the __session cookie, verifies it,
and automatically creates/authenticates users in Django.

Supports allowlist functionality via DJANGO_ALLOWED_USERS environment variable (comma-separated emails).
"""

import logging
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseForbidden

logger = logging.getLogger(__name__)
User = get_user_model()

# Firebase Admin SDK - lazy import to avoid errors if not configured
_firebase_app = None
_firebase_auth = None


def _get_firebase_auth():
    """Lazy initialization of Firebase Admin SDK."""
    global _firebase_app, _firebase_auth
    if _firebase_auth is not None:
        return _firebase_auth

    try:
        import firebase_admin
        from firebase_admin import auth, credentials

        # Initialize Firebase Admin SDK if not already initialized
        if not firebase_admin._apps:
            # Try to use default credentials (works on Cloud Run with service account)
            # Or use GOOGLE_APPLICATION_CREDENTIALS environment variable
            try:
                cred = credentials.ApplicationDefault()
                _firebase_app = firebase_admin.initialize_app(cred)
                logger.info('Firebase Admin SDK initialized with ApplicationDefault credentials')
            except Exception as e:
                logger.warning(f'Could not initialize Firebase with ApplicationDefault: {e}')
                # Try with explicit credentials file if provided
                cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
                if cred_path and os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    _firebase_app = firebase_admin.initialize_app(cred)
                    logger.info(
                        f'Firebase Admin SDK initialized with credentials file: {cred_path}'
                    )
                else:
                    logger.warning(
                        'Firebase Admin SDK not configured - Firebase auth will not work. '
                        'Make sure the Cloud Run service account has Firebase Admin permissions.'
                    )
                    return None
        else:
            logger.info('Firebase Admin SDK already initialized')

        _firebase_auth = auth
        return _firebase_auth
    except ImportError:
        logger.error(
            'Firebase Admin SDK not installed - Firebase auth will not work. '
            'Install with: pip install firebase-admin'
        )
        return None
    except Exception as e:
        logger.error(f'Error initializing Firebase Admin SDK: {e}', exc_info=True)
        return None


class SignInRejected(Exception):
    """A genuine Firebase token that still may not sign in. `message` is shown to the person."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


NOT_VERIFIED_MESSAGE = (
    'Access denied. This email address has not been verified. '
    'Use "Sign in with Google", or "Forgot password?" on the sign-in page — '
    'opening the link it emails you confirms the address is yours.'
)
NOT_ALLOWED_MESSAGE = (
    'Access denied. Your email address is not authorized to access this application. '
    'Please contact the administrator to be added to the allowlist.'
)


def require_verified_email(decoded_token):
    """The email a decoded Firebase token proves its holder owns.

    Returns None when the token carries no email. Raises SignInRejected when
    Firebase has not verified it: anyone can register an email/password
    account for an address that isn't theirs, so an unverified email proves
    nothing. Google sign-ins always arrive verified.
    """
    email = decoded_token.get('email')
    if not email:
        return None
    if decoded_token.get('email_verified') is not True:
        logger.warning(f'Refusing sign-in for {email}: email not verified by Firebase')
        raise SignInRejected(NOT_VERIFIED_MESSAGE)
    return email


def is_email_allowed(email):
    """Whether this address is on the allowlist (database first, then env)."""
    if not email:
        return False

    email = email.lower()

    try:
        from gift.models import AllowedEmail

        if AllowedEmail.objects.filter(email__iexact=email).exists():
            return True
    except Exception as e:
        logger.error(f'Error checking database allowlist: {e}')

    allowed_users_env = os.getenv('DJANGO_ALLOWED_USERS', '')
    return email in {e.strip().lower() for e in allowed_users_env.split(',') if e.strip()}


def _free_username(username):
    """`username`, or the first numbered variant nobody holds yet."""
    candidate, n = username, 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f'{username}{n}'
    return candidate


def resolve_user_for_email(email):
    """Map a verified, allowlisted Firebase email onto a Django account.

    Callers must check `require_verified_email` and `is_email_allowed` first:
    this creates an account when none matches.

    An account's email is its identity and is never overwritten here. The only
    account matched by username is one with no email at all (wiki imports,
    kids a parent created) — it is claimed once and from then on resolves by
    email. Returns None if the lookup fails outright.
    """
    # Use email prefix as username
    username = email.split('@')[0]

    user = None
    try:
        # Check for linked email first
        try:
            from gift.models import LinkedEmail

            linked = LinkedEmail.objects.filter(email__iexact=email).first()
            if linked:
                user = linked.user
                logger.info(f'Found linked email for {email}, authenticating as {user.username}')
        except Exception as e:
            logger.error(f'Error checking linked emails: {e}')

        # If not linked, proceed with regular lookup
        if not user:
            # First try to find by email (most reliable identifier)
            users_by_email = User.objects.filter(email__iexact=email)
            if users_by_email.exists():
                if users_by_email.count() > 1:
                    logger.warning(
                        f'Multiple users found with email {email}. Using the first one.'
                    )
                user = users_by_email.first()
                # Freshen the username, but never onto one somebody else holds: a
                # parent assigning their kid an address whose prefix is taken would
                # otherwise trip the unique constraint and lock the kid out.
                if user.username != username:
                    if User.objects.filter(username=username).exclude(pk=user.pk).exists():
                        logger.info(
                            f'Keeping username {user.username} for {email}: '
                            f'{username} is already taken'
                        )
                    else:
                        user.username = username
                        user.save(update_fields=['username'])
                        logger.info(f'Updated username for {email} to: {username}')

        # Not found by email: an account that has no email yet may be claimed by
        # its username. One that has an email belongs to that address — a
        # matching prefix (smith@yahoo.com vs smith@gmail.com) is someone else.
        if not user and username:
            user = User.objects.filter(
                username=username, email='', is_staff=False, is_superuser=False
            ).first()
            if user:
                user.email = email
                user.save(update_fields=['email'])
                logger.info(f'Account {username} had no email; claimed by {email}')

        # If still not found, create new user
        if not user:
            user = User.objects.create_user(
                username=_free_username(username),
                email=email,
            )
            logger.info(f'Created new user from Firebase auth: {user.username} ({email})')

    except Exception as e:
        logger.error(f'Error getting or creating user: {e}', exc_info=True)
        return None

    return user


class FirebaseAuthBackend(ModelBackend):
    """
    Authentication backend that authenticates users based on Firebase session cookies.
    Uses Firebase's recommended session cookie pattern (not ID tokens).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            email = self.verified_email(request)
        except SignInRejected:
            return None
        if not email or not is_email_allowed(email):
            return None
        return resolve_user_for_email(email)

    def verified_email(self, request):
        """The verified email behind this request's Firebase cookie, or None.

        Reads only — no account is looked up or created. Raises SignInRejected
        when the cookie is genuine but its email is unverified.
        """
        if not request:
            return None

        # Get Firebase session cookie (Firebase Hosting forwards __session cookie)
        session_cookie = request.COOKIES.get('__session')
        if not session_cookie:
            return None

        # Verify Firebase session cookie (not ID token)
        firebase_auth = _get_firebase_auth()
        if not firebase_auth:
            logger.warning('Firebase Admin SDK not available - cannot verify session cookies')
            return None

        try:
            # Verify session cookie (check_revoked=False for performance)
            # Python Firebase Admin SDK method signature: verify_session_cookie(session_cookie, check_revoked=False)
            try:
                decoded_token = firebase_auth.verify_session_cookie(
                    session_cookie, check_revoked=False
                )
                logger.info('Firebase session cookie verified successfully')
            except (ValueError, firebase_auth.InvalidSessionCookieError) as e:
                # Fallback: Try verifying as ID token
                # This handles cases where the client might have set an ID token as the cookie
                # or if the Cloud Functions environment creates ID tokens (emulator behavior)
                # This is necessary for the current giftwiki-dev environment
                logger.warning(
                    f'Session cookie verification failed ({e}), attempting ID token verification fallback'
                )
                try:
                    decoded_token = firebase_auth.verify_id_token(
                        session_cookie, check_revoked=False
                    )
                    logger.info('Firebase ID token verified successfully (fallback)')
                except Exception as id_token_error:
                    logger.warning(f'ID token verification fallback also failed: {id_token_error}')
                    # Re-raise the original error or return None
                    return None

            email = require_verified_email(decoded_token)
            if not email:
                logger.warning('Firebase token verified but no email found')
                return None

            logger.info(f'Firebase token verified successfully for email: {email}')
            return email

        except SignInRejected:
            raise
        except Exception as e:
            logger.warning(f'Firebase token verification failed: {e}', exc_info=True)
            return None


class FirebaseAuthMiddleware:
    """
    Middleware that automatically authenticates users based on Firebase session cookies.
    This runs before Django's AuthenticationMiddleware.

    The middleware reads the Firebase session cookie from the __session cookie,
    verifies it with Firebase Admin SDK, and authenticates the user in Django.

    Uses Firebase's recommended session cookie pattern (not ID tokens).

    Allowlist Support:
    - Set DJANGO_ALLOWED_USERS environment variable to a comma-separated list of email addresses
    - Only users whose email is in the allowlist will be authenticated
    - If DJANGO_ALLOWED_USERS is not set, uses default allowlist
    """

    def __init__(self, get_response):
        self.get_response = get_response
        allowed_users_env = os.getenv('DJANGO_ALLOWED_USERS', '').strip()
        if allowed_users_env:
            self.allowed_users = {
                email.strip().lower() for email in allowed_users_env.split(',') if email.strip()
            }
            logger.info(f'Allowlist loaded with {len(self.allowed_users)} allowed users from env')
        else:
            self.allowed_users = set()
            logger.info('No DJANGO_ALLOWED_USERS environment variable set. Relying solely on database.')

    def _is_user_allowed(self, email):
        """Whether this email is on the allowlist."""
        return is_email_allowed(email)

    def __call__(self, request):
        # Skip authentication for the liveness check and auth pages. /health/db/
        # and /metrics never get here: their middleware answers them first.
        if request.path in [
            '/health/',
            '/auth.html',
            '/sessionLogin',
            '/privacy/',
            '/data-deletion/',
            '/robots.txt',
            # PWA plumbing the browser fetches on its own; none of it is per-user
            '/manifest.webmanifest',
            '/sw.js',
            '/offline/',
        ] or request.path.startswith('/auth.html'):
            return self.get_response(request)

        # Check for Firebase session cookie (Firebase Hosting forwards __session cookie)
        session_cookie = request.COOKIES.get('__session')

        # Log cookie information for debugging
        all_cookies = list(request.COOKIES.keys())
        cookie_header = request.META.get('HTTP_COOKIE', '')
        logger.info(
            f'Request to {request.path} - Cookies present: {all_cookies}, Has __session: {bool(session_cookie)}, Cookie header length: {len(cookie_header)}'
        )

        if session_cookie:
            logger.info(f'Found __session cookie, length: {len(session_cookie)}')

        if not session_cookie:
            # No session cookie found - this is normal for unauthenticated requests
            # If user is already authenticated in Django session, allow the request
            if hasattr(request, 'user') and request.user.is_authenticated:
                logger.info(
                    f'User {request.user.email} already authenticated in Django session for {request.path}'
                )
                return self.get_response(request)
            logger.info(
                f'No Firebase session cookie found for {request.path} - all cookies: {all_cookies}'
            )
            return self.get_response(request)

        # Verify the cookie, then the allowlist — and only then touch accounts,
        # so a refused sign-in never creates or changes a WikiUser.
        try:
            email = FirebaseAuthBackend().verified_email(request)
        except SignInRejected as rejection:
            return HttpResponseForbidden(rejection.message)

        if not email:
            # Session cookie invalid or expired - allow request but user won't be authenticated
            logger.debug(f'Firebase session cookie verification failed for {request.path}')
            return self.get_response(request)

        if not self._is_user_allowed(email):
            logger.warning(
                f'Access denied for user {email} - not in allowlist. Request path: {request.path}'
            )
            return HttpResponseForbidden(NOT_ALLOWED_MESSAGE)

        authenticated_user = resolve_user_for_email(email)
        if not authenticated_user:
            return self.get_response(request)

        try:
            # Check if user is already authenticated in session to avoid redundant DB queries
            if hasattr(request, 'user') and request.user.is_authenticated:
                # Check if it's the same user
                if request.user.pk == authenticated_user.pk:
                    return self.get_response(request)

            # Login the user (creates session)
            # Since Firebase Hosting strips cookies, we cannot rely on Django sessions being persisted.
            # We set request.user directly for this request only.
            request.user = authenticated_user

            # Manually trigger login signal if needed, but for now just setting the user is enough
            logger.info(
                f'Authenticated user via Firebase (stateless): {authenticated_user.username} ({email})'
            )
        except Exception as e:
            logger.error(f'Error authenticating user: {e}', exc_info=True)

        return self.get_response(request)
