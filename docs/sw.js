// 시약선 노트 service worker: the app runs from its cached copy; a new
// version installs in the background and waits until the person taps update.
const CACHE = "hcg-notes-0f995aa2";
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
