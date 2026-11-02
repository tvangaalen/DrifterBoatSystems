// Caches only the app shell, so the home-screen app opens instantly. Live data (api/...) is never cached:
// a stale energy or anchor reading must never look current. A new CACHE name makes iPhones load a new version.
const CACHE = "drifter-v0.13.0-shell";
const SHELL = ["./", "app.css", "app.js", "energy.js", "anchor.js", "guard.js", "washer.js", "manifest.webmanifest", "icons/icon.svg", "icons/apple-touch-icon.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.includes("/api/")) return;
  // network first (the boat LAN is fast), the cached shell only when the server cannot be reached
  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(CACHE).then(k => k.put(e.request, c)); return r; }).catch(() => caches.match(e.request)));
});
