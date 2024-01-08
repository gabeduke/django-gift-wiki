from django.db import connections
from django.http import HttpResponse, HttpResponseServerError

class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/health/':
            try:
                # Check database connection
                connection = connections['default']
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return HttpResponse('ok')
            except Exception as e:
                # If any exception occurred while checking the database, return a server error
                return HttpResponseServerError('Database check failed')
        return self.get_response(request)