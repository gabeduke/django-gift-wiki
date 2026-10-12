"""Colour themes people can pick for themselves.

A theme is a single brand colour. Everything else — hover, tints, borders,
the logo's constellation lines — is derived from it in CSS (custom.css,
"THEMES"), so adding one is a line here and a line there. tests/api/test_themes.py
keeps the two in step.

Every colour clears WCAG AA both for white text on it (buttons) and for it
on the cream page (links). The app icon on the home screen doesn't change:
the manifest is shared, and iOS freezes the icon at install anyway.
"""

DEFAULT_THEME = 'forest'

# key -> (label, brand colour)
THEMES = {
    'forest': ('Forest', '#2d6a4f'),
    'lake': ('Lake', '#1e6079'),
    'midnight': ('Midnight', '#33497c'),
    'plum': ('Plum', '#6e3f74'),
    'cranberry': ('Cranberry', '#9a2c3e'),
    'slate': ('Slate', '#434c5c'),
}

THEME_CHOICES = [(key, label) for key, (label, _colour) in THEMES.items()]


def theme_for(user):
    """The theme key to render for `user`, falling back to the default."""
    key = getattr(user, 'color_palette', None)
    return key if key in THEMES else DEFAULT_THEME


def theme_colour(key):
    return THEMES.get(key, THEMES[DEFAULT_THEME])[1]
