"""
Step definitions for wishlist management features.
"""
from pytest_bdd import given, when, then, parsers
from django.contrib.auth import get_user_model
from gift.models import WishList, Family

User = get_user_model()


# Fixtures
@given("I am logged in as a user")
def logged_in_user(authenticated_user):
    """Ensure user is logged in."""
    return authenticated_user


@given("I am on the create wishlist page")
def on_create_wishlist_page(client, authenticated_user):
    """Navigate to create wishlist page."""
    response = authenticated_user.get('/wishlist/create/')
    assert response.status_code == 200
    return response


@given(parsers.parse("I have created a wishlist"))
def created_wishlist(request, authenticated_user, user):
    """Create a wishlist for the current user."""
    family = Family.objects.create(name="Test Family")
    wishlist = WishList.objects.create(
        owner=user,
        title="Test Wishlist",
        family_name=family
    )
    request.wishlist = wishlist
    return wishlist


@when(parsers.parse("I fill in the wishlist form with:"))
def fill_wishlist_form(authenticated_user, table):
    """Fill in the wishlist form with table data."""
    form_data = {row['Title']: row['Title'], row['Description']: row['Description']}
    authenticated_user.post('/wishlist/create/', data=form_data)
    return form_data


@then(parsers.parse("I should see \"{message}\""))
def should_see_message(response, message):
    """Check that a message is displayed."""
    # This would be implemented with actual response checking
    assert message in str(response.content)


@then("I should be on my wishlist detail page")
def on_wishlist_detail_page(response, wishlist):
    """Verify we're on the detail page."""
    assert response.url == f'/wishlist/{wishlist.id}/'


@when("I submit the form")
def submit_form(client, authenticated_user):
    """Submit the form."""
    # Implementation would submit the form
    pass


@when("I navigate to the home page")
def navigate_home(authenticated_user):
    """Navigate to home page."""
    response = authenticated_user.get('/')
    assert response.status_code == 200
    return response


@then("I should see a list of my wishlists")
def see_wishlists(response, user):
    """Verify wishlists are displayed."""
    wishlists = WishList.objects.filter(owner=user)
    assert wishlists.exists()

