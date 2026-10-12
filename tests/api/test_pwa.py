"""Progressive Web App plumbing: manifest, service worker, offline page, share target.

The manifest and worker are fetched by browsers on their own schedule, so the
tests also pin down that they stay public and never query the database — a
background fetch that woke the Neon compute would quietly burn the free-tier
allowance (see CLAUDE.md).
"""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.staticfiles import finders

pytestmark = pytest.mark.unit


def manifest(client):
    response = client.get('/manifest.webmanifest')
    assert response.status_code == 200
    return json.loads(response.content)


class TestManifest:
    def test_served_as_a_manifest(self, client):
        response = client.get('/manifest.webmanifest')

        assert response['Content-Type'] == 'application/manifest+json'
        assert response['Cache-Control'] == 'no-cache'

    def test_installable_basics(self, client):
        data = manifest(client)

        assert data['name'] == 'Wikileet'
        assert data['display'] == 'standalone'
        assert data['start_url'].startswith('/')
        assert data['scope'] == '/'
        assert data['theme_color'] == '#2d6a4f'

    def test_has_regular_and_maskable_icons_at_both_required_sizes(self, client):
        icons = manifest(client)['icons']

        for purpose in ('any', 'maskable'):
            sizes = {icon['sizes'] for icon in icons if icon['purpose'] == purpose}
            assert sizes == {'192x192', '512x512'}

    def test_every_icon_exists_and_is_versioned_by_content(self, client):
        """The ?v= hash is what makes an installed app pick up a new logo:
        static URLs aren't fingerprinted here, so without it the browser would
        keep the old icon."""
        data = manifest(client)
        sources = [icon['src'] for icon in data['icons']]
        sources += [
            icon['src'] for shortcut in data['shortcuts'] for icon in shortcut.get('icons', [])
        ]

        for src in sources:
            url = urlparse(src)
            assert parse_qs(url.query).get('v'), f'{src} has no content version'
            assert finders.find(url.path.removeprefix('/static/')), f'{src} does not exist'

    def test_quick_add_shortcut_opens_quick_add(self, client):
        shortcuts = manifest(client)['shortcuts']

        assert '?quick_add=1' in shortcuts[0]['url']

    def test_share_target_points_at_the_share_view(self, client):
        share = manifest(client)['share_target']

        assert share['action'] == '/share/'
        assert share['method'] == 'GET'
        assert set(share['params']) == {'title', 'text', 'url'}


class TestServiceWorker:
    def test_served_as_javascript_from_the_root(self, client):
        response = client.get('/sw.js')

        assert response.status_code == 200
        assert response['Content-Type'].startswith('application/javascript')
        # An HTTP-cached worker would never update
        assert response['Cache-Control'] == 'no-cache'

    def test_is_configured_before_its_logic_runs(self, client):
        body = client.get('/sw.js').content.decode()

        assert body.index('var SW_VERSION') < body.index("addEventListener('install'")
        assert 'var OFFLINE_URL = "/offline/"' in body
        assert '/static/brand/logo.svg?v=' in body

    def test_never_caches_pages(self, client):
        """Pages show what other people have bought; serving a stale copy could
        lead to a double-bought gift. Navigations go to the network, and only
        fall back to the offline page."""
        body = client.get('/sw.js').content.decode()

        assert "request.mode === 'navigate'" in body
        assert 'caches.match(OFFLINE_URL)' in body


class TestOfflinePage:
    def test_public_and_standalone(self, client):
        response = client.get('/offline/')

        assert response.status_code == 200
        content = response.content.decode()
        assert "You're offline" in content
        # Cached once for everyone, so it must not carry the signed-in nav
        assert 'wl-nav' not in content

    def test_same_for_a_signed_in_user(self, authenticated_user):
        content = authenticated_user.get('/offline/').content.decode()

        assert 'wl-nav' not in content
        assert 'testuser' not in content


