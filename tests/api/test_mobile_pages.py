"""Putting the right information in the right place: birthday labels that say
when to shop, shoppers seeing what's still available first, and the pages
that changed shape for phones."""
from datetime import date
from types import SimpleNamespace

import pytest

from gift.models import ChangelogEntry, Item
from gift.templatetags.gift_extras import birthday_label

TODAY = date(2026, 10, 12)


def person(birthday):
    return SimpleNamespace(birthday=birthday)


class TestBirthdayLabel:
    def test_leads_with_the_next_birthday_and_the_age_they_turn(self):
        assert birthday_label(person(date(1958, 3, 4)), TODAY) == 'Mar 4 · turns 69'

    def test_counts_down_when_it_is_close(self):
        assert birthday_label(person(date(1958, 10, 20)), TODAY) == 'Oct 20 · turns 68 · in 8 days'

    def test_tomorrow_and_today(self):
        assert birthday_label(person(date(2000, 10, 13)), TODAY) == 'Oct 13 · turns 26 · tomorrow'
        assert birthday_label(person(date(2000, 10, 12)), TODAY) == 'Oct 12 · turns 26 · today 🎉'

    def test_wraps_into_next_year(self):
        assert birthday_label(person(date(2019, 1, 5)), TODAY) == 'Jan 5 · turns 8'

    def test_leap_day_birthdays_fall_on_feb_28(self):
        assert birthday_label(person(date(1992, 2, 29)), TODAY) == 'Feb 28 · turns 35'

    def test_empty_without_a_birthday(self):
        assert birthday_label(person(None), TODAY) == ''
        assert birthday_label(None, TODAY) == ''


@pytest.mark.django_db
class TestItemOrder:
    def names(self, client, wishlist):
        response = client.get(f'/wishlist/{wishlist.id}/')
        return [item.name for item in response.context['uncategorized_items']]

    @pytest.fixture
    def items(self, wishlist, other_user):
        Item.objects.create(wishlist=wishlist, name='Bought', purchased=True, purchased_by=other_user)
        Item.objects.create(wishlist=wishlist, name='Available')

    def test_shoppers_see_what_is_still_available_first(self, authenticated_other_user, wishlist, items):
        assert self.names(authenticated_other_user, wishlist) == ['Available', 'Bought']

    def test_owners_order_ignores_purchases(self, authenticated_user, wishlist, items):
        # Sorting by `purchased` for the owner would give away what's been bought.
        assert self.names(authenticated_user, wishlist) == ['Bought', 'Available']


@pytest.mark.django_db
class TestPagesOnPhones:
    def test_top_level_pages_have_no_back_link(self, authenticated_user):
        for url in ('/my-purchases/', '/received-gifts/', '/changelog/'):
            assert 'wl-back' not in authenticated_user.get(url).content.decode(), url

    def test_new_list_form_matches_edit_list(self, authenticated_user, other_user):
        content = authenticated_user.get('/wishlist/create/').content.decode()

        assert 'The basics' in content
        assert "placeholder=\"testuser&#x27;s wishlist\"" in content
        assert 'class="wl-chip-check"' in content  # managers as chips
        # No old wiki pages to import, so no empty "import" section
        assert 'Bring over an old list' not in content

    def test_whats_new_card_always_links_to_the_details(self, authenticated_user):
        ChangelogEntry.objects.create(
            slug='one', title='One', body='Body.', published_at=date(2026, 1, 1)
        )
        content = authenticated_user.get('/').content.decode()

        assert 'class="wl-changelog-more" href="/changelog/">See details</a>' in content
