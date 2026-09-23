"""Tests for quick-add — adding an item to any list from the nav (issue #112).

The permission rule is not new: it's the same one `item_add` and
`sneaky_item_add` already enforce, reached through one JSON endpoint.
Owner-side (owner, dependent, manager) adds an ordinary item; anyone else
adds a surprise item the recipient can't see. The tests below pin that
matrix down, because getting it backwards would spoil a gift.
"""
import json

import pytest
from django.contrib.auth import get_user_model

from gift.models import Item, WishList

User = get_user_model()

QUICK_ADD_URL = '/item/quick-add/'
PICKER_URL = '/wishlist/picker/'


def quick_add(client, wishlist_id, **fields):
    payload = {'wishlist_id': wishlist_id}
    payload.update(fields)
    return client.post(QUICK_ADD_URL, data=json.dumps(payload), content_type='application/json')


@pytest.mark.unit
class TestQuickAddPermissions:
    """Who gets an ordinary item and who gets a surprise one."""

    def test_owner_adds_an_ordinary_item(self, authenticated_user, wishlist, user):
        response = quick_add(authenticated_user, wishlist.id, name='Coffee Grinder')

        assert response.status_code == 200
        item = Item.objects.get(name='Coffee Grinder')
        assert item.wishlist == wishlist
        assert item.is_sneaky is False
        assert item.added_by == user
        assert item.updated_by == user

    def test_owner_never_creates_a_surprise_on_their_own_list(
        self, authenticated_user, wishlist
    ):
        """Even if the client asks for one — an owner seeing their own surprise
        item would be nonsense, and the flag is not client-controlled."""
        quick_add(authenticated_user, wishlist.id, name='Not Sneaky', is_sneaky=True)

        assert Item.objects.get(name='Not Sneaky').is_sneaky is False

    def test_dependent_adds_an_ordinary_item(self, authenticated_other_user, user, other_user, family):
        """The list is kept on the dependent's behalf, so they're owner-side."""
        wishlist = WishList.objects.create(
            owner=user, dependent=other_user, title="Kid's List", family_name=family
        )

        quick_add(authenticated_other_user, wishlist.id, name='Scooter')

        assert Item.objects.get(name='Scooter').is_sneaky is False

    def test_manager_adds_an_ordinary_item(self, authenticated_other_user, wishlist, other_user):
        wishlist.managers.add(other_user)

        quick_add(authenticated_other_user, wishlist.id, name='Managed Item')

        assert Item.objects.get(name='Managed Item').is_sneaky is False

    def test_everyone_else_adds_a_surprise_item(
        self, authenticated_other_user, wishlist, other_user
    ):
        response = quick_add(authenticated_other_user, wishlist.id, name='Secret Telescope')

        assert response.status_code == 200
        item = Item.objects.get(name='Secret Telescope')
        assert item.is_sneaky is True
        assert item.added_by == other_user

    def test_response_says_whether_it_was_a_surprise(
        self, authenticated_other_user, authenticated_user, wishlist
    ):
        """The UI tells the user which kind of item they just created, so the
        answer has to come back from the server that decided it."""
        surprise = quick_add(authenticated_other_user, wishlist.id, name='Surprise One')
        own = quick_add(authenticated_user, wishlist.id, name='Own One')

        assert surprise.json()['is_sneaky'] is True
        assert own.json()['is_sneaky'] is False


@pytest.mark.unit
class TestQuickAddValidation:
    def test_name_is_required(self, authenticated_user, wishlist):
        response = quick_add(authenticated_user, wishlist.id, name='   ')

        assert response.status_code == 400
        assert Item.objects.filter(wishlist=wishlist).count() == 0

    def test_missing_name_key_is_rejected(self, authenticated_user, wishlist):
        response = quick_add(authenticated_user, wishlist.id)

        assert response.status_code == 400

    def test_name_is_trimmed(self, authenticated_user, wishlist):
        quick_add(authenticated_user, wishlist.id, name='  Wool Socks  ')

        assert Item.objects.filter(name='Wool Socks').exists()

    def test_overlong_name_is_rejected(self, authenticated_user, wishlist):
        """Item.name is max_length=255 — Postgres would raise rather than truncate."""
        response = quick_add(authenticated_user, wishlist.id, name='x' * 256)

        assert response.status_code == 400
        assert Item.objects.filter(wishlist=wishlist).count() == 0

    def test_optional_url_is_saved(self, authenticated_user, wishlist):
        quick_add(
            authenticated_user, wishlist.id, name='Linked Item', url='https://example.com/thing'
        )

        assert Item.objects.get(name='Linked Item').url == 'https://example.com/thing'

    def test_malformed_url_is_rejected(self, authenticated_user, wishlist):
        response = quick_add(authenticated_user, wishlist.id, name='Bad Link', url='not a url')

        assert response.status_code == 400
        assert not Item.objects.filter(name='Bad Link').exists()

    def test_blank_url_is_allowed(self, authenticated_user, wishlist):
        response = quick_add(authenticated_user, wishlist.id, name='No Link', url='')

        assert response.status_code == 200
        assert Item.objects.get(name='No Link').url in ('', None)

    def test_unknown_wishlist_is_404(self, authenticated_user, db):
        response = quick_add(authenticated_user, 999999, name='Nowhere')

        assert response.status_code == 404

    def test_malformed_json_is_rejected(self, authenticated_user, wishlist):
        response = authenticated_user.post(
            QUICK_ADD_URL, data='{not json', content_type='application/json'
        )

        assert response.status_code == 400


