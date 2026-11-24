"""Nothing that changes state happens on a GET (#128, #129).

CSRF protection doesn't cover GETs, and the __session cookie is SameSite=Lax,
which still rides along on a top-level GET. So a link, an <img> tag, a link
prefetcher or a crawler could mark a gift bought — the app's worst failure,
since then nobody buys it — or sign a family member out. Both are POST only,
and the pages reach them through forms carrying a CSRF token.
"""

from html.parser import HTMLParser

import pytest
from django.contrib.auth import SESSION_KEY
from django.test import Client
from django.urls import reverse

from gift.models import Item

pytestmark = pytest.mark.unit

LOGOUT_PATHS = ['/logout/', '/accounts/logout/']


class Controls(HTMLParser):
    """The links and forms on a page, as a browser would see them."""

    def __init__(self, html):
        super().__init__()
        self.links = []
        self.forms = []
        self._form = None
        self._button = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        elif tag == 'form':
            self._form = {
                'action': attrs.get('action', ''),
                'method': (attrs.get('method') or 'get').lower(),
                'fields': {},
                'buttons': [],
            }
            self.forms.append(self._form)
        elif tag == 'input' and self._form is not None and attrs.get('name'):
            self._form['fields'][attrs['name']] = attrs.get('value', '')
        elif tag == 'button' and self._form is not None:
            self._button = {'class': (attrs.get('class') or '').split(), 'text': ''}
            self._form['buttons'].append(self._button)

    def handle_data(self, data):
        if self._button is not None:
            self._button['text'] += data

    def handle_endtag(self, tag):
        if tag == 'form':
            self._form = None
        elif tag == 'button' and self._button is not None:
            self._button['text'] = self._button['text'].strip()
            self._button = None

    def forms_to(self, url):
        return [form for form in self.forms if form['action'] == url]


