from django.db import connections
from django.http import HttpResponse, HttpResponseServerError
import logging

# Get the logger for database queries
db_logger = logging.getLogger('django.db.backends')
logger = logging.getLogger(__name__)

class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/health/':
            # Temporarily suppress SQL query logging for health checks to reduce log noise
            # Health checks run every 5 seconds (readiness) and 20 seconds (liveness)
            old_level = db_logger.level
            try:
                # Suppress DEBUG level logs (which include SQL queries) for health checks
                db_logger.setLevel(logging.WARNING)
                
                # Check database connection
                connection = connections['default']
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                
                return HttpResponse('ok')
            except Exception as e:
                # Log the actual error for debugging (but don't expose details in response)
                logger.error(f"Health check failed: {type(e).__name__}: {str(e)}", exc_info=True)
                # If any exception occurred while checking the database, return a server error
                return HttpResponseServerError('Database check failed')
            finally:
                # Always restore the original logging level
                db_logger.setLevel(old_level)
        return self.get_response(request)
