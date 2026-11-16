"""Lists kept for a kid: who sees the surprises and the purchases.

The rules live in gift/visibility.py. A list kept for someone (a parent's list
for their kid) has a **recipient**, the kid, and **keepers**, the owner and
managers who run it. Keepers are givers too, so they see surprise items and
what's been bought, and can mark things bought. The kid sees none of it.

Everything else is unchanged: on someone's own list the owner is the
recipient, a manager sees surprises but not purchases, and anyone else is a
giver.

Each test below looks at one window onto a list (the wishlist page, the
purchase link, the glance JSON, the home card, Edit List) from the point of
view of one of those people.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from gift.models import Item, WishList
from gift.visibility import (
    access_for,
    active_items_visible_to,
    is_kept_for_someone,
    recipient_of,
)

User = get_user_model()

pytestmark = pytest.mark.unit

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


@pytest.fixture
def kid(db):
    return make_user('kiddo')


@pytest.fixture
def co_parent(db):
    return make_user('coparent')


@pytest.fixture
def helper(db):
    """Helps edit `wishlist`, which is the `user` fixture's own list."""
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
    """Bought first, so an order that sorted by `purchased` would show."""
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


def page(client, wishlist):
    response = client.get(f'/wishlist/{wishlist.id}/')
    assert response.status_code == 200
    return response


def listed_names(response):
    grouped = list(response.context['uncategorized_items'])
    for _category, items in response.context['sorted_category_items']:
        grouped.extend(items)
    return [item.name for item in grouped]


def glance(client, wishlist):
    response = client.get(f'/wishlist/{wishlist.id}/glance/')
    assert response.status_code == 200
    return {item['name']: item for item in response.json()['items']}


# ---------------------------------------------------------------------------
# access_for(): the rules themselves
# ---------------------------------------------------------------------------


class TestAccessForTruthTable:
    """One row per kind of person. Columns follow ListAccess's fields."""

    FIELDS = ('can_manage', 'is_recipient', 'is_keeper', 'sees_surprises', 'sees_purchases')

    @pytest.fixture
    def cast(self, user, kid, co_parent, other_user, helper, kid_list, wishlist):
        wishlist.managers.add(helper)
        return {
            'keeper-owner': (kid_list, user),
            'keeper-manager': (kid_list, co_parent),
            'kid': (kid_list, kid),
            'giver on a kid list': (kid_list, other_user),
            'owner of own list': (wishlist, user),
            'manager of own list': (wishlist, helper),
            'giver on own list': (wishlist, other_user),
        }

    @pytest.mark.parametrize(
        'who, expected',
        [
            # who                    manage recip  keeper surpr  purch
            ('keeper-owner',         (True,  False, True,  True,  True)),
            ('keeper-manager',       (True,  False, True,  True,  True)),
            ('kid',                  (True,  True,  False, False, False)),
            ('giver on a kid list',  (False, False, False, True,  True)),
            ('owner of own list',    (True,  True,  False, False, False)),
            ('manager of own list',  (True,  False, False, True,  False)),
            ('giver on own list',    (False, False, False, True,  True)),
        ],
    )  # fmt: skip
    def test_normal_view(self, cast, who, expected):
        wishlist, person = cast[who]
        access = access_for(wishlist, person)

        assert tuple(getattr(access, field) for field in self.FIELDS) == expected
        assert access.hiding is False

    @pytest.mark.parametrize(
        'who, hiding',
        [
            ('keeper-owner', True),
            ('keeper-manager', True),
            ('kid', False),
            ('giver on a kid list', True),
            ('owner of own list', False),
            ('manager of own list', True),
            ('giver on own list', True),
        ],
    )
    def test_over_the_shoulder_hides_both_secrets_from_everyone(self, cast, who, hiding):
        """`hiding` is only true for people the mode actually took something
        from — the recipient had nothing to hide in the first place."""
        wishlist, person = cast[who]
        normal = access_for(wishlist, person)
        shoulder = access_for(wishlist, person, over_the_shoulder=True)

        assert shoulder.sees_surprises is False
        assert shoulder.sees_purchases is False
        assert shoulder.hiding is hiding
        # Who you are doesn't change, only what you're shown
        assert shoulder.can_manage == normal.can_manage
        assert shoulder.is_recipient == normal.is_recipient
        assert shoulder.is_keeper == normal.is_keeper


