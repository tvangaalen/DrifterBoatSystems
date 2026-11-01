// History: loading the chart data from the server cache and the Update button.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function applyHistoryData(data, shiftToLatest = false) {
  const oldMax = historyRangeMax,
    oldDuration = historyRangeStart != null && historyRangeEnd != null ? historyRangeEnd - historyRangeStart : null,
    wasAtLatest = historyRangeEnd == null || oldMax == null || Math.abs(historyRangeEnd - oldMax) < 120000;
  historyAllPoints = data.bms || [];
  dashboardHistoryAllPoints = data.dashboard || [];
  const stamps = [...historyAllPoints, ...dashboardHistoryAllPoints].map(point => Date.parse(point.captured_at)).filter(Number.isFinite);
  historyRangeMin = Math.min(...stamps);
  historyRangeMax = Math.max(...stamps);
  if (shiftToLatest && oldDuration != null) {
    historyRangeEnd = historyRangeMax;
    historyRangeStart = Math.max(historyRangeMin, historyRangeEnd - oldDuration);
  } else {
    historyRangeStart =
      historyRangeStart == null ? Math.max(historyRangeMin, historyRangeMax - 4 * 3600000) : Math.max(historyRangeMin, historyRangeStart);
    historyRangeEnd = wasAtLatest ? historyRangeMax : Math.min(historyRangeMax, historyRangeEnd);
  }
  if (historyRangeStart >= historyRangeEnd) historyRangeStart = historyRangeMin;
  const startInput = $('historyRangeStart'),
    endInput = $('historyRangeEnd'),
    minSeconds = Math.floor(historyRangeMin / 1000),
    maxSeconds = Math.ceil(historyRangeMax / 1000);
  [startInput, endInput].forEach(input => {
    input.min = String(minSeconds);
    input.max = String(maxSeconds);
  });
  startInput.value = String(Math.floor(historyRangeStart / 1000));
  endInput.value = String(Math.ceil(historyRangeEnd / 1000));
  historyMaxHours = Number(data.max_hours);
  historyLoaded = true;
  applyHistoryRange();
}
async function requestHistoryData(refresh = false) {
  const r = await fetch(`/api/history/chart-data${refresh ? '/update' : ''}`, { method: refresh ? 'POST' : 'GET', cache: 'no-store' }),
    data = await r.json();
  if (!r.ok) throw Error(data.detail || 'Could not load server history cache');
  applyHistoryData(data, refresh);
}
async function loadHistory() {
  if (historyLoaded) {
    renderHistory();
    return;
  }
  try {
    await requestHistoryData(false);
  } catch (e) {
    $('historyCount').textContent = e.message;
  }
}
async function updateHistory() {
  if (historyUpdating) return;
  historyUpdating = true;
  const button = $('historyUpdate');
  button.disabled = true;
  button.textContent = 'Updating…';
  try {
    await requestHistoryData(true);
    button.textContent = 'Up to date';
    setTimeout(() => {
      button.textContent = 'Update';
      button.disabled = false;
    }, 1400);
  } catch (e) {
    button.textContent = 'Failed';
    $('historyCount').textContent = e.message;
    setTimeout(() => {
      button.textContent = 'Update';
      button.disabled = false;
    }, 1800);
  } finally {
    historyUpdating = false;
  }
}
