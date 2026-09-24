"""Tests for gift/rules.py — the domain rules shared by the views and the assistant.

These rules were inline in gift/views.py until the assistant needed them too.
Importing them from a view module would have dragged the whole request layer
into the tool layer, so they live here instead.
"""

import pytest
from django.contrib.auth.models import AnonymousUser

from gift.models import Item
from gift.rules import (
    ItemValidationError,
    can_add_openly,
    create_item_for,
    is_recipient_side,
    may_see_purchase_info,
    person_display_name,
    visible_items,
    visible_items_for,
)


@pytest.mark.unit
class TestCanAddOpenly:
    def test_owner_adds_openly(self, wishlist, user):
        assert can_add_openly(wishlist, user) is True

    def test_dependent_adds_openly(self, wishlist, other_user):
        wishlist.dependent = other_user
        wishlist.save()

        assert can_add_openly(wishlist, other_user) is True

    def test_manager_adds_openly(self, wishlist, other_user):
        wishlist.managers.add(other_user)

        assert can_add_openly(wishlist, other_user) is True

    def test_everyone_else_does_not(self, wishlist, other_user):
        assert can_add_openly(wishlist, other_user) is False


@pytest.mark.unit
class TestPersonDisplayName:
    def test_full_name_wins(self, user):
        user.first_name = 'Ada'
        user.last_name = 'Lovelace'

        assert person_display_name(user) == 'Ada Lovelace'

    def test_username_is_the_fallback(self, user):
        assert person_display_name(user) == 'testuser'

    def test_none_is_empty(self):
        assert person_display_name(None) == ''


@pytest.fixture
def surprise(db, wishlist, other_user):
    """A surprise item added by a gift-giver — hidden from the recipient."""
    return Item.objects.create(
        wishlist=wishlist, name='Secret Bike', is_sneaky=True, added_by=other_user
    )


@pytest.mark.unit
class TestVisibleItems:
    def test_owner_never_sees_a_surprise(self, wishlist, user, item, surprise):
        names = {i.name for i in visible_items(wishlist, user)}

        assert names == {item.name}

    def test_dependent_never_sees_a_surprise(self, wishlist, other_user, item, surprise):
        wishlist.dependent = other_user
        wishlist.save()

        names = {i.name for i in visible_items(wishlist, other_user)}

        assert names == {item.name}

    def test_manager_does_see_surprises(self, wishlist, other_user, item, surprise):
        """A manager helps run the list without being its recipient — hiding
        surprises from them would break the feature, not protect it."""
        wishlist.managers.add(other_user)

        names = {i.name for i in visible_items(wishlist, other_user)}

        assert names == {item.name, surprise.name}

    def test_gift_giver_sees_surprises(self, wishlist, other_user, item, surprise):
        names = {i.name for i in visible_items(wishlist, other_user)}

        assert names == {item.name, surprise.name}

    def test_deleted_and_archived_items_are_excluded(self, wishlist, user):
        from django.utils import timezone

        Item.objects.create(wishlist=wishlist, name='Gone', is_deleted=True)
        Item.objects.create(wishlist=wishlist, name='Archived', archived_at=timezone.now())
        Item.objects.create(wishlist=wishlist, name='Here')

        assert {i.name for i in visible_items(wishlist, user)} == {'Here'}

    def test_priority_items_come_first(self, wishlist, user):
        Item.objects.create(wishlist=wishlist, name='Ordinary')
        Item.objects.create(wishlist=wishlist, name='Wanted', is_priority=True)

        assert [i.name for i in visible_items(wishlist, user)][0] == 'Wanted'

    def test_anonymous_viewer_never_sees_a_surprise(self, wishlist, item, surprise):
        """An anonymous viewer is nobody's recipient on record, so the failure
        direction has to be 'surprises excluded', not 'surprises leaked'."""
        names = {i.name for i in visible_items(wishlist, AnonymousUser())}

        assert names == {item.name}


@pytest.mark.unit
class TestPurchaseInfoAudience:
    """Purchase information has a wider audience than surprise items: it is
    hidden from managers too, because a manager reads the list with the owner."""

    def test_owner_may_not_see_purchase_info(self, wishlist, user):
        assert may_see_purchase_info(wishlist, user) is False

    def test_dependent_may_not_see_purchase_info(self, wishlist, other_user):
        wishlist.dependent = other_user
        wishlist.save()

        assert may_see_purchase_info(wishlist, other_user) is False

    def test_manager_may_not_see_purchase_info(self, wishlist, other_user):
        wishlist.managers.add(other_user)

        assert may_see_purchase_info(wishlist, other_user) is False

    def test_gift_giver_may_see_purchase_info(self, wishlist, other_user):
        assert may_see_purchase_info(wishlist, other_user) is True

    def test_anonymous_viewer_may_not_see_purchase_info(self, wishlist):
        assert may_see_purchase_info(wishlist, AnonymousUser()) is False


