"""
Middleware to handle the Prometheus metrics endpoint early in the request chain.
It runs before sessions, CSRF and authentication, so it gates itself: metrics
are operator-only (see `ops_token`) and anyone else gets a 404.
"""

from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from gift.middleware.ops_token import not_found, ops_request_allowed

METRICS_PATHS = ('/metrics', '/metrics/')


class MetricsMiddleware:
    """Serve `/metrics` to an operator holding `OPS_TOKEN`, 404 to anyone else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in METRICS_PATHS:
            if not ops_request_allowed(request):
                return not_found()
            return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

        return self.get_response(request)
