// 냉장고 셰프 service worker: the app shell from cache, refreshed in the background.
const CACHE = "fridge-chef-d99e00e0";
const SHELL = ["./", "./index.html", "./recipes.js", "./vendor/anthropic-sdk.mjs"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("fridge-chef-") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;   // the AI and the fonts go to the network
  // the app's identity (manifest, icons) always comes from the network
  if (/(\.webmanifest|\/icon-[^/]*\.png)$/.test(url.pathname)) { e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req))); return; }
  // network first, so a new version shows on the next opening; the cached copy when offline
  e.respondWith(fetch(req).then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req, { ignoreSearch: true })));
});
