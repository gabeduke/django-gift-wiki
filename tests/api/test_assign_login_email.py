"""Assigning a login email to an existing managed (child) account.

Managed users are created by a parent and often have no email at all, so they
can never sign in. These cover the flow that grants one an email and gets it
onto the allowlist in a single step.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from gift.models import AllowedEmail, LinkedEmail, WishList

User = get_user_model()


@pytest.fixture
def managed_user(db, user, wishlist):
    """A child account with no email, stewarded by the `user` fixture's wishlist."""
    kid = User.objects.create_user(username='ellie', password='unusable-pass')
    wishlist.dependent = kid
    wishlist.save()
    return kid


@pytest.mark.api
class TestAssignLoginEmail:
    def test_manager_assigning_an_email_also_allowlists_it(self, authenticated_user, managed_user):
        """Setting the email without the allowlist row would fail login silently."""
        response = authenticated_user.post(
            reverse('gift:assign_login_email', args=[managed_user.id]),
            {'email': 'ellie.duke@gmail.com'},
        )

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == 'ellie.duke@gmail.com'
        assert AllowedEmail.objects.filter(email='ellie.duke@gmail.com').exists()

    def test_a_stranger_cannot_assign_an_email_to_someone_elses_kid(
        self, authenticated_other_user, managed_user
    ):
        """other_user manages no wishlist that stewards this child."""
        response = authenticated_other_user.post(
            reverse('gift:assign_login_email', args=[managed_user.id]),
            {'email': 'attacker@example.com'},
        )

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == ''
        assert not AllowedEmail.objects.filter(email='attacker@example.com').exists()

    def test_a_wishlist_manager_may_assign_an_email(self, managed_user, other_user, wishlist):
        """Managers get the same reach as the owner, matching edit_managed_user."""
        from django.test import Client

        wishlist.managers.add(other_user)
        client = Client()
        client.force_login(other_user)

        response = client.post(
            reverse('gift:assign_login_email', args=[managed_user.id]),
            {'email': 'ellie.duke@gmail.com'},
        )

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == 'ellie.duke@gmail.com'

    def test_an_email_already_on_another_account_is_rejected(
        self, authenticated_user, managed_user, other_user
    ):
        """Two accounts sharing an email makes the middleware pick one at random."""
        response = authenticated_user.post(
            reverse('gift:assign_login_email', args=[managed_user.id]),
            {'email': other_user.email},
        )

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == ''
        assert not AllowedEmail.objects.filter(email=other_user.email).exists()

    def test_an_email_already_linked_to_another_account_is_rejected(
        self, authenticated_user, managed_user, other_user
    ):
        """LinkedEmail wins the middleware lookup, so the kid would log in as someone else."""
        LinkedEmail.objects.create(user=other_user, email='shared@example.com')

        response = authenticated_user.post(
            reverse('gift:assign_login_email', args=[managed_user.id]),
            {'email': 'shared@example.com'},
        )

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == ''

    def test_account_page_offers_sign_in_for_a_kid_without_an_email(
        self, authenticated_user, managed_user
    ):
        """The affordance has to live in the row people already look at."""
        response = authenticated_user.get(reverse('gift:account'))
        content = response.content.decode()

        assert 'Enable sign-in' in content
        assert reverse('gift:assign_login_email', args=[managed_user.id]) in content

    def test_account_page_shows_the_address_once_a_kid_can_sign_in(
        self, authenticated_user, managed_user
    ):
        managed_user.email = 'ellie.duke@gmail.com'
        managed_user.save()

        response = authenticated_user.get(reverse('gift:account'))
        content = response.content.decode()

        assert 'ellie.duke@gmail.com' in content
        assert 'Can sign in' in content


@pytest.mark.api
class TestManagedUserCanUseTheirList:
    """What a kid can actually do once they are signed in.

    Guards the payoff of assigning an email: getting in the door is worthless
    if every edit on their own list is rejected.
    """

    def test_dependent_can_add_an_item_to_their_own_list(self, managed_user, wishlist):
        from django.test import Client

        client = Client()
        client.force_login(managed_user)

        response = client.post(
            reverse('gift:add_item', args=[wishlist.id]),
            {'name': 'Lego set', 'description': 'the big one', 'price': '59.99'},
        )

        assert response.status_code == 302
        assert wishlist.items.filter(name='Lego set', is_deleted=False).exists()
