"""Progressive Web App support: the manifest, the service worker, versioned assets.

Static files here are served at fixed, unhashed URLs: `STATICFILES_STORAGE` was
removed in Django 5.1, so the manifest storage it names is silently ignored.
Without a fingerprint in the URL an installed app would keep its old icon
forever and a service worker couldn't tell a changed file from a cached one, so
everything the PWA references goes through `versioned_static`, which appends a
hash of the file's contents.

None of this touches the database. The manifest and service worker are fetched
by the browser on its own schedule, and the Firebase middleware lets them
through without verifying a session for the same reason — see its skip list
in `FirebaseAuthMiddleware.__call__` and the Neon notes in CLAUDE.md.
"""

import hashlib
from functools import lru_cache

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.urls import reverse

APP_NAME = 'Wikileet'
THEME_COLOR = '#2d6a4f'  # --brand
BACKGROUND_COLOR = '#f7f4ef'  # --bg-page

# Fetched when the service worker installs, so the app can still open (to an
# offline page) with no connection. Keep it small: every install downloads it.
PRECACHE_STATIC = [
    'brand/logo.svg',
    'brand/icon-192.png',
]


def _hash_static(path):
    found = finders.find(path)
    if not found:
        return ''
    with open(found, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:12]


_hash_static_cached = lru_cache(maxsize=None)(_hash_static)


def static_version(path):
    """Short content hash of a static file, or '' if it can't be found.

    Cached for the life of the process in production — a deploy is a new
    process, which is exactly when the files can change. In development files
    change under a running server, so it's recomputed every time.
    """
    if settings.DEBUG:
        return _hash_static(path)
    return _hash_static_cached(path)


def versioned_static(path):
    """`static(path)` with a content hash appended, so a changed file gets a new URL."""
    version = static_version(path)
    url = static(path)
    return f'{url}?v={version}' if version else url


def build_manifest():
    """The web app manifest, as a dict ready for JSON."""
    home = reverse('gift:home')
    return {
        'id': home,
        'name': APP_NAME,
        'short_name': APP_NAME,
        'description': 'Family wishlists — add gift ideas the moment they come to mind.',
        'start_url': f'{home}?source=pwa',
        'scope': home,
        'display': 'standalone',
        'theme_color': THEME_COLOR,
        'background_color': BACKGROUND_COLOR,
        'categories': ['lifestyle', 'shopping'],
        'icons': [
            {
                'src': versioned_static('brand/icon-192.png'),
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': versioned_static('brand/icon-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': versioned_static('brand/icon-maskable-192.png'),
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'maskable',
            },
            {
                'src': versioned_static('brand/icon-maskable-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'maskable',
            },
        ],
        # Long-press the home-screen icon (Android, desktop Chrome)
        'shortcuts': [
            {
                'name': 'Add a gift idea',
                'short_name': 'Add idea',
                'description': "Drop an item on someone's list",
                'url': f'{home}?quick_add=1',
                'icons': [{'src': versioned_static('brand/icon-192.png'), 'sizes': '192x192'}],
            },
            {
                'name': 'My Purchases',
                'short_name': 'Purchases',
                'url': reverse('gift:my_purchases'),
            },
            {
                'name': 'My Lists',
                'short_name': 'My Lists',
                'url': reverse('gift:account'),
            },
        ],
        # Android: "Share" from a shopping app or the browser lands in quick add
        'share_target': {
            'action': reverse('gift:share_target'),
            'method': 'GET',
            'params': {'title': 'title', 'text': 'text', 'url': 'url'},
        },
    }


def service_worker_version():
    """Changes whenever anything the worker precaches changes, so it reinstalls."""
    parts = [static_version(path) for path in PRECACHE_STATIC]
    parts.append(static_version('js/sw.js'))
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:12]
