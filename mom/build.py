#!/usr/bin/env python3
"""Build 최책임의 예비맘 혜택 지도 into docs/mom/ for GitHub Pages.

    python3 mom/build.py            # look up coordinates that are missing or approximate, then build
    python3 mom/build.py --offline  # build from what is in mom/data only

Data in mom/data/:
  - places.json     places with a benefit for pregnant women (each benefit lists its sources)
  - policies.json   government and local-government support (the 정책 tab)
  - blog.json       네이버 블로그 posts, collected by mom/fetch_blog.py (titles, links, dates)
  - geocode_cache.json   name+address -> [lat, lng]

Coordinates come from the Kakao Local API when KAKAO_REST_KEY is set (the same key as 노포 지도);
otherwise the coordinates written in places.json are used as they are.
"""
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mom"
DATA = SRC / "data"
OUT = ROOT / "docs" / "mom"
CACHE_FILE = DATA / "geocode_cache.json"

MANIFEST = {
    "name": "최책임의 예비맘 혜택 지도",
    "short_name": "예비맘 혜택",
    "description": "임산부에게 할인·우선입장·선물을 주는 식당, 카페, 베이커리, 호텔, 리조트와 정부·지자체 임신 지원을 한 지도에.",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#3b1f33",
    "theme_color": "#3b1f33",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "related_applications": [{"platform": "play", "id": "io.github.yosebchoi.mommap"}],
    "prefer_related_applications": False,
}

SW = """// 예비맘 혜택 지도 service worker: the app shell from cache, the data fresh when online.
const CACHE = "mom-map-__VERSION__";
const DATA = ["places.json", "policies.json", "blog.json"];
const SHELL = ["./", "./index.html", ...DATA.map(d => "./" + d)];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" })))));
});
self.addEventListener("message", e => { if (e.data === "skip-waiting") self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("mom-map-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (req.mode === "navigate") {
    e.respondWith(caches.open(CACHE).then(c => c.match("./index.html")).then(hit => hit || fetch(req)));
    return;
  }
  const name = url.pathname.split("/").pop();
  if (url.origin === location.origin && DATA.includes(name)) {
    e.respondWith(caches.open(CACHE).then(c => fetch(req).then(res => { if (res.ok) c.put("./" + name, res.clone()); return res; })
      .catch(() => c.match("./" + name))));
    return;
  }
  if (url.origin === location.origin && /(\\.webmanifest|\\/icon-[^/]*\\.png)$/.test(url.pathname)) {
    e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req)));
    return;
  }
  if (/tile\\.openstreetmap|nominatim|kakao/.test(url.hostname)) return;
  e.respondWith(caches.open(CACHE).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") c.put(req, res.clone());
    return res;
  }))));
});
"""


def icon(size, maskable=False):
    """A map pin holding a small heart, on dusk plum, with a blush moon behind it."""
    im = Image.new("RGB", (size, size), "#3b1f33")
    d = ImageDraw.Draw(im)
    k = size / 512 * (0.72 if maskable else 1.0)
    c = size / 2
    P = lambda x, y: (c + (x - 256) * k, c + (y - 256) * k)
    d.ellipse([*P(96, 96), *P(416, 416)], fill="#5a2f4c")
    # pin
    d.ellipse([*P(146, 70), *P(366, 290)], fill="#fbe9ee")
    d.polygon([P(166, 230), P(346, 230), P(256, 440)], fill="#fbe9ee")
    # heart
    d.ellipse([*P(196, 128), *P(262, 194)], fill="#e2577f")
    d.ellipse([*P(250, 128), *P(316, 194)], fill="#e2577f")
    d.polygon([P(200, 172), P(312, 172), P(256, 238)], fill="#e2577f")
    return im


