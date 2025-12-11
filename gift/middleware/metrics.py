"""
Middleware to handle Prometheus metrics endpoint early in the request chain.
This bypasses authentication, CSRF, and other security checks for the metrics endpoint.
"""
from django.http import HttpResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


class MetricsMiddleware:
    """
    Middleware that handles the /metrics endpoint early in the request chain.
    This ensures metrics are accessible without authentication or CSRF checks.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle metrics endpoint early, before any other middleware
        if request.path in ['/metrics', '/metrics/']:
            try:
                return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
            except ImportError:
                return HttpResponse("Prometheus client not installed", status=503)
        
        return self.get_response(request)

