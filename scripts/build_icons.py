"""Build Wikileet's logo and every app icon from one definition.

The mark is Cassiopeia, the W-shaped constellation: four stars and a wishing
star, joined by faint lines into a W. It's declared once below as simple
shapes, and this script writes both the vector logos and the PNG icons the PWA
manifest and iOS need. Nothing is hand-drawn per size, so the icons can't
drift from the logo.

    make icons

There are two drawings of the same constellation. Fine lines and small stars
look right on a home screen and vanish at favicon size, so tiny renderings use
a bolder cut, the way type is redrawn for small sizes:

    logo.svg        full detail, for anything shown large
    logo-small.svg  bold cut, for the browser tab
    logo_mark.html  the bold cut as an inline SVG template for the nav, with
                    its stars and lines coloured by CSS variables so they
                    follow the user's colour theme (gift/themes.py)

It also writes `icons.json`, which records the hashes of the SVGs the PNGs were
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
INLINE_MARK = (
    Path(__file__).resolve().parent.parent
    / 'gift'
    / 'templates'
    / 'gift'
    / 'partials'
    / 'logo_mark.html'
)
CANVAS = 512
SUPERSAMPLE = 4

CREAM = '#f7f4ef'  # --bg-page
GREEN = '#2d6a4f'  # --brand
SAGE = '#8fb6a1'  # the constellation lines: present, but quieter than the stars
EMBER = '#c4631e'  # the wishing star

TILE = CREAM  # the background the mark sits on

# Cassiopeia's five stars, left to right, centred on the canvas. The last is
# the one you wish on.
STARS = [(90, 214), (168, 348), (236, 262), (310, 356), (382, 200)]

# Shapes on a 512x512 canvas, painted in order (later shapes sit on top):
#   ('rect', x0, y0, x1, y1, corner_radius, fill)
#   ('ellipse', cx, cy, rx, ry, rotation_degrees, fill)
#   ('poly', [(x, y), ...], fill)
#   ('stroke', [(x, y), ...], width, colour)  -- round caps and joins
#   ('star', cx, cy, outer_radius, inner_radius, fill)  -- four points


def constellation(line_width, radii, sparkle, spread):
    """The mark at one weight. `spread` pushes the stars apart from the centre,
    so a bolder cut doesn't clump."""
    c = CANVAS / 2
    stars = [(c + (x - c) * spread, c + (y - c) * spread) for x, y in STARS]
    shapes = [('stroke', stars, line_width, SAGE)]
    # Every star but the last is a dot; the last is the sparkle
    for (x, y), r in zip(stars[:-1], radii, strict=True):
        shapes.append(('ellipse', x, y, r, r, 0, GREEN))
    wx, wy = stars[-1]
    shapes.append(('star', wx, wy, sparkle[0], sparkle[1], EMBER))
    return shapes


MARKS = {
    'full': constellation(line_width=14, radii=(24, 19, 28, 21), sparkle=(66, 17), spread=1.15),
    'small': constellation(line_width=36, radii=(46, 40, 50, 42), sparkle=(104, 34), spread=1.14),
}


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


def svg_points(points):
    return ' '.join(f'{fmt(x)},{fmt(y)}' for x, y in points)


