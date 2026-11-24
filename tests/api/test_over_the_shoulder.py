"""Over the shoulder: looking at a list together without spoiling anything.

A parent sitting down with their kid, or anyone showing a list to the person
it's for, turns the mode on and this session is shown every list the way its
recipient sees it — no surprise items, no purchase marks, nothing that can be
marked bought — with a banner on every page so it can't be forgotten.

It lives in the session (see gift/visibility.py), so it describes this screen
rather than the person, and the tests turn it on the way the page does: a POST
to /over-the-shoulder/.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext

from gift.context_processors import over_the_shoulder
from gift.models import Item, WishList
from gift.visibility import OVER_THE_SHOULDER_SESSION_KEY, request_access

User = get_user_model()

pytestmark = pytest.mark.unit

TOGGLE_URL = '/over-the-shoulder/'
BANNER = 'class="wl-shoulder"'
SNEAKY_HEADING = 'Sneaky things added by others'
SHOULDER_BUTTON = 'name="on" value="1"'
PROGRESS = 'class="wl-progress"'


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def make_user(username):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='pass12345'
    )


def turn_on(client, **extra):
    return client.post(TOGGLE_URL, {'on': '1', **extra})


def turn_off(client, **extra):
    return client.post(TOGGLE_URL, extra)


def is_on(client):
    return bool(client.session.get(OVER_THE_SHOULDER_SESSION_KEY))


@pytest.fixture
def kid(db):
    return make_user('kiddo')


@pytest.fixture
def co_parent(db):
    return make_user('coparent')


@pytest.fixture
def helper(db):
    return make_user('helper')


@pytest.fixture
def kid_list(user, kid, co_parent, family):
    """`user` keeps this list for `kid`; `co_parent` helps manage it."""
    wishlist = WishList.objects.create(
        owner=user, dependent=kid, title="Kiddo's List", family_name=family
    )
    wishlist.managers.add(co_parent)
    return wishlist


@pytest.fixture
def kid_items(kid_list, other_user):
    return {
        'bought': Item.objects.create(
            wishlist=kid_list, name='Lego Castle', purchased=True, purchased_by=other_user
        ),
        'plain': Item.objects.create(wishlist=kid_list, name='Scooter'),
        'surprise': Item.objects.create(
            wishlist=kid_list, name='Secret Bike', is_sneaky=True, added_by=other_user
        ),
    }


@pytest.fixture
def own_items(wishlist, other_user, helper):
    """`wishlist` is the `user` fixture's own list; `helper` manages it."""
    wishlist.managers.add(helper)
    return {
        'bought': Item.objects.create(
            wishlist=wishlist, name='Wool Socks', purchased=True, purchased_by=other_user
        ),
        'plain': Item.objects.create(wishlist=wishlist, name='Coffee Grinder'),
        'surprise': Item.objects.create(
            wishlist=wishlist, name='Secret Telescope', is_sneaky=True, added_by=other_user
        ),
    }


# Everyone the mode takes something from: (who, which list, its items).
SHARERS = [
    ('keeper-owner', 'kid'),
    ('keeper-manager', 'kid'),
    ('giver on a kid list', 'kid'),
    ('giver on own list', 'own'),
    ('manager of own list', 'own'),
]


@pytest.fixture
def cast(user, co_parent, other_user, helper, kid, kid_list, wishlist, kid_items, own_items):
    people = {
        'keeper-owner': user,
        'keeper-manager': co_parent,
        'giver on a kid list': other_user,
        'giver on own list': other_user,
        'manager of own list': helper,
        'kid': kid,
        'owner of own list': user,
    }
    lists = {'kid': (kid_list, kid_items), 'own': (wishlist, own_items)}
    return people, lists


@pytest.fixture(params=SHARERS, ids=[who for who, _ in SHARERS])
def sharer(request, cast):
    """A signed-in sharer with the mode on, and the list they're showing."""
    who, which = request.param
    people, lists = cast
    client = signed_in(people[who])
    turn_on(client)
    wishlist, items = lists[which]
    return client, wishlist, items


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


