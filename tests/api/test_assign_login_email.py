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


@pytest.mark.api
class TestAssignLoginEmailCannotTakeOverAnAccount:
    """Assigning an address hands over the account, so it is a one-time grant
    to an account nobody signs in to yet — never a way to re-point a live one."""

    def _assign(self, client, target, email='attacker@example.com'):
        return client.post(reverse('gift:assign_login_email', args=[target.id]), {'email': email})

    def test_an_account_that_already_has_an_email_keeps_it(self, authenticated_user, managed_user):
        managed_user.email = 'ellie.duke@gmail.com'
        managed_user.save()

        response = self._assign(authenticated_user, managed_user)

        assert response.status_code == 302
        managed_user.refresh_from_db()
        assert managed_user.email == 'ellie.duke@gmail.com'
        assert not AllowedEmail.objects.filter(email='attacker@example.com').exists()

    def test_an_account_that_has_signed_in_is_refused(self, authenticated_user, managed_user):
        from django.utils import timezone

        managed_user.last_login = timezone.now()
        managed_user.save()

        self._assign(authenticated_user, managed_user)

        managed_user.refresh_from_db()
        assert managed_user.email == ''

    def test_an_account_with_a_linked_address_is_refused(self, authenticated_user, managed_user):
        LinkedEmail.objects.create(user=managed_user, email='ellie@school.example')

        self._assign(authenticated_user, managed_user)

        managed_user.refresh_from_db()
        assert managed_user.email == ''

    @pytest.mark.parametrize('flag', ['is_staff', 'is_superuser'])
    def test_a_staff_account_is_refused(self, authenticated_user, wishlist, flag):
        admin = User.objects.create_user(username='boss', **{flag: True})
        wishlist.dependent = admin
        wishlist.save()

        self._assign(authenticated_user, admin)

        admin.refresh_from_db()
        assert admin.email == ''
        assert not AllowedEmail.objects.filter(email='attacker@example.com').exists()


@pytest.mark.api
class TestDependentChoiceIsLimitedToPeopleYouManage:
    """With steward proxy on, the list form let a member name anyone — an
    admin included — as the `dependent`, which made them a "managed user"."""

    @pytest.fixture(autouse=True)
    def steward_proxy_on(self):
        from unittest.mock import patch

        with patch('giftwiki.feature_flags.get_steward_proxy_enabled', return_value=True):
            yield

    def test_only_yourself_and_people_you_manage_are_offered(
        self, user, other_user, managed_user
    ):
        from gift.forms import WishListForm

        admin = User.objects.create_user(username='boss', is_staff=True)

        choices = set(WishListForm(user=user).fields['dependent'].queryset)

        assert choices == {user, managed_user}
        assert admin not in choices
        assert other_user not in choices

    def test_a_manager_is_offered_the_kid_too(self, other_user, managed_user, wishlist):
        from gift.forms import WishListForm

        wishlist.managers.add(other_user)

        assert managed_user in WishListForm(user=other_user).fields['dependent'].queryset

    def test_posting_an_admin_as_dependent_does_not_make_them_managed(
        self, authenticated_other_user, other_user, family
    ):
        admin = User.objects.create_user(username='boss', is_staff=True)

        authenticated_other_user.post(
            reverse('gift:create_wishlist'),
            {'title': 'Trap', 'family_name': family.id, 'dependent': admin.id},
        )

        assert not WishList.objects.filter(dependent=admin).exists()
