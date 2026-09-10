"""Issue #84: deleted items still show up in item counts on the user page.

Soft-deleted items (is_deleted=True) must not be counted anywhere a user sees a
total, or the list appears to contain things it does not.
"""

import pytest

from gift.models import Item


@pytest.fixture
def wishlist_with_a_deleted_item(db, wishlist):
    """One live item, one soft-deleted. Every count should say 1."""
    Item.objects.create(wishlist=wishlist, name='Live item')
    Item.objects.create(wishlist=wishlist, name='Deleted item', is_deleted=True)
    return wishlist


@pytest.mark.unit
class TestDeletedItemsAreNotCounted:
    def test_home_card_count_excludes_deleted_items_for_owner(
        self, authenticated_user, wishlist_with_a_deleted_item
    ):
        response = authenticated_user.get('/')

        card = next(
            w for group in response.context['wishlists_grouped'].values()
            for w in group if w.id == wishlist_with_a_deleted_item.id
        )
        assert card.card_item_count == 1

    def test_home_card_count_excludes_deleted_items_for_others(
        self, authenticated_other_user, wishlist_with_a_deleted_item
    ):
        response = authenticated_other_user.get('/')

        card = next(
            w for group in response.context['wishlists_grouped'].values()
            for w in group if w.id == wishlist_with_a_deleted_item.id
        )
        assert card.card_item_count == 1

    def test_profile_page_excludes_deleted_items(
        self, authenticated_user, wishlist_with_a_deleted_item
    ):
        response = authenticated_user.get('/profile/')

        content = response.content.decode()
        assert 'Live item' in content
        assert 'Deleted item' not in content

    def test_wishlist_detail_total_excludes_deleted_items(
        self, authenticated_other_user, wishlist_with_a_deleted_item
    ):
        response = authenticated_other_user.get(f'/wishlist/{wishlist_with_a_deleted_item.id}/')

        assert response.context['total_count'] == 1
