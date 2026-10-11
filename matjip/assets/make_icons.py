"""App icons from the character picture (assets/character.png: the rounded-square picture, corners transparent).

python3 matjip/assets/make_icons.py   then   python3 android-app/make_icons.py

- icon-512 / icon-192 ("any"): the rounded picture itself
- icon-maskable-512: the picture's inner square at 84% over a blurred copy of itself, so a launcher's
  circle or squircle keeps the hat and the face
"""
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).resolve().parent
PIC = Image.open(HERE / "character.png").convert("RGBA")
INSET = 0.075   # trims the rounded corners off: what is left is picture edge to edge


def inner():
    w = PIC.width
    d = round(w * INSET)
    return PIC.crop((d, d, w - d, w - d)).convert("RGB")


def framed(size, scale):
    """The inner picture at `scale` of the canvas, on a soft, slightly darker blow-up of itself."""
    sq = inner()
    bg = sq.resize((size, size), Image.LANCZOS).filter(ImageFilter.GaussianBlur(size * 0.035))
    bg = ImageEnhance.Brightness(bg).enhance(0.82)
    n = round(size * scale)
    bg.paste(sq.resize((n, n), Image.LANCZOS), ((size - n) // 2, (size - n) // 2))
    return bg


if __name__ == "__main__":
    for name, size in (("icon-512.png", 512), ("icon-192.png", 192)):
        PIC.resize((size, size), Image.LANCZOS).save(HERE / name)
    framed(512, 0.84).save(HERE / "icon-maskable-512.png")
    print("icons drawn")
