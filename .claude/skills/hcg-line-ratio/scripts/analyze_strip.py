#!/usr/bin/env python3
"""Estimate test-line (T) intensity relative to control line (C) on a
lateral-flow strip photo (e.g. an hCG pregnancy test strip).

Dependencies: numpy, Pillow only.

Pipeline
  1. Find the colored handle (pink/magenta "HCG" printed end) -> strip axis.
     Or skip detection with --box / --angle.
  2. Rotate so the strip is horizontal and cut out the band that runs from
     the handle edge into the reaction window.
  3. Per column, convert the chosen channel (green by default; magenta/purple
     lines absorb green most) to optical density OD = -log10(I / I_bg),
     with I_bg a robust local background estimated along the strip.
  4. Find peaks; the line nearest the handle is C, the next one further
     away is T. Report peak-height and area ratios plus a noise floor.
"""
import argparse
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- helpers
def largest_component(mask):
    """4-connected largest component of a small boolean grid (BFS)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    best = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, comp = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    out = np.zeros_like(mask, bool)
    if best:
        ys, xs = zip(*best)
        out[list(ys), list(xs)] = True
    return out


def smooth(x, k):
    k = max(1, int(k) | 1)
    if k == 1:
        return x.copy()
    pad = k // 2
    xp = np.pad(x, pad, mode="edge")
    return np.convolve(xp, np.ones(k) / k, mode="valid")


def running_percentile(x, win, q):
    win = max(3, int(win) | 1)
    pad = win // 2
    xp = np.pad(x, pad, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(xp, win)
    return np.percentile(view, q, axis=1)


def find_peaks(y, min_height, min_dist):
    idx = [i for i in range(1, len(y) - 1)
           if y[i] >= y[i - 1] and y[i] > y[i + 1] and y[i] >= min_height]
    idx.sort(key=lambda i: -y[i])
    kept = []
    for i in idx:
        if all(abs(i - j) >= min_dist for j in kept):
            kept.append(i)
    return sorted(kept)


def peak_area(y, i, half):
    a, b = max(0, i - half), min(len(y), i + half + 1)
    return float(np.clip(y[a:b], 0, None).sum())


def fwhm(y, i):
    h = y[i] / 2
    a = i
    while a > 0 and y[a] > h:
        a -= 1
    b = i
    while b < len(y) - 1 and y[b] > h:
        b += 1
    return b - a


# ---------------------------------------------------------- strip finding
def detect_handle(img, scale=8):
    """Return (center_xy, angle_deg, length, width) of the colored handle."""
    a = np.asarray(img).astype(np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    # pink/magenta print: red well above green, fairly bright
    m = (R - G > 28) & (R > 120) & (B - G > -10)
    h, w = m.shape
    hh, ww = h // scale, w // scale
    grid = m[: hh * scale, : ww * scale].reshape(hh, scale, ww, scale).mean((1, 3)) > 0.25
    comp = largest_component(grid)
    if comp.sum() < 20:
        raise RuntimeError("colored handle not found; pass --box x0,y0,x1,y1")
    # keep full-res pink pixels inside the component's blocks
    big = np.kron(comp, np.ones((scale, scale), bool))
    full = np.zeros_like(m)
    full[: hh * scale, : ww * scale] = big
    ys, xs = np.nonzero(m & full)
    pts = np.stack([xs, ys], 1).astype(float)
    c = pts.mean(0)
    cov = np.cov((pts - c).T)
    evals, evecs = np.linalg.eigh(cov)
    v = evecs[:, 1]  # major axis
    ang = math.degrees(math.atan2(v[1], v[0]))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    proj = (pts - c) @ np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
    perp = (pts - c) @ np.array([-math.sin(math.radians(ang)), math.cos(math.radians(ang))])
    length = np.percentile(proj, 99.5) - np.percentile(proj, 0.5)
    width = np.percentile(perp, 99) - np.percentile(perp, 1)
    return c, ang, float(length), float(width)


def rotate_about(img, center, ang):
    """Rotate so that direction `ang` becomes +x; returns image and mapped center."""
    rot = img.rotate(ang, resample=Image.BICUBIC, center=tuple(center), expand=False,
                     fillcolor=(255, 255, 255))
    return rot, center  # rotation about center keeps center fixed


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--box", help="manual crop x0,y0,x1,y1 of a horizontal strip region "
                                  "(reaction window incl. both lines); disables auto detection")
    ap.add_argument("--control-side", choices=["left", "right"], default="right",
                    help="with --box: which side the control line is on (default right)")
    ap.add_argument("--channel", choices=["g-r", "g", "gray"], default="g-r",
                    help="g-r: green OD minus red OD (colour-selective, ignores black "
                         "print/shadows; default). g: plain green OD")
    ap.add_argument("--debug", help="write an annotated PNG here")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    info = {"image": args.image}
    if args.box:
        x0, y0, x1, y1 = map(int, args.box.split(","))
        band = img.crop((x0, y0, x1, y1))
        if args.control_side == "left":
            band = band.transpose(Image.FLIP_LEFT_RIGHT)
        strip_w = y1 - y0
        info["mode"] = "manual-box"
    else:
        c, ang, L, W = detect_handle(img)
        rot, c = rotate_about(img, c, ang)
        # decide which side of the handle the strip continues on: the side
        # with the stronger control-line-like dip right next to the handle
        cx, cy = c
        half_w = W * 0.30
        best = None
        for side in (-1, 1):
            edge = cx + side * L / 2
            reach = L * 0.9
            xa, xb = (edge - reach, edge) if side < 0 else (edge, edge + reach)
            box = (int(xa), int(cy - half_w), int(xb), int(cy + half_w))
            b = rot.crop(box)
            if side > 0:
                b = b.transpose(Image.FLIP_LEFT_RIGHT)
            # colour-selective signal: magenta/purple lines absorb green much
            # more than red, while black print, shadows and creases are neutral
            ab = np.asarray(b).astype(float)
            pr, pg = np.median(ab[..., 0], 0), np.median(ab[..., 1], 0)
            od = (-np.log10(np.clip(pg, 1, None) / max(1.0, np.percentile(pg, 90)))
                  + np.log10(np.clip(pr, 1, None) / max(1.0, np.percentile(pr, 90))))
            # skip the few pixels right at the handle edge
            score = od[: int(len(od) * 0.97)][-int(len(od) * 0.5):].max()
            if best is None or score > best[0]:
                best = (score, b, side, box)
        _, band, side, box = best
        strip_w = W
        info.update(mode="auto", handle_center=[round(cx, 1), round(cy, 1)],
                    angle_deg=round(ang, 2), handle_len_px=round(L, 1),
                    strip_width_px=round(W, 1), strip_side="left" if side < 0 else "right")
        # drop the last few px that bleed into the handle print
        bw, bh = band.size
        band = band.crop((0, 0, int(bw - 0.02 * L), bh))

    a = np.asarray(band).astype(float)
    line_w = max(3, strip_w * 0.10)  # typical line ~1-1.5 mm on a 4 mm strip

    def od_of(chan):
        prof = smooth(np.median(chan, 0), line_w * 0.3)  # median across width
        bg = smooth(running_percentile(prof, line_w * 5, 85), line_w * 3)
        return np.clip(-np.log10(np.clip(prof, 1, None) / np.clip(bg, 1, None)), -1, None)

    od_g = od_of(a[..., 1])
    if args.channel == "g-r":
        od = od_g - od_of(a[..., 0])
    elif args.channel == "g":
        od = od_g
    else:
        od = od_of(a.mean(2))

    # noise from the residual in the window outside peaks
    mad = np.median(np.abs(od - np.median(od))) * 1.4826
    noise = max(mad, 1e-4)
    peaks = find_peaks(od, max(3 * noise, 0.004), line_w * 2)
    if not peaks:
        print(json.dumps({**info, "error": "no lines found"}, ensure_ascii=False))
        sys.exit(2)
    # control = significant peak closest to the handle (= right end of band)
    strong = max(od[p] for p in peaks)
    c_cands = [p for p in peaks if od[p] >= 0.35 * strong]
    C = max(c_cands)
    # test = strongest peak left of C within a plausible spacing
    lo, hi = C - strip_w * 3.0, C - strip_w * 0.5
    t_cands = [p for p in peaks if lo <= p <= hi]
    half = int(round(line_w * 1.2))
    res = {
        **info,
        "channel": args.channel,
        "noise_od": round(float(noise), 4),
        "control": {"x": int(C), "peak_od": round(float(od[C]), 4),
                    "area": round(peak_area(od, C, half), 3), "fwhm_px": fwhm(od, C)},
    }
    if t_cands:
        T = max(t_cands, key=lambda p: od[p])
        res["test"] = {"x": int(T), "peak_od": round(float(od[T]), 4),
                       "area": round(peak_area(od, T, half), 3), "fwhm_px": fwhm(od, T),
                       "snr": round(float(od[T] / noise), 1),
                       "spacing_px": int(C - T)}
        res["ratio_peak"] = round(float(od[T] / od[C]), 3)
        res["ratio_area"] = round(res["test"]["area"] / max(res["control"]["area"], 1e-9), 3)
        res["test_detected"] = bool(od[T] >= 5 * noise)
        # cross-check with plain green-channel OD at the same positions
        res["ratio_peak_green"] = round(float(od_g[T] / max(od_g[C], 1e-9)), 3)
    else:
        res["test"] = None
        res["ratio_peak"] = 0.0
        res["ratio_area"] = 0.0
        res["test_detected"] = False
        res["upper_bound_ratio"] = round(float(3 * noise / od[C]), 3)
    r = res["ratio_peak"]
    res["grade"] = ("none" if not res["test_detected"] else
                    "very faint" if r < 0.10 else
                    "faint" if r < 0.30 else
                    "medium" if r < 0.60 else
                    "strong" if r < 0.90 else
                    "equal-or-darker")

    if args.debug:
        W_, H_ = band.size
        ph = 220
        canvas = Image.new("RGB", (W_, H_ + ph), "white")
        canvas.paste(band, (0, 0))
        d = ImageDraw.Draw(canvas)
        top = max(od.max(), 0.05)
        pts = [(i, H_ + ph - 10 - (ph - 30) * max(0, v) / top) for i, v in enumerate(od)]
        d.line(pts, fill=(0, 0, 0), width=2)
        d.line([(0, H_ + ph - 10 - (ph - 30) * 3 * noise / top), (W_, H_ + ph - 10 - (ph - 30) * 3 * noise / top)],
               fill=(180, 180, 180), width=1)
        for key, col in (("control", (0, 120, 255)), ("test", (255, 80, 0))):
            if res.get(key):
                x = res[key]["x"]
                d.line([(x, 0), (x, H_ + ph)], fill=col, width=1)
                d.text((x + 3, H_ + 4), key[0].upper(), fill=col)
        canvas.save(args.debug)
        res["debug_image"] = args.debug

    print(json.dumps(res, ensure_ascii=False, indent=None if args.json else 2))


if __name__ == "__main__":
    main()
