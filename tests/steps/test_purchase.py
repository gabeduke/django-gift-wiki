"""BDD step definitions for purchase.feature.

Scenarios live in ../features/purchase.feature. Fixtures (``user``,
``other_user``, ``wishlist``, ``item``, ``authenticated_user``,
``authenticated_other_user``) come from the root ``conftest.py``. A local
``third_user`` fixture covers the "already-purchased" spoiler scenarios.
"""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from pytest_bdd import given, scenarios, then, when

pytestmark = pytest.mark.bdd

scenarios(str(Path(__file__).parent.parent / 'features' / 'purchase.feature'))

User = get_user_model()


@pytest.fixture
def third_user(db):
    return User.objects.create_user(
        username='thirduser', email='third@example.com', password='thirdpass123'
    )


@pytest.fixture
def authenticated_third_user(third_user):
    c = Client()
    c.force_login(third_user)
    return c


@given('a wishlist with an unpurchased item', target_fixture='purchase_item')
def purchase_item(item):
    assert item.purchased is False
    assert item.purchased_by is None
    return item


@given('the other user has already purchased the item')
def other_user_purchased(authenticated_other_user, purchase_item):
    authenticated_other_user.post(f'/item/purchase/{purchase_item.id}/')
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is True


@when('the other user marks the item as purchased')
def other_user_marks_purchased(authenticated_other_user, purchase_item):
    authenticated_other_user.post(f'/item/purchase/{purchase_item.id}/')


@when('the owner tries to mark the item as purchased')
def owner_tries_to_purchase(authenticated_user, purchase_item):
    authenticated_user.post(f'/item/purchase/{purchase_item.id}/')


@when('a third user tries to mark the item as purchased')
def third_user_tries_to_purchase(authenticated_third_user, purchase_item):
    authenticated_third_user.post(f'/item/purchase/{purchase_item.id}/')


@when('a third user views the wishlist page', target_fixture='wishlist_response')
def third_user_views(authenticated_third_user, purchase_item):
    return authenticated_third_user.get(f'/wishlist/{purchase_item.wishlist_id}/')


@when('the owner views the wishlist page', target_fixture='wishlist_response')
def owner_views(authenticated_user, purchase_item):
    return authenticated_user.get(f'/wishlist/{purchase_item.wishlist_id}/')


@then('the item is marked purchased by the other user')
def assert_purchased_by_other(purchase_item, other_user):
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is True
    assert purchase_item.purchased_by == other_user


@then('the item is still unpurchased')
def assert_unpurchased(purchase_item):
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is False
    assert purchase_item.purchased_by is None


@then('the page shows "Purchased by"')
def page_shows_purchased_by(wishlist_response):
    assert wishlist_response.status_code == 200
    assert 'Purchased by' in wishlist_response.content.decode()


@then('the page does not show "Purchased by"')
def page_hides_purchased_by(wishlist_response):
    assert wishlist_response.status_code == 200
    assert 'Purchased by' not in wishlist_response.content.decode()
