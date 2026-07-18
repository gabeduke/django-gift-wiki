#!/bin/sh

# Create the staticfiles directory if it doesn't exist
mkdir -p /app/staticfiles

# Log environment info for debugging
echo "=== Container Startup ==="
echo "K_SERVICE: ${K_SERVICE:-not set}"
echo "PORT: ${PORT:-not set (will use 8000)}"
echo "DJANGO_SETTINGS_MODULE: ${DJANGO_SETTINGS_MODULE:-not set}"
echo "DJANGO_DB_HOST: ${DJANGO_DB_HOST:-not set}"

# Detect if we're running on Cloud Run (has K_SERVICE env var)
# With Cloud Run Jobs, we no longer run migrations here
if [ -n "$K_SERVICE" ]; then
    echo "Running on Cloud Run - expecting migrations to be handled by Cloud Run Job..."
    # Fail fast if the migration job did not apply all migrations. This prevents
    # the service from starting in an inconsistent state and serving 500 errors.
    echo "Checking for unapplied migrations..."
    if ! python manage.py migrate --check --noinput; then
        echo "ERROR: Unapplied migrations detected! The migration job may have failed. Cannot start server."
        exit 1
    fi
    echo "Migrations are up to date"
else
    echo "Running on Kubernetes - skipping migrations (handled by initContainer)..."
fi

# Collect static files (if needed)
# Only run if not using S3, or if using S3 and STATIC_ROOT is set
echo "Collecting static files..."
if ! python manage.py collectstatic --noinput; then
    echo "WARNING: collectstatic failed, but continuing (may not be critical if using S3)..."
else
    echo "Static files collected successfully"
fi

# Validate PORT is set (Cloud Run requirement)
if [ -z "$PORT" ]; then
    echo "WARNING: PORT environment variable not set, using default 8000"
    echo "This may cause issues on Cloud Run - PORT should be set automatically"
    PORT=8000
fi

# Test database connection before starting server
echo "Testing database connection..."
if ! python manage.py check --database default 2>/dev/null; then
    echo "WARNING: Django check failed, but attempting to test connection directly..."
    if ! python -c "
import os
import sys
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'giftwiki.settings')
try:
    django.setup()
    from django.db import connections
    conn = connections['default']
    with conn.cursor() as cursor:
        cursor.execute('SELECT 1')
    print('Database connection successful')
except Exception as e:
    print(f'Database connection failed: {e}')
    sys.exit(1)
"; then
        echo "ERROR: Database connection test failed! Cannot start server."
        exit 1
    fi
else
    echo "Database connection successful"
fi

# Skip superuser creation - handled by migration job or manual setup
# python manage.py createsuperusers

# Start the Gunicorn server
# Cloud Run injects the PORT environment variable
echo "Starting Gunicorn on 0.0.0.0:${PORT}..."
exec gunicorn --bind 0.0.0.0:${PORT} --access-logfile - --error-logfile - --log-level info giftwiki.wsgi:application
