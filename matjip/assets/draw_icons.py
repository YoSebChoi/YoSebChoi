#!/usr/bin/env python3
"""Draws the app icons in matjip/assets (run once; build.py copies them).

The launch screen is the signboard itself: the whole screen is 간판 red (the
manifest background_color) and the icon carries the painted lettering, the trim
lines and a round 원조 stamp. Android 12+ shows only the central circle of the
icon (about two thirds of it) on the launch screen, so everything sits inside
that circle; the home-screen icon is the same red plate.

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
    """k scales the artwork around the centre (1.0 keeps it inside the launch-screen circle)."""
    im = Image.new("RGB", (W, W), RED)
    c = W / 2
    s = lambda v: v * W / 1024 * k
    f = lambda px: ImageFont.truetype(font_path, int(px))
    # flat red: the icon must melt into the launch screen's red with no visible edge
    d = ImageDraw.Draw(im)
    # trim lines above and below the lettering, kept inside the circle
    for y, w in ((c - s(170), s(6)), (c - s(150), s(2.5)), (c + s(150), s(2.5)), (c + s(170), s(6))):
        half = math.sqrt(max(0, (s(318)) ** 2 - (y - c) ** 2)) - s(26)
        d.line([(c - half, y), (c + half, y)], fill=CREAM, width=max(1, int(w)))
    # painted 노포 with its shadow
    big = f(s(262))
    centered(d, (c + s(7), c - s(6) + s(9)), "노포", big, RED_DEEP)
    centered(d, (c, c - s(6)), "노포", big, CREAM)
    # small line under the trim, like the second line of a 간판
    centered(d, (c, c + s(222)), "오래된 맛집", f(s(46)), PEACH)
    # round 원조 stamp on the upper right, slightly rotated
    r = s(150)
    stamp = Image.new("RGBA", (int(r), int(r)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.ellipse([s(6), s(6), r - s(6), r - s(6)], fill=CREAM + (255,))
    sd.ellipse([s(18), s(18), r - s(18), r - s(18)], outline=RED + (255,), width=int(s(5)))
    centered(sd, (r / 2, r / 2), "원조", f(s(48)), RED)
    stamp = stamp.rotate(14, resample=Image.BICUBIC)
    # its centre stays about 250 px from the middle, well inside the 341 px launch-screen circle
    im.paste(stamp, (int(c + s(108) ), int(c - s(258))), stamp)
    return im


def main():
    font = sys.argv[1]
    draw(font).resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    closer = draw(font, k=1.12)   # the plain icon (install dialog, browser tab, older launch screens)
    closer.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    closer.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")


if __name__ == "__main__":
    main()
