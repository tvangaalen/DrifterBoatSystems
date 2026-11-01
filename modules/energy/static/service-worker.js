// Offline shell for the installed iPhone PWA: network first, the cached copy when the server cannot be reached.
// A new CACHE name (it carries the version) is what makes an installed PWA drop the old files and load the new ones.
// SHELL lists everything index.html loads; tests/test_release.py checks that it stays in step with the page.
const CACHE = 'mastervolt-v2.1.2-shell';
const SHELL = [
  '/',
  '/static/index.html',
  '/static/css/app.css',
  '/static/js/core.js',
  '/static/js/dashboard.js',
  '/static/js/controls.js',
  '/static/js/shell.js',
  '/static/js/settings.js',
  '/static/js/bms.js',
  '/static/js/history-data.js',
  '/static/js/charts.js',
  '/static/js/history-render.js',
  '/static/js/reports.js',
  '/static/js/history-view.js',
  '/static/js/pies.js',
  '/static/js/history-load.js',
  '/static/js/main.js',
  '/manifest.webmanifest',
  '/static/icons/app-icon.svg'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return; // live data is never cached
  e.respondWith(
    fetch(e.request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return response;
      })
      .catch(() => caches.match(e.request).then(cached => cached || caches.match('/')))
  );
});