@pytest.mark.unit
class TestRecipientSide:
    def test_owner_is_recipient_side(self, wishlist, user):
        assert is_recipient_side(wishlist, user) is True

    def test_manager_is_not_recipient_side(self, wishlist, other_user):
        wishlist.managers.add(other_user)

        assert is_recipient_side(wishlist, other_user) is False


@pytest.mark.unit
class TestVisibleItemsFor:
    def test_shape_for_a_gift_giver(self, wishlist, other_user, item):
        (entry,) = visible_items_for(wishlist, other_user)

        assert entry['id'] == item.id
        assert entry['name'] == 'Test Item'
        assert entry['price'] == '29.99'
        assert entry['is_surprise'] is False
        assert entry['categories'] == []

    def test_purchase_keys_are_absent_for_the_owner(
        self, wishlist, user, item, other_user
    ):
        item.purchased = True
        item.purchased_by = other_user
        item.save()

        (entry,) = visible_items_for(wishlist, user)

        assert 'purchased' not in entry
        assert 'purchased_by' not in entry

    def test_purchase_keys_are_absent_for_a_manager(self, wishlist, other_user, item):
        """Managers read the list with the owner, so they are spoiler-side too."""
        wishlist.managers.add(other_user)
        item.purchased = True
        item.save()

        (entry,) = visible_items_for(wishlist, other_user)

        assert 'purchased' not in entry

    def test_purchase_keys_are_present_for_a_gift_giver(
        self, wishlist, other_user, item
    ):
        item.purchased = True
        item.purchased_by = other_user
        item.save()

        (entry,) = visible_items_for(wishlist, other_user)

        assert entry['purchased'] is True
        assert entry['purchased_by'] == 'otheruser'

    def test_a_surprise_is_never_serialized_for_the_recipient(
        self, wishlist, user, item, surprise
    ):
        names = [e['name'] for e in visible_items_for(wishlist, user)]

        assert names == [item.name]

    def test_a_surprise_is_flagged_for_a_gift_giver(
        self, wishlist, other_user, surprise
    ):
        entry = next(
            e for e in visible_items_for(wishlist, other_user)
            if e['id'] == surprise.id
        )

        assert entry['is_surprise'] is True


@pytest.mark.unit
class TestCreateItemFor:
    def test_owner_gets_an_ordinary_item(self, wishlist, user):
        item = create_item_for(user, wishlist, 'Coffee Grinder')

        assert item.is_sneaky is False
        assert item.added_by == user
        assert item.updated_by == user

    def test_gift_giver_gets_a_surprise(self, wishlist, other_user):
        item = create_item_for(other_user, wishlist, 'Secret Bike')

        assert item.is_sneaky is True

    def test_manager_gets_an_ordinary_item(self, wishlist, other_user):
        wishlist.managers.add(other_user)

        assert create_item_for(other_user, wishlist, 'Socks').is_sneaky is False

    def test_dependent_gets_an_ordinary_item(self, wishlist, other_user):
        wishlist.dependent = other_user
        wishlist.save()

        assert create_item_for(other_user, wishlist, 'Socks').is_sneaky is False

    def test_name_is_trimmed(self, wishlist, user):
        assert create_item_for(user, wishlist, '  Wool Socks  ').name == 'Wool Socks'

    def test_blank_name_is_rejected(self, wishlist, user):
        with pytest.raises(ItemValidationError):
            create_item_for(user, wishlist, '   ')

    def test_overlong_name_is_rejected(self, wishlist, user):
        with pytest.raises(ItemValidationError):
            create_item_for(user, wishlist, 'x' * 256)

    def test_url_is_saved(self, wishlist, user):
        item = create_item_for(user, wishlist, 'Linked', url='https://example.com/thing')

        assert item.url == 'https://example.com/thing'

    def test_malformed_url_is_rejected(self, wishlist, user):
        with pytest.raises(ItemValidationError):
            create_item_for(user, wishlist, 'Bad Link', url='not a url')

    def test_blank_url_becomes_none(self, wishlist, user):
        assert create_item_for(user, wishlist, 'No Link', url='   ').url is None

    def test_nothing_is_created_when_validation_fails(self, wishlist, user):
        with pytest.raises(ItemValidationError):
            create_item_for(user, wishlist, '')

        assert Item.objects.filter(wishlist=wishlist).count() == 0
