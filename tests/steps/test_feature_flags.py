"""BDD step definitions for feature_flags.feature.

Views import ``get_steward_proxy_enabled`` / ``get_profile_picture_enabled``
inside the function body (`gift/views.py`), so patching the accessor on
``giftwiki.feature_flags`` takes effect on the next request.
"""

from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

pytestmark = pytest.mark.bdd

scenarios(str(Path(__file__).parent.parent / 'features' / 'feature_flags.feature'))


@given('the other user is the dependent on the wishlist')
def assign_dependent(wishlist, other_user):
    wishlist.dependent = other_user
    wishlist.save()


@given('STEWARD_PROXY_ENABLED is on')
def steward_on(monkeypatch):
    monkeypatch.setattr(
        'giftwiki.feature_flags.get_steward_proxy_enabled', lambda: True
    )


@given('STEWARD_PROXY_ENABLED is off')
def steward_off(monkeypatch):
    monkeypatch.setattr(
        'giftwiki.feature_flags.get_steward_proxy_enabled', lambda: False
    )


@given('PROFILE_PICTURE_ENABLED is on')
def profile_picture_on(monkeypatch):
    monkeypatch.setattr(
        'giftwiki.feature_flags.get_profile_picture_enabled', lambda: True
    )


@given('PROFILE_PICTURE_ENABLED is off')
def profile_picture_off(monkeypatch):
    monkeypatch.setattr(
        'giftwiki.feature_flags.get_profile_picture_enabled', lambda: False
    )


@when('the dependent opens the wishlist edit page', target_fixture='response')
def dependent_opens_edit(authenticated_other_user, wishlist):
    return authenticated_other_user.get(f'/wishlist/{wishlist.id}/edit/')


@when('the user opens the profile page', target_fixture='response')
def user_opens_profile(authenticated_user):
    return authenticated_user.get('/profile/')


@then('the response status is 200')
def assert_200(response):
    assert response.status_code == 200


@then('the response status is 302')
def assert_302(response):
    assert response.status_code == 302


@then('the page shows the profile picture field')
def page_shows_picture_field(response):
    assert response.status_code == 200
    assert 'name="profile_picture"' in response.content.decode()


@then('the page does not show the profile picture field')
def page_hides_picture_field(response):
    assert response.status_code == 200
    assert 'name="profile_picture"' not in response.content.decode()
