import logging

from django.db import connections
from django.http import HttpResponse, HttpResponseServerError

# Get the logger for database queries
db_logger = logging.getLogger('django.db.backends')
logger = logging.getLogger(__name__)

LIVENESS_PATH = '/health/'
READINESS_PATH = '/health/db/'


class HealthCheckMiddleware:
    """Serve the liveness and readiness endpoints.

    `/health/` answers "is this process up?" and deliberately does not touch the
    database. Probes hit it every few seconds, and running `SELECT 1` on each hit
    kept resetting Neon's autosuspend timer — the compute never slept, which is
    what put the project on a paid plan.

    `/health/db/` is the real connectivity check. Poll it sparingly: anything
    more frequent than Neon's suspend timeout holds the compute awake again.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == LIVENESS_PATH:
            return HttpResponse('ok')
        if request.path == READINESS_PATH:
            return self._check_database()
        return self.get_response(request)

    def _check_database(self):
        # Temporarily suppress SQL query logging to keep the check out of the logs
        old_level = db_logger.level
        try:
            db_logger.setLevel(logging.WARNING)

            connection = connections['default']
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')

            return HttpResponse('ok')
        except Exception as e:
            # Log the actual error for debugging (but don't expose details in response)
            logger.error(f'Health check failed: {type(e).__name__}: {str(e)}', exc_info=True)
            return HttpResponseServerError('Database check failed')
        finally:
            # Always restore the original logging level
            db_logger.setLevel(old_level)
