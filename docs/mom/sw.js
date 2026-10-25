// 예비맘 혜택 지도 service worker: the app shell from cache, the data fresh when online.
const CACHE = "mom-map-7286d053";
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
  if (url.origin === location.origin && /(\.webmanifest|\/icon-[^/]*\.png)$/.test(url.pathname)) {
    e.respondWith(fetch(req, { cache: "no-store" }).catch(() => caches.match(req)));
    return;
  }
  if (/tile\.openstreetmap|nominatim|kakao/.test(url.hostname)) return;
  e.respondWith(caches.open(CACHE).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") c.put(req, res.clone());
    return res;
  }))));
});
