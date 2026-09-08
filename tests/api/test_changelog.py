"""
Tests for the changelog / "What's new" feature — issue #90.

Active entries show in a dismissible card on the home page until the user
POSTs to /changelog/dismiss/ (recorded per-user via the seen_by M2M). The
/changelog/ page lists every active entry and the nav shows an unseen-count
badge. Entries are created directly in fixtures here because the 0022 data
migration does not run under pytest's --nomigrations.
"""

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from gift.models import ChangelogEntry

User = get_user_model()


def make_entry(slug, title, published=date(2026, 7, 27), **kwargs):
    """Create an active changelog entry with a simple friendly body."""
    return ChangelogEntry.objects.create(
        slug=slug,
        title=title,
        body=f'{title} — a short friendly description.',
        published_at=published,
        **kwargs,
    )


@pytest.mark.unit
class TestHomeWhatsNewCard:
    """The dismissible "What's new" card at the top of the home page."""

    def test_unseen_entries_shown_on_home(self, authenticated_user):
        make_entry('feature-one', 'Feature One')
        make_entry('feature-two', 'Feature Two', published=date(2026, 7, 21))
        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'wl-changelog-card' in content
        assert 'Feature One' in content
        assert 'Feature Two' in content
        assert 'Jul 27, 2026' in content  # published date rendered
        assert 'Got it, thanks!' in content

    def test_no_card_when_nothing_unseen(self, authenticated_user):
        response = authenticated_user.get('/')
        assert 'wl-changelog-card' not in response.content.decode()

    def test_dismiss_hides_entries_and_persists(self, authenticated_user):
        make_entry('feature-one', 'Feature One')
        response = authenticated_user.post('/changelog/dismiss/')
        assert response.status_code == 302
        assert response.url == '/'

        content = authenticated_user.get('/').content.decode()
        assert 'wl-changelog-card' not in content
        assert 'Feature One' not in content

        # Dismissal persists across requests
        content = authenticated_user.get('/').content.decode()
        assert 'wl-changelog-card' not in content
        assert 'Feature One' not in content

    def test_dismissal_is_per_user(self, authenticated_user, authenticated_other_user):
        make_entry('feature-one', 'Feature One')
        authenticated_user.post('/changelog/dismiss/')

        assert 'Feature One' not in authenticated_user.get('/').content.decode()
        content = authenticated_other_user.get('/').content.decode()
        assert 'wl-changelog-card' in content
        assert 'Feature One' in content

    def test_inactive_entries_not_shown_on_home(self, authenticated_user):
        make_entry('hidden-one', 'Hidden Feature', is_active=False)
        make_entry('visible-one', 'Visible Feature')
        content = authenticated_user.get('/').content.decode()
        assert 'Hidden Feature' not in content
        assert 'Visible Feature' in content

    def test_anonymous_sees_no_card(self, client, db):
        make_entry('feature-one', 'Feature One')
        response = client.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'wl-changelog-card' not in content
        assert 'Feature One' not in content

    def test_seen_entries_stay_hidden_when_new_ones_added(self, authenticated_user, user):
        old = make_entry('old-news', 'Old News', published=date(2026, 7, 18))
        old.seen_by.add(user)
        make_entry('new-hotness', 'New Hotness')

        content = authenticated_user.get('/').content.decode()
        assert 'New Hotness' in content
        assert 'Old News' not in content
        # Card and badge reflect only the single unseen entry
        assert '<span class="wl-count-badge">1</span>' in content
        assert '<span class="wl-nav-badge">1</span>' in content


@pytest.mark.unit
class TestChangelogDismiss:
    """The POST-only bulk dismiss endpoint."""

    def test_anonymous_redirected_to_login(self, client):
        response = client.post('/changelog/dismiss/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_get_not_allowed(self, authenticated_user):
        response = authenticated_user.get('/changelog/dismiss/')
        assert response.status_code == 405

    def test_marks_all_unseen_active_entries_seen(self, authenticated_user, user):
        make_entry('entry-a', 'Entry A')
        make_entry('entry-b', 'Entry B')
        make_entry('entry-gone', 'Entry Gone', is_active=False)

        authenticated_user.post('/changelog/dismiss/')

        seen = ChangelogEntry.objects.filter(seen_by=user)
        assert seen.count() == 2
        assert not seen.filter(slug='entry-gone').exists()

    def test_dismiss_is_idempotent(self, authenticated_user, user):
        make_entry('entry-a', 'Entry A')
        authenticated_user.post('/changelog/dismiss/')
        authenticated_user.post('/changelog/dismiss/')
        assert ChangelogEntry.objects.filter(seen_by=user).count() == 1


@pytest.mark.unit
class TestChangelogPage:
    """The /changelog/ history page."""

    def test_requires_login(self, client):
        response = client.get('/changelog/')
        assert response.status_code == 302
        assert response.url.startswith('/auth.html')

    def test_lists_entries_newest_first(self, authenticated_user):
        make_entry('older', 'Older Entry', published=date(2026, 7, 18))
        make_entry('newer', 'Newer Entry', published=date(2026, 7, 27))
        response = authenticated_user.get('/changelog/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Newer Entry' in content
        assert 'Older Entry' in content
        assert content.index('Newer Entry') < content.index('Older Entry')

    def test_inactive_entries_hidden(self, authenticated_user):
        make_entry('gone', 'Gone Entry', is_active=False)
        make_entry('live', 'Live Entry')
        content = authenticated_user.get('/changelog/').content.decode()
        assert 'Gone Entry' not in content
        assert 'Live Entry' in content

    def test_seen_entries_still_listed(self, authenticated_user, user):
        entry = make_entry('seen-one', 'Seen Entry')
        entry.seen_by.add(user)
        content = authenticated_user.get('/changelog/').content.decode()
        assert 'Seen Entry' in content


@pytest.mark.unit
class TestNavBadge:
    """The unseen-count badge on the "What's New" nav link."""

    def test_nav_link_and_badge_present_with_unseen(self, authenticated_user):
        make_entry('one', 'Entry One')
        make_entry('two', 'Entry Two')
        content = authenticated_user.get('/').content.decode()
        assert '/changelog/' in content
        assert "What's New" in content
        assert '<span class="wl-nav-badge">2</span>' in content

    def test_badge_absent_after_dismiss(self, authenticated_user):
        make_entry('one', 'Entry One')
        authenticated_user.post('/changelog/dismiss/')
        content = authenticated_user.get('/').content.decode()
        assert '/changelog/' in content  # link stays
        assert 'wl-nav-badge' not in content

    def test_badge_reflects_partial_seen(self, authenticated_user, user):
        seen = make_entry('seen', 'Seen Entry')
        seen.seen_by.add(user)
        make_entry('unseen', 'Unseen Entry')
        content = authenticated_user.get('/').content.decode()
        assert '<span class="wl-nav-badge">1</span>' in content

    def test_anonymous_has_no_badge(self, client, db):
        make_entry('one', 'Entry One')
        response = client.get('/')
        assert response.status_code == 200
        assert 'wl-nav-badge' not in response.content.decode()
