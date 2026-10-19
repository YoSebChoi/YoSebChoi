// 우리 단지 거래 추적 service worker: the app shell from cache, refreshed in the background.
const CACHE = "apt-watch-cd5b63ebdf";
const SHELL = ["./", "./index.html", "./tracker.js", "./data.json"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("apt-watch-") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (/(\.webmanifest|\/icon-[^/]*\.png)$/.test(url.pathname)) { e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req))); return; }
  // network first, so new data shows on the next opening; the cached copy when offline
  e.respondWith(fetch(req).then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req, { ignoreSearch: true })));
});
