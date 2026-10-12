"""The logo and app icons stay in step with their one definition.

scripts/build_icons.py declares the mark once and renders every file from it.
These tests fail when someone edits the logo (or an icon) by hand, or changes
the definition without re-running `make icons` — either way the installed app
would show something other than the logo.
"""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.build_icons import ICONS, OUT_DIR, build_svg

pytestmark = pytest.mark.unit

STAMP = OUT_DIR / 'icons.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_logo_matches_its_definition():
    assert (OUT_DIR / 'logo.svg').read_text() == build_svg(), (
        'gift/static/brand/logo.svg differs from scripts/build_icons.py — run `make icons`'
    )


def test_icons_were_rendered_from_the_current_logo():
    stamp = json.loads(STAMP.read_text())
    assert stamp['source_sha256'] == sha(OUT_DIR / 'logo.svg'), (
        'The logo changed since the icons were rendered — run `make icons`'
    )


@pytest.mark.parametrize('name', sorted(ICONS))
def test_each_icon_is_the_one_that_was_rendered(name):
    stamp = json.loads(STAMP.read_text())
    assert stamp['files'][name] == sha(OUT_DIR / name)[:12], (
        f'{name} was changed by hand — run `make icons` to regenerate it'
    )


@pytest.mark.parametrize('name', sorted(ICONS))
def test_each_icon_has_its_declared_size(name):
    size, _radius, _scale, opaque = ICONS[name]
    with Image.open(OUT_DIR / name) as image:
        assert image.size == (size, size)
        # Maskable and Apple icons are full-bleed: any transparency would show
        # up as black or white corners once the OS applies its mask.
        if opaque:
            assert image.mode == 'RGB'
