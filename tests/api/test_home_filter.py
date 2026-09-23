"""Tests for the quick filter on the home wishlist view (issue #110).

The filtering itself happens in the browser, so what's testable here is the
server-rendered contract the JS hooks into: the input, the empty state, and
the `data-search` blob on each row. The blob is what decides whether a row
matches, so its contents are the real behavior under test.
"""
import html
import re
from datetime import date

import pytest
from django.contrib.auth import get_user_model

from gift.models import WishList

User = get_user_model()


def birthday_today():
    """A birthday whose next occurrence is today (1992 is a leap year, so any
    month/day combo — including Feb 29 — is a valid date)."""
    today = date.today()
    return date(1992, today.month, today.day)


def search_blobs(content):
    """Every data-search value on the page, in document order.

    Entities are unescaped because that's what getAttribute() hands the JS —
    asserting on the raw HTML would fail on a title like "Milo's List" that
    Django escapes on the way out.
    """
    return [html.unescape(blob) for blob in re.findall(r'data-search="([^"]*)"', content)]


@pytest.mark.unit
class TestHomeFilterMarkup:
    def test_filter_input_rendered(self, authenticated_user, wishlist):
        """The filter box sits on the page for signed-in users."""
        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="wl-filter"' in content
        assert 'type="search"' in content

    def test_empty_state_rendered_for_js_to_reveal(self, authenticated_user, wishlist):
        """A hidden 'nothing matches' element the JS can show."""
        content = authenticated_user.get('/').content.decode()
        assert 'id="wl-filter-empty"' in content

    def test_no_filter_markup_for_anonymous_visitors(self, client, db):
        """Anonymous visitors get the sign-in page — no filter box or empty state."""
        content = client.get('/').content.decode()
        assert 'id="wl-filter"' not in content
        assert 'id="wl-filter-empty"' not in content
        assert 'data-search=' not in content


@pytest.mark.unit
class TestRowSearchText:
    def test_row_search_text_covers_title_and_owner(self, authenticated_user, wishlist):
        """A row matches on its own title and on the owner's name."""
        content = authenticated_user.get('/').content.decode()
        blobs = search_blobs(content)
        assert 'test wishlist testuser' in blobs

    def test_search_text_is_lowercased(self, authenticated_user, wishlist):
        """Lowercased server-side so the JS can compare without re-casing."""
        content = authenticated_user.get('/').content.decode()
        blobs = search_blobs(content)
        assert blobs, 'no rows rendered — the assertion below would pass vacuously'
        for blob in blobs:
            assert blob == blob.lower()

    def test_search_text_uses_full_name_when_set(self, authenticated_user, user, family):
        """Someone searching "Eleanor" finds the list, even though the row's
        underlying username is something else."""
        owner = User.objects.create_user(
            username='edukeaccount',
            email='eleanor@example.com',
            first_name='Eleanor',
            last_name='Duke',
        )
        WishList.objects.create(owner=owner, title='Birthday Ideas', family_name=family)

        content = authenticated_user.get('/').content.decode()
        assert 'birthday ideas eleanor duke' in search_blobs(content)

    def test_search_text_uses_dependent_not_owner(self, authenticated_user, user, family):
        """Rows display the dependent as the person, so the filter must match
        the dependent — matching the owner would find a name that isn't shown."""
        dependent = User.objects.create_user(
            username='kidaccount', email='kid@example.com', first_name='Milo', last_name='Duke'
        )
        steward = User.objects.create_user(
            username='stewardaccount',
            email='steward@example.com',
            first_name='Rosa',
            last_name='Marin',
        )
        WishList.objects.create(
            owner=steward, dependent=dependent, title="Milo's List", family_name=family
        )

        content = authenticated_user.get('/').content.decode()
        blobs = search_blobs(content)
        assert "milo's list milo duke" in blobs
        assert not any('rosa' in blob for blob in blobs)

    def test_search_text_falls_back_to_username(self, authenticated_user, user, family):
        """No first/last name set — the row shows the username, so match that."""
        owner = User.objects.create_user(username='zephyr', email='zephyr@example.com')
        WishList.objects.create(owner=owner, title='Stuff', family_name=family)

        content = authenticated_user.get('/').content.decode()
        assert 'stuff zephyr' in search_blobs(content)


@pytest.mark.unit
class TestBirthdayRowSearchText:
    def test_birthday_row_exposes_search_text(self, authenticated_user, wishlist):
        """Birthday rows are people too — they filter like any other row."""
        User.objects.create_user(
            username='bday',
            email='bday@example.com',
            first_name='Ada',
            last_name='Lovelace',
            birthday=birthday_today(),
        )
        content = authenticated_user.get('/').content.decode()
        assert 'ada lovelace' in search_blobs(content)

    def test_birthday_row_falls_back_to_username(self, authenticated_user, wishlist):
        """Managed accounts often have no full name set."""
        User.objects.create_user(
            username='nonamebday', email='noname@example.com', birthday=birthday_today()
        )
        content = authenticated_user.get('/').content.decode()
        assert 'nonamebday' in search_blobs(content)
