"""The MCP tool layer, and above all the spoiler rules it has to keep.

The tools take the acting user first and answer through `gift.services`, the same
rules the web pages use. These tests pin the matrix down from the tools' side:
what an owner-side person (owner, the person a list is kept for, a manager) can
learn, versus a gift-giver. Getting it backwards spoils a gift.
"""

import pytest

from gift.models import Item
from gift_mcp.tools import BY_NAME, Context, ToolError, call_tool, check_arguments

CTX = Context(origin='https://gifts.example')


def run(user, tool, **arguments):
    return call_tool(tool, arguments, user, CTX)


@pytest.mark.unit
class TestWhatOwnerSideSees:
    """The owner of a list must never learn about surprises or purchases through a tool."""

    def test_list_counts_exclude_surprises(self, user, wishlist, plain_item, surprise_item):
        (row,) = run(user, 'list_wishlists')['wishlists']
        assert row['you_are'] == 'owner-side'
        assert row['for_me'] is True
        assert row['item_count'] == 1  # the surprise is not even counted

    def test_get_wishlist_hides_surprises(self, user, wishlist, plain_item, surprise_item):
        listing = run(user, 'get_wishlist', wishlist_id=wishlist.id)
        assert [i['name'] for i in listing['items']] == ['Plain Mug']

    def test_get_wishlist_never_includes_purchase_status(
        self, user, wishlist, plain_item, bought_item
    ):
        listing = run(user, 'get_wishlist', wishlist_id=wishlist.id)
        assert {i['name'] for i in listing['items']} == {'Plain Mug', 'Bought Scarf'}
        assert all('purchased' not in item for item in listing['items'])

    def test_search_never_finds_a_surprise(self, user, wishlist, surprise_item):
        assert run(user, 'search_items', query='Surprise')['items'] == []
        assert run(user, 'search_items', query='bike', wishlist_id=wishlist.id)['items'] == []

    def test_unpurchased_filter_is_ignored_so_it_cannot_leak(
        self, user, wishlist, plain_item, bought_item
    ):
        """Dropping bought items from a result would reveal which ones were bought."""
        found = run(user, 'search_items', query='a', unpurchased_only=True)
        assert {i['name'] for i in found['items']} == {'Plain Mug', 'Bought Scarf'}
        assert 'ignored' in found['note']

    def test_the_person_a_list_is_kept_for_is_owner_side_too(
        self, wishlist, plain_item, surprise_item, bought_item, make_user
    ):
        kid = make_user('kid', 'kid@example.com')
        wishlist.dependent = kid
        wishlist.save()

        listing = run(kid, 'get_wishlist', wishlist_id=wishlist.id)
        assert listing['you_are'] == 'owner-side'
        assert {i['name'] for i in listing['items']} == {'Plain Mug', 'Bought Scarf'}
        assert all('purchased' not in i for i in listing['items'])

    def test_a_manager_sees_surprises_like_the_wishlist_page_but_never_purchases(
        self, wishlist, plain_item, surprise_item, bought_item, make_user
    ):
        """The app's own rule: a manager isn't who the list is for, so they may see surprises
        (they help run the list), but being owner-side they never learn what has been bought.
        The tools must agree with the page, not invent a stricter or looser rule."""
        parent = make_user('parent', 'parent@example.com')
        wishlist.managers.add(parent)

        listing = run(parent, 'get_wishlist', wishlist_id=wishlist.id)
        assert listing['you_are'] == 'owner-side'
        assert {i['name'] for i in listing['items']} == {
            'Plain Mug',
            'Surprise Bike',
            'Bought Scarf',
        }
        assert all('purchased' not in i for i in listing['items'])


@pytest.mark.unit
class TestWhatGiftGiversSee:
    def test_sees_surprises_and_who_added_them(self, giver, wishlist, plain_item, surprise_item):
        listing = run(giver, 'get_wishlist', wishlist_id=wishlist.id)
        assert listing['you_are'] == 'gift-giver'
        by_name = {i['name']: i for i in listing['items']}
        assert by_name['Surprise Bike']['surprise'] is True
        assert by_name['Surprise Bike']['added_by'] == giver.username
        assert 'surprise' not in by_name['Plain Mug']

    def test_sees_purchase_status(self, giver, wishlist, plain_item, bought_item):
        by_name = {
            i['name']: i for i in run(giver, 'get_wishlist', wishlist_id=wishlist.id)['items']
        }
        assert by_name['Bought Scarf']['purchased'] is True
        assert by_name['Plain Mug']['purchased'] is False

    def test_counts_include_surprises(self, giver, wishlist, plain_item, surprise_item):
        (row,) = run(giver, 'list_wishlists')['wishlists']
        assert row['item_count'] == 2
        assert row['for_me'] is False

    def test_search_finds_surprises(self, giver, wishlist, surprise_item):
        (found,) = run(giver, 'search_items', query='bike')['items']
        assert found['name'] == 'Surprise Bike'
        assert found['list']['id'] == wishlist.id

    def test_unpurchased_filter_applies_to_other_peoples_lists(
        self, giver, wishlist, plain_item, bought_item
    ):
        found = run(giver, 'search_items', query='a', unpurchased_only=True)
        assert [i['name'] for i in found['items']] == ['Plain Mug']
        assert 'note' not in found

    def test_deleted_and_archived_items_stay_out(self, giver, wishlist, plain_item):
        from django.utils import timezone

        Item.objects.create(wishlist=wishlist, name='Gone Hat', is_deleted=True)
        Item.objects.create(wishlist=wishlist, name='Old Hat', archived_at=timezone.now())
        names = [i['name'] for i in run(giver, 'get_wishlist', wishlist_id=wishlist.id)['items']]
        assert names == ['Plain Mug']


