"""Tests for the collapsible wishlist groups on the home page (issue #86).

JS behavior itself isn't unit-tested — these assert the server-rendered
markup/contracts the JS hooks into: toggle buttons, aria wiring, bulk
controls, and the data attributes used for localStorage persistence.
"""
import re
from datetime import date

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


def birthday_today():
    """A birthday whose next occurrence is today (1992 is a leap year, so any
    month/day combo — including Feb 29 — is a valid date)."""
    today = date.today()
    return date(1992, today.month, today.day)


@pytest.mark.unit
class TestCollapsibleGroups:
    def test_expand_collapse_all_controls_rendered(self, authenticated_user, wishlist):
        """Expand all / Collapse all buttons sit next to the grouping selector."""
        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="wl-expand-all"' in content
        assert 'id="wl-collapse-all"' in content
        assert re.search(
            r'<button type="button" id="wl-expand-all" class="btn btn-outline-secondary btn-sm">',
            content,
        )
        assert re.search(
            r'<button type="button" id="wl-collapse-all" class="btn btn-outline-secondary btn-sm">',
            content,
        )

    def test_group_header_is_accessible_toggle_button(self, authenticated_user, wishlist):
        """Each group header is a real <button> with aria-expanded/aria-controls
        wired to the section body, and keeps the count badge."""
        response = authenticated_user.get('/?group_by=house')
        content = response.content.decode()
        assert (
            '<button type="button" class="wl-family-header wl-collapse-toggle" '
            'aria-expanded="true" aria-controls="wl-group-body-1">' in content
        )
        assert '<div class="wl-section-body" id="wl-group-body-1">' in content
        assert 'wl-count-badge' in content
        assert 'wl-chevron' in content

    def test_every_aria_controls_has_matching_body_id(self, authenticated_user, wishlist):
        """No toggle points at a missing section body."""
        User.objects.create_user(username='bday', email='bday@example.com', birthday=birthday_today())
        response = authenticated_user.get('/?group_by=house')
        content = response.content.decode()
        controls = re.findall(r'aria-controls="([^"]+)"', content)
        assert len(controls) >= 2  # birthdays section + at least one group
        for target in controls:
            assert f'id="{target}"' in content

    def test_grouping_mode_exposed_to_js(self, authenticated_user, wishlist):
        """The current grouping mode is rendered as a data attribute so the JS
        can scope localStorage keys per grouping."""
        response = authenticated_user.get('/?group_by=house')
        assert 'data-grouping="house"' in response.content.decode()

        response = authenticated_user.get('/?group_by=alpha')
        assert 'data-grouping="alpha"' in response.content.decode()

    def test_group_label_exposed_to_js(self, authenticated_user, wishlist):
        """Each section carries its group label for the localStorage key scheme."""
        response = authenticated_user.get('/?group_by=house')
        assert 'data-group-label="Test Family"' in response.content.decode()

        response = authenticated_user.get('/?group_by=alpha')
        assert 'data-group-label="T"' in response.content.decode()

    def test_upcoming_birthdays_section_is_collapsible(self, authenticated_user):
        """The Upcoming birthdays section shares the group markup and gets the
        same toggle treatment."""
        User.objects.create_user(username='bday', email='bday@example.com', birthday=birthday_today())
        response = authenticated_user.get('/')
        content = response.content.decode()
        assert 'data-group-label="Upcoming Birthdays"' in content
        assert 'aria-controls="wl-group-body-birthdays"' in content
        assert '<div class="wl-section-body" id="wl-group-body-birthdays">' in content

    def test_no_toggle_markup_for_anonymous_visitors(self, client, db):
        """Anonymous visitors get the sign-in page — no collapse controls/JS."""
        response = client.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'wl-collapse-toggle' not in content
        assert 'wl-expand-all' not in content
