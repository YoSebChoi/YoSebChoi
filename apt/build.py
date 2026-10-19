"""Builds 우리 단지 거래 추적 into docs/apt/ (GitHub Pages): the page with its version, the tracker, one data
file (the complexes, the 국토교통부 실거래 of 반송동 with each trade tied to one of our complexes, and the blog
posts), the service worker, the manifest and the icons.

Naver 부동산 listings are never part of this: the Android app reads them on the phone and keeps them there.

python3 apt/build.py
"""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC.parent / "docs" / "apt"

MANIFEST = {
    "id": "./",
    "name": "우리 단지 거래 추적",
    "short_name": "단지 거래",
    "description": "시범한빛마을 KCC스위첸과 이웃 단지의 매물이 사라지는 것으로 거래를 추정하고 실거래로 확인해요",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#2f5d8a",
    "theme_color": "#f4f6f8",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SW = """// 우리 단지 거래 추적 service worker: the app shell from cache, refreshed in the background.
const CACHE = "apt-watch-__VERSION__";
const SHELL = ["./", "./index.html", "./tracker.js", "./data.json"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("apt-watch-") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (/(\\.webmanifest|\\/icon-[^/]*\\.png)$/.test(url.pathname)) { e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req))); return; }
  // network first, so new data shows on the next opening; the cached copy when offline
  e.respondWith(fetch(req).then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req, { ignoreSearch: true })));
});
"""


def load(name, default):
    p = SRC / "data" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def tie_trades(complexes, trades):
    """Each 반송동 trade → the key of our complex whose 단지명 pattern (and 지번, when we know it) fits, else None."""
    out = []
    for t in trades:
        key = None
        for c in complexes:
            if re.search(c["molit"], t["nm"], re.I):
                if c.get("jibun") and t.get("jibun") and t["jibun"].split("-")[0] != c["jibun"]:
                    continue
                key = c["key"]
                break
        out.append({**t, "cx": key})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load("complexes.json", {"complexes": []})
    trades_doc = load("trades.json", {"trades": [], "months": {}})
    blog = load("blog.json", {"posts": []})
    trades = tie_trades(cfg["complexes"], trades_doc.get("trades", []))
    # the other 반송동 complexes' names, so the app can show what was left untied
    others = sorted({t["nm"] for t in trades if not t["cx"]})
    data = {
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "center": cfg.get("center"),
        "complexes": [{k: v for k, v in c.items() if not k.startswith("blog")} for c in cfg["complexes"]],
        "trades": [t for t in trades if t["cx"]],
        "tradesUpdated": trades_doc.get("updated"),
        "tradeMonths": sorted(trades_doc.get("months", {})),
        "otherNames": others,
        "blog": blog.get("posts", []),
        "blogUpdated": blog.get("updated"),
    }
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tracker = (SRC / "tracker.js").read_text(encoding="utf-8")
    (OUT / "tracker.js").write_text(tracker, encoding="utf-8")

    page = (SRC / "index.html").read_text(encoding="utf-8")
    manifest = json.loads(json.dumps(MANIFEST))
    for old in OUT.glob("icon-*.*.png"):
        old.unlink()
    from PIL import Image
    Image.open(SRC / "assets/icon-512.png").resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    shutil.copyfile(SRC / "assets/icon-512.png", OUT / "icon-512.png")
    shutil.copyfile(SRC / "assets/icon-maskable-512.png", OUT / "icon-maskable-512.png")
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        hashed = name.replace(".png", f".{hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:8]}.png")
        shutil.copyfile(OUT / name, OUT / hashed)
        for entry in manifest["icons"]:
            if entry["src"] == name:
                entry["src"] = hashed
        page = page.replace(f'href="{name}"', f'href="{hashed}"')
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    version = hashlib.sha256((page + tracker + manifest_text + json.dumps(data, ensure_ascii=False)).encode()).hexdigest()[:10]
    (OUT / "index.html").write_text(page.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(manifest_text, encoding="utf-8")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    # the page compares itself with this on opening (GitHub Pages serves a cached page for up to 10 minutes)
    (OUT / "version.txt").write_text(version + "\n", encoding="utf-8")
    print(f"docs/apt/ built (version {version}): {len(data['trades'])} trades of our complexes, {len(data['blog'])} blog posts")


if __name__ == "__main__":
    main()
