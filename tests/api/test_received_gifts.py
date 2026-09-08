"""
Tests for the received-gifts archive — issue #88.

The owner archives purchased gifts from their wishlist; archived items move to
the /received-gifts/ page (grouped by year) and surprise items are revealed.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model

from gift.models import Item, WishList

User = get_user_model()


def archived_item(wishlist, name, year, month=12, day=25, **kwargs):
    """Create an archived (received) gift with an explicit archived_at date."""
    return Item.objects.create(
        wishlist=wishlist,
        name=name,
        purchased=True,
        archived_at=datetime(year, month, day, tzinfo=UTC),
        **kwargs,
    )


@pytest.mark.unit
class TestWishlistArchivePurchased:
    """The owner-only 'archive received gifts' action on wishlist_detail."""

    def test_non_owner_cannot_archive(self, authenticated_other_user, wishlist, other_user):
        gift = Item.objects.create(
            wishlist=wishlist, name='Bought Gift', purchased=True, purchased_by=other_user
        )
        response = authenticated_other_user.post(f'/wishlist/{wishlist.id}/archive-purchased/')
        assert response.status_code == 302
        gift.refresh_from_db()
        assert gift.archived_at is None

    def test_anonymous_redirected_to_login(self, client, wishlist):
        response = client.post(f'/wishlist/{wishlist.id}/archive-purchased/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_owner_archives_only_purchased_active_items(
        self, authenticated_user, wishlist, other_user
    ):
        purchased = Item.objects.create(
            wishlist=wishlist, name='Bought Gift', purchased=True, purchased_by=other_user
        )
        sneaky_purchased = Item.objects.create(
            wishlist=wishlist,
            name='Sneaky Gift',
            purchased=True,
            purchased_by=other_user,
            is_sneaky=True,
        )
        unpurchased = Item.objects.create(wishlist=wishlist, name='Still Wanted')
        unpurchased_sneaky = Item.objects.create(
            wishlist=wishlist, name='Sneaky Wanted', is_sneaky=True
        )
        deleted = Item.objects.create(
            wishlist=wishlist, name='Deleted Gift', purchased=True, is_deleted=True
        )

        response = authenticated_user.post(
            f'/wishlist/{wishlist.id}/archive-purchased/', follow=True
        )
        assert response.status_code == 200
        assert '2 gifts moved to your received gifts' in response.content.decode()

        purchased.refresh_from_db()
        sneaky_purchased.refresh_from_db()
        assert purchased.archived_at is not None
        assert sneaky_purchased.archived_at is not None
        # Archiving reveals surprise items
        assert sneaky_purchased.is_sneaky is False

        # Unpurchased and deleted items stay on the active list untouched
        unpurchased.refresh_from_db()
        unpurchased_sneaky.refresh_from_db()
        deleted.refresh_from_db()
        assert unpurchased.archived_at is None
        assert unpurchased_sneaky.archived_at is None
        assert unpurchased_sneaky.is_sneaky is True
        assert deleted.archived_at is None

    def test_second_archive_only_moves_new_purchases(
        self, authenticated_user, wishlist, other_user
    ):
        first = Item.objects.create(wishlist=wishlist, name='First Gift', purchased=True)
        authenticated_user.post(f'/wishlist/{wishlist.id}/archive-purchased/')
        first.refresh_from_db()
        first_archived_at = first.archived_at
        assert first_archived_at is not None

        second = Item.objects.create(wishlist=wishlist, name='Second Gift', purchased=True)
        response = authenticated_user.post(
            f'/wishlist/{wishlist.id}/archive-purchased/', follow=True
        )
        assert '1 gift moved to your received gifts' in response.content.decode()

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.archived_at == first_archived_at  # Not re-archived
        assert second.archived_at is not None

    def test_archived_items_vanish_from_detail(self, authenticated_user, wishlist):
        Item.objects.create(wishlist=wishlist, name='Bought Gift', purchased=True)
        Item.objects.create(wishlist=wishlist, name='Still Wanted')
        authenticated_user.post(f'/wishlist/{wishlist.id}/archive-purchased/')

        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        content = response.content.decode()
        assert 'Bought Gift' not in content
        assert 'Still Wanted' in content

    def test_archived_items_excluded_from_edit_formset(self, authenticated_user, wishlist):
        archived_item(wishlist, 'Old Gift', 2024)
        Item.objects.create(wishlist=wishlist, name='Active Item')
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/')
        content = response.content.decode()
        assert 'Old Gift' not in content
        assert 'Active Item' in content

    def test_unpurchased_sneaky_stays_hidden_after_archive(
        self, authenticated_user, wishlist, other_user
    ):
        Item.objects.create(wishlist=wishlist, name='Sneaky Wanted', is_sneaky=True)
        Item.objects.create(wishlist=wishlist, name='Bought Gift', purchased=True)
        authenticated_user.post(f'/wishlist/{wishlist.id}/archive-purchased/')

        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert 'Sneaky Wanted' not in response.content.decode()


@pytest.mark.unit
class TestReceivedGiftsPage:
    """The /received-gifts/ archive page."""

    def test_requires_login(self, client):
        response = client.get('/received-gifts/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_empty_state(self, authenticated_user):
        response = authenticated_user.get('/received-gifts/')
        assert response.status_code == 200
        assert 'No received gifts yet' in response.content.decode()

    def test_shows_own_archived_items_with_purchaser(
        self, authenticated_user, wishlist, other_user
    ):
        archived_item(wishlist, 'Wrapped Present', 2024, purchased_by=other_user, price='42.00')
        response = authenticated_user.get('/received-gifts/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Wrapped Present' in content
        assert 'otheruser' in content  # Who to thank
        assert '$42.00' in content
        assert 'Test Wishlist' in content  # Source wishlist title

    def test_does_not_show_items_from_other_users_lists(
        self, authenticated_user, other_user, family
    ):
        other_wishlist = WishList.objects.create(
            owner=other_user, title='Other List', family_name=family
        )
        archived_item(other_wishlist, 'Not My Gift', 2024)
        response = authenticated_user.get('/received-gifts/')
        content = response.content.decode()
        assert 'Not My Gift' not in content
        assert 'No received gifts yet' in content

    def test_unarchived_items_not_shown(self, authenticated_user, wishlist):
        Item.objects.create(wishlist=wishlist, name='Active Item', purchased=True)
        response = authenticated_user.get('/received-gifts/')
        assert 'Active Item' not in response.content.decode()

    def test_grouped_by_year_newest_first(self, authenticated_user, wishlist):
        archived_item(wishlist, 'Gift 2023', 2023)
        archived_item(wishlist, 'Gift 2024', 2024)
        response = authenticated_user.get('/received-gifts/')
        content = response.content.decode()
        assert 'wl-cat-label">2024<' in content
        assert 'wl-cat-label">2023<' in content
        assert content.index('wl-cat-label">2024<') < content.index('wl-cat-label">2023<')

    def test_year_headers_show_counts(self, authenticated_user, wishlist):
        archived_item(wishlist, 'Gift One', 2024)
        archived_item(wishlist, 'Gift Two', 2024)
        archived_item(wishlist, 'Gift Three', 2023)
        response = authenticated_user.get('/received-gifts/')
        content = response.content.decode()
        assert 'wl-count-badge">2</span>' in content
        assert 'wl-count-badge">1</span>' in content

    def test_newest_first_within_year(self, authenticated_user, wishlist):
        archived_item(wishlist, 'Older Gift', 2024, month=6, day=1)
        archived_item(wishlist, 'Newer Gift', 2024, month=12, day=25)
        response = authenticated_user.get('/received-gifts/')
        content = response.content.decode()
        assert content.index('Newer Gift') < content.index('Older Gift')

    def test_nav_link_present(self, authenticated_user):
        response = authenticated_user.get('/')
        content = response.content.decode()
        assert '/received-gifts/' in content
        assert '>Received</a>' in content


@pytest.mark.unit
class TestThankYouToggle:
    """The owner-only thank-you-sent toggle on the received page."""

    def test_owner_can_mark_thank_you_sent(self, authenticated_user, wishlist, other_user):
        gift = archived_item(wishlist, 'Thanked Gift', 2024, purchased_by=other_user)
        assert gift.thank_you_sent is False
        response = authenticated_user.post(f'/item/{gift.id}/thank-you/')
        assert response.status_code == 302
        gift.refresh_from_db()
        assert gift.thank_you_sent is True

    def test_toggle_flips_back(self, authenticated_user, wishlist):
        gift = archived_item(wishlist, 'Flip Gift', 2024, thank_you_sent=True)
        authenticated_user.post(f'/item/{gift.id}/thank-you/')
        gift.refresh_from_db()
        assert gift.thank_you_sent is False

    def test_non_owner_gets_404(self, authenticated_other_user, wishlist):
        gift = archived_item(wishlist, 'Guarded Gift', 2024)
        response = authenticated_other_user.post(f'/item/{gift.id}/thank-you/')
        assert response.status_code == 404
        gift.refresh_from_db()
        assert gift.thank_you_sent is False

    def test_unarchived_item_gets_404(self, authenticated_user, wishlist):
        active = Item.objects.create(wishlist=wishlist, name='Active Item', purchased=True)
        response = authenticated_user.post(f'/item/{active.id}/thank-you/')
        assert response.status_code == 404

    def test_thank_you_state_rendered_on_page(self, authenticated_user, wishlist):
        archived_item(wishlist, 'Thanked Gift', 2024, thank_you_sent=True)
        response = authenticated_user.get('/received-gifts/')
        assert '✓ Thank-you sent' in response.content.decode()


@pytest.mark.unit
class TestSneakyToReceivedFlow:
    """End-to-end: a surprise gift is revealed to the owner when archived."""

    def test_surprise_gift_revealed_on_archive(
        self, authenticated_user, authenticated_other_user, wishlist
    ):
        # Giver adds a surprise gift to the owner's list
        authenticated_other_user.post(
            f'/wishlist/{wishlist.id}/add_surprise_item/',
            {'name': 'Mystery Gift', 'description': '', 'price': '', 'price_range': '', 'url': ''},
        )
        gift = Item.objects.get(name='Mystery Gift')
        assert gift.is_sneaky is True

        # The owner can't see it on their list
        content = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert 'Mystery Gift' not in content

        # The giver marks it purchased, then the owner archives received gifts
        authenticated_other_user.get(f'/item/purchase/{gift.id}/')
        authenticated_user.post(f'/wishlist/{wishlist.id}/archive-purchased/')

        # Revealed: no longer sneaky, visible on the received page with who to thank
        gift.refresh_from_db()
        assert gift.is_sneaky is False
        assert gift.archived_at is not None
        content = authenticated_user.get('/received-gifts/').content.decode()
        assert 'Mystery Gift' in content
        assert 'otheruser' in content
