"""
Prometheus metrics middleware for Django.

Tracks request duration, count, and status codes for Prometheus monitoring.
"""
import os
import time
from prometheus_client import Counter, Histogram, Gauge
from django.db import connections
from django.core.cache import cache

# Get environment from env var (defaults to 'unknown' if not set)
ENVIRONMENT = os.getenv('DJANGO_ENVIRONMENT', 'unknown')

# Request metrics - includes environment label for differentiation
http_requests_total = Counter(
    'wikileet_http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status_code', 'environment']
)

http_request_duration_seconds = Histogram(
    'wikileet_http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint', 'environment'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf'))
)

# Database metrics
db_query_duration_seconds = Histogram(
    'wikileet_db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation', 'table']
)

db_connections_active = Gauge(
    'wikileet_db_connections_active',
    'Number of active database connections'
)

# Cache metrics
cache_operations_total = Counter(
    'wikileet_cache_operations_total',
    'Total number of cache operations',
    ['operation', 'status']
)

cache_operation_duration_seconds = Histogram(
    'wikileet_cache_operation_duration_seconds',
    'Cache operation duration in seconds',
    ['operation']
)


class PrometheusMiddleware:
    """
    Middleware to track Prometheus metrics for Django requests.
    
    Tracks:
    - Request count and duration
    - HTTP status codes
    - Database query metrics
    - Cache operation metrics
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Exclude these paths from metrics to reduce noise
        self.excluded_paths = [
            '/health/',
            '/metrics',
            '/static/',
            '/media/',
            '/__debug__/',
        ]

    def __call__(self, request):
        # Skip metrics for excluded paths
        if any(request.path.startswith(path) for path in self.excluded_paths):
            return self.get_response(request)
        
        # Track request start time
        start_time = time.time()
        
        # Get response
        response = self.get_response(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Normalize endpoint (remove IDs, etc.)
        endpoint = self._normalize_path(request.path)
        
        # Record metrics with environment label
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
            environment=ENVIRONMENT
        ).inc()
        
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=endpoint,
            environment=ENVIRONMENT
        ).observe(duration)
        
        return response
    
    def _normalize_path(self, path):
        """
        Normalize paths to reduce cardinality in metrics.
        Replaces IDs and UUIDs with placeholders.
        """
        import re
        # Replace numeric IDs
        path = re.sub(r'/\d+/', '/<id>/', path)
        # Replace UUIDs
        path = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/',
            '/<uuid>/',
            path,
            flags=re.IGNORECASE
        )
        # Limit path length
        if len(path) > 100:
            path = path[:100]
        return path

