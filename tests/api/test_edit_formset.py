"""Reproduce wishlist edit formset issue."""
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

    def test_edit_wishlist_renders_server_side_fallback(self, authenticated_user, user):
        """The edit page renders server-side item forms as a fallback for browsers that can't run Vue."""
        family = Family.objects.create(name='Fallback Family')
        wishlist = WishList.objects.create(owner=user, title='Fallback List', family_name=family)
        category = Category.objects.create(family=family, name='Fallback Cat')
        item = Item.objects.create(wishlist=wishlist, name='Fallback Item', updated_by=user)
        item.categories.add(category)

        response = authenticated_user.get(f'/wishlist/{wishlist.id}/edit/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'wishlist-edit-fallback' in content
        assert f'name="form-0-id" value="{item.id}"' in content
        assert 'name="form-0-name"' in content
        assert 'id="wishlist-edit-app" style="display: none;"' in content

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
