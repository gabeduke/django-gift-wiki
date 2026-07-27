"""
Tests for sneaky (surprise) items — issue #7.

A sneaky item is added to someone's wishlist by another user and is hidden
from the list owner/recipient until the gift is received and archived.
"""

import pytest
from django.contrib.auth import get_user_model

from gift.models import Item

User = get_user_model()


@pytest.fixture
def sneaky_item(db, wishlist, other_user):
    """A surprise item on `wishlist` added by someone other than the owner."""
    return Item.objects.create(
        wishlist=wishlist, name='Secret Surprise Gift', is_sneaky=True, updated_by=other_user
    )


@pytest.mark.unit
class TestSneakyItemAdd:
    """The 'Add a surprise gift' flow on someone else's wishlist."""

    def test_non_owner_can_view_add_form(self, authenticated_other_user, wishlist):
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/add_surprise_item/')
        assert response.status_code == 200
        assert 'Add a Surprise Gift' in response.content.decode()

    def test_non_owner_can_create_sneaky_item(
        self, authenticated_other_user, wishlist, other_user
    ):
        response = authenticated_other_user.post(
            f'/wishlist/{wishlist.id}/add_surprise_item/',
            {
                'name': 'Sneaky Lego Set',
                'description': 'The big one',
                'price': '59.99',
                'price_range': '',
                'url': '',
            },
        )
        assert response.status_code == 302
        item = Item.objects.get(name='Sneaky Lego Set')
        assert item.is_sneaky is True
        assert item.wishlist == wishlist
        assert item.updated_by == other_user
        assert item.price is not None

    def test_owner_cannot_view_add_form(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/add_surprise_item/')
        assert response.status_code == 302

    def test_owner_cannot_create_sneaky_item(self, authenticated_user, wishlist):
        response = authenticated_user.post(
            f'/wishlist/{wishlist.id}/add_surprise_item/',
            {'name': 'Self Surprise', 'description': '', 'price': '', 'price_range': '', 'url': ''},
        )
        assert response.status_code == 302
        assert not Item.objects.filter(name='Self Surprise').exists()

    def test_anonymous_redirected_to_login(self, client, wishlist):
        response = client.get(f'/wishlist/{wishlist.id}/add_surprise_item/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_owner_does_not_see_surprise_button(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        assert 'add_surprise_item' not in response.content.decode()

    def test_non_owner_sees_surprise_button(self, authenticated_other_user, wishlist):
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        assert 'add_surprise_item' in response.content.decode()


@pytest.mark.unit
class TestSneakyVisibility:
    """Sneaky items are hidden from the owner server-side, visible to everyone else."""

    def test_sneaky_item_hidden_from_owner_detail(self, authenticated_user, wishlist, sneaky_item):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        assert 'Secret Surprise Gift' not in response.content.decode()

    def test_sneaky_item_visible_to_others_with_badge(
        self, authenticated_other_user, wishlist, sneaky_item
    ):
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Secret Surprise Gift' in content
        assert '🤫 Surprise' in content

    def test_owner_edit_formset_excludes_sneaky_item(
        self, authenticated_user, wishlist, item, sneaky_item
    ):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Test Item' in content  # Normal items are still editable
        assert 'Secret Surprise Gift' not in content

    def test_manager_edit_formset_includes_sneaky_item(
        self, authenticated_other_user, other_user, wishlist, sneaky_item
    ):
        wishlist.managers.add(other_user)
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200
        assert 'Secret Surprise Gift' in response.content.decode()

    def test_owner_gets_404_on_item_edit(self, authenticated_user, sneaky_item):
        response = authenticated_user.get(f'/item/edit/{sneaky_item.id}/')
        assert response.status_code == 404

    def test_owner_gets_404_on_item_delete(self, authenticated_user, sneaky_item):
        response = authenticated_user.post(f'/item/delete/{sneaky_item.id}/')
        assert response.status_code == 404
        sneaky_item.refresh_from_db()
        assert sneaky_item.is_deleted is False

    def test_owner_gets_404_on_item_purchase(self, authenticated_user, sneaky_item):
        response = authenticated_user.get(f'/item/purchase/{sneaky_item.id}/')
        assert response.status_code == 404

    def test_non_owner_can_purchase_sneaky_item(
        self, authenticated_other_user, other_user, sneaky_item
    ):
        response = authenticated_other_user.get(f'/item/purchase/{sneaky_item.id}/')
        assert response.status_code == 302
        sneaky_item.refresh_from_db()
        assert sneaky_item.purchased is True
        assert sneaky_item.purchased_by == other_user

    def test_owner_home_card_count_hides_sneaky_items(
        self, authenticated_user, wishlist, item, sneaky_item
    ):
        """The wishlist card on home must not reveal the surprise via its item count."""
        response = authenticated_user.get('/')
        assert response.status_code == 200
        assert 'wl-list-meta">1 items<' in response.content.decode()

    def test_other_user_home_card_count_includes_sneaky_items(
        self, authenticated_other_user, wishlist, item, sneaky_item
    ):
        response = authenticated_other_user.get('/')
        assert response.status_code == 200
        assert 'wl-list-meta">2 items<' in response.content.decode()

    def test_owner_profile_hides_sneaky_item_names(
        self, authenticated_user, wishlist, item, sneaky_item
    ):
        response = authenticated_user.get('/profile/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Test Item' in content
        assert 'Secret Surprise Gift' not in content
