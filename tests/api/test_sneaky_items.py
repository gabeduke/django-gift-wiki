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

    def test_sneaky_item_visible_to_others_in_its_own_section(
        self, authenticated_other_user, wishlist, sneaky_item
    ):
        """The inline badge is gone: sneaky items are no longer interleaved
        with the recipient's own items, they live under their own heading."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Secret Surprise Gift' in content
        assert 'Sneaky things added by others' in content

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


@pytest.mark.unit
class TestSneakySection:
    """Sneaky items live in their own labelled section, not folded into the
    owner's categories — the whole point is that they read as *other people's*
    additions rather than as things the recipient asked for.
    """

    SECTION_HEADING = 'Sneaky things added by others'

    def test_non_owner_sees_the_section_with_its_items(
        self, authenticated_other_user, wishlist, sneaky_item
    ):
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')

        content = response.content.decode()
        assert self.SECTION_HEADING in content
        assert 'Secret Surprise Gift' in content
        assert list(response.context['sneaky_items']) == [sneaky_item]

    def test_sneaky_items_are_pulled_out_of_the_category_groups(
        self, authenticated_other_user, wishlist, item, sneaky_item
    ):
        """They used to render inline with a badge, which is how the feature
        went unnoticed for six weeks."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')

        grouped = list(response.context['uncategorized_items'])
        for _category, items in response.context['sorted_category_items']:
            grouped.extend(items)

        assert sneaky_item not in grouped
        assert item in grouped

    def test_empty_section_still_renders_for_non_owner(
        self, authenticated_other_user, wishlist, item
    ):
        """A section that only appears once items exist cannot teach anyone the
        feature exists. Non-owners always see it, empty or not."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')

        content = response.content.decode()
        assert self.SECTION_HEADING in content
        assert list(response.context['sneaky_items']) == []

    def test_owner_never_sees_the_section(self, authenticated_user, wishlist, sneaky_item):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')

        content = response.content.decode()
        assert self.SECTION_HEADING not in content
        assert not response.context['sneaky_items']

    def test_steward_never_sees_the_section(self, authenticated_other_user, wishlist, other_user):
        """The dependent is a recipient too — the surprise must hold for them."""
        wishlist.dependent = other_user
        wishlist.save()
        Item.objects.create(
            wishlist=wishlist, name='Secret Surprise Gift', is_sneaky=True, updated_by=other_user
        )

        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')

        assert self.SECTION_HEADING not in response.content.decode()

    def test_total_count_excludes_sneaky_items(
        self, authenticated_other_user, wishlist, item, sneaky_item
    ):
        """The headline count reflects what the recipient actually asked for."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')

        assert response.context['total_count'] == 1


@pytest.mark.unit
class TestSneakyAttribution:
    """Knowing who claimed an idea is what stops two people buying it."""

    def test_added_by_is_recorded_when_a_sneaky_item_is_created(
        self, authenticated_other_user, wishlist, other_user
    ):
        authenticated_other_user.post(
            f'/wishlist/{wishlist.id}/add_surprise_item/',
            {'name': 'Pottery class gift card', 'description': ''},
        )

        created = Item.objects.get(name='Pottery class gift card')
        assert created.added_by == other_user

    def test_added_by_survives_an_edit_by_someone_else(self, wishlist, user, other_user):
        """`updated_by` is clobbered on every save, which is why attribution
        needs its own field."""
        created = Item.objects.create(
            wishlist=wishlist, name='Binoculars', is_sneaky=True,
            added_by=other_user, updated_by=other_user,
        )

        created.name = 'Better binoculars'
        created.save(current_user=user)

        created.refresh_from_db()
        assert created.updated_by == user
        assert created.added_by == other_user
