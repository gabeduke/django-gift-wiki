from gift.models import WishList, Item


def is_owner_or_steward(user, obj):
    if isinstance(obj, WishList):
        return user == obj.owner or user == obj.steward
    elif isinstance(obj, Item):
        return user == obj.wishlist.owner or user == obj.wishlist.steward
    else:
        return False
