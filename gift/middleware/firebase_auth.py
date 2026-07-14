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


class FirebaseAuthBackend(ModelBackend):
    """
    Authentication backend that authenticates users based on Firebase session cookies.
    Uses Firebase's recommended session cookie pattern (not ID tokens).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
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

            email = decoded_token.get('email')
            if not email:
                logger.warning('Firebase token verified but no email found')
                return None

            logger.info(f'Firebase token verified successfully for email: {email}')

            # Use email prefix as username
            username = email.split('@')[0]

            # Get or create user
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
                    try:
                        user = User.objects.get(email=email)
                        # Update username if it changed
                        if user.username != username:
                            user.username = username
                            user.save(update_fields=['username'])
                            logger.info(f'Updated username for {email} to: {username}')
                    except User.DoesNotExist:
                        pass

                # If not found by email, try by username
                if not user and username:
                    try:
                        user = User.objects.get(username=username)
                        # Update email if provided and different
                        if user.email != email:
                            user.email = email
                            user.save(update_fields=['email'])
                            logger.info(f'Updated email for {username} to: {email}')
                    except User.DoesNotExist:
                        pass

                # If still not found, create new user
                if not user:
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                    )
                    logger.info(f'Created new user from Firebase auth: {username} ({email})')

                # Update email if provided and different (only if user already existed)
                if email and user.email != email:
                    user.email = email
                    user.save(update_fields=['email'])

            except Exception as e:
                logger.error(f'Error getting or creating user: {e}', exc_info=True)
                return None

            return user

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
        """
        Check if a user's email is in the allowlist.
        Returns True if email is in allowlist.
        """
        if not email:
            return False
            
        email = email.lower()

        # Check database allowlist
        try:
            from gift.models import AllowedEmail
            if AllowedEmail.objects.filter(email__iexact=email).exists():
                return True
        except Exception as e:
            logger.error(f'Error checking database allowlist: {e}')

        # Fallback to env allowlist
        return email in self.allowed_users

    def __call__(self, request):
        # Skip authentication for health check, metrics, and auth pages
        if request.path in [
            '/health/',
            '/metrics',
            '/metrics/',
            '/auth.html',
            '/sessionLogin',
            '/privacy/',
            '/data-deletion/',
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

        # Verify session cookie and authenticate user
        backend = FirebaseAuthBackend()
        authenticated_user = backend.authenticate(request)

        if not authenticated_user:
            # Session cookie invalid or expired - allow request but user won't be authenticated
            logger.debug(f'Firebase session cookie verification failed for {request.path}')
            return self.get_response(request)

        email = authenticated_user.email

        # Check allowlist before authenticating
        if not self._is_user_allowed(email):
            logger.warning(
                f'Access denied for user {email} - not in allowlist. Request path: {request.path}'
            )
            return HttpResponseForbidden(
                'Access denied. Your email address is not authorized to access this application. '
                'Please contact the administrator to be added to the allowlist.'
            )

        try:
            # Check if user is already authenticated in session to avoid redundant DB queries
            if hasattr(request, 'user') and request.user.is_authenticated:
                # Check if it's the same user
                if request.user.email == email:
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
