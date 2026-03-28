"""
WSGI config for giftwiki project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

# OpenTelemetry Imports
_otel_available = False
try:
    from opentelemetry import trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _otel_available = True
except ImportError as e:
    print(f'OpenTelemetry packages not available, tracing disabled: {e}')

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'giftwiki.settings')


def https_app(environ, start_response):
    environ['wsgi.url_scheme'] = 'https'
    return get_wsgi_application()(environ, start_response)


# Initialize OpenTelemetry in Production/Dev
if _otel_available and os.getenv('DJANGO_ENVIRONMENT') in ['prod', 'dev']:
    try:
        # Set up tracer provider
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)

        # Set up Cloud Trace exporter
        cloud_trace_exporter = CloudTraceSpanExporter()
        span_processor = BatchSpanProcessor(cloud_trace_exporter)
        tracer_provider.add_span_processor(span_processor)

        # Instrument Django
        DjangoInstrumentor().instrument()

        # Instrument Psycopg2 (Database)
        Psycopg2Instrumentor().instrument(enable_commenter=True, commenter_options={})

    except Exception as e:
        print(f'Failed to setup OpenTelemetry: {e}')

application = https_app
# application = get_wsgi_application()
