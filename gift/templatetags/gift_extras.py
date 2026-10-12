"""Custom template filters for the gift app."""
from datetime import date

from django import template

from gift.pwa import versioned_static

register = template.Library()


BIRTHDAY_SOON_DAYS = 60


def _next_birthday(birthday, today):
    """The next occurrence of `birthday` on or after `today` (Feb 29 → Feb 28)."""
    for year in (today.year, today.year + 1):
        try:
            candidate = birthday.replace(year=year)
        except ValueError:
            candidate = birthday.replace(year=year, day=28)
        if candidate >= today:
            return candidate
    return candidate


@register.filter
def birthday_label(user, today=None):
    """A shopper-friendly birthday line for a WikiUser, e.g. 'Oct 20 · turns 68 · in 8 days'.

    What matters when you're buying is when the day is and how old they'll be,
    so the label leads with the next birthday rather than today's age. The
    countdown only appears once it's close enough to act on.
    """
    if not user or not user.birthday:
        return ''
    today = today or date.today()
    upcoming = _next_birthday(user.birthday, today)
    days = (upcoming - today).days
    label = f"{upcoming:%b} {upcoming.day} · turns {upcoming.year - user.birthday.year}"
    if days == 0:
        return f"{label} · today 🎉"
    if days == 1:
        return f"{label} · tomorrow"
    if days <= BIRTHDAY_SOON_DAYS:
        return f"{label} · in {days} days"
    return label


@register.simple_tag
def vstatic(path):
    """Like {% static %}, plus a content hash so browsers and the service worker
    notice when the file changes. See gift/pwa.py for why that's needed here."""
    return versioned_static(path)
