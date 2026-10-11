"""App icons and launch pictures from the illustration fridge/assets/chef-art.png
(최책임 peeking into the fridge, a square picture with rounded corners on white).

python3 fridge/assets/make_chef_icons.py

- chef-face.png        the face and hat, for Android's launch screen circle (fridge-app/make_icons.py)
- chef-face.jpg, chef-art.jpg  light copies for the page: the header, and the splash that opens on the circle
- icon-512.png         the whole picture with its rounded corners (transparent outside)
- icon-maskable-512.png  the picture a little smaller on its own green, so a launcher's
                         mask never cuts the hat (Android shows only the middle two thirds)
"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
GREEN = (200, 226, 187)   # the picture's own background, also the launch screen colour
art = Image.open(HERE / "chef-art.png").convert("RGB")
n = art.width


def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=r, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, mask=m)
    return out


# the corners of the source are white: cut them off along the picture's own curve
pic = rounded(art, round(n * 0.12))

pic.resize((512, 512), Image.LANCZOS).save(HERE / "icon-512.png")

mask = Image.new("RGBA", (512, 512), GREEN + (255,))
s = round(512 * 0.82)
# a little low, so the hat's crown clears the top of a round mask
mask.alpha_composite(pic.resize((s, s), Image.LANCZOS), ((512 - s) // 2, (512 - s) // 2 + 20))
mask.convert("RGB").save(HERE / "icon-maskable-512.png")

cx, cy, side = round(n * 450 / 746), round(n * 318 / 746), round(n * 560 / 746)
art.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)).resize((512, 512), Image.LANCZOS).save(HERE / "chef-face.png")
# the page loads these two on every opening: light JPEGs (the PNGs stay as sources for Android)
Image.open(HERE / "chef-face.png").convert("RGB").resize((384, 384), Image.LANCZOS).save(HERE / "chef-face.jpg", quality=84, optimize=True, progressive=True)
art.resize((560, 560), Image.LANCZOS).save(HERE / "chef-art.jpg", quality=84, optimize=True, progressive=True)
print("chef icons drawn")
