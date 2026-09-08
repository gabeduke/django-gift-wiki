"""Tests for the 'Upcoming birthdays' section on the home page."""
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from gift.models import WishList

User = get_user_model()


def make_birthday(days_from_today):
    """Return a birthday whose next occurrence is `days_from_today` days from today."""
    target = date.today() + timedelta(days=days_from_today)
    if (target.month, target.day) == (2, 29):
        # Feb 29 birthdays are observed on Feb 28 in non-leap years; nudge the
        # target so day offsets stay exact in tests.
        target += timedelta(days=1)
    return date(1992, target.month, target.day)  # 1992 is a leap year


@pytest.mark.unit
class TestUpcomingBirthdays:
    def test_section_hidden_when_no_birthdays(self, authenticated_user):
        """No users with a birthday set -> the section is not rendered at all."""
        response = authenticated_user.get('/')
        assert response.status_code == 200
        assert 'Upcoming Birthdays' not in response.content.decode()
        assert list(response.context['upcoming_birthdays']) == []

    def test_users_without_birthdays_excluded(self, authenticated_user, other_user):
        """Only users with a birthday set appear in the section."""
        User.objects.create_user(
            username='hasbday', email='hasbday@example.com', birthday=make_birthday(10)
        )

        response = authenticated_user.get('/')
        assert response.status_code == 200
        entries = response.context['upcoming_birthdays']
        assert [entry['user'].username for entry in entries] == ['hasbday']

    def test_ordering_wraps_year_boundary(self, authenticated_user):
        """A birthday that just passed goes to the back of the queue (next year),
        behind a birthday coming up in a few days — not sorted by raw month/day."""
        User.objects.create_user(
            username='past-bday', email='past@example.com', birthday=make_birthday(-1)
        )
        User.objects.create_user(
            username='soon-bday', email='soon@example.com', birthday=make_birthday(10)
        )

        response = authenticated_user.get('/')
        entries = response.context['upcoming_birthdays']
        assert [entry['user'].username for entry in entries] == ['soon-bday', 'past-bday']
        assert entries[0]['days_until'] == 10
        assert entries[1]['days_until'] > 300

    def test_limit_of_five(self, authenticated_user):
        """At most 5 upcoming birthdays are shown."""
        for i in range(1, 8):
            User.objects.create_user(
                username=f'bday{i}',
                email=f'bday{i}@example.com',
                birthday=make_birthday(i * 5),
            )

        response = authenticated_user.get('/')
        entries = response.context['upcoming_birthdays']
        assert [entry['user'].username for entry in entries] == [
            'bday1',
            'bday2',
            'bday3',
            'bday4',
            'bday5',
        ]

    def test_birthday_today_is_upcoming(self, authenticated_user):
        """A birthday today counts as upcoming (days_until=0) and is flagged as today."""
        birthday = make_birthday(0)
        User.objects.create_user(
            username='todaybday', email='today@example.com', birthday=birthday
        )

        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'todaybday' in content
        assert 'today!' in content
        assert f"{birthday.strftime('%b')} {birthday.day}" in content
        entries = response.context['upcoming_birthdays']
        assert entries[0]['days_until'] == 0
        assert entries[0]['turning_age'] == date.today().year - 1992

    def test_name_links_to_most_recently_updated_wishlist(self, authenticated_user):
        """The person's name links to their most recently updated wishlist."""
        person = User.objects.create_user(
            username='linkedbday', email='linked@example.com', birthday=make_birthday(7)
        )
        old_list = WishList.objects.create(owner=person, title='Old List')
        new_list = WishList.objects.create(owner=person, title='New List')
        WishList.objects.filter(pk=old_list.pk).update(
            updated_at=timezone.now() - timedelta(days=10)
        )

        response = authenticated_user.get('/')
        entries = response.context['upcoming_birthdays']
        assert entries[0]['wishlist_id'] == new_list.id
        assert f'/wishlist/{new_list.id}/' in response.content.decode()

    def test_no_wishlist_means_no_link(self, authenticated_user):
        """A person without any wishlist still shows up, just without a link."""
        User.objects.create_user(
            username='nolistbday', email='nolist@example.com', birthday=make_birthday(7)
        )

        response = authenticated_user.get('/')
        entries = response.context['upcoming_birthdays']
        assert entries[0]['wishlist_id'] is None
        assert 'nolistbday' in response.content.decode()

    def test_wishlist_link_follows_list_person_convention(self, authenticated_user, user):
        """A managed kid's list (owner=parent, dependent=kid) belongs to the kid:
        the kid's birthday links to it, the parent's birthday does not."""
        kid = User.objects.create_user(
            username='kidbday', email='kid@example.com', birthday=make_birthday(7)
        )
        user.birthday = make_birthday(3)
        user.save()
        kid_list = WishList.objects.create(owner=user, dependent=kid, title='Kid List')

        response = authenticated_user.get('/')
        entries = {e['user'].username: e for e in response.context['upcoming_birthdays']}
        assert entries['kidbday']['wishlist_id'] == kid_list.id
        assert entries['testuser']['wishlist_id'] is None
