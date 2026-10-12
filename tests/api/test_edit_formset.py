"""Reproduce wishlist edit formset issue."""
import re

import pytest
from django.contrib.auth import get_user_model

from gift.models import Category, Family, Item, WishList

User = get_user_model()


@pytest.mark.unit
class TestWishlistEditFormset:
    def test_edit_wishlist_with_items(self, authenticated_user, user):
        """Full formset submission on wishlist edit should redirect."""
        family = Family.objects.create(name='Edit Family')
        wishlist = WishList.objects.create(owner=user, title='Edit List', family_name=family)
        category = Category.objects.create(family=family, name='Edit Cat')
        items = []
        for i in range(3):
            item = Item.objects.create(wishlist=wishlist, name=f'Item {i}', updated_by=user)
            item.categories.add(category)
            items.append(item)

        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': family.id,
            'form-TOTAL_FORMS': '3',
            'form-INITIAL_FORMS': '3',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        for i, item in enumerate(items):
            data[f'form-{i}-id'] = item.id
            data[f'form-{i}-name'] = item.name
            data[f'form-{i}-description'] = ''
            data[f'form-{i}-price'] = ''
            data[f'form-{i}-price_range'] = ''
            data[f'form-{i}-url'] = ''
            data[f'form-{i}-purchased'] = 'false'
            data[f'form-{i}-category'] = category.id
            data[f'form-{i}-DELETE'] = ''

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        print('POST status:', response.status_code)
        if response.status_code == 200:
            content = response.content.decode()
            print('Messages:', [m for m in ['Please correct', 'errorlist', 'text-danger'] if m in content])
        assert response.status_code == 302

    def test_edit_wishlist_add_new_item(self, authenticated_user, user):
        """Adding a new item via the edit formset should redirect."""
        family = Family.objects.create(name='Add Family')
        wishlist = WishList.objects.create(owner=user, title='Add List', family_name=family)
        category = Category.objects.create(family=family, name='Add Cat')
        item = Item.objects.create(wishlist=wishlist, name='Existing', updated_by=user)
        item.categories.add(category)

        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': family.id,
            'form-TOTAL_FORMS': '2',
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
            'form-0-category': category.id,
            'form-0-DELETE': '',
            'form-1-id': '',
            'form-1-name': 'New Item',
            'form-1-description': '',
            'form-1-price': '',
            'form-1-price_range': '',
            'form-1-url': '',
            'form-1-purchased': 'false',
            'form-1-category': category.id,
            'form-1-DELETE': '',
        }

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        print('POST status:', response.status_code)
        if response.status_code == 200:
            content = response.content.decode()
            print('Messages:', [m for m in ['Please correct', 'errorlist', 'text-danger'] if m in content])
        assert response.status_code == 302

    def test_edit_wishlist_renders_item_cards(self, authenticated_user, user):
        """Items are an ordinary server-rendered formset — no client framework
        has to load for the page to work."""
        family = Family.objects.create(name='Card Family')
        wishlist = WishList.objects.create(owner=user, title='Card List', family_name=family)
        category = Category.objects.create(family=family, name='Card Cat')
        item = Item.objects.create(wishlist=wishlist, name='Card Item', updated_by=user)
        item.categories.add(category)

        response = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'class="wl-card wl-edit-item' in content
        assert f'name="form-0-id" value="{item.id}"' in content
        assert 'name="form-0-name"' in content
        # The blank card js/edit-list.js clones for "Add item"
        assert 'id="wl-empty-item"' in content
        assert 'name="form-__prefix__-name"' in content
        assert 'vue' not in content.lower()

    def test_item_names_are_never_written_into_a_script(self, authenticated_user, user):
        """The old editor interpolated names into JS template literals, so a
        name containing a backtick or ${…} broke the page or ran as code."""
        wishlist = WishList.objects.create(owner=user, title='Script List')
        Item.objects.create(wishlist=wishlist, name='Evil `${alert(1)}` thing', updated_by=user)

        content = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/').content.decode()
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', content, flags=re.DOTALL)

        assert 'value="Evil `${alert(1)}` thing"' in content  # an inert attribute value
        assert not any('alert(1)' in script for script in scripts)


    def test_edit_wishlist_delete_item(self, authenticated_user, user):
        """Deleting an item via the edit formset should redirect."""
        family = Family.objects.create(name='Del Family')
        wishlist = WishList.objects.create(owner=user, title='Del List', family_name=family)
        category = Category.objects.create(family=family, name='Del Cat')
        item = Item.objects.create(wishlist=wishlist, name='To Delete', updated_by=user)
        item.categories.add(category)

        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': family.id,
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
            'form-0-category': category.id,
            'form-0-DELETE': 'on',
        }

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)
        print('POST status:', response.status_code)
        if response.status_code == 200:
            content = response.content.decode()
            print('Messages:', [m for m in ['Please correct', 'errorlist', 'text-danger'] if m in content])
        assert response.status_code == 302


@pytest.mark.unit
class TestEditPageNeverSpoilsPurchases:
    """Only owners and managers reach the edit page, so it must not reveal —
    or reset — which items have been bought."""

    def make_list(self, user, buyer):
        family = Family.objects.create(name='Spoiler Family')
        wishlist = WishList.objects.create(owner=user, title='Spoiler List', family_name=family)
        bought = Item.objects.create(
            wishlist=wishlist, name='Bought Thing', purchased=True, purchased_by=buyer, updated_by=user
        )
        return wishlist, bought

    def test_no_purchased_field_is_rendered(self, authenticated_user, user, other_user):
        wishlist, _ = self.make_list(user, other_user)

        content = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/').content.decode()

        assert 'name="form-0-purchased"' not in content
        assert 'name="form-__prefix__-purchased"' not in content

    def test_saving_keeps_what_was_bought(self, authenticated_user, user, other_user):
        wishlist, bought = self.make_list(user, other_user)
        data = {
            'title': wishlist.title,
            'description': '',
            'family_name': wishlist.family_name_id,
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': bought.id,
            'form-0-name': 'Bought Thing (renamed)',
            'form-0-description': '',
            'form-0-price': '',
            'form-0-price_range': '',
            'form-0-url': '',
        }

        response = authenticated_user.post(f'/wishlist/{wishlist.id}/edit/', data)

        assert response.status_code == 302
        bought.refresh_from_db()
        assert bought.name == 'Bought Thing (renamed)'
        assert bought.purchased is True
        assert bought.purchased_by == other_user
