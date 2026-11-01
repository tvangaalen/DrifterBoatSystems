// History: the time range (presets, custom, zoom) and fetching the dense view of a short period.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function renderHistory() {
  scheduleContributions();
  const has = historyPoints.length > 0;
  $('historyEmpty').hidden = has;
  $('historyCharts').hidden = !has;
  if (historyActiveTab === 'storage' && has) {
    const remainingKey = historyLegendSelection.remaining || 'total',
      loadKey = historyLegendSelection.storageLoad || 'total';
    drawStackedHistoryChart($('historyRemaining'), historySnapshots('remaining'), ' Ah', historySeries.slice(1), remainingKey, false, {
      min: 0,
      max: 1000,
      leftUnit: ' kWh',
      leftScale: NOMINAL_BANK_VOLTAGE_V / 1000,
      leftDecimals: 1,
      right: { unit: '%', scale: 100 / BANK_CAPACITY_AH, decimals: 0, ticks: [0, 0.25, 0.5, 0.75, 1].map(f => f * BANK_CAPACITY_AH) },
      guides: [BANK_CAPACITY_AH]
    });
    setHistoryLegend('historyRemainingLegend', 'remaining', historySeries.slice(1));
    const loadVeff = bmsEffectiveVoltage();
    drawStackedHistoryChart($('historyLoad'), historySnapshotsPower(), ' W', historySeries.slice(1), loadKey, false, {
      right: { unit: ' A', scale: 1 / loadVeff }
    });
    setHistoryLegend('historyLoadLegend', 'storageLoad', historySeries.slice(1));
    [1, 2, 3].forEach(index => {
      const chartKey = `cellVoltage${index}`,
        selected = historyLegendSelection[chartKey] || 'total';
      drawCellVoltageChart($(`historyVoltage${index}`), bmsCellSnapshots(`BATTERY ${index}`), selected);
      setCellVoltageLegend(`historyVoltageLegend${index}`, chartKey);
    });
  } else if (historyActiveTab === 'sources') renderSourcesHistory();
  else if (historyActiveTab === 'loads') renderLoadsHistory();
  else if (historyActiveTab === 'alarms') renderAlarmsHistory();
  const allPoints = [...historyPoints, ...dashboardHistoryPoints];
  let from = Infinity,
    to = -Infinity;
  allPoints.forEach(point => {
    const stamp = Date.parse(point.captured_at);
    if (Number.isFinite(stamp)) {
      from = Math.min(from, stamp);
      to = Math.max(to, stamp);
    }
  });
  const zoomLabel = Number.isInteger(historyZoomHours) ? historyZoomHours : historyZoomHours.toFixed(2);
  $('historyCount').textContent = allPoints.length
    ? `${zoomLabel} hrs · ${historyBmsCount} BMS · ${historyDashboardCount} Dashboard · ${new Date(from).toLocaleDateString()} – ${new Date(to).toLocaleDateString()}`
    : 'No history stored yet.';
}
function historyRangeDateTime(value) {
  const date = new Date(value);
  return `${String(date.getDate()).padStart(2, '0')}/${String(date.getMonth() + 1).padStart(2, '0')} ${date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`;
}
let historyZoomStart = null,
  historyZoomEnd = null;
function historyView() {
  return historyZoomStart != null && historyZoomEnd != null
    ? { start: historyZoomStart, end: historyZoomEnd }
    : { start: historyRangeStart, end: historyRangeEnd };
}
function syncHistoryRangeUi() {
  const span = historyRangeEnd - historyRangeStart,
    full = historyRangeMax - historyRangeMin,
    atEnd = Math.abs(historyRangeEnd - historyRangeMax) < 120000;
  document.querySelectorAll('#historyRangePresets button').forEach(button => {
    const hours = Number(button.dataset.hours);
    button.disabled = hours > 0 && hours * 3600000 > full + 120000;
    button.classList.toggle(
      'active',
      atEnd &&
        (hours === 0
          ? Math.abs(historyRangeStart - historyRangeMin) < 120000
          : Math.abs(span - hours * 3600000) < Math.max(120000, hours * 36000))
    );
  });
  $('historyRangeStartValue').textContent = historyRangeDateTime(historyRangeStart);
  $('historyRangeEndValue').textContent = historyRangeDateTime(historyRangeEnd);
  const view = historyView();
  $('historyZoomStartValue').textContent = historyRangeDateTime(view.start);
  $('historyZoomEndValue').textContent = historyRangeDateTime(view.end);
  $('historyRangeZoomToggle').classList.toggle('active', historyZoomStart != null);
}
function applyHistoryRange(keepZoom = false) {
  if (!keepZoom) {
    historyZoomStart = historyZoomEnd = null;
    const zs = $('historyZoomStart'),
      ze = $('historyZoomEnd'),
      low = String(Math.floor(historyRangeStart / 1000)),
      high = String(Math.ceil(historyRangeEnd / 1000));
    zs.min = ze.min = low;
    zs.max = ze.max = high;
    zs.value = low;
    ze.value = high;
  }
  const view = historyView();
  syncHistoryRangeUi();
  historyPoints = historyAllPoints.filter(point => {
    const time = Date.parse(point.captured_at);
    return time >= view.start && time <= view.end;
  });
  dashboardHistoryPoints = dashboardHistoryAllPoints.filter(point => {
    const time = Date.parse(point.captured_at);
    return time >= view.start && time <= view.end;
  });
  historyZoomHours = (view.end - view.start) / 3600000;
  historyBmsCount = historyPoints.length;
  historyDashboardCount = dashboardHistoryPoints.length;
  $('historyRangeStartLabel').textContent = historyRangeDateTime(view.start);
  $('historyRangeEndLabel').textContent = historyRangeDateTime(view.end);
  const baseHours = (historyRangeEnd - historyRangeStart) / 3600000,
    hoursText = h => h.toFixed(h < 10 ? 1 : 0);
  $('historyRangeDuration').textContent =
    historyZoomStart != null
      ? `${hoursText(historyZoomHours)} hours · zoomed in from ${hoursText(baseHours)}`
      : `${hoursText(historyZoomHours)} hours selected`;
  renderHistory();
  scheduleDenseHistoryView(view);
}
let historyDenseTimer = null,
  historyDenseSeq = 0;
