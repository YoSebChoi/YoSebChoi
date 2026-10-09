"""Builds 냉장고 셰프 into docs/fridge/ (GitHub Pages): the page with its version, the recipes,
the service worker, the manifest and the icons (each also under a content-hashed name, so no cache
can hand out an old icon or launch screen).

python3 fridge/build.py
"""
import hashlib
import json
import shutil
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC.parent / "docs" / "fridge"

MANIFEST = {
    "id": "./",
    "name": "냉장고 셰프",
    "short_name": "냉장고 셰프",
    "description": "냉장고 사진이나 재료로 오늘 메뉴와 출처 있는 레시피를 찾아 줘요",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#1f6f62",
    "theme_color": "#f7f3ea",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SW = """// 냉장고 셰프 service worker: the app shell from cache, refreshed in the background.
const CACHE = "fridge-chef-__VERSION__";
const SHELL = ["./", "./index.html", "./recipes.js", "./vendor/anthropic-sdk.mjs"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("fridge-chef-") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;   // the AI and the fonts go to the network
  // the app's identity (manifest, icons) always comes from the network
  if (/(\\.webmanifest|\\/icon-[^/]*\\.png)$/.test(url.pathname)) { e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req))); return; }
  // network first, so a new version shows on the next opening; the cached copy when offline
  e.respondWith(fetch(req).then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req, { ignoreSearch: true })));
});
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    page = (SRC / "index.html").read_text(encoding="utf-8")
    recipes = (SRC / "recipes.js").read_text(encoding="utf-8")
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
    sdk = (SRC / "vendor/anthropic-sdk.mjs").read_text(encoding="utf-8")
    # the 식약처 recipe DB (fridge/fetch_recipes.py); without it the app has its built-in recipes only
    db_src = SRC / "data/foodsafety.json"
    db = db_src.read_text(encoding="utf-8") if db_src.exists() else ""
    if db:
        (OUT / "recipes-db.json").write_text(db, encoding="utf-8")
    elif (OUT / "recipes-db.json").exists():
        (OUT / "recipes-db.json").unlink()
    version = hashlib.sha256((page + recipes + sdk + db + SW + manifest_text).encode()).hexdigest()[:8]
    (OUT / "index.html").write_text(page.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "recipes.js").write_text(recipes, encoding="utf-8")
    (OUT / "vendor").mkdir(exist_ok=True)
    shutil.copyfile(SRC / "vendor/anthropic-sdk.mjs", OUT / "vendor/anthropic-sdk.mjs")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(manifest_text, encoding="utf-8")
    print(f"built {version}" + (f" with {len(json.loads(db)['recipes'])} 식약처 recipes" if db else " (no 식약처 recipe DB yet)"))


if __name__ == "__main__":
    main()
