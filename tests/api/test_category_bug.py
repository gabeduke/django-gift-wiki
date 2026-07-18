"""Tests for category creation via modal/AJAX and item assignment."""
import json

import pytest
from django.contrib.auth import get_user_model

from gift.models import Category, Family, Item, WishList

User = get_user_model()


@pytest.mark.unit
class TestCategoryCreation:
    def test_create_category_via_ajax(self, authenticated_user, user):
        """A manager can create a category via AJAX and it appears in the response."""
        family = Family.objects.create(name='Ajax Family')
        wishlist = WishList.objects.create(owner=user, title='Ajax List', family_name=family)

        response = authenticated_user.post(
            f'/wishlist/{wishlist.id}/category/create/',
            data=json.dumps({'name': 'New Ajax Category'}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'success'
        assert data['category_name'] == 'New Ajax Category'
        assert Category.objects.filter(family=family, name='New Ajax Category').exists()

    def test_add_item_with_existing_category(self, authenticated_user, user):
        """After creating a category, an item can be saved with that category selected."""
        family = Family.objects.create(name='Item Family')
        wishlist = WishList.objects.create(owner=user, title='Item List', family_name=family)
        category = Category.objects.create(family=family, name='Existing Category')

        data = {
            'name': 'Categorized Item',
            'description': '',
            'price': '',
            'price_range': '',
            'url': '',
            'category': category.id,
        }
        response = authenticated_user.post(f'/wishlist/{wishlist.id}/add_item/', data)
        assert response.status_code == 302
        item = Item.objects.get(name='Categorized Item')
        assert item.categories.filter(name='Existing Category').exists()

    def test_non_manager_cannot_create_category_via_ajax(
        self, authenticated_other_user, user
    ):
        """A user who does not manage the wishlist cannot create a category."""
        family = Family.objects.create(name='Protected Family')
        wishlist = WishList.objects.create(owner=user, title='Protected List', family_name=family)

        response = authenticated_other_user.post(
            f'/wishlist/{wishlist.id}/category/create/',
            data=json.dumps({'name': 'Hacker Category'}),
            content_type='application/json',
        )
        assert response.status_code == 403
        assert not Category.objects.filter(family=family, name='Hacker Category').exists()
