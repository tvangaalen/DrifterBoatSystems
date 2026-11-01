// The Settings page: load/save, Float protection switch and the database status.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function applyFloatSetting(enabled) {
  settingsFloatEnabled = !!enabled;
  const button = $('settingFloatToggle');
  button.textContent = enabled ? 'ON' : 'OFF';
  button.classList.toggle('on', enabled);
  button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  $('floatSettings').hidden = !enabled;
}
function toggleFloatSetting() {
  applyFloatSetting(!settingsFloatEnabled);
  $('settingsStatus').textContent = '';
}
async function loadSettings() {
  $('settingsStatus').textContent = '';
  try {
    const r = await fetch('/api/settings', { cache: 'no-store' }),
      s = await r.json();
    if (!r.ok) throw Error(s.detail || 'Could not load settings');
    $('settingAcLimit').value = s.default_ac_limit;
    $('settingFloatCellMv').value = Number(s.float_cell_trigger_mv ?? 3500);
    $('settingBulkCellMv').value = Number(s.float_cell_resume_mv ?? 3420);
    $('settingBmsInterval').value = s.bms_refresh_interval;
    $('settingBmsRetry').value = s.bms_connection_retry_seconds;
    $('settingBalancerInterval').value = s.balancer_refresh_interval ?? 30;
    $('settingBalancerRetry').value = s.balancer_connection_retry_seconds ?? 30;
    $('settingBmsPopup').value = s.bms_popup_seconds;
    $('settingHistoryDays').value = s.history_retention_days ?? 7;
    applyFloatSetting(s.float_protection_enabled);
    loadDbStatus();
  } catch (e) {
    $('settingsStatus').textContent = e.message;
  }
}
const fmtBytes = b =>
  b == null
    ? '—'
    : b >= 1073741824
      ? (b / 1073741824).toFixed(2) + ' GB'
      : b >= 1048576
        ? Math.round(b / 1048576) + ' MB'
        : Math.round(b / 1024) + ' KB';
