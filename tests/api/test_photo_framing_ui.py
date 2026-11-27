"""Framing a photo before it's saved: the page's side of it.

Dragging and zooming happen in the browser (js/photo-framer.js). What the
server relies on is the markup: each photo form posts the four crop_* inputs,
empty until a photo is framed, and the framer script is on the page.
"""

import re

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from gift.models import WikiUser

pytestmark = pytest.mark.api

CROP_FIELDS = ('crop_x', 'crop_y', 'crop_w', 'crop_h')
FRAMER_SCRIPT = re.compile(r'<script src="/static/js/photo-framer\.js\?v=[^"]+"></script>')


def forms_posting_to(html, marker):
    """Every <form>…</form> in `html` whose opening tag contains `marker`."""
    return [
        form
        for form in re.findall(r'<form\b.*?</form>', html, flags=re.S)
        if marker in form.split('>', 1)[0]
    ]


def assert_empty_crop_inputs(form):
    for name in CROP_FIELDS:
        tags = re.findall(rf'<input[^>]*name="{name}"[^>]*>', form)
        assert len(tags) == 1, f'{name}: expected one input, found {len(tags)}'
        assert 'type="hidden"' in tags[0]
        # Empty means "not framed": the server then crops the way it always has
        assert 'value=' not in tags[0]


@pytest.fixture
def kid(db, wishlist):
    """Someone the signed-in user keeps a list for, so they can set their photo."""
    kid = WikiUser.objects.create_user(username='ellie', first_name='Ellie', last_name='Duke')
    wishlist.dependent = kid
    wishlist.save()
    return kid


class TestFramerScript:
    def test_the_script_exists(self):
        assert finders.find('js/photo-framer.js')

    def test_it_never_exports_the_picture_itself(self):
        """The original file is uploaded and the server crops it; a canvas
        export here would re-encode the photo in the browser."""
        source = open(finders.find('js/photo-framer.js'), encoding='utf-8').read()
        for name in CROP_FIELDS:
            assert name in source
        assert 'toBlob' not in source
        assert 'toDataURL' not in source


class TestProfilePhotoPicker:
    def test_the_account_page_has_the_crop_inputs_and_the_framer(self, authenticated_user):
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        (form,) = forms_posting_to(html, f'action="{reverse("gift:profile_picture")}"')
        assert_empty_crop_inputs(form)
        assert 'data-framer' in form
        assert 'Use this photo' in form
        assert FRAMER_SCRIPT.search(html)

    def test_the_framer_starts_hidden_and_no_js_can_still_save(self, authenticated_user):
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        (form,) = forms_posting_to(html, f'action="{reverse("gift:profile_picture")}"')
        framer = re.search(r'<div[^>]*data-framer\b[^>]*>', form).group(0)
        assert ' hidden' in framer
        assert re.search(r'<noscript>\s*<button type="submit"', form)

    def test_cancel_does_not_submit(self, authenticated_user):
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        cancel = re.search(r'<button[^>]*data-framer-cancel[^>]*>', html).group(0)
        assert 'type="button"' in cancel

    def test_a_kids_picker_gets_its_own_inputs(self, authenticated_user, kid):
        """The picker is on the page twice here; each form carries its own
        crop inputs, so framing one photo can't leak into the other."""
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        action = reverse('gift:managed_user_picture', args=[kid.id])
        (form,) = forms_posting_to(html, f'action="{action}"')
        assert_empty_crop_inputs(form)
        assert 'data-framer' in form


class TestCoverPhoto:
    def test_decorate_has_the_crop_inputs_and_the_framer(self, authenticated_user, wishlist):
        url = reverse('gift:decorate_wishlist', args=[wishlist.id])
        html = authenticated_user.get(url).content.decode()

        (form,) = forms_posting_to(html, 'data-decorate')
        assert_empty_crop_inputs(form)
        assert 'data-framer-aspect="3"' in form
        assert 'Drag to move it, slide to zoom.' in form
        assert 'shaded edges' in form
        assert FRAMER_SCRIPT.search(html)

    def test_narrow_screens_show_the_whole_framed_cover(self):
        """The cover is the framer's 3:1. Its height cap must stay high enough
        that a phone or tablet (up to ~800px wide) shows the whole frame; only
        a full-width desktop page trims it, to about the My Lists card's 4:1."""
        css = open(finders.find('css/custom.css'), encoding='utf-8').read()
        rule = re.search(r'^\.wl-cover \{(.*?)\}', css, flags=re.S | re.M).group(1)
        assert 'aspect-ratio: 3 / 1' in rule
        cap = re.search(r'max-height: (\d+)px', rule)
        assert cap is None or int(cap.group(1)) >= 265
