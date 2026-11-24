"""🤔 Considering: a giver says they're thinking of buying something.

It is exactly as secret as a purchase (gift/visibility.py, `sees_purchases`):
other givers see who's considering what, so nobody doubles up, but the
recipient, a manager of someone's own list, and anyone over the shoulder never
learn it, through the page, the toggle or My Purchases.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from gift.models import Item, WishList

User = get_user_model()

pytestmark = pytest.mark.unit

ON_PAGE = 'is considering'


def url(item):
    return f'/item/{item.id}/considering/'


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def make_user(username, first_name=''):
    return User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='pass12345',
        first_name=first_name,
    )


def background(client, item):
    return client.post(url(item), HTTP_X_REQUESTED_WITH='fetch')


@pytest.fixture
def aunt(db):
    return make_user('aunt', first_name='Sue')


@pytest.fixture
def giver(other_user):
    return signed_in(other_user)


@pytest.fixture
def kid_list(user, family):
    """`user` keeps this list for a kid; givers buy for the kid."""
    kid = make_user('kiddo')
    wishlist = WishList.objects.create(
        owner=user, dependent=kid, title="Kiddo's List", family_name=family
    )
    return wishlist, kid


class TestToggle:
    def test_giver_considers_and_stops_in_the_background(self, giver, other_user, item):
        response = background(giver, item)
        assert response.json() == {'considering': True}
        assert list(item.considered_by.all()) == [other_user]

        response = background(giver, item)
        assert response.json() == {'considering': False}
        assert not item.considered_by.exists()

    def test_without_js_it_returns_to_the_page(self, giver, item):
        response = giver.post(url(item), {'next': '/my-purchases/'})
        assert response.status_code == 302
        assert response.url == '/my-purchases/'

    def test_next_must_stay_on_site(self, giver, wishlist, item):
        response = giver.post(url(item), {'next': 'https://evil.example/'})
        assert response.url == f'/wishlist/{wishlist.id}/'

    def test_post_only(self, giver, item):
        assert giver.get(url(item)).status_code == 405

    def test_several_givers_can_consider_one_item(self, giver, aunt, other_user, item):
        background(giver, item)
        background(signed_in(aunt), item)
        assert set(item.considered_by.all()) == {other_user, aunt}

    def test_recipient_cannot(self, authenticated_user, item):
        response = background(authenticated_user, item)
        assert response.status_code == 403
        assert not item.considered_by.exists()

    def test_manager_of_someones_own_list_cannot(self, other_user, wishlist, item):
        wishlist.managers.add(other_user)
        response = background(signed_in(other_user), item)
        assert response.status_code == 403
        assert not item.considered_by.exists()

    def test_not_over_the_shoulder(self, giver, item):
        giver.post('/over-the-shoulder/', {'on': '1'})
        response = background(giver, item)
        assert response.status_code == 403
        assert not item.considered_by.exists()

    def test_kid_cannot_but_keeper_can(self, user, other_user, kid_list):
        wishlist, kid = kid_list
        item = Item.objects.create(wishlist=wishlist, name='Kite')

        assert background(signed_in(kid), item).status_code == 403
        assert background(signed_in(user), item).json() == {'considering': True}

    def test_recipient_gets_404_for_a_surprise(self, authenticated_user, wishlist, other_user):
        surprise = Item.objects.create(
            wishlist=wishlist, name='Secret', is_sneaky=True, added_by=other_user
        )
        assert background(authenticated_user, surprise).status_code == 404

    def test_cannot_start_considering_something_bought(self, giver, aunt, item):
        item.purchased = True
        item.purchased_by = aunt
        item.save()
        response = background(giver, item)
        assert response.status_code == 409
        assert not item.considered_by.exists()

    def test_can_still_drop_a_mark_once_someone_bought_it(self, giver, other_user, aunt, item):
        item.considered_by.add(other_user)
        item.purchased = True
        item.purchased_by = aunt
        item.save()
        assert background(giver, item).json() == {'considering': False}


class TestListPage:
    def test_giver_sees_who_else_is_considering(self, giver, aunt, wishlist, item):
        item.considered_by.add(aunt)
        page = giver.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert '🤔 Sue is considering' in page
        assert url(item) in page

    def test_own_mark_shows_as_the_toggle_not_a_note(self, giver, other_user, wishlist, item):
        item.considered_by.add(other_user)
        page = giver.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert ON_PAGE not in page
        assert 'class="wl-consider is-on"' in page

    def test_recipient_never_sees_it(self, authenticated_user, aunt, wishlist, item):
        item.considered_by.add(aunt)
        page = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert ON_PAGE not in page
        assert '/considering/' not in page

    def test_kid_never_sees_it(self, aunt, kid_list):
        wishlist, kid = kid_list
        item = Item.objects.create(wishlist=wishlist, name='Kite')
        item.considered_by.add(aunt)
        page = signed_in(kid).get(f'/wishlist/{wishlist.id}/').content.decode()
        assert ON_PAGE not in page
        assert '/considering/' not in page

    def test_hidden_over_the_shoulder(self, giver, aunt, wishlist, item):
        item.considered_by.add(aunt)
        giver.post('/over-the-shoulder/', {'on': '1'})
        page = giver.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert ON_PAGE not in page
        assert '/considering/' not in page

    def test_gone_once_bought(self, giver, aunt, other_user, wishlist, item):
        item.considered_by.add(aunt)
        item.purchased = True
        item.purchased_by = other_user
        item.save()
        page = giver.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert ON_PAGE not in page
        assert url(item) not in page

    def test_surprise_items_get_it_too(self, giver, aunt, wishlist):
        surprise = Item.objects.create(
            wishlist=wishlist, name='Secret', is_sneaky=True, added_by=aunt
        )
        surprise.considered_by.add(aunt)
        page = giver.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert '🤔 Sue is considering' in page
        assert url(surprise) in page


    def test_not_in_the_recipients_edit_forms(self, authenticated_user, aunt, wishlist, item):
        """Like `purchased`, the Edit Item form and Edit List formset never carry it."""
        item.considered_by.add(aunt)
        for path in (f'/item/edit/{item.id}/', f'/wishlist/{wishlist.id}/edit/'):
            response = authenticated_user.get(path)
            assert response.status_code == 200, path
            page = response.content.decode()
            assert 'considered_by' not in page
            assert ON_PAGE not in page


class TestMyPurchases:
    def test_considering_listed_with_totals(self, giver, other_user, wishlist):
        Item.objects.create(
            wishlist=wishlist,
            name='Bought Thing',
            price='10.00',
            purchased=True,
            purchased_by=other_user,
        )
        Item.objects.create(wishlist=wishlist, name='Maybe Thing', price='25.50')
        Item.objects.create(wishlist=wishlist, name='Unpriced Maybe', price_range='under_50')
        for item in Item.objects.filter(name__contains='Maybe'):
            item.considered_by.add(other_user)

        page = giver.get('/my-purchases/').content.decode()
        assert 'Bought Thing' in page
        assert 'Maybe Thing' in page
        assert 'Under $50' in page
        assert '$10.00 spent' in page
        assert '2 considering ($25.50)' in page
        assert '1 without a price' in page
        assert page.index('Bought Thing') < page.index('Maybe Thing')

    def test_says_when_someone_else_got_it(self, giver, other_user, aunt, item):
        item.considered_by.add(other_user)
        item.purchased = True
        item.purchased_by = aunt
        item.save()
        page = giver.get('/my-purchases/').content.decode()
        assert 'Someone else got this' in page
        # Not counted as still being considered
        assert '$0.00 spent' in page
        assert '1 considering' not in page

    def test_buying_moves_it_to_bought(self, giver, other_user, item):
        item.considered_by.add(other_user)
        response = giver.post(f'/item/purchase/{item.id}/', {'next': '/my-purchases/'})
        assert response.url == '/my-purchases/'
        page = giver.get('/my-purchases/').content.decode()
        assert page.count('Test Item') == 1
        assert '$29.99 spent' in page

    def test_toggle_reloads_here_so_totals_stay_right(self, giver, other_user, item):
        item.considered_by.add(other_user)
        page = giver.get('/my-purchases/').content.decode()
        assert url(item) in page
        assert 'data-bg-toggle="considering"' not in page

    def test_hidden_once_the_giver_manages_that_own_list(self, giver, other_user, wishlist, item):
        item.considered_by.add(other_user)
        wishlist.managers.add(other_user)
        page = giver.get('/my-purchases/').content.decode()
        assert 'Test Item' not in page

    def test_hidden_over_the_shoulder(self, giver, other_user, item):
        item.considered_by.add(other_user)
        giver.post('/over-the-shoulder/', {'on': '1'})
        page = giver.get('/my-purchases/').content.decode()
        assert 'Test Item' not in page

    def test_deleted_and_archived_items_drop_off(self, giver, other_user, item):
        from django.utils import timezone

        gone = Item.objects.create(wishlist=item.wishlist, name='Gone', is_deleted=True)
        given = Item.objects.create(
            wishlist=item.wishlist, name='Given', archived_at=timezone.now()
        )
        gone.considered_by.add(other_user)
        given.considered_by.add(other_user)
        page = giver.get('/my-purchases/').content.decode()
        assert 'Gone' not in page
        assert 'Given' not in page
