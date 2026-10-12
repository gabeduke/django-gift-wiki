import json

from django.conf import settings
from django.utils.safestring import mark_safe

from gift.models import ChangelogEntry
from gift.themes import DEFAULT_THEME, theme_colour, theme_for


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


def unseen_changelog_count(request):
    """
    Adds unseen_changelog_count for the "What's New" nav badge.
    The table is tiny, so a plain COUNT per request is fine — no caching.
    """
    if not request.user.is_authenticated:
        return {'unseen_changelog_count': 0}
    return {
        'unseen_changelog_count': ChangelogEntry.objects.filter(is_active=True)
        .exclude(seen_by=request.user)
        .count()
    }


def theme(request):
    """The signed-in user's colour theme, for <html data-theme> and the
    browser's theme-color. Reads the already-loaded user — no extra query."""
    key = theme_for(request.user) if request.user.is_authenticated else DEFAULT_THEME
    return {
        'theme': key if key != DEFAULT_THEME else '',
        'theme_colour': theme_colour(key),
    }