class TestNoDatabase:
    @pytest.mark.parametrize('path', ['/manifest.webmanifest', '/sw.js', '/offline/'])
    def test_anonymous_fetch_runs_no_queries(self, client, db, django_assert_num_queries, path):
        with django_assert_num_queries(0):
            assert client.get(path).status_code == 200

    @pytest.mark.parametrize('path', ['/manifest.webmanifest', '/sw.js', '/offline/'])
    def test_signed_in_fetch_runs_no_queries(
        self, authenticated_user, django_assert_num_queries, path
    ):
        """Browsers send the session cookie along; it must not be resolved."""
        with django_assert_num_queries(0):
            assert authenticated_user.get(path).status_code == 200


class TestShareTarget:
    def share(self, client, **params):
        response = client.get('/share/', params)
        assert response.status_code == 302
        url = urlparse(response['Location'])
        assert url.path == '/'
        return {key: values[0] for key, values in parse_qs(url.query).items()}

    def test_opens_quick_add_with_title_and_url(self, authenticated_user):
        params = self.share(
            authenticated_user, title='Lego Titanic', url='https://example.com/titanic'
        )

        assert params == {
            'quick_add': '1',
            'name': 'Lego Titanic',
            'url': 'https://example.com/titanic',
        }

    def test_finds_a_link_buried_in_the_text(self, authenticated_user):
        """Plenty of shopping apps send no url, just a pitch with a link in it."""
        params = self.share(
            authenticated_user,
            text='Check out Lego Titanic on Example! https://example.com/t/123',
        )

        assert params['url'] == 'https://example.com/t/123'
        assert params['name'] == 'Check out Lego Titanic on Example!'

    def test_prefers_the_title_for_the_name(self, authenticated_user):
        params = self.share(
            authenticated_user,
            title='Lego Titanic',
            text='Look at this https://example.com/t/123',
        )

        assert params['name'] == 'Lego Titanic'
        assert params['url'] == 'https://example.com/t/123'

    def test_works_with_nothing_shared(self, authenticated_user):
        assert self.share(authenticated_user) == {'quick_add': '1'}

    def test_caps_the_name_at_the_field_length(self, authenticated_user):
        params = self.share(authenticated_user, title='x' * 400)

        assert len(params['name']) == 255

    def test_signed_out_users_sign_in_first_and_come_back(self, client):
        response = client.get('/share/', {'title': 'Lego'})

        assert response.status_code == 302
        assert response['Location'].startswith('/auth.html?next=')


class TestBaseTemplate:
    def test_links_the_manifest_and_icons(self, authenticated_user):
        content = authenticated_user.get('/').content.decode()

        assert '<link rel="manifest" href="/manifest.webmanifest">' in content
        assert '<meta name="theme-color" content="#2d6a4f">' in content
        assert 'rel="apple-touch-icon" href="/static/brand/apple-touch-icon.png?v=' in content
        assert 'name="apple-mobile-web-app-capable" content="yes"' in content

    def test_signed_out_pages_are_installable_too(self, client):
        content = client.get('/').content.decode()

        assert '<link rel="manifest"' in content

    def test_registers_the_service_worker(self, client):
        content = client.get('/').content.decode()

        assert 'data-sw-url="/sw.js"' in content

    def test_tab_bar_only_for_signed_in_users(self, client, authenticated_user):
        assert 'class="wl-tabbar"' in authenticated_user.get('/').content.decode()
        assert 'class="wl-tabbar"' not in client.get('/').content.decode()

    def test_tab_bar_reaches_pages_the_mobile_nav_used_to_hide(self, authenticated_user):
        """Phones hide the top nav's links; the tab bar and More sheet are the
        only way to Purchases, Received and What's new there."""
        content = authenticated_user.get('/').content.decode()
        tabbar = content[content.index('class="wl-tabbar"') : content.index('id="wl-toasts"')]

        for path in ('/my-purchases/', '/received-gifts/', '/changelog/', '/profile/'):
            assert f'href="{path}"' in tabbar

    def test_install_banner_only_on_home(self, authenticated_user, wishlist):
        assert 'id="wl-install-banner"' in authenticated_user.get('/').content.decode()
        detail = authenticated_user.get(f'/wishlist/{wishlist.id}/').content.decode()
        assert 'id="wl-install-banner"' not in detail
