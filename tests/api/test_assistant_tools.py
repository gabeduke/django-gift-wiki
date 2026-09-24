"""Tests for the assistant's tool layer.

Two kinds of test live here. The first kind checks the tools do their job. The
second kind is adversarial: it pins down the permission boundary, which is the
only thing standing between a manipulated model and a spoiled gift.
"""

import inspect

import pytest

from assistant import tools
from gift.models import Item

# Shared by both of TestTheBoundary's "no identity argument anywhere" checks.
FORBIDDEN_IDENTITY_PARAMS = {'user_id', 'username', 'email', 'as_user', 'on_behalf_of', 'owner'}


@pytest.fixture
def surprise(db, wishlist, other_user):
    return Item.objects.create(
        wishlist=wishlist, name='Secret Bike', is_sneaky=True, added_by=other_user
    )


@pytest.mark.unit
class TestListWishlists:
    def test_lists_every_list_with_its_person(self, db, wishlist, user):
        (entry,) = tools.list_wishlists(user)

        assert entry['id'] == wishlist.id
        assert entry['title'] == 'Test Wishlist'
        assert entry['person'] == 'testuser'

    def test_counts_hide_surprises_from_the_recipient(self, db, wishlist, user, item, surprise):
        (entry,) = tools.list_wishlists(user)

        assert entry['item_count'] == 1

    def test_counts_include_surprises_for_a_gift_giver(
        self, db, wishlist, other_user, item, surprise
    ):
        (entry,) = tools.list_wishlists(other_user)

        assert entry['item_count'] == 2

    def test_says_whether_the_person_can_add_openly(self, db, wishlist, user, other_user):
        assert tools.list_wishlists(user)[0]['can_add_openly'] is True
        assert tools.list_wishlists(other_user)[0]['can_add_openly'] is False

    def test_counts_include_surprises_for_a_manager(
        self, db, wishlist, other_user, item, surprise
    ):
        """A manager runs the list without being its recipient (gift/rules.py's
        is_recipient_side/can_add_openly distinction), so a manager must see
        surprises even though they can also add items openly. Counting by
        can_add_openly instead of is_recipient_side would collapse that
        distinction and hide this manager's surprise from them."""
        wishlist.managers.add(other_user)

        (entry,) = tools.list_wishlists(other_user)

        assert entry['item_count'] == 2


@pytest.mark.unit
class TestGetWishlist:
    def test_returns_visible_items(self, db, wishlist, other_user, item, surprise):
        result = tools.get_wishlist(other_user, wishlist.id)

        assert {i['name'] for i in result['items']} == {item.name, surprise.name}

    def test_recipient_never_gets_a_surprise(self, db, wishlist, user, item, surprise):
        result = tools.get_wishlist(user, wishlist.id)

        assert [i['name'] for i in result['items']] == [item.name]

    def test_recipient_never_gets_purchase_information(self, db, wishlist, user, item, other_user):
        item.purchased = True
        item.purchased_by = other_user
        item.save()

        (entry,) = tools.get_wishlist(user, wishlist.id)['items']

        assert 'purchased' not in entry
        assert 'purchased_by' not in entry


@pytest.mark.unit
class TestSearchItems:
    def test_matches_on_name(self, db, wishlist, other_user, item):
        result = tools.search_items(other_user, 'test it')

        assert [r['name'] for r in result['results']] == [item.name]

    def test_never_returns_an_item_the_viewer_could_not_see_on_the_page(
        self, db, wishlist, user, surprise
    ):
        result = tools.search_items(user, 'bike')

        assert result['results'] == []

    def test_max_price_filters(self, db, wishlist, other_user, item):
        assert tools.search_items(other_user, 'test', max_price=10)['results'] == []
        assert tools.search_items(other_user, 'test', max_price=100)['results']

    def test_unpurchased_only_filters_for_a_gift_giver(self, db, wishlist, other_user, item):
        item.purchased = True
        item.save()

        assert tools.search_items(other_user, 'test', unpurchased_only=True)['results'] == []

    def test_unpurchased_only_is_ignored_for_the_recipient(self, db, wishlist, user, item):
        """Honouring the filter would leak the thing it filters on: an item
        missing from the results is an item somebody already bought."""
        item.purchased = True
        item.save()

        result = tools.search_items(user, 'test', unpurchased_only=True)

        assert [r['name'] for r in result['results']] == [item.name]
        assert result['note']


