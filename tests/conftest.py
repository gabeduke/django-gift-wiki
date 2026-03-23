"""
Shared test fixtures for the test suite.
"""

import pytest
from django.contrib.auth import get_user_model

from gift.models import Family, Item, WishList

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser', email='test@example.com', password='testpass123'
    )


@pytest.fixture
def admin_user(db):
    """Create a test admin user."""
    return User.objects.create_superuser(
        username='admin', email='admin@example.com', password='adminpass123'
    )


@pytest.fixture
def family(db):
    """Create a test family."""
    return Family.objects.create(name='Test Family', description='Test family description')


@pytest.fixture
def wishlist(db, user, family):
    """Create a test wishlist."""
    return WishList.objects.create(
        owner=user, title='Test Wishlist', description='A test wishlist', family_name=family
    )


@pytest.fixture
def item(db, wishlist, user):
    """Create a test item."""
    return Item.objects.create(
        wishlist=wishlist,
        name='Test Item',
        description='A test item',
        price='19.99',
        updated_by=user,
    )
