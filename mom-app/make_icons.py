"""Draws the Android launcher icons from the web app's maskable icon (run after mom/build.py).

python3 mom-app/make_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "mom-app/android/app/src/main/res"
MASKABLE = Image.open(ROOT / "docs/mom/icon-maskable-512.png").convert("RGBA")
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

for name, k in DENSITIES.items():
    out = RES / f"mipmap-{name}"
    out.mkdir(parents=True, exist_ok=True)
    # adaptive foreground, 108dp: the launcher crops it to its own shape (the pin sits in the 66dp safe zone)
    MASKABLE.resize((round(108 * k),) * 2, Image.LANCZOS).save(out / "ic_launcher_foreground.png")
    # legacy icons (Android 7 and older): 48dp, rounded square and round
    n = round(48 * k)
    img = MASKABLE.resize((n, n), Image.LANCZOS)
    for file, draw in (("ic_launcher.png", lambda d: d.rounded_rectangle((0, 0, n - 1, n - 1), radius=n // 5, fill=255)),
                       ("ic_launcher_round.png", lambda d: d.ellipse((0, 0, n - 1, n - 1), fill=255))):
        mask = Image.new("L", (n, n), 0)
        draw(ImageDraw.Draw(mask))
        icon = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        icon.paste(img, mask=mask)
        icon.save(out / file)
print("icons drawn")
