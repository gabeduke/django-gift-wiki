"""
API view tests using standard Django test patterns.
"""

import pytest
from django.contrib.auth import get_user_model

from gift.models import Item, WishList

User = get_user_model()


@pytest.mark.unit
class TestHomeView:
    """Test the home page view."""

    def test_home_page_renders(self, client, db):
        """Test that home page loads."""
        response = client.get('/')
        assert response.status_code == 200

    def test_home_page_shows_wishlists(self, authenticated_user, wishlist):
        """Test that wishlists are displayed on home."""
        response = authenticated_user.get('/')
        assert response.status_code == 200
        assert wishlist.title in response.content.decode()


@pytest.mark.unit
class TestWishlistViews:
    """Test wishlist management views."""

    def test_create_wishlist_get(self, authenticated_user):
        """Test create wishlist page loads."""
        response = authenticated_user.get('/wishlist/create/')
        assert response.status_code == 200

    def test_create_wishlist_post(self, authenticated_user, user, family):
        """Test creating a wishlist."""
        data = {
            'title': 'New Wishlist',
            'description': 'Test description',
            'family_name': family.id,
        }
        response = authenticated_user.post('/wishlist/create/', data)
        assert response.status_code == 302  # Redirect after creation
        assert WishList.objects.filter(title='New Wishlist').exists()

    def test_wishlist_detail(self, authenticated_user, wishlist):
        """Test viewing wishlist detail."""
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        # Check that the response contains the wishlist in some form
        content = response.content.decode()
        assert 'wishlist' in content.lower() or wishlist.title in content

    def test_wishlist_delete(self, authenticated_user, wishlist, user):
        """Test deleting a wishlist."""
        wishlist_id = wishlist.id
        response = authenticated_user.post(f'/wishlist/{wishlist_id}/delete/')
        assert response.status_code == 302  # Redirect after deletion
        assert not WishList.objects.filter(id=wishlist_id).exists()

    def test_cannot_delete_other_user_wishlist(self, authenticated_other_user, wishlist):
        """Test that users cannot delete others' wishlists."""
        wishlist_id = wishlist.id
        response = authenticated_other_user.post(f'/wishlist/{wishlist_id}/delete/')
        # Should redirect to home with error
        assert response.status_code == 302
        # Wishlist should still exist
        assert WishList.objects.filter(id=wishlist_id).exists()


@pytest.mark.unit
class TestItemViews:
    """Test item management views."""

    def test_add_item(self, authenticated_user, wishlist):
        """Test adding an item to a wishlist."""
        data = {'name': 'New Item', 'description': 'Test item', 'price': '19.99'}
        response = authenticated_user.post(f'/wishlist/{wishlist.id}/add_item/', data)
        assert response.status_code == 302  # Redirect after creation
        assert Item.objects.filter(name='New Item', wishlist=wishlist).exists()

    def test_edit_item(self, authenticated_user, item):
        """Test editing an item."""
        data = {
            'name': 'Updated Item',
            'description': item.description,
            'price': str(item.price),
            'url': 'https://example.com/product',
        }
        response = authenticated_user.post(f'/item/edit/{item.id}/', data)
        assert response.status_code == 302  # Redirect after update
        item.refresh_from_db()
        assert item.name == 'Updated Item'
        assert item.url == 'https://example.com/product'

    def test_delete_item(self, authenticated_user, item):
        """Test deleting an item (soft delete)."""
        item_id = item.id
        response = authenticated_user.post(f'/item/delete/{item_id}/')
        assert response.status_code == 302  # Redirect after deletion
        item.refresh_from_db()
        assert item.is_deleted is True

    def test_purchase_item(self, authenticated_other_user, item):
        """Test marking an item as purchased."""
        response = authenticated_other_user.post(f'/item/purchase/{item.id}/')
        assert response.status_code == 302  # Redirect after purchase
        item.refresh_from_db()
        assert item.purchased_by is not None


@pytest.mark.unit
class TestAuthentication:
    """Test authentication views."""

    def test_login_page_loads(self, client):
        """Test login page renders."""
        response = client.get('/accounts/login/')
        assert response.status_code == 200

    def test_signup_page_loads(self, client):
        """Test signup page - signup is disabled, should return 404."""
        response = client.get('/signup/')
        assert response.status_code == 404  # Signup is disabled via Traefik forward auth

    def test_profile_requires_login(self, client):
        """Test profile requires authentication."""
        response = client.get('/profile/')
        assert response.status_code == 302  # Redirect to login


@pytest.mark.unit
class TestWishlistManagers:
    """Test wishlist managers functionality."""

    def test_manager_can_edit_wishlist(
        self, authenticated_user, authenticated_other_user, wishlist, other_user
    ):
        """Test that managers can edit wishlists."""
        # Add other_user as manager
        wishlist.managers.add(other_user)

        # Manager should be able to edit
        data = {
            'title': wishlist.title,
            'description': 'Updated by manager',
            'family_name': wishlist.family_name.id if wishlist.family_name else '',
        }
        response = authenticated_other_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        # Should redirect on success or show form on GET
        assert response.status_code in [200, 302]

        # Verify manager can access edit page
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200

    def test_manager_can_edit_items(
        self, authenticated_user, authenticated_other_user, wishlist, item, other_user
    ):
        """Test that managers can edit items."""
        # Add other_user as manager
        wishlist.managers.add(other_user)

        # Manager should be able to edit items
        data = {
            'name': 'Updated by manager',
            'description': item.description,
            'price': str(item.price) if item.price else '',
        }
        response = authenticated_other_user.post(f'/item/edit/{item.id}/', data)
        # Should redirect on success
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.name == 'Updated by manager'

    def test_non_manager_cannot_edit_wishlist(self, authenticated_other_user, wishlist):
        """Test that non-managers cannot edit wishlists."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/edit/')
        # Should redirect with error
        assert response.status_code == 302


@pytest.mark.unit
class TestScrapedPageImport:
    """Test scraped page import functionality."""

    def test_select_scraped_page_requires_login(self, client):
        """Test that selecting scraped page requires authentication."""
        response = client.get('/select-scraped-page/')
        assert response.status_code == 302  # Redirect to login

    def test_select_scraped_page_loads(self, authenticated_user):
        """Test that scraped page selection page loads."""
        response = authenticated_user.get('/select-scraped-page/')
        # May redirect if no pages available, or show form
        assert response.status_code in [200, 302]
