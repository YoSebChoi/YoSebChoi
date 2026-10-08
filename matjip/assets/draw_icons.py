#!/usr/bin/env python3
"""Draws the app icons in matjip/assets (run once; build.py copies them).

The icon is a red 노포 signboard hanging under a warm lamp on a night street.
Everything that matters sits inside the central circle Android shows on the
launch screen (about two thirds of the icon), and the dark ground matches the
manifest's background_color, so the launch screen reads as one dark street with
the lit signboard in the middle.

    python3 matjip/assets/draw_icons.py path/to/BlackHanSans-Regular.ttf
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

NIGHT = (18, 22, 28)        # #12161c, the manifest background_color: a cool night
RED = (200, 36, 27)
RED_DARK = (168, 29, 22)
CREAM = (244, 237, 225)
LAMP = (255, 196, 110)
OUT = Path(__file__).resolve().parent


def draw(font_path, W=1024, scale=1.0):
    im = Image.new("RGB", (W, W), NIGHT)
    c = W / 2
    s = lambda v: v * W / 1024 * scale

    # warm light falling on the signboard
    glow = Image.new("L", (W, W), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([c - s(330), c - s(300), c + s(330), c + s(300)], fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(s(120)))
    im.paste(Image.new("RGB", (W, W), (112, 72, 38)), (0, 0), glow)

    d = ImageDraw.Draw(im)
    pw, ph = s(520), s(330)                    # the plate; its corners stay inside the 2/3 circle
    x0, y0 = c - pw / 2, c - ph / 2 + s(28)
    x1, y1 = x0 + pw, y0 + ph
    # strings to a nail, and the lamp above
    nail = (c, y0 - s(118))
    for x in (x0 + s(70), x1 - s(70)):
        d.line([nail, (x, y0 + s(6))], fill=(120, 100, 82), width=int(s(7)))
    d.ellipse([nail[0] - s(12), nail[1] - s(12), nail[0] + s(12), nail[1] + s(12)], fill=(150, 130, 110))
    # plate with a shadow and a double cream frame, like the opening screen's 간판
    shadow = Image.new("L", (W, W), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([x0 + s(6), y0 + s(18), x1 + s(6), y1 + s(26)], radius=s(26), fill=170)
    im.paste((10, 6, 4), (0, 0), shadow.filter(ImageFilter.GaussianBlur(s(18))))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x1, y1], radius=s(26), fill=RED)
    d.rounded_rectangle([x0, y0 + ph * .55, x1, y1], radius=s(26), fill=RED_DARK)
    d.rectangle([x0, y0 + ph * .55, x1, y0 + ph * .55 + s(30)], fill=RED_DARK)
    d.rounded_rectangle([x0 + s(14), y0 + s(14), x1 - s(14), y1 - s(14)], radius=s(16), outline=CREAM, width=int(s(9)))
    d.rounded_rectangle([x0 + s(32), y0 + s(32), x1 - s(32), y1 - s(32)], radius=s(10), outline=CREAM, width=int(s(3)))
    # 노포 in signboard lettering, a little light on its top edge
    f = ImageFont.truetype(font_path, int(s(196)))
    t = "노포"
    bb = d.textbbox((0, 0), t, font=f)
    tx, ty = c - (bb[2] - bb[0]) / 2 - bb[0], (y0 + y1) / 2 - (bb[3] - bb[1]) / 2 - bb[1] - s(4)
    d.text((tx + s(4), ty + s(6)), t, font=f, fill=(110, 18, 14))
    d.text((tx, ty), t, font=f, fill=(255, 250, 240))
    # the lamp: a small shade with its bulb, above the nail
    ly = nail[1] - s(70)
    d.line([(c, 0), (c, ly)], fill=(90, 76, 64), width=int(s(5)))
    d.pieslice([c - s(46), ly - s(10), c + s(46), ly + s(60)], 180, 360, fill=(70, 58, 48))
    bulb = Image.new("L", (W, W), 0)
    ImageDraw.Draw(bulb).ellipse([c - s(34), ly + s(10), c + s(34), ly + s(44)], fill=255)
    im.paste(Image.new("RGB", (W, W), LAMP), (0, 0), bulb.filter(ImageFilter.GaussianBlur(s(10))))
    return im


def main():
    font = sys.argv[1]
    big = draw(font)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    # the plain icon (install dialog, browser tab, older launch screens): the same scene a bit closer
    closer = draw(font, scale=1.18)
    closer.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    closer.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")


if __name__ == "__main__":
    main()
