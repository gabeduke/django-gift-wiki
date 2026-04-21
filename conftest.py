"""
Pytest configuration and shared fixtures for the gift wiki project.
"""

import os

os.environ.setdefault('DJANGO_ALLOWED_USERS', 'test@example.com,other@example.com')

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from gift.models import Family, Item, WishList

User = get_user_model()


@pytest.fixture
def api_client():
    """Fixture for Django REST framework APIClient."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser', email='test@example.com', password='testpass123'
    )


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(
        username='otheruser', email='other@example.com', password='otherpass123'
    )


@pytest.fixture
def family(db):
    """Create a test family."""
    return Family.objects.create(name='Test Family', description='Test family for testing')


@pytest.fixture
def wishlist(db, user, family):
    """Create a test wishlist."""
    return WishList.objects.create(
        owner=user,
        title='Test Wishlist',
        description='Test wishlist description',
        family_name=family,
    )


@pytest.fixture
def item(db, wishlist):
    """Create a test item."""
    return Item.objects.create(
        wishlist=wishlist, name='Test Item', description='Test item description', price='29.99'
    )


@pytest.fixture
def authenticated_user(user):
    """Authenticated user client — its own Client so parallel fixtures don't clobber its session."""
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def authenticated_other_user(other_user):
    """Authenticated other-user client — its own Client so parallel fixtures don't clobber its session."""
    c = Client()
    c.force_login(other_user)
    return c


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    """Set up test database."""
    with django_db_blocker.unblock():
        # Create necessary data for all tests
        pass
