"""BDD step definitions for ownership.feature.

Scenarios live in ../features/ownership.feature. Fixtures (``user``,
``other_user``, ``wishlist``, ``item``, ``authenticated_user``,
``authenticated_other_user``) come from the root ``conftest.py``.
"""

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from gift.models import Item, WishList

pytestmark = pytest.mark.bdd

scenarios(str(Path(__file__).parent.parent / 'features' / 'ownership.feature'))


@given('a wishlist owned by the current user', target_fixture='owned_wishlist')
def owned_wishlist(wishlist):
    return wishlist


@given('an item on that wishlist', target_fixture='owned_item')
def owned_item(item):
    return item


@given('the other user is a manager of the wishlist')
def add_manager(owned_wishlist, other_user):
    owned_wishlist.managers.add(other_user)


@when(parsers.parse('the owner edits the item name to "{new_name}"'))
def owner_edits_item(authenticated_user, owned_item, new_name):
    authenticated_user.post(
        f'/item/edit/{owned_item.id}/',
        {'name': new_name, 'description': owned_item.description or ''},
    )


@when(parsers.parse('a non-owner edits the item name to "{new_name}"'))
def non_owner_edits_item(authenticated_other_user, owned_item, new_name):
    authenticated_other_user.post(
        f'/item/edit/{owned_item.id}/',
        {'name': new_name, 'description': owned_item.description or ''},
    )


@when(parsers.parse('the other user edits the item name to "{new_name}"'))
def manager_edits_item(authenticated_other_user, owned_item, new_name):
    authenticated_other_user.post(
        f'/item/edit/{owned_item.id}/',
        {'name': new_name, 'description': owned_item.description or ''},
    )


@then(parsers.parse('the item name is "{expected_name}"'))
def item_name_is(owned_item, expected_name):
    owned_item.refresh_from_db()
    assert owned_item.name == expected_name


@when('a non-owner attempts to delete the wishlist')
def non_owner_deletes_wishlist(authenticated_other_user, owned_wishlist):
    authenticated_other_user.post(f'/wishlist/{owned_wishlist.id}/delete/')


@then('the wishlist still exists')
def wishlist_exists(owned_wishlist):
    assert WishList.objects.filter(id=owned_wishlist.id).exists()


@when('the owner deletes the wishlist')
def owner_deletes_wishlist(authenticated_user, owned_wishlist):
    authenticated_user.post(f'/wishlist/{owned_wishlist.id}/delete/')


@then('the wishlist no longer exists')
def wishlist_gone(owned_wishlist):
    assert not WishList.objects.filter(id=owned_wishlist.id).exists()
    # Items cascade on wishlist hard-delete
    assert not Item.objects.filter(wishlist_id=owned_wishlist.id).exists()
