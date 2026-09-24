"""Tests for gift/rules.py — the domain rules shared by the views and the assistant.

These rules were inline in gift/views.py until the assistant needed them too.
Importing them from a view module would have dragged the whole request layer
into the tool layer, so they live here instead.
"""

import pytest

from gift.rules import can_add_openly, person_display_name


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
