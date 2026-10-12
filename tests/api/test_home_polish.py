"""Home page touches for the holiday season: countdown, greeting, a shorter
"What's new" card."""

from datetime import date
from unittest import mock

import pytest

from gift.models import ChangelogEntry
from gift.views import CHANGELOG_CARD_LIMIT, HOLIDAY_COUNTDOWN_DAYS, days_until_christmas

pytestmark = pytest.mark.unit


class TestDaysUntilChristmas:
    def test_counts_down_in_the_run_up(self):
        assert days_until_christmas(date(2026, 12, 1)) == 24

    def test_christmas_day_is_zero(self):
        assert days_until_christmas(date(2026, 12, 25)) == 0

    def test_starts_at_the_countdown_window(self):
        start = date(2026, 12, 25).toordinal() - HOLIDAY_COUNTDOWN_DAYS
        assert days_until_christmas(date.fromordinal(start)) == HOLIDAY_COUNTDOWN_DAYS
        assert days_until_christmas(date.fromordinal(start - 1)) is None

    def test_quiet_after_christmas(self):
        assert days_until_christmas(date(2026, 12, 26)) is None

    def test_quiet_in_summer(self):
        assert days_until_christmas(date(2026, 7, 4)) is None


class TestHomePage:
    def home(self, client, today):
        with mock.patch('gift.views.timezone.localdate', return_value=today):
            return client.get('/').content.decode()

    def test_shows_the_countdown_in_season(self, authenticated_user):
        content = self.home(authenticated_user, date(2026, 12, 15))

        assert 'class="wl-countdown"' in content
        assert '10</span> days until Christmas' in content

    def test_christmas_eve_and_day(self, authenticated_user):
        assert 'Christmas is tomorrow!' in self.home(authenticated_user, date(2026, 12, 24))
        assert 'Merry Christmas!' in self.home(authenticated_user, date(2026, 12, 25))

    def test_no_countdown_out_of_season(self, authenticated_user):
        assert 'class="wl-countdown"' not in self.home(authenticated_user, date(2026, 3, 1))

    def test_greets_the_user(self, authenticated_user, user):
        user.first_name = 'Sarah'
        user.save()

        assert 'Hi, Sarah' in authenticated_user.get('/').content.decode()

    def test_greets_by_username_without_a_first_name(self, authenticated_user):
        assert 'Hi, testuser' in authenticated_user.get('/').content.decode()


class TestWhatsNewCard:
    def make_entries(self, count):
        for i in range(count):
            ChangelogEntry.objects.create(
                slug=f'entry-{i}',
                title=f'Entry {i}',
                body='Something nice.',
                published_at=date(2026, 1, i + 1),
            )

    def test_shows_only_the_newest_few(self, authenticated_user):
        self.make_entries(CHANGELOG_CARD_LIMIT + 3)

        content = authenticated_user.get('/').content.decode()
        card = content[content.index('wl-changelog-card') : content.index('wl-changelog-dismiss')]

        assert card.count('wl-changelog-entry-title') == CHANGELOG_CARD_LIMIT
        assert f'Entry {CHANGELOG_CARD_LIMIT + 2}' in card  # newest first
        assert '…and 3 more' in card

    def test_badge_counts_everything_unseen(self, authenticated_user):
        self.make_entries(CHANGELOG_CARD_LIMIT + 3)

        content = authenticated_user.get('/').content.decode()

        assert f'<span class="wl-count-badge">{CHANGELOG_CARD_LIMIT + 3}</span>' in content

    def test_no_more_link_when_everything_fits(self, authenticated_user):
        self.make_entries(CHANGELOG_CARD_LIMIT)

        assert 'more</a>' not in authenticated_user.get('/').content.decode()

    def test_dismissing_still_clears_every_entry(self, authenticated_user):
        self.make_entries(CHANGELOG_CARD_LIMIT + 3)

        authenticated_user.post('/changelog/dismiss/')

        assert 'wl-changelog-card' not in authenticated_user.get('/').content.decode()
