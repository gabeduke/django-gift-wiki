"""
Cloud Run Host Validation Middleware

This middleware patches Django's ALLOWED_HOSTS validation to allow Cloud Run domains.
Since Django's CommonMiddleware validates ALLOWED_HOSTS before our middleware runs,
we need to patch the validation function itself.
"""

import logging
import os

from django.conf import settings
from django.core.exceptions import DisallowedHost

logger = logging.getLogger(__name__)

# Store the original get_host method before patching
_original_get_host = None
_patched = False


class CloudRunHostValidationMiddleware:
    """
    Middleware that patches Django's host validation to allow Cloud Run domains.
    This must run before CommonMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.cloud_run_domains = ['.run.app', '.a.run.app']

        # Patch Django's host validation if we're on Cloud Run (only once)
        global _patched
        if os.getenv('K_SERVICE') and not _patched:
            self._patch_host_validation()
            logger.info("Cloud Run host validation patch applied", extra={"service": os.getenv('K_SERVICE')})
            _patched = True

    def _patch_host_validation(self):
        """Patch Django's host validation to allow Cloud Run domains."""
        from django.http import HttpRequest

        global _original_get_host

        # Store the original method if not already stored
        if _original_get_host is None:
            _original_get_host = HttpRequest.get_host

        def patched_get_host(request_self):
            """Patched get_host that allows Cloud Run domains."""
            # Get the raw host from headers directly (bypass validation)
            host_header = request_self.META.get('HTTP_HOST', '')
            if not host_header:
                # Fallback to SERVER_NAME if HTTP_HOST not available
                host_header = request_self.META.get('SERVER_NAME', '')

            host_without_port = host_header.split(':')[0]

            # Check if it's a Cloud Run domain first - if so, allow it
            if any(host_without_port.endswith(domain) for domain in self.cloud_run_domains):
                return host_header

            # If ALLOWED_HOSTS is empty and we're on Cloud Run, allow it
            if os.getenv('K_SERVICE') and not settings.ALLOWED_HOSTS:
                return host_header

            # Otherwise use the original validation
            try:
                return _original_get_host(request_self)
            except DisallowedHost:
                # If original validation fails but we're on Cloud Run, allow it anyway
                if os.getenv('K_SERVICE'):
                    logger.warning("DisallowedHost bypassed for Cloud Run request", extra={"host": host_header})
                    return host_header
                raise

        # Monkey patch the method
        HttpRequest.get_host = patched_get_host

    def __call__(self, request):
        return self.get_response(request)