async function loadDbStatus() {
  const box = $('dbStatus');
  try {
    const r = await fetch('/api/history/status', { cache: 'no-store' }),
      d = await r.json();
    if (!r.ok) throw Error(d.detail || 'Could not load the database status');
    const when = v =>
        v
          ? new Date(v).toLocaleString('en-GB', {
              day: '2-digit',
              month: '2-digit',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              hourCycle: 'h23'
            })
          : '—',
      num = v => (v == null ? '—' : Number(v).toLocaleString('en-GB'));
    const rows = [
      ['Database size', fmtBytes(d.size_bytes) + (d.wal_bytes ? ` + ${fmtBytes(d.wal_bytes)} log` : '')],
      ['Records', num(d.records)],
      ...Object.entries(d.by_source || {})
        .sort()
        .map(([source, count]) => [`· ${source}`, num(count)]),
      ['Oldest record', when(d.oldest)],
      ['Newest record', when(d.newest)],
      ['Stored period', d.span_days == null ? '—' : `${d.span_days.toFixed(1)} of ${d.retention_days} days`],
      ['Growth', d.records_per_day == null ? '—' : `${num(Math.round(d.records_per_day))} records/day`],
      [`Expected size at ${d.retention_days} days`, fmtBytes(d.projected_bytes_at_retention)],
      ['Reusable space in file', fmtBytes(d.reusable_bytes)],
      ['Chart cache in memory', `${num(d.chart_cache.bms)} BMS · ${num(d.chart_cache.dashboard)} dashboard`],
      ['Free disk space', fmtBytes(d.disk_free_bytes)]
    ];
    box.innerHTML = rows.map(([label, value]) => `<span>${esc(label)}</span><strong>${esc(value)}</strong>`).join('');
  } catch (e) {
    box.textContent = e.message;
  }
}
async function saveSettings() {
  const acRaw = $('settingAcLimit').value.trim(),
    cellMvRaw = $('settingFloatCellMv').value.trim(),
    bulkCellMvRaw = $('settingBulkCellMv').value.trim(),
    bmsRaw = $('settingBmsInterval').value.trim(),
    retryRaw = $('settingBmsRetry').value.trim(),
    balancerIntervalRaw = $('settingBalancerInterval').value.trim(),
    balancerRetryRaw = $('settingBalancerRetry').value.trim(),
    popupRaw = $('settingBmsPopup').value.trim(),
    historyRaw = $('settingHistoryDays').value.trim();
  const ac = Number(acRaw),
    cellMv = Number(cellMvRaw),
    bulkCellMv = Number(bulkCellMvRaw),
    bmsInterval = Number(bmsRaw),
    bmsRetry = Number(retryRaw),
    balancerInterval = Number(balancerIntervalRaw),
    balancerRetry = Number(balancerRetryRaw),
    bmsPopup = Number(popupRaw),
    historyDays = Number(historyRaw);
  const status = $('settingsStatus');
  if (!/^\d{1,2}$/.test(acRaw) || ac < 3 || ac > 15) {
    status.textContent = 'Default AC limit must be between 3 and 15';
    return;
  }
  if (cellMvRaw === '' || !Number.isFinite(cellMv) || cellMv < 3300 || cellMv > 3650) {
    status.textContent = 'The cell-voltage Float trigger must be between 3300 and 3650 mV';
    return;
  }
  if (bulkCellMvRaw === '' || !Number.isFinite(bulkCellMv) || bulkCellMv < 3200 || bulkCellMv > 3650) {
    status.textContent = 'The cell-voltage Bulk level must be between 3200 and 3650 mV';
    return;
  }
  if (bulkCellMv > cellMv - 30) {
    const message = 'The cell-voltage Bulk level must be at least 30 mV below the Float trigger';
    status.textContent = message;
    showBmsInfo('Invalid Float protection settings', message, 0);
    return;
  }
  if (!/^\d{1,3}$/.test(bmsRaw) || bmsInterval < 5 || bmsInterval > 300) {
    status.textContent = 'BMS refresh interval must be between 5 and 300 seconds';
    return;
  }
  if (!/^\d{1,3}$/.test(retryRaw) || bmsRetry < 1 || bmsRetry > 300) {
    status.textContent = 'BMS connection retry must be between 1 and 300 seconds';
    return;
  }
  if (!/^\d{1,3}$/.test(balancerIntervalRaw) || balancerInterval < 5 || balancerInterval > 300) {
    status.textContent = 'Balancer refresh interval must be between 5 and 300 seconds';
    return;
  }
  if (!/^\d{1,3}$/.test(balancerRetryRaw) || balancerRetry < 5 || balancerRetry > 300) {
    status.textContent = 'Balancer connection retry must be between 5 and 300 seconds';
    return;
  }
  if (!/^\d{1,2}$/.test(popupRaw) || bmsPopup < 1 || bmsPopup > 60) {
    status.textContent = 'BMS pop-up duration must be between 1 and 60 seconds';
    return;
  }
  if (!/^\d{1,3}$/.test(historyRaw) || historyDays < 1 || historyDays > 365) {
    status.textContent = 'Save history period must be between 1 and 365 days';
    return;
  }
  status.textContent = 'Saving…';
  try {
    const payload = {
      default_ac_limit: ac,
      float_protection_enabled: settingsFloatEnabled,
      float_cell_trigger_mv: cellMv,
      float_cell_resume_mv: bulkCellMv,
      bms_refresh_interval: bmsInterval,
      bms_popup_seconds: bmsPopup,
      bms_connection_retry_seconds: bmsRetry,
      balancer_refresh_interval: balancerInterval,
      balancer_connection_retry_seconds: balancerRetry,
      history_retention_days: historyDays
    };
    const r = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
      saved = await r.json();
    if (!r.ok) throw Error(saved.detail || 'Could not save settings');
    state.settings = saved;
    status.textContent = 'Settings saved';
  } catch (e) {
    status.textContent = e.message;
  }
}
