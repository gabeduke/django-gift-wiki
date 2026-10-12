"""Colour themes: each person picks a brand colour; the app (logo included)
follows. gift/themes.py is the list; custom.css derives every shade from it."""

import re
from pathlib import Path

import pytest

from gift.themes import DEFAULT_THEME, THEMES

pytestmark = pytest.mark.unit

CSS = Path(__file__).resolve().parents[2] / 'gift' / 'static' / 'css' / 'custom.css'


def contrast(a, b):
    def luminance(hex_colour):
        channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class TestThemeDefinitions:
    def test_css_defines_exactly_the_themes_in_python(self):
        defined = dict(
            re.findall(r'\[data-theme="(\w+)"\]\s*\{\s*--brand:\s*(#[0-9a-f]{6});', CSS.read_text())
        )
        expected = {key: colour for key, (_label, colour) in THEMES.items() if key != DEFAULT_THEME}

        assert defined == expected

    def test_default_theme_is_the_root_brand(self):
        root = re.search(r'--brand:\s*(#[0-9a-f]{6});', CSS.read_text()).group(1)

        assert root == THEMES[DEFAULT_THEME][1]

    @pytest.mark.parametrize('key', sorted(THEMES))
    def test_white_text_is_readable_on_every_theme(self, key):
        assert contrast(THEMES[key][1], '#ffffff') >= 4.5

    @pytest.mark.parametrize('key', sorted(THEMES))
    def test_theme_colour_is_readable_on_the_page(self, key):
        assert contrast(THEMES[key][1], '#f7f4ef') >= 4.5


class TestPickingATheme:
    def test_saves_the_choice(self, authenticated_user, user):
        response = authenticated_user.post('/profile/theme/', {'theme': 'plum'})

        assert response.status_code == 302
        user.refresh_from_db()
        assert user.color_palette == 'plum'

    def test_background_save_answers_with_json(self, authenticated_user, user):
        response = authenticated_user.post(
            '/profile/theme/', {'theme': 'lake'}, headers={'X-Requested-With': 'XMLHttpRequest'}
        )

        assert response.json() == {'status': 'ok', 'theme': 'lake', 'colour': THEMES['lake'][1]}

    def test_rejects_an_unknown_theme(self, authenticated_user, user):
        response = authenticated_user.post(
            '/profile/theme/', {'theme': 'sunset'}, headers={'X-Requested-With': 'XMLHttpRequest'}
        )

        assert response.status_code == 400
        user.refresh_from_db()
        assert user.color_palette == DEFAULT_THEME

    def test_post_only(self, authenticated_user):
        assert authenticated_user.get('/profile/theme/').status_code == 405

    def test_requires_sign_in(self, client, db):
        assert client.post('/profile/theme/', {'theme': 'plum'}).status_code == 302

    def test_my_lists_offers_every_theme_with_yours_selected(self, authenticated_user, user):
        user.color_palette = 'slate'
        user.save()

        content = authenticated_user.get('/profile/').content.decode()

        for key in THEMES:
            assert f'name="theme" value="{key}"' in content
        assert 'value="slate" data-colour="#434c5c" checked' in content


class TestPagesWearTheTheme:
    def test_themed_user_gets_data_theme_and_status_bar_colour(self, authenticated_user, user):
        user.color_palette = 'cranberry'
        user.save()

        content = authenticated_user.get('/').content.decode()

        assert '<html lang="en" data-theme="cranberry">' in content
        assert '<meta name="theme-color" content="#9a2c3e">' in content

    def test_default_theme_adds_nothing(self, authenticated_user):
        content = authenticated_user.get('/').content.decode()

        assert '<html lang="en">' in content
        assert f'<meta name="theme-color" content="{THEMES[DEFAULT_THEME][1]}">' in content

    def test_signed_out_pages_use_the_default(self, client, db):
        assert '<html lang="en">' in client.get('/').content.decode()

    def test_nav_logo_is_inline_so_it_can_follow_the_theme(self, authenticated_user):
        content = authenticated_user.get('/').content.decode()

        assert 'class="wl-logo-mark"' in content
        assert 'style="fill: var(--brand)"' in content

    def test_a_stale_saved_value_falls_back_to_the_default(self, authenticated_user, user):
        """Values from the old switcher (or anything unknown) must not break pages."""
        type(user).objects.filter(pk=user.pk).update(color_palette='sunset')

        content = authenticated_user.get('/').content.decode()

        assert '<html lang="en">' in content