@pytest.mark.unit
class TestAddItem:
    def test_owner_adds_an_ordinary_item(self, db, wishlist, user):
        result = tools.add_item(user, wishlist.id, 'Coffee Grinder')

        assert result['is_surprise'] is False
        assert Item.objects.get(name='Coffee Grinder').added_by == user

    def test_gift_giver_adds_a_surprise(self, db, wishlist, other_user):
        result = tools.add_item(other_user, wishlist.id, 'Secret Socks')

        assert result['is_surprise'] is True
        assert Item.objects.get(name='Secret Socks').is_sneaky is True

    def test_validation_failures_come_back_as_errors_not_exceptions(self, db, wishlist, user):
        result = tools.run_tool(user, 'add_item', {'wishlist_id': wishlist.id, 'name': '  '})

        assert 'error' in result
        assert Item.objects.count() == 0


@pytest.mark.unit
class TestTheBoundary:
    """The rule is that acting as someone else is unsayable, not refused."""

    def test_no_tool_takes_an_argument_naming_a_user(self):
        for name in tools.TOOLS:
            parameters = set(inspect.signature(tools.TOOLS[name]).parameters)
            assert parameters & FORBIDDEN_IDENTITY_PARAMS == set(), (
                f'{name} exposes an identity argument'
            )

    def test_no_declaration_offers_the_model_a_user_argument(self):
        for declaration in tools.TOOL_DECLARATIONS:
            properties = set(declaration['parameters'].get('properties', {}))
            assert properties & FORBIDDEN_IDENTITY_PARAMS == set(), (
                f"{declaration['name']} offers an identity"
            )

    def test_every_tool_takes_user_first(self):
        for name, function in tools.TOOLS.items():
            first = list(inspect.signature(function).parameters)[0]
            assert first == 'user', f'{name} does not take user first'

    def test_an_extra_argument_from_the_model_is_refused(
        self, db, wishlist, user, other_user, monkeypatch
    ):
        """A manipulated model inventing `user_id` must not be able to smuggle
        it through run_tool — not even into a tool whose signature would
        otherwise swallow it via **kwargs. The gate has to reject the call
        before it reaches the tool, not rely on every tool raising TypeError
        on an argument it doesn't recognise."""
        calls = []

        def spy(user, wishlist_id=None, **kwargs):
            calls.append(kwargs)
            return {'ok': True}

        monkeypatch.setitem(tools.TOOLS, 'get_wishlist', spy)

        result = tools.run_tool(
            user, 'get_wishlist', {'wishlist_id': wishlist.id, 'user_id': other_user.id}
        )

        assert 'error' in result
        assert calls == []

    def test_unknown_tool_names_are_refused(self, db, user):
        assert 'error' in tools.run_tool(user, 'delete_everything', {})

    def test_a_missing_wishlist_is_an_error_not_a_crash(self, db, user):
        assert 'error' in tools.run_tool(user, 'get_wishlist', {'wishlist_id': 999999})

    def test_a_non_numeric_wishlist_id_is_an_error_not_a_crash(self, db, user):
        """Django's IntegerField coercion raises ValueError here, not TypeError
        — run_tool has to catch that too, or its 'always {"error": ...}, never
        an exception' contract is false for the argument shape a model is most
        likely to actually send."""
        result = tools.run_tool(user, 'get_wishlist', {'wishlist_id': 'the blue one'})

        assert 'error' in result

    def test_a_non_string_item_name_is_an_error_not_a_crash(self, db, wishlist, user):
        """create_item_for's `.strip()` raises AttributeError on a non-string
        name, not TypeError — same contract gap as the non-numeric id above."""
        result = tools.run_tool(user, 'add_item', {'wishlist_id': wishlist.id, 'name': 123})

        assert 'error' in result
        assert Item.objects.count() == 0

    def test_there_is_no_write_tool_beyond_add(self):
        """Read + add only: the blast radius of a successful injection is one
        junk item somebody removes with a tap."""
        assert set(tools.TOOLS) == {'list_wishlists', 'get_wishlist', 'search_items', 'add_item'}

    def test_the_advertised_tool_set_matches_the_callable_tool_set(self):
        """TOOL_DECLARATIONS is what the model is actually offered — a fifth
        declaration, or a renamed one that's silently uncallable, has to fail
        this even though it wouldn't fail the TOOLS-only check above."""
        assert {declaration['name'] for declaration in tools.TOOL_DECLARATIONS} == set(tools.TOOLS)
