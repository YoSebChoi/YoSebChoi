"""Draws the app icon: three apartment blocks on a blue sky, the middle one with a lit window and a
small price tag going down (the listing that disappeared). → apt/assets/icon-512.png, icon-maskable-512.png

python3 apt/assets/make_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
S = 4  # draw big, then scale down for smooth edges
SKY, SKY2 = (47, 93, 138), (74, 127, 176)
WALL, WALL2, WALL3 = (244, 246, 248), (214, 222, 232), (190, 202, 216)
WIN, LIT, TAG = (120, 150, 182), (255, 196, 77), (232, 93, 79)


def draw(size, pad):
    n = size * S
    img = Image.new("RGBA", (n, n), SKY)
    d = ImageDraw.Draw(img)
    for y in range(n):  # a soft sky
        t = y / n
        d.line([(0, y), (n, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(SKY2, SKY)))
    u = (n - 2 * pad * S) / 100  # a 100×100 grid inside the padding
    o = pad * S
    R = lambda x0, y0, x1, y1: [o + x0 * u, o + y0 * u, o + x1 * u, o + y1 * u]
    ground = 86
    blocks = [(10, 40, 32, WALL3), (68, 34, 90, WALL2), (33, 16, 67, WALL)]
    for x0, top, x1, col in blocks:
        d.rounded_rectangle(R(x0, top, x1, ground), radius=2 * u, fill=col)
        cols = 2 if x1 - x0 < 30 else 3
        w = (x1 - x0 - 6) / cols
        for r in range(int((ground - top - 10) // 9)):
            for c in range(cols):
                wx, wy = x0 + 3 + c * w + 1.2, top + 6 + r * 9
                lit = (x0 == 33 and r == 2 and c == 1)
                d.rectangle(R(wx, wy, wx + w - 2.4, wy + 4.6), fill=LIT if lit else WIN)
    d.rectangle(R(4, ground, 96, ground + 3), fill=(36, 70, 104))
    # the tag: a little price label with a down arrow, hanging by the lit window
    d.rounded_rectangle(R(58, 18, 86, 31), radius=3 * u, fill=TAG)
    d.polygon([tuple(R(66, 22.5, 0, 0)[:2]), tuple(R(78, 22.5, 0, 0)[:2]), tuple(R(72, 28.5, 0, 0)[:2])], fill=(255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


draw(512, 6).save(OUT / "icon-512.png")
draw(512, 18).save(OUT / "icon-maskable-512.png")   # the launcher's safe zone is the middle 80%
print("icons →", OUT)
