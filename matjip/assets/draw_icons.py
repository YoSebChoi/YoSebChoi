#!/usr/bin/env python3
"""Draws the app icons in matjip/assets (run once; build.py copies them).

The launch screen is the signboard itself: the whole screen is 간판 red (the
manifest background_color) with only the painted lettering 노포 / 지도 in the
middle, as large as Android's launch-screen circle allows. The home-screen
icon is the same red plate.

    python3 matjip/assets/draw_icons.py path/to/BlackHanSans-Regular.ttf
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RED = (196, 35, 27)          # #c4231b, the manifest background_color
RED_DEEP = (122, 16, 12)     # the shadow of painted letters
CREAM = (247, 238, 222)
PEACH = (255, 214, 190)
OUT = Path(__file__).resolve().parent


def centered(d, xy, text, font, fill):
    bb = d.textbbox((0, 0), text, font=font)
    d.text((xy[0] - (bb[2] - bb[0]) / 2 - bb[0], xy[1] - (bb[3] - bb[1]) / 2 - bb[1]), text, font=font, fill=fill)


def draw(font_path, W=1024, k=1.0):
    """Just the lettering, as large as the launch-screen circle allows.

    Android 12+ shows the icon in a fixed-size circle (two thirds of the icon), so
    the two lines 노포 / 지도 are sized to fill that circle edge to edge; the icon
    is flat red so the circle never shows against the red screen."""
    im = Image.new("RGB", (W, W), RED)
    d = ImageDraw.Draw(im)
    c = W / 2
    R = W / 3 * k                      # radius of the visible circle
    lines = ["노포", "지도"]
    gap = 0.28                         # space between the lines, as a share of a line
    # grow the type until the block's corners touch the circle
    size = 50
    while True:
        f = ImageFont.truetype(font_path, size + 4)
        boxes = [d.textbbox((0, 0), t, font=f) for t in lines]
        w = max(b[2] - b[0] for b in boxes)
        h = sum(b[3] - b[1] for b in boxes) * (1 + gap)
        if math.hypot(w / 2, h / 2) > R * 0.94:
            break
        size += 4
    f = ImageFont.truetype(font_path, size)
    boxes = [d.textbbox((0, 0), t, font=f) for t in lines]
    hs = [b[3] - b[1] for b in boxes]
    total = sum(hs) * (1 + gap)
    y = c - total / 2
    shadow = max(2, size // 30)
    for t, b, h in zip(lines, boxes, hs):
        x = c - (b[2] - b[0]) / 2 - b[0]
        d.text((x + shadow, y - b[1] + shadow * 1.3), t, font=f, fill=RED_DEEP)
        d.text((x, y - b[1]), t, font=f, fill=CREAM)
        y += h * (1 + gap)
    return im


def main():
    font = sys.argv[1]
    draw(font).resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    closer = draw(font, k=1.2)   # the plain icon (install dialog, browser tab, older launch screens)
    closer.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    closer.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")


if __name__ == "__main__":
    main()
