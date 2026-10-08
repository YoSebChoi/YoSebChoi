// 노포 지도 service worker: the app shell is served from cache; the store list
// is fetched fresh when online and falls back to the cached copy offline.
const CACHE = "nopo-map-8c3fe268";
const SHELL = ["./", "./index.html", "./stores.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" })))));
});
self.addEventListener("message", e => { if (e.data === "skip-waiting") self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("nopo-map-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (req.mode === "navigate") {
    e.respondWith(caches.open(CACHE).then(c => c.match("./index.html")).then(hit => hit || fetch(req)));
    return;
  }
  if (url.origin === location.origin && url.pathname.endsWith("/stores.json")) {
    e.respondWith(caches.open(CACHE).then(c => fetch(req).then(res => { if (res.ok) c.put("./stores.json", res.clone()); return res; })
      .catch(() => c.match("./stores.json"))));
    return;
  }
  // the app's identity (manifest, icons) always comes from the network: installing the app reads these,
  // and a stale copy here would install the old icon and launch screen
  if (url.origin === location.origin && /(\.webmanifest|\/icon-[^/]*\.png)$/.test(url.pathname)) {
    e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req)));
    return;
  }
  // map tiles and place search always go to the network; the library and fonts are cached
  if (/tile\.openstreetmap|cartocdn|nominatim/.test(url.hostname)) return;
  e.respondWith(caches.open(CACHE).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") c.put(req, res.clone());
    return res;
  }))));
});
