#!/usr/bin/env python3
"""Generate the PWA icons in frontend/icons/.

The icons are committed, so this only needs running when the mark or the brand
colour changes:

    python scripts/make-icons.py

Everything is drawn at 4x and downsampled, which is cheaper than hand-tuning
antialiasing and keeps the barbell's edges clean at 192px.
"""

import os

from PIL import Image, ImageDraw

ACCENT = '#5b5ce2'  # --accent from frontend/styles.css
GLYPH = '#ffffff'
SS = 4  # supersampling factor

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend', 'icons')


def barbell(size, scale=1.0, radius_ratio=None):
    """A barbell mark on an accent square.

    `scale` shrinks the glyph so a maskable icon keeps it inside the safe zone.
    `radius_ratio` rounds the corners; None leaves the square full-bleed, which is
    what Apple and maskable icons want.
    """
    px = size * SS
    image = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if radius_ratio is None:
        draw.rectangle([0, 0, px - 1, px - 1], fill=ACCENT)
    else:
        draw.rounded_rectangle([0, 0, px - 1, px - 1], radius=px * radius_ratio, fill=ACCENT)

    mid = px / 2

    def bar(half_width, half_height, corner):
        draw.rounded_rectangle(
            [mid - half_width * px * scale, mid - half_height * px * scale,
             mid + half_width * px * scale, mid + half_height * px * scale],
            radius=corner * px * scale, fill=GLYPH)

    def plate(offset, half_height, half_width=0.035, corner=0.022):
        left = mid + offset * px * scale
        draw.rounded_rectangle(
            [left - half_width * px * scale, mid - half_height * px * scale,
             left + half_width * px * scale, mid + half_height * px * scale],
            radius=corner * px * scale, fill=GLYPH)

    bar(0.30, 0.042, 0.030)      # the bar itself
    for side in (-1, 1):
        plate(side * 0.205, 0.175)  # inner plates
        plate(side * 0.310, 0.110)  # outer plates

    return image.resize((size, size), Image.LANCZOS)


def flatten(image):
    """Drop the alpha channel; iOS composites transparent icons onto black."""
    opaque = Image.new('RGB', image.size, ACCENT)
    opaque.paste(image, mask=image.split()[3])
    return opaque


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []

    for size in (192, 512):
        path = os.path.join(OUT_DIR, f'icon-{size}.png')
        barbell(size, radius_ratio=0.22).save(path)
        written.append(path)

    # Maskable: full bleed, glyph shrunk to stay inside the inner 80% safe zone.
    path = os.path.join(OUT_DIR, 'icon-maskable-512.png')
    barbell(512, scale=0.78).save(path)
    written.append(path)

    path = os.path.join(OUT_DIR, 'apple-touch-icon.png')
    flatten(barbell(180)).save(path)
    written.append(path)

    for path in written:
        print('%8d bytes  %s' % (os.path.getsize(path), os.path.relpath(path)))


if __name__ == '__main__':
    main()
