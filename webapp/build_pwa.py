#!/usr/bin/env python3
"""Build the installable (PWA) copy of the web app into docs/ for GitHub Pages.

webapp/index.html stays the single source (it is also published as a
claude.ai artifact, which adds its own document skeleton). This script wraps
it in a full HTML document with the manifest, theme colour and service
worker, and draws the app icons.

    python3 webapp/build_pwa.py
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webapp" / "index.html"
OUT = ROOT / "docs"
VERSION = "4"  # bump to make installed apps pick up a new build

HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#a3245c">
<meta name="description" content="임신테스트기 사진에서 대조선 대비 시약선 진하기를 재고 날짜별로 기록해요.">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
"""

TAIL = """
<script>
if ("serviceWorker" in navigator) {
  addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
// ask the browser not to evict the locally stored records
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
</script>
</body>
</html>
"""

MANIFEST = {
    "name": "시약선 노트",
    "short_name": "시약선 노트",
    "description": "임신테스트기 사진에서 대조선 대비 시약선 진하기를 재고 기록해요.",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#f8f5f6",
    "theme_color": "#a3245c",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SW = """// 시약선 노트 service worker: app shell cached for offline use
const CACHE = "hcg-notes-v%s";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  if (req.mode === "navigate") {
    // network first so updates arrive; cached page when offline
    e.respondWith(fetch(req).then(res => {
      const copy = res.clone(); caches.open(CACHE).then(c => c.put("./index.html", copy)); return res;
    }).catch(() => caches.match("./index.html")));
    return;
  }
  // everything else (icons, Google Fonts): cache first, fill on miss
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return res;
  })));
});
""" % VERSION


def icon(size, maskable=False):
    s = size / 512
    im = Image.new("RGB", (size, size), "#a3245c")
    d = ImageDraw.Draw(im)
    # a test strip seen from above: white strip, faint T line, strong C line
    scale = 0.78 if maskable else 1.0  # keep content inside the maskable safe zone
    def box(x0, y0, x1, y1):
        cx = cy = size / 2
        f = lambda v, c: c + (v * s - c) * scale
        return [f(x0, cx), f(y0, cy), f(x1, cx), f(y1, cy)]
    d.rounded_rectangle(box(70, 196, 442, 316), radius=28 * s * scale, fill="#fbf7f8")
    d.rounded_rectangle(box(318, 196, 442, 316), radius=28 * s * scale, fill="#f4b5ca")
    d.rectangle(box(318, 196, 340, 316), fill="#f4b5ca")
    d.rectangle(box(196, 206, 214, 306), fill="#e9b9cb")   # T
    d.rectangle(box(262, 206, 280, 306), fill="#8e1a4c")   # C
    return im


def main():
    OUT.mkdir(exist_ok=True)
    body = SRC.read_text(encoding="utf-8")
    (OUT / "index.html").write_text(HEAD + body + TAIL, encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "sw.js").write_text(SW, encoding="utf-8")
    icon(192).save(OUT / "icon-192.png")
    icon(512).save(OUT / "icon-512.png")
    icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
    (OUT / ".nojekyll").write_text("")
    print("built", *sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
