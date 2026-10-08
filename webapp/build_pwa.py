#!/usr/bin/env python3
"""Build the installable (PWA) copy of the web app into docs/ for GitHub Pages.

webapp/index.html stays the single source (it is also published as a
claude.ai artifact, which adds its own document skeleton). This script wraps
it in a full HTML document with the manifest, theme colour and service
worker, and draws the app icons.

    python3 webapp/build_pwa.py
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webapp" / "index.html"
OUT = ROOT / "docs"

HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#e6ede7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1412" media="(prefers-color-scheme: dark)">
<meta name="description" content="임신테스트기 사진에서 대조선 대비 시약선 진하기를 재고 날짜별로 기록해요.">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-180.png">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head>
<body>
"""

TAIL = """
<div class="update-bar" id="updateBar" role="status" hidden>
  <span>새 버전이 나왔어요. 기록은 그대로 남아요.</span>
  <span class="update-actions">
    <button class="btn ghost" id="updateLater" type="button">나중에</button>
    <button class="btn primary" id="updateNow" type="button">지금 업데이트</button>
  </span>
</div>
<style>
.update-bar { position: fixed; left: 0; right: 0; top: 0; z-index: 10; display: flex; flex-wrap: wrap; align-items: center;
  justify-content: space-between; gap: 10px; padding: calc(12px + env(safe-area-inset-top, 0px)) 18px 12px;
  background: var(--surface); color: var(--ink); box-shadow: var(--shadow); font-size: 14px; border-radius: 0 0 20px 20px; }
.update-actions { display: flex; gap: 8px; }
</style>
<script>
window.APP_VERSION = "__VERSION__";
(() => {
  const foot = document.querySelector("footer");
  if (foot) { const p = document.createElement("p"); p.textContent = "앱 버전 " + window.APP_VERSION; foot.appendChild(p); }
  // ask the browser not to evict the locally stored records
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  if (!("serviceWorker" in navigator)) return;
  // the Android app (hcg-app/) always loads the live page and gets the native bridge injected into it;
  // a cached copy would skip that injection, so there is no offline copy or update prompt there
  if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
    navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister())).catch(() => {});
    return;
  }
  const bar = document.getElementById("updateBar");
  let waiting = null, wantReload = false;
  const offer = w => { waiting = w; bar.hidden = false; };
  document.getElementById("updateNow").addEventListener("click", () => {
    wantReload = true;
    if (waiting) waiting.postMessage("skip-waiting"); else location.reload();
  });
  document.getElementById("updateLater").addEventListener("click", () => { bar.hidden = true; });
  // reload only for an update the person asked for; the first install also changes the
  // controller, and reloading then would throw away whatever they had on screen
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!wantReload) return; wantReload = false; location.reload();
  });
  addEventListener("load", async () => {
    try {
      const reg = await navigator.serviceWorker.register("sw.js");
      if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
      reg.addEventListener("updatefound", () => {
        const w = reg.installing;
        if (w) w.addEventListener("statechange", () => {
          if (w.state === "installed" && navigator.serviceWorker.controller) offer(w);
        });
      });
      // look for a new version whenever the app comes back to the foreground
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reg.update().catch(() => {}); });
    } catch (e) { /* offline or unsupported: the app still works */ }
  });
})();
</script>
</body>
</html>
"""

MANIFEST = {
    "name": "시약선 노트",
    "short_name": "시약선 노트",
    "description": "임신테스트기 사진에서 대조선 대비 시약선 진하기를 재고 기록해요.",
    "lang": "ko",
    # the app owns only its own page, so other apps in sub-folders of this site
    # (matjip/ …) can be installed separately; "id" keeps the identity of the
    # copy installed back when start_url was "./" (an id resolves against the
    # site's origin, not this folder, hence the repository path)
    "id": "/YoSebChoi/",
    "start_url": "./index.html",
    "scope": "./index.html",
    "display": "standalone",
    "background_color": "#edf1ec",
    "theme_color": "#e6ede7",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SW = """// 시약선 노트 service worker: the app runs from its cached copy; a new
// version installs in the background and waits until the person taps update.
const CACHE = "hcg-notes-__VERSION__";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-180.png", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" })))));
});
self.addEventListener("message", e => { if (e.data === "skip-waiting") self.skipWaiting(); });
self.addEventListener("activate", e => {
  // only old app files are removed; records live in the page's storage, not here
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("hcg-notes-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url), base = new URL("./", self.registration.scope);
  if (req.method !== "GET") return;
  // other apps live in sub-folders of this site (matjip/ …): leave their pages and files alone
  if (url.origin === base.origin && url.pathname.slice(base.pathname.length).includes("/")) return;
  if (req.mode === "navigate") {
    e.respondWith(caches.open(CACHE).then(c => c.match("./index.html")).then(hit => hit || fetch(req)));
    return;
  }
  // icons, Google Fonts: cache first, fill on miss
  e.respondWith(caches.open(CACHE).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") c.put(req, res.clone());
    return res;
  }))));
});
"""


def icon(size, maskable=False):
    """A test strip on the launch-screen colour: white strip, rose handle, faint T, clear C."""
    S = 4 * size  # draw large, then downsample for smooth edges
    im = Image.new("RGB", (S, S))
    # flat, and the same as the manifest background_color, so on Android's launch screen
    # only the strip shows, exactly where the page's splash picks it up
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, S, S], fill=(237, 241, 236))
    scale = 0.74 if maskable else 1.0  # keep content inside the maskable safe zone
    u = S / 512
    def box(x0, y0, x1, y1):
        c = S / 2
        f = lambda v: c + (v * u - c) * scale
        return [f(x0), f(y0), f(x1), f(y1)]
    r = lambda v: v * u * scale
    shadow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(box(70, 226, 442, 336), radius=r(54), fill=60)
    shadow = shadow.filter(ImageFilter.GaussianBlur(r(18)))
    im.paste((150, 168, 158), (0, 0), shadow)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box(52, 196, 460, 316), radius=r(60), fill=(252, 253, 251))
    d.rounded_rectangle(box(340, 196, 460, 316), radius=r(60), fill=(236, 196, 211))
    d.rectangle(box(340, 196, 380, 316), fill=(236, 196, 211))
    d.rounded_rectangle(box(160, 218, 322, 294), radius=r(12), fill=(234, 238, 233))
    d.rectangle(box(212, 218, 230, 294), fill=(222, 190, 203))   # T, faint
    d.rectangle(box(268, 218, 286, 294), fill=(152, 84, 112))    # C
    return im.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    body = SRC.read_text(encoding="utf-8")
    icons = {"icon-180.png": icon(180), "icon-192.png": icon(192), "icon-512.png": icon(512),
             "icon-maskable-512.png": icon(512, maskable=True)}
    h = hashlib.sha256((HEAD + body + TAIL + SW + json.dumps(MANIFEST)).encode())
    for name, im in icons.items():
        im.save(OUT / name)
        h.update((OUT / name).read_bytes())
    # the version follows the content (icons included), so every real change offers an update
    version = h.hexdigest()[:8]
    (OUT / "index.html").write_text((HEAD + body + TAIL).replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print("built version", version, "->", *sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