function scheduleDenseHistoryView(view) {
  historyDenseSeq++;
  const seq = historyDenseSeq;
  clearTimeout(historyDenseTimer);
  // The broad fetch behind historyAllPoints is index-sampled across the whole retention period (fine for multi-day
  // views, but a short preset/zoom can then land on an uneven, sparse slice of it and render as broken-looking
  // disconnected bars). For a short-enough view, quietly fetch that exact window at full resolution and re-render.
  if ((view.end - view.start) / 3600000 > 48) return;
  historyDenseTimer = setTimeout(() => refreshDenseHistoryView(view, seq), 120);
}
async function refreshDenseHistoryView(view, seq) {
  try {
    const hours = Math.max(0.25, (view.end - view.start) / 3600000),
      r = await fetch(`/api/history/chart-data?hours=${hours}`, { cache: 'no-store' }),
      data = await r.json();
    if (!r.ok || seq !== historyDenseSeq) return;
    const within = point => {
        const t = Date.parse(point.captured_at);
        return t >= view.start && t <= view.end;
      },
      bms = (data.bms || []).filter(within),
      dash = (data.dashboard || []).filter(within);
    if (bms.length > historyPoints.length) historyPoints = bms;
    if (dash.length > dashboardHistoryPoints.length) dashboardHistoryPoints = dash;
    historyBmsCount = historyPoints.length;
    historyDashboardCount = dashboardHistoryPoints.length;
    renderHistory();
  } catch (e) {}
}
function changeHistoryRange(handle) {
  const startInput = $('historyRangeStart'),
    endInput = $('historyRangeEnd'),
    minimumGap = 60,
    start = Number(startInput.value),
    end = Number(endInput.value);
  if (handle === 'start' && start > end - minimumGap) startInput.value = String(end - minimumGap);
  if (handle === 'end' && end < start + minimumGap) endInput.value = String(start + minimumGap);
  historyRangeStart = Number(startInput.value) * 1000;
  historyRangeEnd = Number(endInput.value) * 1000;
  applyHistoryRange();
}
function setHistoryPreset(hours) {
  if (historyRangeMax == null || historyRangeMin == null) return;
  historyRangeEnd = historyRangeMax;
  historyRangeStart = hours ? Math.max(historyRangeMin, historyRangeEnd - hours * 3600000) : historyRangeMin;
  $('historyRangeStart').value = String(Math.floor(historyRangeStart / 1000));
  $('historyRangeEnd').value = String(Math.ceil(historyRangeEnd / 1000));
  applyHistoryRange();
}
function showRangePanel(which) {
  const panels = {
    custom: ['historyRangeCustom', 'historyRangeCustomToggle', 'Custom', 'Hide custom'],
    zoom: ['historyRangeZoom', 'historyRangeZoomToggle', 'Zoom', 'Hide zoom']
  };
  Object.entries(panels).forEach(([name, [panelId, buttonId, closed, open]]) => {
    const panel = $(panelId),
      button = $(buttonId),
      show = name === which && panel.hidden;
    panel.hidden = !show;
    button.setAttribute('aria-expanded', String(show));
    button.textContent = show ? open : closed;
  });
}
function toggleHistoryCustom() {
  showRangePanel('custom');
}
function toggleHistoryZoom() {
  showRangePanel('zoom');
}
function changeHistoryZoom(handle) {
  const startInput = $('historyZoomStart'),
    endInput = $('historyZoomEnd'),
    gap = 60;
  let start = Number(startInput.value),
    end = Number(endInput.value);
  if (handle === 'start' && start > end - gap) {
    start = end - gap;
    startInput.value = String(start);
  }
  if (handle === 'end' && end < start + gap) {
    end = start + gap;
    endInput.value = String(end);
  }
  historyZoomStart = start * 1000;
  historyZoomEnd = end * 1000;
  if (historyZoomStart <= historyRangeStart + 1000 && historyZoomEnd >= historyRangeEnd - 1000) historyZoomStart = historyZoomEnd = null;
  applyHistoryRange(true);
}
function resetHistoryZoom() {
  applyHistoryRange();
}