class TestToggle:
    def test_turning_on_sets_the_session_flag(self, authenticated_user):
        response = turn_on(authenticated_user)

        assert response.status_code == 302
        assert response.url == '/'
        assert is_on(authenticated_user)

    def test_posting_without_on_turns_it_off(self, authenticated_user):
        turn_on(authenticated_user)

        turn_off(authenticated_user)

        assert not is_on(authenticated_user)

    def test_any_other_value_turns_it_off(self, authenticated_user):
        turn_on(authenticated_user)

        authenticated_user.post(TOGGLE_URL, {'on': '0'})

        assert not is_on(authenticated_user)

    def test_turning_off_when_already_off_is_harmless(self, authenticated_user):
        assert turn_off(authenticated_user).status_code == 302
        assert not is_on(authenticated_user)

    def test_goes_back_to_the_page_it_came_from(self, authenticated_user, wishlist):
        response = turn_on(authenticated_user, next=f'/wishlist/{wishlist.id}/')

        assert response.url == f'/wishlist/{wishlist.id}/'

    @pytest.mark.parametrize(
        'next_url',
        [
            'https://evil.example.com/',
            '//evil.example.com/wishlist/1/',
            'javascript:alert(1)',
            'http://testserver.evil.example.com/',
        ],
    )
    def test_refuses_an_off_site_next(self, authenticated_user, next_url):
        response = turn_on(authenticated_user, next=next_url)

        assert response.status_code == 302
        assert response.url == '/'
        assert is_on(authenticated_user)

    def test_refuses_an_off_site_next_when_turning_off(self, authenticated_user):
        response = turn_off(authenticated_user, next='https://evil.example.com/')

        assert response.url == '/'

    def test_post_only(self, authenticated_user):
        assert authenticated_user.get(TOGGLE_URL).status_code == 405
        assert not is_on(authenticated_user)

    def test_requires_sign_in(self, client, db):
        response = turn_on(client)

        assert response.status_code == 302
        assert response.url.startswith('/auth.html')
        assert not client.session.get(OVER_THE_SHOULDER_SESSION_KEY)

    def test_belongs_to_the_session_not_the_person(self, user, wishlist):
        """It describes who's looking at this screen; the same person's phone
        in their pocket is unaffected."""
        laptop, phone = signed_in(user), signed_in(user)

        turn_on(laptop)

        assert is_on(laptop)
        assert not is_on(phone)
        assert BANNER not in phone.get('/').content.decode()


class TestBanner:
    def test_absent_when_off(self, authenticated_user, wishlist):
        for path in ('/', f'/wishlist/{wishlist.id}/', '/my-purchases/', '/profile/'):
            assert BANNER not in authenticated_user.get(path).content.decode(), path

    def test_on_every_page_while_on(self, authenticated_user, wishlist):
        turn_on(authenticated_user)

        for path in (
            '/',
            f'/wishlist/{wishlist.id}/',
            f'/wishlist/{wishlist.id}/edit/',
            '/my-purchases/',
            '/received-gifts/',
            '/profile/',
            '/changelog/',
        ):
            response = authenticated_user.get(path)
            assert response.status_code == 200, path
            assert BANNER in response.content.decode(), path

    def test_turn_off_comes_back_to_the_same_page(self, authenticated_user, wishlist):
        turn_on(authenticated_user)

        content = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        banner = content[content.index(BANNER) :]
        banner = banner[: banner.index('</div>')]

        assert f'action="{TOGGLE_URL}"' in banner
        assert f'name="next" value="/wishlist/{wishlist.id}/"' in banner
        assert 'name="on"' not in banner
        assert 'Turn off' in banner

    def test_gone_once_turned_off(self, authenticated_user):
        turn_on(authenticated_user)
        turn_off(authenticated_user)

        assert BANNER not in authenticated_user.get('/').content.decode()

    def test_signed_out_pages_have_no_banner(self, client, db):
        assert BANNER not in client.get('/').content.decode()
        assert BANNER not in client.get('/privacy/').content.decode()

    def test_context_processor_leaves_signed_out_sessions_alone(self):
        """Public pages promise no queries, so the session isn't even looked at."""

        class Untouchable:
            def get(self, *args):
                raise AssertionError('session read for a signed-out request')

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        request.session = Untouchable()

        assert over_the_shoulder(request) == {'over_the_shoulder': False}


# ---------------------------------------------------------------------------
# What a sharer is shown
# ---------------------------------------------------------------------------


