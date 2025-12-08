#!/bin/sh

# Create the staticfiles directory if it doesn't exist
mkdir -p /app/staticfiles

# Skip migrations - they should be run via the migration job before pods start
# This allows multiple pods to start without migration conflicts
# python manage.py migrate --noinput

# Collect static files (if needed)
# Only run if not using S3, or if using S3 and STATIC_ROOT is set
python manage.py collectstatic --noinput || echo "Warning: collectstatic failed, continuing..."

# Skip superuser creation - handled by migration job
# python manage.py createsuperusers

# Start the Gunicorn server
gunicorn --bind 0.0.0.0:8000 giftwiki.wsgi:application