class Geocoder:
    def __init__(self, offline):
        self.offline = offline
        self.kakao = os.environ.get("KAKAO_REST_KEY", "").strip()
        self.cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

    def _kakao(self, kind, query):
        url = f"https://dapi.kakao.com/v2/local/search/{kind}.json?" + urllib.parse.urlencode({"query": query, "size": 1})
        req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {self.kakao}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents", [])
        return [round(float(docs[0]["y"]), 6), round(float(docs[0]["x"]), 6)] if docs else None

    def locate(self, p):
        key = p["n"] + "@" + p["a"]
        if key in self.cache:
            return self.cache[key]
        if self.offline or not self.kakao:
            return None
        name = re.sub(r"[「」]|\(.*?\)", " ", p["n"]).split("  ")[0].strip()
        region = " ".join(p["a"].split()[:2])
        ll = None
        try:
            ll = self._kakao("keyword", f"{region} {name}") or self._kakao("address", p["a"])
        except Exception as e:  # a lookup that fails keeps the written coordinates
            print("geocode failed:", p["n"], e, file=sys.stderr)
        if ll:
            self.cache[key] = ll
        return ll

    def save(self):
        CACHE_FILE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def norm(s):
    return re.sub(r"\s+", "", s or "").lower()


def main():
    offline = "--offline" in sys.argv
    geo = Geocoder(offline)
    places = json.loads((DATA / "places.json").read_text(encoding="utf-8"))["places"]
    policies = json.loads((DATA / "policies.json").read_text(encoding="utf-8"))
    blog = json.loads((DATA / "blog.json").read_text(encoding="utf-8")) if (DATA / "blog.json").exists() else {"posts": []}
    posts = blog.get("posts", [])

    out = []
    for i, p in enumerate(places):
        p = dict(p)
        if not p.get("brand") and (p.get("x") or not p.get("ll")):
            ll = geo.locate(p)
            if ll:
                p["ll"] = ll
                p.pop("x", None)
        if not p.get("brand") and not p.get("ll"):
            print("no location:", p["n"], file=sys.stderr)
            continue
        # 네이버 블로그 posts that name this place: newest first, a few of them
        kws = [norm(k) for k in p.get("kw", []) if k]
        seen = {s["u"] for s in p["src"]}
        found = []
        for b in posts:
            text = norm(b["title"] + " " + b.get("desc", ""))
            if b["url"] not in seen and any(k in text for k in kws):
                d = b["date"]
                found.append({"t": "blog", "n": b["title"], "d": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "u": b["url"], "by": b["blog"]})
        found.sort(key=lambda s: s["d"], reverse=True)
        p["src"] = p["src"] + found[:8]
        p["nb"] = len(found)
        p["id"] = len(out)
        p["k"] = hashlib.sha1(norm(p["n"]).encode()).hexdigest()[:8]
        p.pop("kw", None)
        out.append(p)
    geo.save()

    # the 블로그 tab: every collected post, newest first, with the place it was linked to
    feed = [{"t": b["title"], "d": b["date"], "u": b["url"], "by": b["blog"]} for b in posts[:400]]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"updated": now, "blogUpdated": blog.get("updated", ""), "places": out}, ensure_ascii=False, separators=(",", ":"))
    pol = json.dumps(policies, ensure_ascii=False, separators=(",", ":"))
    feed_txt = json.dumps({"updated": blog.get("updated", ""), "posts": feed}, ensure_ascii=False, separators=(",", ":"))
    (OUT / "places.json").write_text(data, encoding="utf-8")
    (OUT / "policies.json").write_text(pol, encoding="utf-8")
    (OUT / "blog.json").write_text(feed_txt, encoding="utf-8")

    page = (SRC / "index.html").read_text(encoding="utf-8")
    manifest = json.loads(json.dumps(MANIFEST))
    for old in OUT.glob("icon-*.*.png"):
        old.unlink()
    for name, size, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False), ("icon-maskable-512.png", 512, True)):
        icon(size, maskable=mask).save(OUT / name)
        hashed = name.replace(".png", f".{hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:8]}.png")
        (OUT / hashed).write_bytes((OUT / name).read_bytes())
        for entry in manifest["icons"]:
            if entry["src"] == name:
                entry["src"] = hashed
        page = page.replace(f'href="{name}"', f'href="{hashed}"').replace(f'src="{name}"', f'src="{hashed}"')
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    version = hashlib.sha256((page + SW + data + pol + feed_txt + manifest_text).encode()).hexdigest()[:8]
    js_key = os.environ.get("KAKAO_JS_KEY", "").strip()
    (OUT / "index.html").write_text(page.replace("__VERSION__", version).replace("__KAKAO_JS_KEY__", js_key), encoding="utf-8")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(manifest_text, encoding="utf-8")
    print(f"built {version}: {len(out)} places, {sum(p['nb'] for p in out)} blog links, {len(feed)} posts")


if __name__ == "__main__":
    main()