class TestWishlistPageWhileOn:
    def test_no_surprises(self, sharer):
        client, wishlist, items = sharer

        response = client.get(f'/wishlist/{wishlist.id}/')
        content = response.content.decode()

        assert items['surprise'].name not in content
        assert SNEAKY_HEADING not in content
        assert 'add_surprise_item' not in content
        assert response.context['sneaky_items'] == []

    def test_no_purchase_marks_buttons_or_progress(self, sharer):
        client, wishlist, items = sharer

        response = client.get(f'/wishlist/{wishlist.id}/')
        content = response.content.decode()

        assert 'Mark Purchased' not in content
        assert 'purchased-badge' not in content
        assert 'Purchased' not in content
        assert '/item/purchase/' not in content
        assert PROGRESS not in content
        assert response.context['purchased_count'] is None

    def test_everything_else_is_still_there(self, sharer):
        client, wishlist, items = sharer

        content = client.get(f'/wishlist/{wishlist.id}/').content.decode()

        assert items['plain'].name in content
        assert items['bought'].name in content
        assert BANNER in content

    def test_no_button_to_turn_it_on_again(self, sharer):
        client, wishlist, _items = sharer

        content = client.get(f'/wishlist/{wishlist.id}/').content.decode()

        assert SHOULDER_BUTTON not in content

    def test_order_does_not_give_away_what_was_bought(self, sharer):
        client, wishlist, items = sharer

        response = client.get(f'/wishlist/{wishlist.id}/')

        assert list(response.context['uncategorized_items']) == [items['bought'], items['plain']]

    def test_access_says_the_mode_is_doing_the_hiding(self, sharer):
        client, wishlist, _items = sharer

        access = client.get(f'/wishlist/{wishlist.id}/').context['access']

        assert access.hiding is True
        assert access.sees_surprises is False
        assert access.sees_purchases is False


class TestRecipientsAreUnaffected:
    """They had nothing hidden from them to begin with."""

    @pytest.mark.parametrize('who, which', [('kid', 'kid'), ('owner of own list', 'own')])
    def test_same_page_either_way(self, cast, who, which):
        people, lists = cast
        wishlist, _items = lists[which]
        client = signed_in(people[who])
        before = client.get(f'/wishlist/{wishlist.id}/')

        turn_on(client)
        after = client.get(f'/wishlist/{wishlist.id}/')

        assert after.context['access'].hiding is False
        assert listed(after) == listed(before)
        assert after.context['sneaky_items'] == before.context['sneaky_items'] == []
        assert BANNER in after.content.decode()


def listed(response):
    grouped = list(response.context['uncategorized_items'])
    for _category, items in response.context['sorted_category_items']:
        grouped.extend(items)
    return grouped


class TestMarkingPurchasedWhileOn:
    def test_refused_and_explained(self, sharer):
        client, _wishlist, items = sharer
        plain = items['plain']

        response = client.post(f'/item/purchase/{plain.id}/', follow=True)

        plain.refresh_from_db()
        assert plain.purchased is False
        assert 'Turn off over-the-shoulder mode before marking anything as purchased.' in (
            response.content.decode()
        )

    def test_cannot_undo_a_purchase_either(self, other_user, own_items):
        bought = own_items['bought']
        client = signed_in(other_user)
        turn_on(client)

        client.post(f'/item/purchase/{bought.id}/')

        bought.refresh_from_db()
        assert bought.purchased_by == other_user

    def test_surprise_is_a_404(self, sharer):
        """Even a refusal would confirm the surprise exists."""
        client, _wishlist, items = sharer

        assert client.post(f'/item/purchase/{items["surprise"].id}/').status_code == 404

    def test_works_again_once_turned_off(self, authenticated_other_user, other_user, own_items):
        plain = own_items['plain']
        turn_on(authenticated_other_user)
        turn_off(authenticated_other_user)

        authenticated_other_user.post(f'/item/purchase/{plain.id}/')

        plain.refresh_from_db()
        assert plain.purchased_by == other_user


class TestMyPurchasesWhileOn:
    def test_shows_a_placeholder_instead(self, authenticated_other_user, own_items):
        turn_on(authenticated_other_user)

        response = authenticated_other_user.get('/my-purchases/')
        content = response.content.decode()

        assert response.status_code == 200
        assert response.context['hidden'] is True
        assert "Hidden while you're over the shoulder" in content
        assert 'Wool Socks' not in content

    def test_back_once_turned_off(self, authenticated_other_user, own_items):
        turn_on(authenticated_other_user)
        turn_off(authenticated_other_user)

        assert 'Wool Socks' in authenticated_other_user.get('/my-purchases/').content.decode()