class TestWhoTheListIsFor:
    def test_kid_list_is_for_the_kid(self, kid_list, kid):
        assert recipient_of(kid_list) == kid
        assert is_kept_for_someone(kid_list) is True

    def test_own_list_is_for_the_owner(self, wishlist, user):
        assert recipient_of(wishlist) == user
        assert is_kept_for_someone(wishlist) is False

    def test_a_list_naming_its_owner_as_dependent_is_still_their_own(self, wishlist, user):
        """No keepers there: the owner is the recipient and sees no secrets."""
        wishlist.dependent = user
        wishlist.save()

        access = access_for(wishlist, user)

        assert is_kept_for_someone(wishlist) is False
        assert access.is_recipient is True
        assert access.is_keeper is False
        assert access.sees_surprises is False
        assert access.sees_purchases is False


class TestActiveItemsVisibleTo:
    def test_keeper_gets_the_surprise(self, kid_list, kid_items, user):
        items = active_items_visible_to(kid_list, access_for(kid_list, user))

        assert kid_items['surprise'] in items

    def test_kid_never_gets_the_surprise(self, kid_list, kid_items, kid):
        items = active_items_visible_to(kid_list, access_for(kid_list, kid))

        assert kid_items['surprise'] not in items
        assert kid_items['plain'] in items

    def test_keeper_over_the_shoulder_does_not_get_the_surprise(self, kid_list, kid_items, user):
        access = access_for(kid_list, user, over_the_shoulder=True)

        assert kid_items['surprise'] not in active_items_visible_to(kid_list, access)


# ---------------------------------------------------------------------------
# The wishlist page
# ---------------------------------------------------------------------------


class TestKeeperSeesTheWholeList:
    @pytest.fixture(params=['owner', 'manager'])
    def keeper_client(self, request, user, co_parent):
        return signed_in(user if request.param == 'owner' else co_parent)

    def test_sees_surprises_in_their_own_section(self, keeper_client, kid_list, kid_items):
        response = page(keeper_client, kid_list)
        content = response.content.decode()

        assert SNEAKY_HEADING in content
        assert 'Secret Bike' in content
        # Hidden from the kid the list is for, not from the parent who owns it
        assert 'Hidden from kiddo' in content
        assert response.context['sneaky_items'] == [kid_items['surprise']]

    def test_sees_what_has_been_bought(self, keeper_client, kid_list, kid_items):
        response = page(keeper_client, kid_list)
        content = response.content.decode()

        assert 'purchased-badge' in content
        assert 'Purchased' in content
        assert PROGRESS in content
        assert '<span class="wl-progress-mono">1/2</span>' in content
        assert response.context['purchased_count'] == 1

    def test_can_mark_things_bought(self, keeper_client, kid_list, kid_items):
        content = page(keeper_client, kid_list).content.decode()

        assert 'Mark Purchased' in content
        assert f'/item/purchase/{kid_items["plain"].id}/' in content
        assert f'/item/purchase/{kid_items["surprise"].id}/' in content

    def test_still_manages_the_list(self, keeper_client, kid_list, kid_items):
        response = page(keeper_client, kid_list)

        assert response.context['access'].can_manage is True
        assert f'/wishlist/{kid_list.id}/edit/' in response.content.decode()

    def test_can_add_a_surprise_and_go_over_the_shoulder(self, keeper_client, kid_list):
        content = page(keeper_client, kid_list).content.decode()

        assert 'add_surprise_item' in content
        assert SHOULDER_BUTTON in content

    def test_what_is_left_to_buy_comes_first(self, keeper_client, kid_list, kid_items):
        assert listed_names(page(keeper_client, kid_list)) == ['Scooter', 'Lego Castle']