@pytest.mark.unit
class TestAddItem:
    def test_owner_adds_an_ordinary_item(self, user, wishlist):
        out = run(user, 'add_item', wishlist_id=wishlist.id, name='Coffee Grinder')
        assert out['added'] is True and out['surprise'] is False
        item = Item.objects.get(pk=out['id'])
        assert item.is_sneaky is False
        assert item.added_by == user and item.updated_by == user
        assert out['list']['url'] == f'https://gifts.example/wishlist/{wishlist.id}/'

    def test_a_gift_giver_adds_a_surprise_the_owner_cannot_see(self, user, giver, wishlist):
        out = run(giver, 'add_item', wishlist_id=wishlist.id, name='Telescope', url='https://x.io')
        assert out['surprise'] is True
        assert 'can’t see it' in out['message']
        item = Item.objects.get(pk=out['id'])
        assert item.is_sneaky is True and item.added_by == giver and item.url == 'https://x.io'

        owner_view = run(user, 'get_wishlist', wishlist_id=wishlist.id)
        assert owner_view['items'] == []
        assert run(user, 'list_wishlists')['wishlists'][0]['item_count'] == 0

    def test_dependent_and_manager_add_openly(self, wishlist, make_user):
        kid = make_user('kid', 'kid@example.com')
        parent = make_user('parent', 'parent@example.com')
        wishlist.dependent = kid
        wishlist.save()
        wishlist.managers.add(parent)
        for person, name in ((kid, 'Kid Idea'), (parent, 'Parent Idea')):
            out = run(person, 'add_item', wishlist_id=wishlist.id, name=name)
            assert out['surprise'] is False

    def test_the_surprise_flag_cannot_be_asked_for(self, user, wishlist):
        with pytest.raises(ToolError, match='Unknown argument: is_sneaky'):
            run(user, 'add_item', wishlist_id=wishlist.id, name='X', is_sneaky=True)

    def test_a_duplicate_is_refused_unless_asked_for(self, user, wishlist, plain_item):
        out = run(user, 'add_item', wishlist_id=wishlist.id, name='  plain MUG ')
        assert out['added'] is False and out['reason'] == 'already_on_the_list'
        assert out['existing']['id'] == plain_item.id
        assert Item.objects.filter(wishlist=wishlist).count() == 1

        again = run(
            user, 'add_item', wishlist_id=wishlist.id, name='Plain Mug', allow_duplicate=True
        )
        assert again['added'] is True
        assert Item.objects.filter(wishlist=wishlist).count() == 2

    def test_a_duplicate_check_never_reveals_a_surprise_to_the_owner(
        self, user, wishlist, surprise_item
    ):
        """If the owner got "already on the list" for a surprise, that would be the spoiler."""
        out = run(user, 'add_item', wishlist_id=wishlist.id, name='Surprise Bike')
        assert out['added'] is True

    @pytest.mark.parametrize(
        'arguments, message',
        [
            ({'name': '   '}, 'Give the item a name'),
            ({'name': 'x' * 256}, 'too long'),
            ({'name': 'Ok', 'url': 'not a url'}, 'valid URL'),
            ({'name': 'Ok', 'description': 'x' * 2001}, 'too long'),
        ],
    )
    def test_bad_input_is_explained(self, user, wishlist, arguments, message):
        with pytest.raises(ToolError, match=message):
            run(user, 'add_item', wishlist_id=wishlist.id, **arguments)
        assert Item.objects.filter(wishlist=wishlist).count() == 0

    def test_an_unknown_list_is_explained(self, user):
        with pytest.raises(ToolError, match='No list has that id'):
            run(user, 'add_item', wishlist_id=99999, name='X')
        with pytest.raises(ToolError, match='No list has that id'):
            run(user, 'get_wishlist', wishlist_id=99999)


@pytest.mark.unit
class TestArguments:
    def test_unknown_arguments_are_refused(self):
        with pytest.raises(ToolError, match='Unknown argument: user_id'):
            check_arguments(BY_NAME['list_wishlists'].input_schema, {'user_id': 1})

    def test_there_is_no_way_to_name_another_user(self):
        """The acting user comes from the credential. No tool even has a parameter for one."""
        for tool in BY_NAME.values():
            assert not {'user', 'user_id', 'as_user', 'email'} & set(
                tool.input_schema['properties']
            )

    def test_required_arguments(self):
        with pytest.raises(ToolError, match='Missing required argument: wishlist_id'):
            check_arguments(BY_NAME['get_wishlist'].input_schema, {})

    @pytest.mark.parametrize('bad', ['1', 1.5, True, None, [1]])
    def test_types_are_checked(self, bad):
        with pytest.raises(ToolError):
            check_arguments(BY_NAME['get_wishlist'].input_schema, {'wishlist_id': bad})

    def test_arguments_must_be_an_object(self):
        with pytest.raises(ToolError, match='must be an object'):
            check_arguments(BY_NAME['list_wishlists'].input_schema, ['x'])

    def test_empty_search_is_refused(self, user):
        with pytest.raises(ToolError, match='something to search for'):
            run(user, 'search_items', query='   ')