class TestSurpriseItemsWhileOn:
    @pytest.fixture(params=['keeper-owner', 'manager of own list'])
    def editor(self, request, cast):
        """Someone who may normally edit the surprise items on their list."""
        people, lists = cast
        which = 'kid' if request.param == 'keeper-owner' else 'own'
        client = signed_in(people[request.param])
        turn_on(client)
        return client, lists[which][1]

    def test_editing_a_surprise_is_a_404(self, editor):
        client, items = editor

        assert client.get(f'/item/edit/{items["surprise"].id}/').status_code == 404

    def test_deleting_a_surprise_is_a_404(self, editor):
        client, items = editor
        surprise = items['surprise']

        assert client.post(f'/item/delete/{surprise.id}/').status_code == 404
        surprise.refresh_from_db()
        assert surprise.is_deleted is False

    def test_ordinary_items_can_still_be_edited(self, editor):
        client, items = editor

        assert client.get(f'/item/edit/{items["plain"].id}/').status_code == 200

    def test_edit_list_leaves_the_surprises_out(self, editor):
        client, items = editor
        wishlist = items['plain'].wishlist

        content = client.get(f'/wishlist/{wishlist.id}/edit/').content.decode()

        assert items['plain'].name in content
        assert items['surprise'].name not in content

    def test_add_surprise_page_sends_you_back_to_the_list(self, sharer):
        client, wishlist, _items = sharer

        response = client.get(f'/wishlist/{wishlist.id}/add_surprise_item/')

        assert response.status_code == 302
        assert response.url == f'/wishlist/{wishlist.id}/'

    def test_add_surprise_post_creates_nothing(self, sharer):
        client, wishlist, _items = sharer

        client.post(f'/wishlist/{wishlist.id}/add_surprise_item/', {'name': 'Shh Kite'})

        assert not Item.objects.filter(name='Shh Kite').exists()


class TestQuickAddWhileOn:
    def quick_add(self, client, wishlist, name):
        return client.post(
            '/item/quick-add/',
            data=json.dumps({'wishlist_id': wishlist.id, 'name': name}),
            content_type='application/json',
        )

    def picker_ids(self, client):
        response = client.get('/wishlist/picker/')
        assert response.status_code == 200
        return {entry['id'] for entry in response.json()['wishlists']}

    def test_picker_only_offers_lists_you_add_to_openly(
        self, authenticated_other_user, other_user, family, wishlist, kid_list
    ):
        theirs = WishList.objects.create(owner=other_user, title='Mine', family_name=family)

        before = self.picker_ids(authenticated_other_user)
        turn_on(authenticated_other_user)
        after = self.picker_ids(authenticated_other_user)

        assert before == {theirs.id, wishlist.id, kid_list.id}
        assert after == {theirs.id}

    def test_keeper_still_gets_the_kid_list(self, authenticated_user, wishlist, kid_list):
        turn_on(authenticated_user)

        assert self.picker_ids(authenticated_user) == {wishlist.id, kid_list.id}

    def test_surprise_add_is_refused(self, authenticated_other_user, wishlist):
        turn_on(authenticated_other_user)

        response = self.quick_add(authenticated_other_user, wishlist, 'Shh Kite')

        assert response.status_code == 400
        assert response.json()['status'] == 'error'
        assert not Item.objects.filter(name='Shh Kite').exists()

    def test_open_add_still_works(self, authenticated_user, kid_list):
        turn_on(authenticated_user)

        response = self.quick_add(authenticated_user, kid_list, 'Roller Skates')

        assert response.status_code == 200
        assert Item.objects.get(name='Roller Skates').is_sneaky is False

    def test_surprise_add_works_again_once_off(self, authenticated_other_user, wishlist):
        turn_on(authenticated_other_user)
        turn_off(authenticated_other_user)

        assert self.quick_add(authenticated_other_user, wishlist, 'Shh Kite').status_code == 200
        assert Item.objects.get(name='Shh Kite').is_sneaky is True


class TestGlanceWhileOn:
    def test_no_purchases_and_no_surprises(self, sharer):
        client, wishlist, items = sharer

        response = client.get(f'/wishlist/{wishlist.id}/glance/')
        listed_items = response.json()['items']

        assert {item['name'] for item in listed_items} == {
            items['plain'].name,
            items['bought'].name,
        }
        for item in listed_items:
            assert 'purchased' not in item
            assert item['is_sneaky'] is False


