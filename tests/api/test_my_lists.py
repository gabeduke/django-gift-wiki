"""My Lists — the lists you curate, as cards, ahead of account settings.

Also the "Mine / Someone else" targeting quick add uses, which the home-screen
shortcuts and the share sheet lean on.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from gift.models import Item, WishList

User = get_user_model()

pytestmark = pytest.mark.unit


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def kid(db):
    return User.objects.create_user(username='kiddo', first_name='Arlo', password='x')


class TestMyListsPage:
    def test_your_list_is_a_card_with_a_preview(self, authenticated_user, wishlist):
        for name in ('Socks', 'Book', 'Mug', 'Scarf', 'Kite'):
            Item.objects.create(wishlist=wishlist, name=name)

        content = authenticated_user.get('/profile/').content.decode()

        assert 'class="wl-card wl-mylist"' in content
        assert 'Socks' in content
        assert '+ 1 more' in content  # four shown, the fifth summarised
        assert 'Kite' not in content

    def test_most_wanted_items_lead_the_preview(self, authenticated_user, wishlist):
        for i in range(5):
            Item.objects.create(wishlist=wishlist, name=f'Plain {i}')
        Item.objects.create(wishlist=wishlist, name='Top Pick', is_priority=True)

        content = authenticated_user.get('/profile/').content.decode()

        assert 'Top Pick' in content

    def test_each_card_opens_quick_add_on_its_own_list(self, authenticated_user, wishlist):
        content = authenticated_user.get('/profile/').content.decode()

        assert f'data-quick-add data-quick-add-list="{wishlist.id}"' in content

    def test_each_card_can_share_its_link(self, authenticated_user, wishlist):
        content = authenticated_user.get('/profile/').content.decode()

        assert f'data-share-url="http://testserver/wishlist/{wishlist.id}/"' in content

    def test_lists_kept_for_someone_else_are_grouped_separately(
        self, authenticated_user, user, kid, family
    ):
        WishList.objects.create(owner=user, dependent=kid, title='Arlo List', family_name=family)

        content = authenticated_user.get('/profile/').content.decode()

        assert 'Lists you look after' in content
        assert 'Arlo List' in content
        assert 'For Arlo' in content

    def test_lists_you_help_manage_appear_too(self, other_user, wishlist):
        """A co-parent who manages a kid's list should find it on My Lists."""
        wishlist.managers.add(other_user)

        content = signed_in(other_user).get('/profile/').content.decode()

        assert wishlist.title in content

    def test_managers_cannot_delete_from_the_card(self, other_user, wishlist):
        wishlist.managers.add(other_user)

        content = signed_in(other_user).get('/profile/').content.decode()

        assert f'/wishlist/{wishlist.id}/delete/' not in content

    def test_owner_can_delete_from_the_card(self, authenticated_user, wishlist):
        content = authenticated_user.get('/profile/').content.decode()

        assert f'/wishlist/{wishlist.id}/delete/' in content

    def test_surprises_never_reach_the_preview(self, authenticated_user, wishlist, other_user):
        Item.objects.create(wishlist=wishlist, name='Shh Secret', is_sneaky=True, added_by=other_user)

        content = authenticated_user.get('/profile/').content.decode()

        assert 'Shh Secret' not in content

    def test_empty_state_invites_a_first_list(self, authenticated_user):
        content = authenticated_user.get('/profile/').content.decode()

        assert 'Start your wishlist' in content

    def test_sign_out_is_reachable(self, authenticated_user):
        content = authenticated_user.get('/profile/').content.decode()

        assert f'href="{reverse("gift:logout")}"' in content


class TestPickerKnowsWhichListsAreYours:
    def picker(self, client):
        return {entry['title']: entry for entry in client.get('/wishlist/picker/').json()['wishlists']}

    def test_your_own_list_is_mine(self, authenticated_user, wishlist):
        assert self.picker(authenticated_user)[wishlist.title]['is_mine'] is True

    def test_someone_elses_list_is_not(self, authenticated_other_user, wishlist):
        assert self.picker(authenticated_other_user)[wishlist.title]['is_mine'] is False

    def test_a_list_you_keep_for_your_kid_is_not_mine(self, authenticated_user, user, kid, family):
        """You can add to it openly, but it's the kid's list, not yours."""
        WishList.objects.create(owner=user, dependent=kid, title="Arlo's List", family_name=family)

        entry = self.picker(authenticated_user)["Arlo's List"]

        assert entry['is_mine'] is False
        assert entry['can_add_openly'] is True

    def test_the_kid_sees_it_as_theirs(self, user, kid, family):
        WishList.objects.create(owner=user, dependent=kid, title="Arlo's List", family_name=family)

        assert self.picker(signed_in(kid))["Arlo's List"]['is_mine'] is True

    def test_picker_answers_manager_checks_from_the_prefetch(
        self, authenticated_other_user, user, family, django_assert_max_num_queries
    ):
        """can_add_openly used to run a query per list; on Neon that adds up."""
        for i in range(8):
            WishList.objects.create(owner=user, title=f'List {i}', family_name=family)

        with django_assert_max_num_queries(6):
            authenticated_other_user.get('/wishlist/picker/')


class TestShortcutsPutYourListFirst:
    def test_shortcuts_offer_mine_and_someone_else(self, client):
        shortcuts = client.get('/manifest.webmanifest').json()['shortcuts']
        urls = [shortcut['url'] for shortcut in shortcuts]

        assert urls[0].endswith('?quick_add=1&for=me')
        assert urls[1].endswith('?quick_add=1&for=others')
        assert '/my-purchases/' not in urls
