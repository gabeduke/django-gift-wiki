"""Tests for the item priority ("most wanted") feature — issue #76."""
import pytest
from django.contrib.auth import get_user_model

from gift.models import Category, Item

User = get_user_model()


@pytest.mark.unit
class TestItemPriority:
    def test_is_priority_defaults_false(self, item):
        """New items are not priority items by default."""
        assert item.is_priority is False

    def test_owner_can_set_priority_via_edit_formset(self, authenticated_user, wishlist, item):
        """The owner can flag an item as most-wanted from the wishlist edit page."""
        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': wishlist.family_name.id,
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': item.id,
            'form-0-name': item.name,
            'form-0-description': '',
            'form-0-price': '',
            'form-0-price_range': '',
            'form-0-url': '',
            'form-0-purchased': 'false',
            'form-0-is_priority': 'on',
            'form-0-category': '',
            'form-0-DELETE': '',
        }

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.is_priority is True

    def test_owner_can_unset_priority_via_edit_formset(self, authenticated_user, wishlist, item):
        """Leaving the checkbox out of the POST clears the priority flag."""
        item.is_priority = True
        item.save()

        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': wishlist.family_name.id,
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': item.id,
            'form-0-name': item.name,
            'form-0-description': '',
            'form-0-price': '',
            'form-0-price_range': '',
            'form-0-url': '',
            'form-0-purchased': 'false',
            'form-0-category': '',
            'form-0-DELETE': '',
        }

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        assert response.status_code == 302
        item.refresh_from_db()
        assert item.is_priority is False

    def test_priority_badge_shown_to_givers(self, authenticated_other_user, wishlist, item):
        """Priority items show a "Most wanted" badge on the detail page."""
        item.is_priority = True
        item.save()

        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'priority-badge' in content
        assert 'Most wanted' in content

    def test_no_priority_badge_without_priority_items(self, authenticated_other_user, wishlist, item):
        """Non-priority items do not get the badge."""
        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        assert 'priority-badge' not in response.content.decode()

    def test_priority_items_sort_first_within_category(self, authenticated_other_user, wishlist):
        """Within a category group, priority items come first; other items keep their order."""
        category = Category.objects.create(family=wishlist.family_name, name='Sort Cat')
        first = Item.objects.create(wishlist=wishlist, name='Normal First')
        priority = Item.objects.create(wishlist=wishlist, name='Priority Middle', is_priority=True)
        last = Item.objects.create(wishlist=wishlist, name='Normal Last')
        for it in (first, priority, last):
            it.categories.add(category)

        response = authenticated_other_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert (
            content.index('Priority Middle')
            < content.index('Normal First')
            < content.index('Normal Last')
        )
