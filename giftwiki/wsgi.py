"""
WSGI config for giftwiki project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'giftwiki.settings')


def https_app(environ, start_response):
    environ["wsgi.url_scheme"] = "https"
    return get_wsgi_application()(environ, start_response)


application = https_app
# application = get_wsgi_application()
