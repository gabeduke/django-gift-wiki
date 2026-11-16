"""BDD step definitions for purchase.feature.

Scenarios live in ../features/purchase.feature. Fixtures (``user``,
``other_user``, ``wishlist``, ``item``, ``authenticated_user``,
``authenticated_other_user``) come from the root ``conftest.py``. A local
``third_user`` fixture covers the "already-purchased" spoiler scenarios, and
``child`` the list a parent (the ``user`` fixture) keeps for their kid.
"""

import re
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


@pytest.fixture
def child(db):
    return User.objects.create_user(
        username='childuser', email='child@example.com', password='childpass123'
    )


@pytest.fixture
def authenticated_child(child):
    c = Client()
    c.force_login(child)
    return c


@given('a wishlist with an unpurchased item', target_fixture='purchase_item')
def purchase_item(item):
    assert item.purchased is False
    assert item.purchased_by is None
    return item


@given('a list kept for a child with an unpurchased item', target_fixture='purchase_item')
def kept_list_item(item, child):
    """The `user` fixture owns the list and keeps it for `child`."""
    item.wishlist.dependent = child
    item.wishlist.save()
    assert item.purchased is False
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


@when('the parent marks the item as purchased')
def parent_marks_purchased(authenticated_user, purchase_item):
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


@when('the parent views the wishlist page', target_fixture='wishlist_response')
def parent_views(authenticated_user, purchase_item):
    return authenticated_user.get(f'/wishlist/{purchase_item.wishlist_id}/')


@when('the child views the wishlist page', target_fixture='wishlist_response')
def child_views(authenticated_child, purchase_item):
    return authenticated_child.get(f'/wishlist/{purchase_item.wishlist_id}/')


@then('the item is marked purchased by the other user')
def assert_purchased_by_other(purchase_item, other_user):
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is True
    assert purchase_item.purchased_by == other_user


@then('the item is marked purchased by the parent')
def assert_purchased_by_parent(purchase_item, user):
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is True
    assert purchase_item.purchased_by == user


@then('the item is still unpurchased')
def assert_unpurchased(purchase_item):
    purchase_item.refresh_from_db()
    assert purchase_item.purchased is False
    assert purchase_item.purchased_by is None


@then('the page shows "Purchased" anonymously')
def page_shows_purchased_anonymous(wishlist_response):
    assert wishlist_response.status_code == 200
    content = wishlist_response.content.decode()
    assert 'purchased-badge' in content
    assert 'purchaser-name' in content


@then('the page hides the purchaser name by default')
def page_hides_purchaser_name(wishlist_response):
    content = wishlist_response.content.decode()
    # The purchaser name is hidden by the .purchaser-name CSS rule by default;
    # verify the span exists and is not marked as visible.
    match = re.search(
        r'<span[^>]*class="[^"]*purchaser-name[^"]*"[^>]*>',
        content,
    )
    assert match, 'purchaser-name span is missing'
    assert 'purchaser-name is-visible' not in content, 'purchaser-name span is visible by default'


@then('the page has a reveal purchaser control')
def page_has_reveal_control(wishlist_response):
    content = wishlist_response.content.decode()
    assert 'reveal-purchaser' in content


@then('the page shows the item as purchased')
def page_shows_purchased(wishlist_response):
    assert wishlist_response.status_code == 200
    content = wishlist_response.content.decode()
    assert 'purchased-badge' in content
    assert 'class="wl-progress"' in content
    # The parent bought it, so the button offers to undo rather than to buy
    assert 'Undo' in content


@then('the page does not show purchase information')
def page_hides_purchase_info(wishlist_response):
    assert wishlist_response.status_code == 200
    content = wishlist_response.content.decode()
    # The purchased badge markup is not rendered for the person the list is
    # for; use a class that only appears in the actual badge HTML, not in the
    # reveal script.
    assert 'purchased-badge' not in content
    assert 'Purchased' not in content
    assert 'class="wl-progress"' not in content
    assert '/item/purchase/' not in content
