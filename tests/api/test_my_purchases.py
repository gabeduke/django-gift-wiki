"""
Tests for the "My purchases" page: a giver's own cross-wishlist purchase history.
"""

import pytest
from django.contrib.auth import get_user_model

from gift.models import Item, WishList

User = get_user_model()


@pytest.fixture
def other_wishlist(db, other_user, family):
    """A wishlist owned by other_user — somewhere `user` can buy gifts from."""
    return WishList.objects.create(
        owner=other_user,
        title='Other User Wishlist',
        description='Wishlist owned by the other user',
        family_name=family,
    )


@pytest.mark.unit
class TestMyPurchasesView:
    """Test the my_purchases view."""

    def test_requires_login(self, client):
        """Unauthenticated users are redirected to the login page."""
        response = client.get('/my-purchases/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_empty_state(self, authenticated_user):
        """A friendly empty state is shown when the user has no purchases."""
        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert "You haven't marked anything as purchased yet" in content
        assert 'Browse Wishlists' in content

    def test_only_own_purchases_appear(
        self, authenticated_user, user, other_user, wishlist, other_wishlist
    ):
        """The page lists items the current user purchased, and nothing else."""
        Item.objects.create(
            wishlist=other_wishlist,
            name='Bought By Me',
            purchased=True,
            purchased_by=user,
            price='10.00',
        )
        Item.objects.create(
            wishlist=wishlist,
            name='Bought By Someone Else',
            purchased=True,
            purchased_by=other_user,
            price='5.00',
        )

        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Bought By Me' in content
        assert 'Bought By Someone Else' not in content

    def test_other_users_purchases_not_shown(
        self, authenticated_other_user, user, other_user, wishlist, other_wishlist
    ):
        """The reverse direction: other_user must not see user's purchases."""
        Item.objects.create(
            wishlist=other_wishlist,
            name='Bought By Me',
            purchased=True,
            purchased_by=user,
            price='10.00',
        )
        Item.objects.create(
            wishlist=wishlist,
            name='Bought By Other',
            purchased=True,
            purchased_by=other_user,
            price='5.00',
        )

        response = authenticated_other_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Bought By Other' in content
        assert 'Bought By Me' not in content

    def test_soft_deleted_items_excluded(self, authenticated_user, user, other_wishlist):
        """Soft-deleted items never show up, even if the user bought them."""
        Item.objects.create(
            wishlist=other_wishlist,
            name='Deleted Purchase',
            purchased=True,
            purchased_by=user,
            is_deleted=True,
            price='12.00',
        )

        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Deleted Purchase' not in content
        assert "You haven't marked anything as purchased yet" in content

    def test_total_spend_sums_priced_items(self, authenticated_user, user, other_wishlist):
        """Total spend sums priced items only; unpriced items still list."""
        Item.objects.create(
            wishlist=other_wishlist, name='Priced One', purchased=True,
            purchased_by=user, price='10.00',
        )
        Item.objects.create(
            wishlist=other_wishlist, name='Priced Two', purchased=True,
            purchased_by=user, price='29.99',
        )
        Item.objects.create(
            wishlist=other_wishlist, name='Unpriced', purchased=True, purchased_by=user,
        )

        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '$39.99' in content
        assert 'Unpriced' in content
        # All 3 purchased items are counted
        assert '<span class="wl-progress-mono">3</span>' in content

    def test_grouped_by_wishlist_with_owner_and_links(
        self, authenticated_user, user, wishlist, other_wishlist
    ):
        """Purchases are grouped under wishlist title + owner, linking to the list."""
        Item.objects.create(
            wishlist=wishlist, name='Item A', purchased=True, purchased_by=user,
        )
        Item.objects.create(
            wishlist=other_wishlist, name='Item B', purchased=True, purchased_by=user,
        )

        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        # Group headers show wishlist titles and owner display names
        assert 'Test Wishlist' in content
        assert 'Other User Wishlist' in content
        assert 'otheruser' in content
        # Items link back to their wishlist detail pages
        assert f'/wishlist/{wishlist.id}/' in content
        assert f'/wishlist/{other_wishlist.id}/' in content

    def test_most_recent_first_within_group(self, authenticated_user, user, other_wishlist):
        """Within a wishlist group, most recently updated purchases come first."""
        Item.objects.create(
            wishlist=other_wishlist, name='Older Purchase', purchased=True, purchased_by=user,
        )
        Item.objects.create(
            wishlist=other_wishlist, name='Newer Purchase', purchased=True, purchased_by=user,
        )

        response = authenticated_user.get('/my-purchases/')
        assert response.status_code == 200
        content = response.content.decode()
        assert content.index('Newer Purchase') < content.index('Older Purchase')
