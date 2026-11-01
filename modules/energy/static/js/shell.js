// The page shell: light/dark theme and switching between the Control panel, BMS, History and Settings pages.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function applyTheme(theme) {
  const light = theme === 'light';
  document.documentElement.dataset.theme = light ? 'light' : 'dark';
  const button = $('themeToggle');
  button.textContent = light ? '☾' : '☀';
  button.setAttribute('aria-label', light ? 'Switch to Dark UI' : 'Switch to Light UI');
  button.title = button.getAttribute('aria-label');
  button.setAttribute('aria-pressed', light ? 'true' : 'false');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = light ? '#ffffff' : '#071017';
  if (typeof historyLoaded !== 'undefined' && historyLoaded) requestAnimationFrame(renderHistory);
}
function toggleTheme() {
  const light = document.documentElement.dataset.theme === 'light';
  const next = light ? 'dark' : 'light';
  try {
    localStorage.setItem('mastervolt-theme', next);
  } catch (e) {}
  applyTheme(next);
}
function showPage(page) {
  currentPage = page;
  $('overviewPage').hidden = page !== 'dashboard';
  $('bmsPage').hidden = page !== 'bms';
  $('historyPage').hidden = page !== 'history';
  $('settingsPage').hidden = page !== 'settings';
  $('navOverview').classList.toggle('active', page === 'dashboard');
  $('navBms').classList.toggle('active', page === 'bms');
  $('navHistory').classList.toggle('active', page === 'history');
  $('navSettings').classList.toggle('active', page === 'settings');
  if (bmsPollTimer) {
    clearInterval(bmsPollTimer);
    bmsPollTimer = null;
  }
  if (page === 'settings') loadSettings();
  if (page === 'bms') {
    loadBms(true);
    bmsPollTimer = setInterval(() => loadBms(false), 2000);
  }
  if (page === 'history') loadHistory();
  window.scrollTo(0, 0);
}
