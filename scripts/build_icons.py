"""Build Wikileet's logo and every app icon from one definition.

The mark is declared once below as a list of simple shapes, and this script
writes both the vector logo (used in the nav and as the favicon) and the PNG
icons the PWA manifest and iOS need. Nothing is hand-drawn per size, so the
icons can't drift from the logo.

    make icons

It also writes `icons.json`, which records the hash of the SVG the PNGs were
rendered from. tests/test_brand_icons.py fails if the logo changes without the
icons being rebuilt, and the hashes double as cache-busting versions for the
manifest, so an installed app picks up a new icon when the logo changes.

No system dependencies: Pillow draws each shape at 4x and downsamples, which
gives clean anti-aliased edges without needing cairo or librsvg.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / 'gift' / 'static' / 'brand'
CANVAS = 512
SUPERSAMPLE = 4

BRAND = '#2d6a4f'

# The mark, on a 512x512 canvas. Painted in order, so later shapes sit on top.
#   ('rect', x0, y0, x1, y1, corner_radius, fill)
#   ('ellipse', cx, cy, rx, ry, rotation_degrees, fill)
#   ('star', cx, cy, outer_radius, inner_radius, fill)
MARK = [
    # Bow loops, behind the lid so they look tied on
    ('ellipse', 206, 170, 58, 30, 28, '#e9b44c'),
    ('ellipse', 306, 170, 58, 30, -28, '#e9b44c'),
    ('ellipse', 214, 174, 26, 11, 28, '#c98f2a'),
    ('ellipse', 298, 174, 26, 11, -28, '#c98f2a'),
    # Box body, the shadow the lid casts, then the lid
    ('rect', 140, 238, 372, 404, 16, '#f7f4ef'),
    ('rect', 140, 238, 372, 262, 0, '#e4ddd4'),
    ('rect', 120, 196, 392, 250, 14, '#ffffff'),
    # Ribbon down the front, and the knot
    ('rect', 236, 196, 276, 404, 0, '#e9b44c'),
    ('ellipse', 256, 192, 24, 20, 0, '#c98f2a'),
    # A little sparkle
    ('star', 398, 122, 30, 9, '#d8f3dc'),
    ('star', 112, 146, 16, 5, '#d8f3dc'),
]


def ellipse_points(cx, cy, rx, ry, rotation, steps=180):
    theta = math.radians(rotation)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    points = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        x, y = rx * math.cos(a), ry * math.sin(a)
        points.append((cx + x * cos_t - y * sin_t, cy + x * sin_t + y * cos_t))
    return points


def star_points(cx, cy, outer, inner):
    points = []
    for i in range(8):
        r = outer if i % 2 == 0 else inner
        a = math.pi / 4 * i - math.pi / 2
        points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return points


def fmt(n):
    return f'{n:.2f}'.rstrip('0').rstrip('.')


def mark_svg_elements(scale=1.0):
    """SVG elements for the mark, scaled about the canvas centre."""
    c = CANVAS / 2
    elements = []
    for shape in MARK:
        kind = shape[0]
        if kind == 'rect':
            _, x0, y0, x1, y1, r, fill = shape
            radius = f' rx="{fmt(r)}"' if r else ''
            elements.append(
                f'<rect x="{fmt(x0)}" y="{fmt(y0)}" width="{fmt(x1 - x0)}" '
                f'height="{fmt(y1 - y0)}"{radius} fill="{fill}"/>'
            )
        elif kind == 'ellipse':
            _, cx, cy, rx, ry, rot, fill = shape
            transform = f' transform="rotate({fmt(rot)} {fmt(cx)} {fmt(cy)})"' if rot else ''
            elements.append(
                f'<ellipse cx="{fmt(cx)}" cy="{fmt(cy)}" rx="{fmt(rx)}" ry="{fmt(ry)}"'
                f'{transform} fill="{fill}"/>'
            )
        elif kind == 'star':
            _, cx, cy, outer, inner, fill = shape
            points = ' '.join(f'{fmt(x)},{fmt(y)}' for x, y in star_points(cx, cy, outer, inner))
            elements.append(f'<polygon points="{points}" fill="{fill}"/>')
    body = '\n    '.join(elements)
    if scale == 1.0:
        return f'<g>\n    {body}\n  </g>'
    offset = c * (1 - scale)
    return f'<g transform="translate({fmt(offset)} {fmt(offset)}) scale({fmt(scale)})">\n    {body}\n  </g>'


def build_svg():
    """The logo: the mark on a rounded brand-green tile."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        'role="img" aria-label="Wikileet">\n'
        f'  <rect width="512" height="512" rx="112" fill="{BRAND}"/>\n'
        f'  {mark_svg_elements()}\n'
        '</svg>\n'
    )


