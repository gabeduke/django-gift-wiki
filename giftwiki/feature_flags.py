"""
Feature flags for the Gift Wiki application.

Feature flags allow enabling/disabling functionality without code changes.
Can be set via environment variables in .env file OR from admin interface.

Priority:
1. Database (from admin) - highest priority
2. Environment variables (.env)
3. Default values

Usage:
    from giftwiki.feature_flags import STEWARD_PROXY_ENABLED

    if STEWARD_PROXY_ENABLED:
        # Show steward/proxy fields
"""

import os
import time

# Cache for database flags
_cache = {}
_cache_valid = False
_cache_loaded_at = 0.0

# The cache is per *process*, and admin's _clear_cache() only reaches the one
# process that served the save. Production runs several gunicorn workers per
# instance and several instances, so without an expiry a flag toggled in admin
# reaches exactly one of them and the others answer with the old value until
# they restart. That is not theoretical: it shipped, and the symptom was the
# assistant bubble vanishing mid-conversation whenever a request happened to
# land on a worker that had never seen the flag, because the endpoint returned
# 'disabled' while the page that rendered the bubble had said otherwise.
# A short TTL makes every process converge on its own.
CACHE_TTL_SECONDS = 60


def _clear_cache():
    """Invalidate this process's feature flag cache immediately.

    Other processes catch up within CACHE_TTL_SECONDS — see the note there.
    """
    global _cache_valid
    _cache_valid = False


def _load_from_database():
    """
    Load feature flags from database.
    Returns dict of flag name -> enabled status.
    """
    try:
        from gift.models import FeatureFlag

        flags = FeatureFlag.objects.all()
        return {flag.name: flag.enabled for flag in flags}
    except Exception:
        # Database might not be ready during migrations
        return {}


def get_flag(env_name: str, db_name: str = None, default: bool = False) -> bool:
    """
    Get a feature flag value with multiple sources.

    Priority:
    1. Database (from admin)
    2. Environment variable
    3. Default value

    Args:
        env_name: Environment variable name
        db_name: Database key name (defaults to env_name)
        default: Default value if not set

    Returns:
        Boolean value of the flag
    """
    if db_name is None:
        db_name = env_name

    # Check cache first
    global _cache_valid, _cache_loaded_at
    expired = time.monotonic() - _cache_loaded_at >= CACHE_TTL_SECONDS
    if not _cache_valid or expired:
        # Replace, not merge: a flag whose row has disappeared since the last
        # load (deleted in admin, or rolled back at a test's transaction
        # boundary) must not keep answering with its last cached value.
        _cache.clear()
        _cache.update(_load_from_database())
        _cache_valid = True
        _cache_loaded_at = time.monotonic()

    # Priority 1: Database
    if db_name in _cache:
        return _cache[db_name]

    # Priority 2: Environment variable
    env_value = os.getenv(env_name, '').upper()
    if env_value == 'TRUE' or env_value == 'FALSE':
        return env_value == 'TRUE'

    # Priority 3: Default
    return default


# Module-level valid cache flag
_cache_valid = False


def get_steward_proxy_enabled():
    """Get STEWARD_PROXY_ENABLED flag - uses cached value unless invalidated."""
    return get_flag('STEWARD_PROXY_ENABLED', 'STEWARD_PROXY_ENABLED', default=False)


def get_profile_picture_enabled():
    """Get PROFILE_PICTURE_ENABLED flag - uses cached value unless invalidated."""
    return get_flag('PROFILE_PICTURE_ENABLED', 'PROFILE_PICTURE_ENABLED', default=False)


def get_assistant_enabled():
    """Get ASSISTANT_ENABLED flag - uses cached value unless invalidated."""
    return get_flag('ASSISTANT_ENABLED', 'ASSISTANT_ENABLED', default=False)


# Module-level accessors - use simple environment variables at import time
# Database flags will be checked when needed via get_flag() functions
STEWARD_PROXY_ENABLED = os.getenv('STEWARD_PROXY_ENABLED', 'FALSE').upper() == 'TRUE'


# Convenience dict for template context
def _get_feature_flags_dict():
    """Get current feature flags for templates."""
    return {
        'STEWARD_PROXY_ENABLED': get_steward_proxy_enabled(),
        'PROFILE_PICTURE_ENABLED': get_profile_picture_enabled(),
        'ASSISTANT_ENABLED': get_assistant_enabled(),
    }


def get_context_processor(request):
    """
    Context processor to make feature flags available in templates.

    Add to settings.py TEMPLATE context_processors or use directly in views.
    """
    # Always get fresh values for context
    return {'feature_flags': _get_feature_flags_dict()}
