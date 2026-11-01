// Shared state, the DOM shortcut `$` and the number/power formatters.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

let state = {},
  appVersion = '', // the server's version (GET /api/version), shown in the footer of the Control panel
  busy = false,
  lastGood = null,
  lastFloatEvent = null,
  lastBulkEvent = null,
  settingsFloatEnabled = true,
  currentPage = 'dashboard',
  bmsPollTimer = null,
  bmsDialogTimer = null,
  bmsDialogResolve = null,
  bmsLastCapture = 0,
  bmsManualPending = false,
  bmsIndividualControl = null,
  bmsIndividualProcessing = false,
  bmsIndividualQueue = [],
  bmsAllChargeControl = null,
  bmsAllDischargeControl = null;
const $ = id => document.getElementById(id);
function num(v, d = 1) {
  return v == null ? '—' : Number(v).toFixed(d);
}
function watts(v) {
  if (v == null) return '—';
  v = Math.max(0, Number(v));
  return v >= 1000 ? (v / 1000).toFixed(2) + ' kW' : Math.round(v) + ' W';
}
function frequency(v) {
  return v == null ? '—' : Math.round(Number(v)) + 'hz';
}
function va(x) {
  let b = [];
  if (x.voltage != null) b.push(num(x.voltage, 2) + ' V');
  if (x.current != null) b.push(num(Math.max(0, +x.current), 1) + ' A');
  return b.join(' · ') || '—';
}