def render_png(size, *, corner_radius, scale, sparkles=True):
    """Rasterise the mark at `size` px.

    corner_radius is in canvas units (0 for a full-bleed square, which is what
    maskable and Apple icons want — the OS applies its own mask). scale shrinks
    the mark about the centre to keep it inside a maskable icon's safe zone.
    The sparkles are dropped at favicon sizes, where they'd only be specks.
    """
    px = CANVAS * SUPERSAMPLE
    k = SUPERSAMPLE
    c = CANVAS / 2

    def tx(x, y):
        return ((c + (x - c) * scale) * k, (c + (y - c) * scale) * k)

    image = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if corner_radius:
        draw.rounded_rectangle((0, 0, px - 1, px - 1), radius=corner_radius * k, fill=BRAND)
    else:
        draw.rectangle((0, 0, px, px), fill=BRAND)

    for shape in MARK:
        kind = shape[0]
        if kind == 'rect':
            _, x0, y0, x1, y1, r, fill = shape
            (ax, ay), (bx, by) = tx(x0, y0), tx(x1, y1)
            if r:
                draw.rounded_rectangle((ax, ay, bx, by), radius=r * scale * k, fill=fill)
            else:
                draw.rectangle((ax, ay, bx, by), fill=fill)
        elif kind == 'ellipse':
            _, cx, cy, rx, ry, rot, fill = shape
            draw.polygon([tx(x, y) for x, y in ellipse_points(cx, cy, rx, ry, rot)], fill=fill)
        elif kind == 'star' and sparkles:
            _, cx, cy, outer, inner, fill = shape
            draw.polygon([tx(x, y) for x, y in star_points(cx, cy, outer, inner)], fill=fill)

    return image.resize((size, size), Image.Resampling.LANCZOS)


# filename -> (pixel size, corner radius in canvas units, mark scale, opaque)
ICONS = {
    'icon-192.png': (192, 112, 1.0, False),
    'icon-512.png': (512, 112, 1.0, False),
    # Maskable: full bleed, mark kept inside the 80% safe-zone circle
    'icon-maskable-512.png': (512, 0, 0.78, True),
    'icon-maskable-192.png': (192, 0, 0.78, True),
    # iOS ignores transparency and rounds the corners itself
    'apple-touch-icon.png': (180, 0, 0.86, True),
    'favicon-32.png': (32, 112, 1.0, False),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    (OUT_DIR / 'logo.svg').write_text(svg)

    stamp = {'source_sha256': sha(svg.encode()), 'files': {}}
    stamp['files']['logo.svg'] = sha(svg.encode())[:12]
    for name, (size, radius, scale, opaque) in ICONS.items():
        image = render_png(size, corner_radius=radius, scale=scale, sparkles=size > 48)
        if opaque:
            image = image.convert('RGB')
        path = OUT_DIR / name
        image.save(path, optimize=True)
        stamp['files'][name] = sha(path.read_bytes())[:12]

    (OUT_DIR / 'icons.json').write_text(json.dumps(stamp, indent=2, sort_keys=True) + '\n')
    print(f'Wrote logo.svg and {len(ICONS)} icons to {OUT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
