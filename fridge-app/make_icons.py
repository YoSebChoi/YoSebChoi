"""Draws the Android launcher icons and the launch-screen face from the web app's pictures
(run after fridge/build.py; the APK workflow runs it too).

python3 fridge-app/make_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "fridge-app/android/app/src/main/res"
MASKABLE = Image.open(ROOT / "docs/fridge/icon-maskable-512.png").convert("RGBA")
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

for name, k in DENSITIES.items():
    out = RES / f"mipmap-{name}"
    out.mkdir(parents=True, exist_ok=True)
    # adaptive foreground: 108dp, the launcher crops it to its own shape (the fridge sits inside the 66dp safe zone)
    MASKABLE.resize((round(108 * k),) * 2, Image.LANCZOS).save(out / "ic_launcher_foreground.png")
    # legacy icons (Android 7 and older): 48dp, square with rounded corners and round
    n = round(48 * k)
    img = MASKABLE.resize((n, n), Image.LANCZOS)
    for file, draw in (("ic_launcher.png", lambda d: d.rounded_rectangle((0, 0, n - 1, n - 1), radius=n // 6, fill=255)),
                       ("ic_launcher_round.png", lambda d: d.ellipse((0, 0, n - 1, n - 1), fill=255))):
        mask = Image.new("L", (n, n), 0)
        draw(ImageDraw.Draw(mask))
        icon = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        icon.paste(img, mask=mask)
        icon.save(out / file)

# launch screen: 최책임's face, the middle of a 288dp square that Android shows as a 192dp circle;
# the page's splash (fridge/index.html) opens on that same circle and widens it into the whole picture
face = Image.open(ROOT / "fridge/assets/chef-face.png").convert("RGBA").resize((576, 576), Image.LANCZOS)
ring = Image.new("L", (576, 576), 0)
ImageDraw.Draw(ring).ellipse((0, 0, 575, 575), fill=255)
splash = Image.new("RGBA", (864, 864), (0, 0, 0, 0))
splash.paste(face, (144, 144), ring)
(RES / "drawable-nodpi").mkdir(exist_ok=True)
splash.save(RES / "drawable-nodpi/splash_chef.png")
old = RES / "drawable/splash_fridge.xml"
if old.exists():
    old.unlink()
print("icons drawn")
