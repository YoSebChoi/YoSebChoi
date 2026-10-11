"""Draws the Android launcher icons from the character picture (matjip/assets/character.png).

python3 android-app/make_icons.py
"""
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "matjip/assets"))
from make_icons import PIC, framed  # noqa: E402

RES = ROOT / "android-app/android/app/src/main/res"
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

for name, k in DENSITIES.items():
    out = RES / f"mipmap-{name}"
    # adaptive foreground, 108dp: launchers show about the middle 66-72dp, so the picture sits there
    # whole (hat to map) over a soft blow-up of itself that fills whatever else a mask shows
    framed(round(108 * k), 0.68).save(out / "ic_launcher_foreground.png")
    # legacy icons (Android 7 and older): the rounded picture itself
    n = round(48 * k)
    for file in ("ic_launcher.png", "ic_launcher_round.png"):
        PIC.resize((n, n), Image.LANCZOS).save(out / file)
print("icons drawn")
