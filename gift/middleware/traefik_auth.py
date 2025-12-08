"""
Traefik Forward Auth Middleware

This middleware handles authentication via Traefik's forward auth.
It reads X-Forwarded-User and X-Forwarded-Email headers set by Traefik
and automatically creates/authenticates users in Django.
"""
import logging
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import login

logger = logging.getLogger(__name__)
User = get_user_model()


class TraefikAuthBackend(ModelBackend):
    """
    Authentication backend that authenticates users based on Traefik forward auth headers.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not request:
            return None
        
        # Get user info from Traefik headers
        forwarded_user = request.META.get('HTTP_X_FORWARDED_USER')
        forwarded_email = request.META.get('HTTP_X_FORWARDED_EMAIL')
        
        if not forwarded_user:
            return None
        
        # Get or create user based on Traefik username
        try:
            user = User.objects.get(username=forwarded_user)
        except User.DoesNotExist:
            # Create new user from Traefik auth
            user = User.objects.create_user(
                username=forwarded_user,
                email=forwarded_email or f'{forwarded_user}@leetserve.com',
                # No password needed - authentication is handled by Traefik
            )
            logger.info(f"Created new user from Traefik auth: {forwarded_user}")
        
        # Update email if provided and different
        if forwarded_email and user.email != forwarded_email:
            user.email = forwarded_email
            user.save(update_fields=['email'])
        
        return user


class TraefikAuthMiddleware:
    """
    Middleware that automatically authenticates users based on Traefik forward auth headers.
    This runs before Django's AuthenticationMiddleware.
    
    Traefik forward auth sets these headers:
    - X-Forwarded-User: The authenticated username
    - X-Forwarded-Email: The authenticated user's email (if available)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip authentication for health check endpoint
        if request.path == '/health/':
            return self.get_response(request)
        
        # Get user info from Traefik headers
        # We run before AuthenticationMiddleware, so we authenticate based on headers
        # Traefik forward auth sets these headers (check multiple possible header names)
        forwarded_user = (
            request.META.get('HTTP_X_FORWARDED_USER') or
            request.META.get('X-Forwarded-User') or
            request.META.get('HTTP_REMOTE_USER') or
            request.META.get('Remote-User')
        )
        forwarded_email = (
            request.META.get('HTTP_X_FORWARDED_EMAIL') or
            request.META.get('X-Forwarded-Email') or
            request.META.get('HTTP_REMOTE_EMAIL') or
            request.META.get('Remote-Email')
        )
        
        # Debug logging to see what headers we're receiving
        if not forwarded_user:
            # Log all headers that might contain user info (for debugging)
            auth_headers = {k: v for k, v in request.META.items() 
                          if 'USER' in k.upper() or 'EMAIL' in k.upper() or 'AUTH' in k.upper()}
            logger.debug(f"No forwarded user header found. Available auth-related headers: {auth_headers}")
        
        if forwarded_user:
            try:
                # Get or create user
                try:
                    user = User.objects.get(username=forwarded_user)
                    # Update email if provided and different
                    if forwarded_email and user.email != forwarded_email:
                        user.email = forwarded_email
                        user.save(update_fields=['email'])
                except User.DoesNotExist:
                    # Create new user from Traefik auth
                    user = User.objects.create_user(
                        username=forwarded_user,
                        email=forwarded_email or f'{forwarded_user}@leetserve.com',
                    )
                    logger.info(f"Created new user from Traefik auth: {forwarded_user}")
                
                # Authenticate the user for this request using the backend
                backend = TraefikAuthBackend()
                authenticated_user = backend.authenticate(request, username=forwarded_user)
                if authenticated_user:
                    # Login the user (creates session)
                    # This will set request.user for subsequent middleware
                    login(request, authenticated_user, backend='gift.middleware.traefik_auth.TraefikAuthBackend')
                    logger.info(f"Successfully authenticated user via Traefik: {forwarded_user} (email: {forwarded_email})")
                else:
                    logger.warning(f"Backend authentication returned None for user: {forwarded_user}")
            except Exception as e:
                logger.error(f"Error authenticating user from Traefik headers: {e}", exc_info=True)

        return self.get_response(request)

