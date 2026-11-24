"""Who may know what about a list.

Two things on a list are secrets: the surprise ("sneaky") items other people
have added, and which items have been bought. Every view that shows or changes
either one asks `access_for()` rather than working it out again, so the rules
live here and nowhere else.

The people around a list:

- The **recipient** is who the gifts are for: the dependent when the list is
  kept for someone (a parent's list for their kid), otherwise the owner.
  Both secrets are kept from them, always.
- **Keepers** run a list for somebody else — the owner and managers of a kid's
  list. They edit it like their own, but they are givers too, so they see
  surprises and can mark things bought.
- A **manager of someone's own list** helps edit it and sees its surprise
  items, but not what's been bought (unchanged from before keepers existed).
- Everyone else is a **giver**: they see and mark purchases, and what they add
  is a surprise.

**Over the shoulder** is a switch for sitting down with a recipient at your own
screen. While it is on, this session is shown every list the way its recipient
sees it — no surprises, no purchase marks — and nothing can be marked bought.
"""

from dataclasses import dataclass

OVER_THE_SHOULDER_SESSION_KEY = 'over_the_shoulder'


def is_over_the_shoulder(request):
    """Whether this session is hiding every list's secrets."""
    return bool(request.session.get(OVER_THE_SHOULDER_SESSION_KEY))


def recipient_of(wishlist):
    """The person the gifts on `wishlist` are for."""
    return wishlist.dependent or wishlist.owner


def is_kept_for_someone(wishlist):
    """Whether the owner runs this list on someone else's behalf."""
    return wishlist.dependent_id is not None and wishlist.dependent_id != wishlist.owner_id


def is_recipient(wishlist, user):
    if is_kept_for_someone(wishlist):
        return user.pk == wishlist.dependent_id
    return user.pk == wishlist.owner_id


def can_add_openly(wishlist, user):
    """Whether `user` may put an ordinary, visible item on `wishlist`.

    That is the owner, the dependent the list is kept for, or a manager.
    Everyone else is a gift-giver, and what they add has to stay hidden from
    the recipient.
    """
    if user.pk == wishlist.owner_id or user.pk == wishlist.dependent_id:
        return True
    # Iterating .all() rather than .filter().exists() lets a
    # prefetch_related('managers') answer this without a query per list.
    return any(manager.pk == user.pk for manager in wishlist.managers.all())


@dataclass(frozen=True)
class ListAccess:
    """What one person may do with, and know about, one list."""

    can_manage: bool  # add, edit and delete ordinary items
    is_recipient: bool  # the gifts are for them
    is_keeper: bool  # runs the list for somebody else
    sees_surprises: bool  # may know the sneaky items exist
    sees_purchases: bool  # may see what's been bought, and mark things bought
    hiding: bool  # over the shoulder is what's keeping secrets from them


def access_for(wishlist, user, over_the_shoulder=False):
    manages = can_add_openly(wishlist, user)
    recipient = is_recipient(wishlist, user)
    keeper = manages and not recipient and is_kept_for_someone(wishlist)

    sees_surprises = not recipient
    sees_purchases = keeper or not manages
    hiding = over_the_shoulder and (sees_surprises or sees_purchases)

    return ListAccess(
        can_manage=manages,
        is_recipient=recipient,
        is_keeper=keeper,
        sees_surprises=sees_surprises and not over_the_shoulder,
        sees_purchases=sees_purchases and not over_the_shoulder,
        hiding=hiding,
    )


def request_access(request, wishlist):
    """`access_for()` the signed-in user, honouring over-the-shoulder mode."""
    return access_for(wishlist, request.user, is_over_the_shoulder(request))


def active_items_visible_to(wishlist, access):
    """Active items on `wishlist` that someone with `access` may know exist.

    Surprise items never reach the recipient — not in a count, not in a
    duplicate check, not anywhere. Everything that shows a list's items to
    someone starts here so that rule lives in one place.
    """
    items = wishlist.items.filter(is_deleted=False, archived_at__isnull=True)
    if not access.sees_surprises:
        items = items.exclude(is_sneaky=True)
    return items