class TestKidSeesNoSecrets:
    @pytest.fixture
    def kid_client(self, kid):
        return signed_in(kid)

    def test_no_purchase_marks_buttons_or_progress(self, kid_client, kid_list, kid_items):
        response = page(kid_client, kid_list)
        content = response.content.decode()

        assert 'Mark Purchased' not in content
        assert 'Purchased' not in content
        assert 'purchased-badge' not in content
        assert '/item/purchase/' not in content
        assert PROGRESS not in content
        assert response.context['purchased_count'] is None

    def test_no_surprises(self, kid_client, kid_list, kid_items):
        response = page(kid_client, kid_list)
        content = response.content.decode()

        assert 'Secret Bike' not in content
        assert SNEAKY_HEADING not in content
        assert 'add_surprise_item' not in content
        assert response.context['sneaky_items'] == []

    def test_still_sees_everything_they_asked_for(self, kid_client, kid_list, kid_items):
        """Bought things stay on the list, looking exactly like the rest."""
        content = page(kid_client, kid_list).content.decode()

        assert 'Scooter' in content
        assert 'Lego Castle' in content

    def test_order_does_not_give_away_what_was_bought(self, kid_client, kid_list, kid_items):
        assert listed_names(page(kid_client, kid_list)) == ['Lego Castle', 'Scooter']

    def test_no_over_the_shoulder_button(self, kid_client, kid_list, kid_items):
        """There's nothing on the page to hide from them."""
        assert SHOULDER_BUTTON not in page(kid_client, kid_list).content.decode()


class TestGiverOnAKidList:
    def test_sees_and_marks_like_on_any_list(self, authenticated_other_user, kid_list, kid_items):
        response = page(authenticated_other_user, kid_list)
        content = response.content.decode()

        assert 'Secret Bike' in content
        assert 'purchased-badge' in content
        assert 'Mark Purchased' in content
        assert PROGRESS in content
        assert response.context['access'].can_manage is False


class TestOwnListUnchanged:
    """Before keepers existed these were the rules, and they still are."""

    def test_owner_sees_no_purchases_and_no_surprises(
        self, authenticated_user, wishlist, own_items
    ):
        response = page(authenticated_user, wishlist)
        content = response.content.decode()

        assert 'Mark Purchased' not in content
        assert 'Purchased' not in content
        assert PROGRESS not in content
        assert 'Secret Telescope' not in content
        assert SNEAKY_HEADING not in content
        assert SHOULDER_BUTTON not in content

    def test_manager_sees_surprises_but_not_purchases(self, helper, wishlist, own_items):
        response = page(signed_in(helper), wishlist)
        content = response.content.decode()

        assert 'Secret Telescope' in content
        assert SNEAKY_HEADING in content
        assert 'Mark Purchased' not in content
        assert 'purchased-badge' not in content
        assert 'purchased by' not in content
        assert PROGRESS not in content
        assert response.context['purchased_count'] is None
        # They do see a secret, so they get the way to hide it
        assert SHOULDER_BUTTON in content

    def test_giver_sees_everything(self, authenticated_other_user, wishlist, own_items):
        content = page(authenticated_other_user, wishlist).content.decode()

        assert 'Secret Telescope' in content
        assert 'purchased-badge' in content
        assert 'Mark Purchased' in content


# ---------------------------------------------------------------------------
# Marking things bought
# ---------------------------------------------------------------------------