class TestHomeWhileOn:
    def card_count(self, client, wishlist):
        response = client.get('/?group_by=alpha')
        for lists in response.context['wishlists_grouped'].values():
            for listed_list in lists:
                if listed_list.id == wishlist.id:
                    return listed_list.card_item_count
        raise AssertionError('list not on the home page')

    def test_card_count_drops_the_surprises(self, sharer):
        client, wishlist, _items = sharer
        turn_off(client)
        before = self.card_count(client, wishlist)

        turn_on(client)

        assert self.card_count(client, wishlist) == before - 1 == 2


class TestEveryoneElseIsUnaffected:
    def test_another_person_still_sees_everything(self, user, other_user, kid_list, kid_items):
        """The parent showing the kid the list doesn't hide anything from the
        grandparent looking at it on their own phone."""
        turn_on(signed_in(user))

        content = signed_in(other_user).get(f'/wishlist/{kid_list.id}/').content.decode()

        assert 'Secret Bike' in content
        assert 'purchased-badge' in content
        assert BANNER not in content


# ---------------------------------------------------------------------------
# The public pages still never touch the database
# ---------------------------------------------------------------------------


PUBLIC_PATHS = ['/manifest.webmanifest', '/sw.js', '/offline/', '/health/', '/robots.txt']


class TestNoDatabase:
    @pytest.mark.parametrize('path', PUBLIC_PATHS)
    def test_anonymous_fetch_runs_no_queries(self, client, db, django_assert_num_queries, path):
        with django_assert_num_queries(0):
            assert client.get(path).status_code == 200

    @pytest.mark.parametrize('path', PUBLIC_PATHS)
    def test_fetch_while_over_the_shoulder_runs_no_queries(
        self, authenticated_user, django_assert_num_queries, path
    ):
        """A session with the mode on still sends its cookie; it must not be
        resolved just to decide on a banner."""
        turn_on(authenticated_user)

        with django_assert_num_queries(0):
            response = authenticated_user.get(path)

        assert response.status_code == 200
        assert BANNER not in response.content.decode()


class TestRequestAccess:
    def test_reads_the_mode_from_the_session(self, rf, other_user, wishlist):
        request = rf.get('/')
        request.user = other_user
        request.session = {}

        assert request_access(request, wishlist).sees_purchases is True

        request.session[OVER_THE_SHOULDER_SESSION_KEY] = True

        assert request_access(request, wishlist).sees_purchases is False
        assert request_access(request, wishlist).hiding is True


class TestNothingToClickThatGivesItAway:
    """Buttons that sweep bought items away would show what was bought."""

    @pytest.fixture
    def kept(self, user, other_user, family):
        wishlist = WishList.objects.create(
            owner=user, dependent=other_user, title="Kid's List", family_name=family
        )
        Item.objects.create(wishlist=wishlist, name='Bike', purchased=True, purchased_by=user)
        return wishlist

    def _client(self, user, on):
        client = Client()
        client.force_login(user)
        if on:
            client.post('/over-the-shoulder/', {'on': '1'})
        return client

    def test_archive_button_goes_away(self, user, kept):
        assert 'Archive Received Gifts' in self._client(user, False).get(
            f'/wishlist/{kept.id}/'
        ).content.decode()
        assert 'Archive Received Gifts' not in self._client(user, True).get(
            f'/wishlist/{kept.id}/'
        ).content.decode()

    def test_clear_purchased_goes_away(self, user, kept):
        assert 'Clear purchased' in self._client(user, False).get(
            f'/wishlist/{kept.id}/edit/'
        ).content.decode()
        assert 'Clear purchased' not in self._client(user, True).get(
            f'/wishlist/{kept.id}/edit/'
        ).content.decode()

    def test_home_does_not_query_per_list(self, user, family):
        client = self._client(user, False)
        for n in range(3):
            owner = User.objects.create_user(username=f'o{n}', email=f'o{n}@example.com')
            WishList.objects.create(owner=owner, title=f'L{n}', family_name=family)
        with CaptureQueriesContext(connection) as few:
            client.get('/?group_by=alpha')
        for n in range(3, 9):
            owner = User.objects.create_user(username=f'o{n}', email=f'o{n}@example.com')
            WishList.objects.create(owner=owner, title=f'L{n}', family_name=family)
        with CaptureQueriesContext(connection) as many:
            client.get('/?group_by=alpha')
        assert len(many) == len(few)
