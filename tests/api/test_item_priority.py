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


@pytest.mark.unit
class TestPriorityStar:
    """The one-tap ⭐ on the list page and My Lists (no trip to Edit List)."""

    def url(self, item):
        return f'/item/{item.id}/most-wanted/'

    def test_owner_stars_and_unstars_in_the_background(self, authenticated_user, item):
        response = authenticated_user.post(self.url(item), HTTP_X_REQUESTED_WITH='fetch')
        assert response.json() == {'is_priority': True}
        item.refresh_from_db()
        assert item.is_priority is True

        response = authenticated_user.post(self.url(item), HTTP_X_REQUESTED_WITH='fetch')
        assert response.json() == {'is_priority': False}

    def test_without_js_it_returns_to_the_page(self, authenticated_user, wishlist, item):
        response = authenticated_user.post(self.url(item), {'next': f'/wishlist/{wishlist.id}/'})
        assert response.status_code == 302
        assert response.url == f'/wishlist/{wishlist.id}/'

    def test_next_must_stay_on_site(self, authenticated_user, wishlist, item):
        response = authenticated_user.post(self.url(item), {'next': 'https://evil.example/'})
        assert response.url == f'/wishlist/{wishlist.id}/'

    def test_someone_else_cannot_star(self, authenticated_other_user, item):
        response = authenticated_other_user.post(self.url(item), HTTP_X_REQUESTED_WITH='fetch')
        assert response.status_code == 403
        item.refresh_from_db()
        assert item.is_priority is False

    def test_post_only(self, authenticated_user, item):
        assert authenticated_user.get(self.url(item)).status_code == 405

    def test_owner_sees_the_star_on_their_list(self, authenticated_user, wishlist, item):
        page = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert f'/item/{item.id}/most-wanted/' in page
        assert 'aria-pressed="false"' in page

    def test_givers_see_a_plain_badge(self, authenticated_other_user, wishlist, item):
        item.is_priority = True
        item.save()
        page = authenticated_other_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert '⭐ Most wanted' in page
        assert '/most-wanted/' not in page

    def test_my_lists_card_has_the_star(self, authenticated_user, item):
        page = authenticated_user.get('/profile/').content.decode()
        assert f'/item/{item.id}/most-wanted/' in page
