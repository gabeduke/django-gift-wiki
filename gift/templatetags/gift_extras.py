"""Custom template filters for the gift app."""
from datetime import date

from django import template

register = template.Library()


@register.filter
def birthday_label(user):
    """Return a friendly birthday label for a WikiUser, e.g. '01/15 (age 8)'."""
    if not user or not user.birthday:
        return ''
    birthday = user.birthday
    today = date.today()
    age = today.year - birthday.year - (
        (today.month, today.day) < (birthday.month, birthday.day)
    )
    return f"{birthday.month}/{birthday.day} (age {age})"
