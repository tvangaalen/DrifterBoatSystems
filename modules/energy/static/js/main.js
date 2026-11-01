// Start-up: resize and swipe handlers, the clock, the polling timers and the service worker.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

window.addEventListener('resize', () => {
  if (currentPage !== 'history') return;
  clearTimeout(historyResizeTimer);
  historyResizeTimer = setTimeout(renderHistory, 160);
});
let swipeStartX = null,
  swipeStartY = null;
document.addEventListener(
  'touchstart',
  e => {
    if (e.touches.length !== 1) return;
    if (e.target.closest && e.target.closest('input,select,textarea,.no-swipe,.rep-table-wrap')) {
      swipeStartX = swipeStartY = null;
      return;
    }
    swipeStartX = e.touches[0].clientX;
    swipeStartY = e.touches[0].clientY;
  },
  { passive: true }
);
document.addEventListener(
  'touchend',
  e => {
    if (swipeStartX == null || !e.changedTouches.length) return;
    const dx = e.changedTouches[0].clientX - swipeStartX,
      dy = e.changedTouches[0].clientY - swipeStartY;
    swipeStartX = swipeStartY = null;
    if (Math.abs(dx) < 70 || Math.abs(dx) <= Math.abs(dy) * 1.5) return;
    if (currentPage === 'history') {
      const tabs = ['sources', 'storage', 'loads', 'alarms', 'reports'],
        at = tabs.indexOf(historyActiveTab),
        to = dx < 0 ? at + 1 : at - 1;
      if (at >= 0 && to >= 0 && to < tabs.length) {
        showHistoryTab(tabs[to]);
        return;
      }
    }
    const pages = ['dashboard', 'bms', 'history', 'settings'],
      index = pages.indexOf(currentPage),
      next = dx < 0 ? index + 1 : index - 1;
    if (next >= 0 && next < pages.length) showPage(pages[next]);
  },
  { passive: true }
);
function tick() {
  $('clock').textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}
applyTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
tick();
setInterval(tick, 30000);
fetch('/api/version', { cache: 'no-store' })
  .then(r => r.json())
  .then(v => {
    appVersion = v.version;
  })
  .catch(() => {});
refresh();
setInterval(refresh, 1000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