@pytest.mark.unit
class TestQuickAddAccess:
    def test_anonymous_users_are_turned_away(self, client, wishlist):
        response = quick_add(client, wishlist.id, name='Anon Item')

        assert response.status_code in (302, 403)
        assert not Item.objects.filter(name='Anon Item').exists()

    def test_get_is_not_allowed(self, authenticated_user, wishlist):
        assert authenticated_user.get(QUICK_ADD_URL).status_code == 405


@pytest.mark.unit
class TestWishlistPicker:
    def test_lists_every_wishlist_with_its_person(self, authenticated_user, wishlist, user):
        response = authenticated_user.get(PICKER_URL)

        assert response.status_code == 200
        entry = next(e for e in response.json()['wishlists'] if e['id'] == wishlist.id)
        assert entry['title'] == 'Test Wishlist'
        assert entry['person'] == 'testuser'
        assert entry['can_add_openly'] is True

    def test_person_is_the_dependent_when_there_is_one(
        self, authenticated_user, user, other_user, family
    ):
        """Matches how the home page labels a list, so the picker reads the same."""
        other_user.first_name = 'Milo'
        other_user.save()
        wishlist = WishList.objects.create(
            owner=user, dependent=other_user, title="Milo's List", family_name=family
        )

        entries = authenticated_user.get(PICKER_URL).json()['wishlists']

        assert next(e for e in entries if e['id'] == wishlist.id)['person'] == 'Milo'

    def test_flags_lists_the_viewer_can_add_to_openly(
        self, authenticated_other_user, wishlist, other_user, user, family
    ):
        """Drives the surprise-gift notice in the modal, so it has to match the
        rule the add endpoint actually applies."""
        own = WishList.objects.create(owner=other_user, title='Mine', family_name=family)

        entries = authenticated_other_user.get(PICKER_URL).json()['wishlists']
        by_id = {e['id']: e for e in entries}

        assert by_id[own.id]['can_add_openly'] is True
        assert by_id[wishlist.id]['can_add_openly'] is False

    def test_managed_lists_count_as_openly_addable(
        self, authenticated_other_user, wishlist, other_user
    ):
        wishlist.managers.add(other_user)

        entries = authenticated_other_user.get(PICKER_URL).json()['wishlists']

        assert next(e for e in entries if e['id'] == wishlist.id)['can_add_openly'] is True

    def test_more_options_url_matches_the_add_rule(
        self, authenticated_other_user, wishlist, other_user, family
    ):
        """'More options…' has to land on the form the viewer is actually
        allowed to use — the full add form for their own list, the surprise
        form for someone else's."""
        own = WishList.objects.create(owner=other_user, title='Mine', family_name=family)

        by_id = {e['id']: e for e in authenticated_other_user.get(PICKER_URL).json()['wishlists']}

        assert by_id[own.id]['more_options_url'] == f'/wishlist/{own.id}/add_item/'
        assert (
            by_id[wishlist.id]['more_options_url']
            == f'/wishlist/{wishlist.id}/add_surprise_item/'
        )

    def test_anonymous_users_are_turned_away(self, client, wishlist):
        response = client.get(PICKER_URL)

        assert response.status_code in (302, 403)


@pytest.mark.unit
class TestMoreOptionsPrefill:
    """'More options…' hands off to the full form — what was typed comes along."""

    def test_item_add_form_prefills_from_query_string(self, authenticated_user, wishlist):
        response = authenticated_user.get(
            f'/wishlist/{wishlist.id}/add_item/?name=Espresso+Machine&url=https://example.com/e'
        )

        assert response.status_code == 200
        form = response.context['form']
        assert form.initial['name'] == 'Espresso Machine'
        assert form.initial['url'] == 'https://example.com/e'

    def test_surprise_form_prefills_from_query_string(self, authenticated_other_user, wishlist):
        response = authenticated_other_user.get(
            f'/wishlist/{wishlist.id}/add_surprise_item/?name=Secret+Kite'
        )

        assert response.status_code == 200
        assert response.context['form'].initial['name'] == 'Secret Kite'

    def test_prefill_is_absent_without_query_params(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/add_item/')

        assert not response.context['form'].initial.get('name')


@pytest.mark.unit
class TestQuickAddEntryPoint:
    def test_nav_offers_quick_add_to_signed_in_users(self, authenticated_user, wishlist):
        content = authenticated_user.get('/').content.decode()

        assert 'id="wl-quick-add-open"' in content
        assert 'id="wl-quick-add-modal"' in content

    def test_nav_hides_quick_add_from_anonymous_visitors(self, client, db):
        content = client.get('/').content.decode()

        assert 'id="wl-quick-add-open"' not in content
        assert 'id="wl-quick-add-modal"' not in content

    def test_quick_add_is_reachable_beyond_the_home_page(self, authenticated_user, wishlist):
        """It lives in the nav precisely so it isn't home-only."""
        content = authenticated_user.get('/my-purchases/').content.decode()

        assert 'id="wl-quick-add-open"' in content


@pytest.mark.unit
class TestRetiredEndpoint:
    def test_old_add_item_ajax_endpoint_is_gone(self, authenticated_user, wishlist):
        """Superseded by quick-add; it was dead code with no callers."""
        response = authenticated_user.post(
            f'/wishlist/{wishlist.id}/add_item_ajax/',
            data=json.dumps({'name': 'Legacy'}),
            content_type='application/json',
        )

        assert response.status_code == 404
