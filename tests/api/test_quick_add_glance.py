"""Quick add's "already on this list" check — the glance endpoint.

When a list is picked, quick add fetches what's on it and warns as you type if
the idea looks like a duplicate, showing givers the surprise items others have
added ("add alongside these sneaky things").

That makes this endpoint another window onto a list, so it must show exactly
what the wishlist page shows: a surprise item reaching its recipient would
spoil the gift, and purchase status reaching anyone owner-side would too.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from gift.models import Item, WishList

User = get_user_model()

pytestmark = pytest.mark.unit


def glance(client, wishlist):
    response = client.get(f'/wishlist/{wishlist.id}/glance/')
    assert response.status_code == 200
    return response.json()


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def names(data):
    return [item['name'] for item in data['items']]


@pytest.fixture
def stocked(wishlist, other_user):
    """A list with one of everything: plain, bought, surprise, deleted, archived."""
    Item.objects.create(wishlist=wishlist, name='Coffee Grinder', url='https://example.com/g')
    Item.objects.create(
        wishlist=wishlist, name='Wool Socks', purchased=True, purchased_by=other_user
    )
    Item.objects.create(
        wishlist=wishlist, name='Secret Telescope', is_sneaky=True, added_by=other_user
    )
    Item.objects.create(wishlist=wishlist, name='Deleted Thing', is_deleted=True)
    Item.objects.create(wishlist=wishlist, name='Last Year', archived_at=timezone.now())
    return wishlist


class TestWhoSeesWhat:
    def test_owner_never_sees_surprise_items(self, authenticated_user, stocked):
        assert 'Secret Telescope' not in names(glance(authenticated_user, stocked))

    def test_dependent_never_sees_surprise_items(self, user, other_user, family):
        wishlist = WishList.objects.create(
            owner=user, dependent=other_user, title="Kid's List", family_name=family
        )
        Item.objects.create(wishlist=wishlist, name='Bike', is_sneaky=True, added_by=user)
        client = signed_in(other_user)

        assert names(glance(client, wishlist)) == []

    def test_giver_sees_surprise_items_and_who_added_them(self, authenticated_other_user, stocked):
        data = glance(authenticated_other_user, stocked)
        surprise = next(item for item in data['items'] if item['name'] == 'Secret Telescope')

        assert surprise['is_sneaky'] is True
        assert surprise['added_by'] == 'otheruser'

    def test_manager_sees_surprise_items_like_the_wishlist_page(self, other_user, stocked):
        """Managers see surprises on the wishlist page (they aren't the
        recipient), so the glance mirrors that rather than inventing a rule."""
        stocked.managers.add(other_user)
        client = signed_in(other_user)

        assert 'Secret Telescope' in names(glance(client, stocked))

    def test_giver_sees_what_has_been_bought(self, authenticated_other_user, stocked):
        items = {item['name']: item for item in glance(authenticated_other_user, stocked)['items']}

        assert items['Wool Socks']['purchased'] is True
        assert items['Coffee Grinder']['purchased'] is False

    def test_owner_never_learns_what_has_been_bought(self, authenticated_user, stocked):
        for item in glance(authenticated_user, stocked)['items']:
            assert 'purchased' not in item

    def test_manager_never_learns_what_has_been_bought(self, other_user, stocked):
        stocked.managers.add(other_user)
        client = signed_in(other_user)

        for item in glance(client, stocked)['items']:
            assert 'purchased' not in item


class TestWhatIsListed:
    def test_deleted_and_archived_items_are_left_out(self, authenticated_other_user, stocked):
        listed = names(glance(authenticated_other_user, stocked))

        assert 'Deleted Thing' not in listed
        assert 'Last Year' not in listed

    def test_links_are_included_for_matching_by_url(self, authenticated_user, stocked):
        items = {item['name']: item for item in glance(authenticated_user, stocked)['items']}

        assert items['Coffee Grinder']['url'] == 'https://example.com/g'
        assert items['Wool Socks']['url'] == ''

    def test_names_the_person_the_list_is_for(self, authenticated_other_user, stocked):
        assert glance(authenticated_other_user, stocked)['person'] == 'testuser'

    def test_empty_list(self, authenticated_user, wishlist):
        assert glance(authenticated_user, wishlist)['items'] == []


class TestAccess:
    def test_requires_sign_in(self, client, wishlist):
        response = client.get(f'/wishlist/{wishlist.id}/glance/')

        assert response.status_code == 302

    def test_unknown_list_is_a_404(self, authenticated_user, db):
        assert authenticated_user.get('/wishlist/99999/glance/').status_code == 404

    def test_get_only(self, authenticated_user, wishlist):
        assert authenticated_user.post(f'/wishlist/{wishlist.id}/glance/').status_code == 405


class TestPickerLinksToGlance:
    def test_each_picker_entry_carries_its_glance_url(self, authenticated_user, wishlist):
        entries = authenticated_user.get('/wishlist/picker/').json()['wishlists']

        assert entries[0]['glance_url'] == f'/wishlist/{wishlist.id}/glance/'


class TestWishlistPageAgreesWithGlance:
    """Both read through active_items_visible_to, so they can't drift apart."""

    def test_owner_sees_the_same_items_on_both(self, authenticated_user, stocked):
        page = authenticated_user.get(f'/wishlist/{stocked.id}/').content.decode()

        for name in names(glance(authenticated_user, stocked)):
            assert name in page
        assert 'Secret Telescope' not in page

    def test_wishlist_page_preselects_itself_for_quick_add(self, authenticated_user, wishlist):
        page = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()

        assert f'data-quick-add-list="{wishlist.id}"' in page
