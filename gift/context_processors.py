import json

from django.conf import settings
from django.utils.safestring import mark_safe


def google_analytics(request):
    """
    Adds firebase_config to the context for global usage (e.g. analytics).
    """
    config = getattr(settings, 'FIREBASE_CLIENT_CONFIG', {})
    return {
        'firebase_config_json': mark_safe(json.dumps(config)),
        'GOOGLE_ANALYTICS_ID': getattr(
            settings, 'GOOGLE_ANALYTICS_ID', None
        ),  # Keep this for backward compat if needed
    }