class TestMarkingPurchased:
    def test_keeper_owner_can_mark_an_item_bought(self, authenticated_user, user, kid_items):
        plain = kid_items['plain']

        response = authenticated_user.get(f'/item/purchase/{plain.id}/')

        assert response.status_code == 302
        plain.refresh_from_db()
        assert plain.purchased is True
        assert plain.purchased_by == user

    def test_keeper_manager_can_mark_an_item_bought(self, co_parent, kid_items):
        plain = kid_items['plain']

        signed_in(co_parent).get(f'/item/purchase/{plain.id}/')

        plain.refresh_from_db()
        assert plain.purchased_by == co_parent

    def test_keeper_can_mark_a_surprise_bought(self, authenticated_user, user, kid_items):
        surprise = kid_items['surprise']

        authenticated_user.get(f'/item/purchase/{surprise.id}/')

        surprise.refresh_from_db()
        assert surprise.purchased_by == user

    def test_keeper_can_undo_their_own_purchase(self, authenticated_user, kid_items):
        plain = kid_items['plain']
        authenticated_user.get(f'/item/purchase/{plain.id}/')

        authenticated_user.get(f'/item/purchase/{plain.id}/')

        plain.refresh_from_db()
        assert plain.purchased is False
        assert plain.purchased_by is None

    def test_keeper_cannot_take_over_someone_elses_purchase(
        self, authenticated_user, other_user, kid_items
    ):
        bought = kid_items['bought']

        authenticated_user.get(f'/item/purchase/{bought.id}/')

        bought.refresh_from_db()
        assert bought.purchased_by == other_user

    def test_kid_cannot_mark_their_own_item_bought(self, kid, kid_items):
        plain = kid_items['plain']

        response = signed_in(kid).get(f'/item/purchase/{plain.id}/')

        assert response.status_code == 302
        plain.refresh_from_db()
        assert plain.purchased is False

    def test_kid_cannot_undo_someone_elses_purchase(self, kid, other_user, kid_items):
        bought = kid_items['bought']

        signed_in(kid).get(f'/item/purchase/{bought.id}/')

        bought.refresh_from_db()
        assert bought.purchased_by == other_user

    def test_kid_gets_a_404_for_a_surprise(self, kid, kid_items):
        """A redirect would confirm the item exists."""
        response = signed_in(kid).get(f'/item/purchase/{kid_items["surprise"].id}/')

        assert response.status_code == 404

    def test_giver_on_a_kid_list_can_mark_an_item_bought(
        self, authenticated_other_user, other_user, kid_items
    ):
        plain = kid_items['plain']

        authenticated_other_user.get(f'/item/purchase/{plain.id}/')

        plain.refresh_from_db()
        assert plain.purchased_by == other_user

    def test_owner_of_own_list_still_cannot(self, authenticated_user, own_items):
        plain = own_items['plain']

        authenticated_user.get(f'/item/purchase/{plain.id}/')

        plain.refresh_from_db()
        assert plain.purchased is False

    def test_manager_of_own_list_still_cannot(self, helper, own_items):
        plain = own_items['plain']

        response = signed_in(helper).get(f'/item/purchase/{plain.id}/', follow=True)

        plain.refresh_from_db()
        assert plain.purchased is False
        assert 'You cannot mark items as purchased on your own list.' in (
            response.content.decode()
        )

    def test_keepers_purchase_shows_on_their_purchases_page(self, authenticated_user, kid_items):
        authenticated_user.get(f'/item/purchase/{kid_items["plain"].id}/')

        content = authenticated_user.get('/my-purchases/').content.decode()

        assert 'Scooter' in content
        assert "Kiddo&#x27;s List" in content


# ---------------------------------------------------------------------------
# Other windows onto a list
# ---------------------------------------------------------------------------


class TestGlance:
    def test_keeper_sees_purchases_and_surprises(self, authenticated_user, kid_list, kid_items):
        items = glance(authenticated_user, kid_list)

        assert items['Lego Castle']['purchased'] is True
        assert items['Scooter']['purchased'] is False
        assert items['Secret Bike']['is_sneaky'] is True

    def test_keeper_manager_sees_them_too(self, co_parent, kid_list, kid_items):
        items = glance(signed_in(co_parent), kid_list)

        assert 'purchased' in items['Scooter']
        assert 'Secret Bike' in items

    def test_kid_sees_neither(self, kid, kid_list, kid_items):
        items = glance(signed_in(kid), kid_list)

        assert set(items) == {'Lego Castle', 'Scooter'}
        for item in items.values():
            assert 'purchased' not in item

    def test_names_the_kid_as_the_person(self, authenticated_user, kid_list):
        response = authenticated_user.get(f'/wishlist/{kid_list.id}/glance/')

        assert response.json()['person'] == 'kiddo'

    def test_manager_of_own_list_sees_surprises_but_not_purchases(
        self, helper, wishlist, own_items
    ):
        items = glance(signed_in(helper), wishlist)

        assert 'Secret Telescope' in items
        for item in items.values():
            assert 'purchased' not in item


