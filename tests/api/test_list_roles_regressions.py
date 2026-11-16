"""Regressions around who owns, manages and is kept on a list.

A list kept for a kid has a parent as `owner`, the other parent in `managers`
and the kid as `dependent`. The kid being the dependent is what hides
purchases and surprise items from them, so nothing may change `dependent` or
`managers` behind somebody's back. Each test here reproduces a way that
happened.
"""

import re
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from gift.models import ScrapedWikiItem, ScrapedWikiPage, WishList

User = get_user_model()


@pytest.fixture
def kid(db):
    return User.objects.create_user(username='ellie', password='unusable-pass')


@pytest.fixture
def kids_list(wishlist, kid, other_user):
    """`user` owns it, `other_user` co-manages it, and it's kept for `kid`."""
    wishlist.dependent = kid
    wishlist.save()
    wishlist.managers.add(other_user)
    return wishlist


@pytest.fixture
def grandma(db):
    return User.objects.create_user(username='grandma', email='grandma@example.com')


@pytest.fixture
def scraped_page(db):
    page = ScrapedWikiPage.objects.create(
        title='Ellie (old wiki)',
        url='https://example.pbworks.com/Ellie',
        scraped_at=timezone.now(),
        item_count=2,
    )
    ScrapedWikiItem.objects.create(scraped_page=page, name='Kite')
    ScrapedWikiItem.objects.create(scraped_page=page, name='Paint set')
    return page


def _client_for(user):
    client = Client()
    client.force_login(user)
    return client


def _manager_boxes(html):
    return re.findall(r'<input[^>]*name="managers"[^>]*>', html)


def _box_value(box):
    return re.search(r'value="(\d+)"', box).group(1)


def _edit_list_data(client, wishlist, **overrides):
    """What the browser posts when someone opens Edit List and hits Save.

    Managers come from the checkboxes as rendered — a manager whose own box
    isn't on the page can't submit it.
    """
    html = client.get(reverse('gift:edit_wishlist', args=[wishlist.id])).content.decode()
    data = {
        'title': wishlist.title,
        'description': wishlist.description or '',
        'family_name': wishlist.family_name_id,
        'managers': [_box_value(b) for b in _manager_boxes(html) if ' checked' in b],
        'form-TOTAL_FORMS': '0',
        'form-INITIAL_FORMS': '0',
        'form-MIN_NUM_FORMS': '0',
        'form-MAX_NUM_FORMS': '1000',
    }
    data.update(overrides)
    return data


def _selected_link(html, managed_user):
    """The list the kid's Edit modal on My Lists has selected, or ''."""
    start = html.index(f'id="editManagedUserModal{managed_user.id}"')
    modal = html[start : html.index('</form>', start)]
    select = re.search(r'<select name="link_to_wishlist".*?</select>', modal, re.S).group(0)
    selected = re.search(r'<option value="(\d*)"[^>]*selected', select)
    return selected.group(1) if selected else ''


@pytest.mark.api
class TestManagerSavingEditList:
    """Bug 1: the managers checkboxes left out whoever was editing."""

    def test_a_manager_who_saves_edit_list_stays_a_manager(self, kids_list, other_user):
        client = _client_for(other_user)

        response = client.post(
            reverse('gift:edit_wishlist', args=[kids_list.id]),
            _edit_list_data(client, kids_list),
        )

        assert response.status_code == 302
        assert other_user in kids_list.managers.all()

    def test_the_owner_is_never_offered_as_a_manager_of_their_own_list(
        self, kids_list, user, other_user
    ):
        html = _client_for(other_user).get(
            reverse('gift:edit_wishlist', args=[kids_list.id])
        ).content.decode()

        offered = {_box_value(b) for b in _manager_boxes(html)}
        assert str(user.id) not in offered
        assert str(other_user.id) in offered

    def test_a_new_list_does_not_offer_its_creator_as_a_manager(
        self, authenticated_user, user, other_user
    ):
        """wishlist_create: the creator becomes the owner, so they're left out."""
        html = authenticated_user.get(reverse('gift:create_wishlist')).content.decode()

        offered = {_box_value(b) for b in _manager_boxes(html)}
        assert str(user.id) not in offered
        assert str(other_user.id) in offered


