"""Domain rules for gift visibility and item creation.

These are deliberately free of request, response, and template concerns: the
wishlist views and the assistant's tool layer both enforce the same rules, and
the tool layer must not have to import a view module to do it.
"""

import logging

logger = logging.getLogger(__name__)


def can_add_openly(wishlist, user):
    """Whether `user` may put an ordinary, visible item on `wishlist`.

    Owner-side means the owner, the dependent the list is kept for, or a
    manager. Everyone else is a gift-giver, and what they add has to stay
    hidden from the recipient.
    """
    if user == wishlist.owner or user == wishlist.dependent:
        return True
    return wishlist.managers.filter(pk=user.pk).exists()


def person_display_name(person):
    """The name shown for a person in the UI: full name when set, else username.

    Mirrors the `get_full_name|default:username` idiom the row templates use —
    get_full_name() returns '' when neither name is set, which is falsy.
    """
    if not person:
        return ''
    return person.get_full_name() or person.username
