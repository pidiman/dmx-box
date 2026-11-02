// Offline shell – API a WebSocket idú vždy na sieť.
const CACHE = "dmxbox-v23";
const SHELL = ["/", "start.html", "start.css", "start.js", "box.html", "box.js", "lights.html", "lights.js", "/ovladanie", "index.html",
  "style.css", "app.js", "manifest.json", "icon.svg", "viz.html", "viz.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api") || url.pathname === "/ws") return;
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