@pytest.mark.api
class TestEditingAManagedUserKeepsTheirLists:
    """Bug 2: editing a kid's details could unlink them from lists."""

    @pytest.fixture
    def grandmas_list(self, grandma, kid, family):
        """Created first, so it's the kid's lowest-id list — outside `user`'s reach."""
        return WishList.objects.create(
            owner=grandma, dependent=kid, title="Ellie's at Grandma's", family_name=family
        )

    @pytest.fixture
    def both_lists(self, grandmas_list, kids_list):
        return grandmas_list, kids_list

    def test_the_edit_modal_preselects_the_requesters_own_list(
        self, authenticated_user, kid, both_lists
    ):
        _grandmas, ours = both_lists

        html = authenticated_user.get(reverse('gift:account')).content.decode()

        assert _selected_link(html, kid) == str(ours.id)

    def test_a_birthday_edit_from_the_modal_unlinks_nothing(
        self, authenticated_user, kid, both_lists
    ):
        grandmas, ours = both_lists
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        response = authenticated_user.post(
            reverse('gift:edit_managed_user', args=[kid.id]),
            {'birthday': '2016-03-04', 'link_to_wishlist': _selected_link(html, kid)},
        )

        assert response.status_code == 302
        kid.refresh_from_db()
        assert str(kid.birthday) == '2016-03-04'
        grandmas.refresh_from_db()
        ours.refresh_from_db()
        assert grandmas.dependent == kid
        assert ours.dependent == kid

    def test_clearing_the_link_only_unlinks_the_requesters_own_list(
        self, authenticated_user, kid, both_lists
    ):
        grandmas, ours = both_lists

        authenticated_user.post(
            reverse('gift:edit_managed_user', args=[kid.id]), {'link_to_wishlist': ''}
        )

        grandmas.refresh_from_db()
        ours.refresh_from_db()
        assert ours.dependent is None
        assert grandmas.dependent == kid

    def test_picking_a_list_kept_for_someone_else_is_rejected(
        self, authenticated_user, user, kid, kids_list, family
    ):
        sibling = User.objects.create_user(username='max', password='unusable-pass')
        siblings_list = WishList.objects.create(
            owner=user, dependent=sibling, title="Max's List", family_name=family
        )

        response = authenticated_user.post(
            reverse('gift:edit_managed_user', args=[kid.id]),
            {'link_to_wishlist': siblings_list.id},
            follow=True,
        )

        siblings_list.refresh_from_db()
        assert siblings_list.dependent == sibling
        assert any(
            m.level_tag == 'error' and "Max's List" in m.message
            for m in response.context['messages']
        )

    def test_picking_a_free_list_links_the_kid(self, authenticated_user, user, kid, kids_list):
        spare = WishList.objects.create(owner=user, title='Spare')

        authenticated_user.post(
            reverse('gift:edit_managed_user', args=[kid.id]), {'link_to_wishlist': spare.id}
        )

        spare.refresh_from_db()
        assert spare.dependent == kid

    def test_creating_a_person_cannot_take_over_a_list_kept_for_someone_else(
        self, authenticated_user, kid, kids_list
    ):
        """create_managed_user shares the form, and with it the same overwrite."""
        authenticated_user.post(
            reverse('gift:create_managed_user'),
            {'username': 'newkid', 'link_to_wishlist': kids_list.id},
        )

        kids_list.refresh_from_db()
        assert kids_list.dependent == kid


@pytest.mark.api
class TestImportingFromEditList:
    """Bug 3: a manager's import returned None, which then replaced the list."""

    def test_a_manager_can_import_a_scraped_page_into_a_list_they_manage(
        self, kids_list, other_user, scraped_page
    ):
        client = _client_for(other_user)

        response = client.post(
            reverse('gift:edit_wishlist', args=[kids_list.id]),
            _edit_list_data(client, kids_list, scraped_page=scraped_page.id),
        )

        assert response.status_code == 302
        assert set(kids_list.items.values_list('name', flat=True)) == {'Kite', 'Paint set'}

    def test_a_failed_import_still_saves_edit_list(
        self, authenticated_user, wishlist, scraped_page
    ):
        with patch('gift.views.import_scraped_page_to_user', return_value=None):
            response = authenticated_user.post(
                reverse('gift:edit_wishlist', args=[wishlist.id]),
                _edit_list_data(
                    authenticated_user, wishlist, title='Renamed', scraped_page=scraped_page.id
                ),
            )

        assert response.status_code == 302
        wishlist.refresh_from_db()
        assert wishlist.title == 'Renamed'

    def test_a_failed_import_on_a_new_list_still_lands_on_it(
        self, authenticated_user, family, scraped_page
    ):
        with patch('gift.views.import_scraped_page_to_user', return_value=None):
            response = authenticated_user.post(
                reverse('gift:create_wishlist'),
                {'title': 'Fresh', 'family_name': family.id, 'scraped_page': scraped_page.id},
            )

        created = WishList.objects.get(title='Fresh')
        assert response.status_code == 302
        assert response.url == reverse('gift:wishlist_detail', args=[created.id])

    def test_a_giver_still_cannot_import_into_someone_elses_list(
        self, kids_list, grandma, scraped_page
    ):
        from gift.views import import_scraped_page_to_user

        assert import_scraped_page_to_user(grandma, scraped_page, target_wishlist=kids_list) is None
        assert not kids_list.items.exists()


@pytest.mark.api
class TestCreateListErrorPath:
    """Bug 4: the error path redirected to an un-namespaced URL name."""

    def test_a_validation_error_while_creating_redirects_home(self, authenticated_user, family):
        with patch.object(WishList, 'save', side_effect=ValidationError('Nope')):
            response = authenticated_user.post(
                reverse('gift:create_wishlist'), {'title': 'Fresh', 'family_name': family.id}
            )

        assert response.status_code == 302
        assert response.url == reverse('gift:home')


@pytest.mark.unit
class TestSignInEmailCase:
    """Bug 5: the email lookup was case-sensitive while everything else wasn't."""

    def test_a_kid_whose_email_was_typed_with_capitals_signs_in_as_themselves(self, db):
        from gift.middleware.firebase_auth import resolve_user_for_email

        kid = User.objects.create(username='emma_2015', email='Emma@Gmail.com')
        accounts_before = User.objects.count()

        assert resolve_user_for_email('emma@gmail.com') == kid
        assert User.objects.count() == accounts_before