class TestHomeCardCount:
    def card_count(self, client, wishlist):
        response = client.get('/?group_by=alpha')
        assert response.status_code == 200
        for lists in response.context['wishlists_grouped'].values():
            for listed in lists:
                if listed.id == wishlist.id:
                    return listed.card_item_count
        raise AssertionError('list not on the home page')

    def test_keeper_count_includes_the_surprise(self, authenticated_user, kid_list, kid_items):
        assert self.card_count(authenticated_user, kid_list) == 3

    def test_keeper_manager_count_includes_the_surprise(self, co_parent, kid_list, kid_items):
        assert self.card_count(signed_in(co_parent), kid_list) == 3

    def test_kid_count_leaves_the_surprise_out(self, kid, kid_list, kid_items):
        client = signed_in(kid)

        assert self.card_count(client, kid_list) == 2
        assert 'wl-list-meta">2 items<' in client.get('/?group_by=alpha').content.decode()

    def test_owner_of_own_list_count_leaves_the_surprise_out(
        self, authenticated_user, wishlist, own_items
    ):
        assert self.card_count(authenticated_user, wishlist) == 2

    def test_manager_of_own_list_count_includes_the_surprise(self, helper, wishlist, own_items):
        assert self.card_count(signed_in(helper), wishlist) == 3


# ---------------------------------------------------------------------------
# Edit List and Tidy up
# ---------------------------------------------------------------------------


class TestEditList:
    def edit_page(self, client, wishlist):
        response = client.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200
        return response.content.decode()

    def test_keeper_can_edit_the_surprises(self, authenticated_user, kid_list, kid_items):
        assert 'Secret Bike' in self.edit_page(authenticated_user, kid_list)

    def test_kid_never_sees_the_surprises(self, kid, kid_list, kid_items):
        content = self.edit_page(signed_in(kid), kid_list)

        assert 'Scooter' in content
        assert 'Secret Bike' not in content
        assert 'name="form-0-purchased"' not in content

    def test_kid_does_not_get_tidy_up(self, kid, kid_list, kid_items):
        content = self.edit_page(signed_in(kid), kid_list)

        assert 'Tidy up' not in content
        assert 'Clear purchased' not in content
        assert f'/wishlist/{kid_list.id}/clear-purchased/' not in content

    def test_keepers_get_tidy_up(self, user, co_parent, kid_list, kid_items):
        for keeper in (user, co_parent):
            assert 'Clear purchased' in self.edit_page(signed_in(keeper), kid_list)

    def test_owner_and_manager_of_own_list_get_tidy_up(
        self, authenticated_user, helper, wishlist, own_items
    ):
        assert 'Clear purchased' in self.edit_page(authenticated_user, wishlist)
        assert 'Clear purchased' in self.edit_page(signed_in(helper), wishlist)


class TestClearPurchased:
    def clear(self, client, wishlist):
        return client.post(f'/wishlist/{wishlist.id}/clear-purchased/')

    def test_kid_cannot_clear_what_the_grown_ups_are_tracking(self, kid, kid_list, kid_items):
        response = self.clear(signed_in(kid), kid_list)

        assert response.status_code == 302
        kid_items['bought'].refresh_from_db()
        assert kid_items['bought'].is_deleted is False

    def test_keeper_owner_can_clear(self, authenticated_user, kid_list, kid_items):
        self.clear(authenticated_user, kid_list)

        kid_items['bought'].refresh_from_db()
        kid_items['plain'].refresh_from_db()
        assert kid_items['bought'].is_deleted is True
        assert kid_items['plain'].is_deleted is False

    def test_keeper_manager_can_clear(self, co_parent, kid_list, kid_items):
        self.clear(signed_in(co_parent), kid_list)

        kid_items['bought'].refresh_from_db()
        assert kid_items['bought'].is_deleted is True

    def test_giver_cannot_clear(self, authenticated_other_user, kid_list, kid_items):
        self.clear(authenticated_other_user, kid_list)

        kid_items['bought'].refresh_from_db()
        assert kid_items['bought'].is_deleted is False

    def test_owner_of_own_list_still_can(self, authenticated_user, wishlist, own_items):
        self.clear(authenticated_user, wishlist)

        own_items['bought'].refresh_from_db()
        assert own_items['bought'].is_deleted is True

    def test_get_is_not_allowed(self, authenticated_user, kid_list):
        response = authenticated_user.get(f'/wishlist/{kid_list.id}/clear-purchased/')

        assert response.status_code == 405
