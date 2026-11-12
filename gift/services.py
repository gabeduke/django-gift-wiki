"""Rules about who may see and add what, shared by every way into the app.

The web views and the MCP server both answer the same two questions — "may this
person know this item exists?" and "does what they add show up for the
recipient?" — and getting either one wrong spoils a gift. They live here, once,
so a new front door can't drift from the old ones.

Nothing in this module knows about HTTP. Every function takes the acting `user`
as an argument: callers pass the person who authenticated, never anything a
client or a language model supplied.
"""

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .models import Item

NAME_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 2000


def can_add_openly(wishlist, user):
    """Whether `user` may put an ordinary, visible item on `wishlist`.

    Owner-side means the owner, the dependent the list is kept for, or a
    manager. Everyone else is a gift-giver, and what they add has to stay
    hidden from the recipient.
    """
    if user == wishlist.owner or user == wishlist.dependent:
        return True
    # Iterating .all() rather than .filter().exists() lets the picker's
    # prefetch_related('managers') answer this without a query per list.
    return any(manager.pk == user.pk for manager in wishlist.managers.all())


def active_items_visible_to(wishlist, user):
    """Active items on `wishlist` that `user` may know exist.

    Surprise items never reach the owner or the dependent the list is kept for
    — not in a count, not in a duplicate check, not anywhere. Everything that
    shows a list's items to someone starts here so that rule lives in one place.
    """
    items = wishlist.items.filter(is_deleted=False, archived_at__isnull=True)
    if user == wishlist.owner or user == wishlist.dependent:
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


def shows_purchases_to(wishlist, user):
    """Whether `user` may see which items have been bought.

    Never the owner side: knowing a gift is already taken is its own spoiler.
    """
    return not can_add_openly(wishlist, user)


class ItemProblem(ValueError):
    """What someone asked for can't become an item. The message is fit to show them."""


def create_item_for(user, wishlist, name, url='', description=''):
    """Add an item to `wishlist` on behalf of `user`, and return it.

    Whether it is a surprise is decided here from who is asking — never from the
    request — so a client can't spoil a gift by asking for the wrong kind, or
    reveal itself by asking for a surprise on its own list.

    Raises ItemProblem for input that can't be saved.
    """
    name = (name or '').strip()
    if not name:
        raise ItemProblem('Give the item a name.')
    if len(name) > NAME_MAX_LENGTH:
        raise ItemProblem(f'That name is too long ({NAME_MAX_LENGTH} characters max).')

    url = (url or '').strip()
    if url:
        try:
            URLValidator()(url)
        except ValidationError:
            raise ItemProblem("That link doesn't look like a valid URL.") from None

    description = (description or '').strip()
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise ItemProblem(f'That note is too long ({DESCRIPTION_MAX_LENGTH} characters max).')

    item = Item(
        wishlist=wishlist,
        name=name,
        url=url or None,
        description=description,
        is_sneaky=not can_add_openly(wishlist, user),
    )
    item.save(current_user=user)
    return item


def added_message(wishlist, item):
    """The sentence shown after an add, which says plainly whether it is a surprise."""
    if item.is_sneaky:
        person = person_display_name(wishlist.dependent or wishlist.owner)
        return f'Surprise gift added to {wishlist.title} — {person} can’t see it. 🤫'
    return f'Added “{item.name}” to {wishlist.title}.'