def strict_client(user):
    """A signed-in client that checks CSRF tokens the way a browser's server would."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    return client


def purchase_url(item):
    return reverse('gift:purchase_item', args=[item.id])


@pytest.fixture
def giver_items(wishlist, other_user):
    """`wishlist` belongs to `user`; `other_user` is a giver on it."""
    return {
        'plain': Item.objects.create(wishlist=wishlist, name='Coffee Grinder'),
        'mine': Item.objects.create(
            wishlist=wishlist, name='Wool Socks', purchased=True, purchased_by=other_user
        ),
        'surprise': Item.objects.create(
            wishlist=wishlist, name='Secret Telescope', is_sneaky=True, added_by=other_user
        ),
    }


# ---------------------------------------------------------------------------
# Marking purchased (#128)
# ---------------------------------------------------------------------------


class TestPurchaseIsPostOnly:
    def test_get_is_refused_and_marks_nothing(self, authenticated_other_user, giver_items):
        plain = giver_items['plain']

        response = authenticated_other_user.get(purchase_url(plain))

        assert response.status_code == 405
        plain.refresh_from_db()
        assert plain.purchased is False
        assert plain.purchased_by is None

    def test_get_does_not_undo_a_purchase(self, authenticated_other_user, other_user, giver_items):
        mine = giver_items['mine']

        response = authenticated_other_user.get(purchase_url(mine))

        assert response.status_code == 405
        mine.refresh_from_db()
        assert mine.purchased is True
        assert mine.purchased_by == other_user

    def test_get_on_a_surprise_is_refused_too(self, authenticated_other_user, giver_items):
        surprise = giver_items['surprise']

        assert authenticated_other_user.get(purchase_url(surprise)).status_code == 405
        surprise.refresh_from_db()
        assert surprise.purchased is False

    def test_post_still_marks_it(self, authenticated_other_user, other_user, giver_items):
        plain = giver_items['plain']

        response = authenticated_other_user.post(purchase_url(plain))

        assert response.status_code == 302
        assert response.url == reverse('gift:wishlist_detail', args=[plain.wishlist_id])
        plain.refresh_from_db()
        assert plain.purchased_by == other_user

    def test_post_without_a_csrf_token_is_refused(self, other_user, giver_items):
        plain = giver_items['plain']

        response = strict_client(other_user).post(purchase_url(plain))

        assert response.status_code == 403
        plain.refresh_from_db()
        assert plain.purchased is False


class TestWishlistPageUsesForms:
    def page(self, client, wishlist):
        response = client.get(reverse('gift:wishlist_detail', args=[wishlist.id]))
        assert response.status_code == 200
        return Controls(response.content.decode())

    def test_no_link_points_at_the_purchase_url(
        self, authenticated_other_user, wishlist, giver_items
    ):
        controls = self.page(authenticated_other_user, wishlist)

        purchase_links = [href for href in controls.links if '/item/purchase/' in href]
        assert purchase_links == []

    def test_every_purchase_button_is_a_post_form_with_a_token(
        self, authenticated_other_user, wishlist, giver_items
    ):
        controls = self.page(authenticated_other_user, wishlist)

        # Mark Purchased, Undo, and the surprise section's button
        for item in giver_items.values():
            forms = controls.forms_to(purchase_url(item))
            assert len(forms) == 1, item.name
            assert forms[0]['method'] == 'post'
            assert forms[0]['fields'].get('csrfmiddlewaretoken')

    def test_the_page_token_lets_the_button_work(self, other_user, wishlist, giver_items):
        """End to end with CSRF checks on, the way a browser submits it."""
        client = strict_client(other_user)
        plain = giver_items['plain']
        form = self.page(client, wishlist).forms_to(purchase_url(plain))[0]

        response = client.post(form['action'], form['fields'])

        assert response.status_code == 302
        plain.refresh_from_db()
        assert plain.purchased_by == other_user

    def test_buttons_keep_their_labels_and_look(
        self, authenticated_other_user, wishlist, giver_items
    ):
        controls = self.page(authenticated_other_user, wishlist)

        def button(item):
            [form] = controls.forms_to(purchase_url(item))
            [only] = form['buttons']
            return only['text'], set(only['class'])

        assert button(giver_items['plain']) == (
            'Mark Purchased',
            {'btn', 'btn-sm', 'btn-outline-primary'},
        )
        assert button(giver_items['mine']) == ('Undo', {'btn', 'btn-sm', 'btn-outline-secondary'})


# ---------------------------------------------------------------------------
# Signing out (#129)
# ---------------------------------------------------------------------------


class TestLogoutIsPostOnly:
    @pytest.mark.parametrize('path', LOGOUT_PATHS)
    def test_get_is_refused_and_the_session_survives(self, authenticated_user, user, path):
        response = authenticated_user.get(path)

        assert response.status_code == 405
        assert '__session' not in response.cookies
        assert authenticated_user.session.get(SESSION_KEY) == str(user.pk)
        assert authenticated_user.get('/profile/').status_code == 200

    @pytest.mark.parametrize('path', LOGOUT_PATHS)
    def test_post_signs_out_and_hands_off_to_firebase(self, authenticated_user, path):
        response = authenticated_user.post(path)

        assert response.status_code == 302
        # auth.html reads ?logout=true and signs out of Firebase in the browser
        assert response.url == '/auth.html?logout=true'
        assert response.cookies['__session'].value == ''
        assert response.cookies['__session']['max-age'] == 0
        assert SESSION_KEY not in authenticated_user.session

    def test_post_without_a_csrf_token_is_refused(self, user):
        client = strict_client(user)

        response = client.post('/logout/')

        assert response.status_code == 403
        assert client.session.get(SESSION_KEY) == str(user.pk)


class TestSignOutControlsAreForms:
    @pytest.mark.parametrize('path', ['/', '/profile/'])
    def test_no_page_links_to_logout(self, authenticated_user, path):
        controls = Controls(authenticated_user.get(path).content.decode())

        assert [href for href in controls.links if 'logout' in href] == []

    @pytest.mark.parametrize(
        'path, expected',
        [
            ('/', 1),  # the phone "More" sheet, on every signed-in page
            ('/profile/', 2),  # ...and the account settings row
        ],
    )
    def test_sign_out_buttons_post_with_a_token(self, authenticated_user, path, expected):
        controls = Controls(authenticated_user.get(path).content.decode())

        forms = controls.forms_to(reverse('gift:logout'))
        assert len(forms) == expected
        for form in forms:
            assert form['method'] == 'post'
            assert form['fields'].get('csrfmiddlewaretoken')

    def test_the_page_token_lets_sign_out_work(self, user):
        client = strict_client(user)
        controls = Controls(client.get('/profile/').content.decode())
        form = controls.forms_to(reverse('gift:logout'))[0]

        response = client.post(form['action'], form['fields'])

        assert response.status_code == 302
        assert response.url == '/auth.html?logout=true'
        assert SESSION_KEY not in client.session

    def test_signed_out_pages_offer_no_sign_out(self, client, db):
        controls = Controls(client.get('/').content.decode())

        assert controls.forms_to(reverse('gift:logout')) == []
