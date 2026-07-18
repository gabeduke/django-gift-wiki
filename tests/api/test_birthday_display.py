"""Tests for birthday display on wishlist list and detail pages."""
import pytest
from django.contrib.auth import get_user_model

from gift.models import Family, WishList

User = get_user_model()


@pytest.mark.unit
class TestBirthdayDisplay:
    def test_home_page_shows_birthday(self, authenticated_user, user):
        """The home page shows the list owner's birthday."""
        family = Family.objects.create(name='Birthday Family')
        user.birthday = '1990-03-15'
        user.save()
        WishList.objects.create(owner=user, title='Birthday List', family_name=family)

        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '3/15' in content
        assert '(age' in content

    def test_home_page_shows_dependent_birthday(self, authenticated_user, user):
        """The home page shows the dependent's birthday when present."""
        family = Family.objects.create(name='Dependent Family')
        dependent = User.objects.create_user(
            username='kid', birthday='2015-07-20', email='kid@example.com'
        )
        WishList.objects.create(
            owner=user, dependent=dependent, title='Kid List', family_name=family
        )

        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '7/20' in content
        assert '(age' in content

    def test_wishlist_detail_shows_birthday(self, authenticated_user, user):
        """The wishlist detail page shows the person's birthday."""
        family = Family.objects.create(name='Detail Family')
        user.birthday = '1985-12-25'
        user.save()
        wishlist = WishList.objects.create(
            owner=user, title='Detail List', family_name=family
        )

        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '12/25' in content
        assert '(age' in content
