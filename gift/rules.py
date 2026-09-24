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


def is_recipient_side(wishlist, viewer):
    """Whether `viewer` is the person this list is for.

    Narrower than can_add_openly: a manager runs the list without being its
    recipient, so surprises stay visible to them. Getting these two audiences
    the same way round is what keeps surprises working AND unspoiled.
    """
    return viewer == wishlist.owner or viewer == wishlist.dependent


def may_see_purchase_info(wishlist, viewer):
    """Whether `viewer` may be told what has been purchased on this list.

    Wider than is_recipient_side: managers are excluded too. 'The bike is
    already bought' spoils a gift just as thoroughly as naming a hidden item.
    """
    return not can_add_openly(wishlist, viewer)


def visible_items(wishlist, viewer):
    """Active items on `wishlist` that `viewer` is allowed to see.

    Priority items first; id keeps a stable order within each group. Archived
    gifts live on the received-gifts page instead of the active list.
    """
    items = (
        wishlist.items.filter(is_deleted=False, archived_at__isnull=True)
        .select_related('purchased_by', 'updated_by', 'added_by')
        .prefetch_related('categories')
        .order_by('-is_priority', 'id')
    )
    if is_recipient_side(wishlist, viewer):
        items = items.exclude(is_sneaky=True)
    return items


def person_display_name(person):
    """The name shown for a person in the UI: full name when set, else username.

    Mirrors the `get_full_name|default:username` idiom the row templates use —
    get_full_name() returns '' when neither name is set, which is falsy.
    """
    if not person:
        return ''
    return person.get_full_name() or person.username