def mark_svg_elements(mark):
    elements = []
    for shape in mark:
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
            if rx == ry and not rot:
                elements.append(
                    f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(rx)}" fill="{fill}"/>'
                )
            else:
                transform = f' transform="rotate({fmt(rot)} {fmt(cx)} {fmt(cy)})"' if rot else ''
                elements.append(
                    f'<ellipse cx="{fmt(cx)}" cy="{fmt(cy)}" rx="{fmt(rx)}" ry="{fmt(ry)}"'
                    f'{transform} fill="{fill}"/>'
                )
        elif kind == 'star':
            _, cx, cy, outer, inner, fill = shape
            elements.append(
                f'<polygon points="{svg_points(star_points(cx, cy, outer, inner))}" fill="{fill}"/>'
            )
        elif kind == 'poly':
            _, points, fill = shape
            elements.append(f'<polygon points="{svg_points(points)}" fill="{fill}"/>')
        elif kind == 'stroke':
            _, points, width, colour = shape
            elements.append(
                f'<polyline points="{svg_points(points)}" fill="none" stroke="{colour}" '
                f'stroke-width="{fmt(width)}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    return '\n    '.join(elements)


def build_svg(variant='full'):
    """A logo: one cut of the mark on a rounded tile."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        'role="img" aria-label="Wikileet">\n'
        f'  <rect width="512" height="512" rx="112" fill="{TILE}"/>\n'
        f'  <g>\n    {mark_svg_elements(MARKS[variant])}\n  </g>\n'
        '</svg>\n'
    )


def build_inline_mark():
    """The bold cut as a nav-sized inline SVG whose colours come from the theme.

    Presentation attributes can't take var(), so the themed colours move into
    style attributes. The ember star and the cream tile stay fixed: they're
    what makes the mark recognisable in every theme.
    """
    svg = build_svg('small')
    svg = svg.replace(f'fill="{GREEN}"', 'style="fill: var(--brand)"')
    svg = svg.replace(f'stroke="{SAGE}"', 'style="stroke: var(--brand-line)"')
    svg = svg.replace(
        'role="img" aria-label="Wikileet"',
        'class="wl-logo-mark" width="30" height="30" aria-hidden="true" focusable="false"',
    )
    header = (
        '{% comment %}Generated by scripts/build_icons.py (make icons) — do not edit. '
        'The nav logo, inline so its stars follow the colour theme.{% endcomment %}\n'
    )
    return header + svg


def render_png(size, *, variant, corner_radius, scale):
    """Rasterise one cut of the mark at `size` px.

    corner_radius is in canvas units (0 for a full-bleed square, which is what
    maskable and Apple icons want — the OS applies its own mask). scale shrinks
    the mark about the centre to keep it inside a maskable icon's safe zone.
    """
    px = CANVAS * SUPERSAMPLE
    k = SUPERSAMPLE
    c = CANVAS / 2

    def tx(x, y):
        return ((c + (x - c) * scale) * k, (c + (y - c) * scale) * k)

    image = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if corner_radius:
        draw.rounded_rectangle((0, 0, px - 1, px - 1), radius=corner_radius * k, fill=TILE)
    else:
        draw.rectangle((0, 0, px, px), fill=TILE)

    for shape in MARKS[variant]:
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
        elif kind == 'star':
            _, cx, cy, outer, inner, fill = shape
            draw.polygon([tx(x, y) for x, y in star_points(cx, cy, outer, inner)], fill=fill)
        elif kind == 'poly':
            _, points, fill = shape
            draw.polygon([tx(x, y) for x, y in points], fill=fill)
        elif kind == 'stroke':
            _, points, width, colour = shape
            w = width * scale * k
            scaled = [tx(x, y) for x, y in points]
            draw.line(scaled, fill=colour, width=round(w), joint='curve')
            for x, y in (scaled[0], scaled[-1]):  # round caps
                draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=colour)

    return image.resize((size, size), Image.Resampling.LANCZOS)


# The vector logos, by filename
LOGOS = {'logo.svg': 'full', 'logo-small.svg': 'small'}

# filename -> (pixel size, cut, corner radius in canvas units, mark scale, opaque)
ICONS = {
    'icon-192.png': (192, 'full', 112, 1.0, False),
    'icon-512.png': (512, 'full', 112, 1.0, False),
    # Maskable: full bleed, mark kept inside the 80% safe-zone circle
    'icon-maskable-512.png': (512, 'full', 0, 0.78, True),
    'icon-maskable-192.png': (192, 'full', 0, 0.78, True),
    # iOS ignores transparency and rounds the corners itself
    'apple-touch-icon.png': (180, 'full', 0, 0.86, True),
    'favicon-32.png': (32, 'small', 112, 1.0, False),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_hash():
    """One hash over every logo the PNGs are rendered from."""
    return sha(''.join(build_svg(variant) for variant in LOGOS.values()).encode())


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = {'source_sha256': source_hash(), 'files': {}}

    for name, variant in LOGOS.items():
        svg = build_svg(variant)
        (OUT_DIR / name).write_text(svg)
        stamp['files'][name] = sha(svg.encode())[:12]

    for name, (size, variant, radius, scale, opaque) in ICONS.items():
        image = render_png(size, variant=variant, corner_radius=radius, scale=scale)
        if opaque:
            image = image.convert('RGB')
        path = OUT_DIR / name
        image.save(path, optimize=True)
        stamp['files'][name] = sha(path.read_bytes())[:12]

    INLINE_MARK.write_text(build_inline_mark())
    (OUT_DIR / 'icons.json').write_text(json.dumps(stamp, indent=2, sort_keys=True) + '\n')
    print(f'Wrote {len(LOGOS)} logos and {len(ICONS)} icons to {OUT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
