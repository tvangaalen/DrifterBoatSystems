// History: the donut charts with the totals over the selected period.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

let contribData = null,
  contribKey = '',
  contribTimer = null,
  contribSeq = 0;
const pieTabs = { sources: 'pieSources', storage: 'pieStorage', loads: 'pieLoads', alarms: 'pieAlarms' };
const pieEnergy = wh => (wh >= 1000 ? `${(wh / 1000).toFixed(2)} kWh` : `${Math.round(wh)} Wh`),
  pieWatts = w => `${Math.round(w)} W`,
  pieCount = n => String(n),
  pieHours = seconds => `${(seconds / 3600).toFixed(seconds < 36000 ? 1 : 0)} h`;
function drawDonut(canvas, slices, centerMain, centerSub) {
  const size = 150,
    dpr = Math.min(devicePixelRatio || 1, 2);
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + 'px';
  canvas.style.height = size + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const styles = getComputedStyle(document.documentElement),
    panel = styles.getPropertyValue('--panel').trim() || '#111f2a',
    text = styles.getPropertyValue('--text').trim() || '#e6f1f7',
    muted = styles.getPropertyValue('--muted').trim() || '#8aa0ad',
    line = styles.getPropertyValue('--line').trim() || '#21323d';
  const cx = size / 2,
    cy = size / 2,
    outer = size / 2 - 4,
    inner = outer * 0.6,
    total = slices.reduce((sum, slice) => sum + Math.max(0, slice.value), 0);
  if (total <= 0) {
    ctx.beginPath();
    ctx.arc(cx, cy, outer, 0, Math.PI * 2);
    ctx.arc(cx, cy, inner, Math.PI * 2, 0, true);
    ctx.closePath();
    ctx.fillStyle = line;
    ctx.fill();
  } else {
    let angle = -Math.PI / 2;
    slices.forEach(slice => {
      if (slice.value <= 0) return;
      const sweep = (slice.value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, outer, angle, angle + sweep);
      ctx.arc(cx, cy, inner, angle + sweep, angle, true);
      ctx.closePath();
      ctx.fillStyle = slice.color;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = panel;
      ctx.stroke();
      angle += sweep;
    });
  }
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = text;
  ctx.font = '800 15px system-ui';
  ctx.fillText(centerMain, cx, cy - 5);
  ctx.fillStyle = muted;
  ctx.font = '9px system-ui';
  ctx.fillText(centerSub, cx, cy + 11);
}
function drawPieCard(id, slices, options) {
  const card = $(id),
    total = slices.reduce((sum, slice) => sum + slice.value, 0),
    row = (slice, total_) =>
      `<div class="pie-row"><i style="background:${slice.color}"></i><span class="pie-name">${esc(slice.label)}</span><span class="pie-val">${options.format(slice.value)}</span><span class="pie-pct">${total > 0 ? Math.round((slice.value / total) * 100) : 0}%</span>${slice.sub ? `<span class="pie-sub">${esc(slice.sub)}</span>` : ''}</div>`;
  drawDonut(card.querySelector('.pie-canvas'), slices, options.format(total), options.centerLabel || 'total');
  card.querySelector('.pie-legend').innerHTML =
    slices.map(slice => row(slice)).join('') +
    `<div class="pie-row pie-total"><i></i><span class="pie-name">Total</span><span class="pie-val">${options.format(total)}</span><span class="pie-pct">${total > 0 ? '100%' : '0%'}</span>${options.totalSub ? `<span class="pie-sub">${esc(options.totalSub)}</span>` : ''}</div>`;
  card.querySelector('.pie-note').textContent = options.note || '';
}
function pieMessage(text, isError) {
  const id = pieTabs[historyActiveTab];
  if (!id) return;
  const card = $(id);
  drawDonut(card.querySelector('.pie-canvas'), [], '…', '');
  card.querySelector('.pie-legend').innerHTML = `<div class="pie-msg${isError ? ' error' : ''}">${esc(text)}</div>`;
  card.querySelector('.pie-note').textContent = '';
}
// "Shore power intake" shows the exact energy taken in from shore power over the selected period (summed on the server).
function renderShoreTotal(data, covers) {
  const box = $('shoreIntakeTotal');
  if (!box || !data || !data.shore) return;
  box.innerHTML = `Total kWh intake over the selected period: <strong>${(data.shore.wh / 1000).toFixed(2)} kWh</strong><small>avg ${pieWatts(data.shore.avg_w)} · ${covers(data.sources_covered_seconds)}</small>`;
}
function renderPies() {
  const data = contribData,
    id = pieTabs[historyActiveTab];
  if (!data || !id) return;
  const meta = (list, key) => list.find(item => item.key === key) || { label: key, color: '#888' },
    sum = (rows, pick) => rows.reduce((total, row) => total + pick(row), 0),
    covers = seconds => `Recorded data covers ${pieHours(seconds)} of the ${pieHours(data.span_seconds)} selected`;
  if (historyActiveTab === 'sources' || historyActiveTab === 'loads') {
    const sources = historyActiveTab === 'sources',
      rows = sources ? data.sources : data.consumers,
      list = sources ? sourcePowerMeta : loadMeta;
    drawPieCard(
      id,
      rows.map(row => ({
        label: meta(list, row.key).label,
        color: meta(list, row.key).color,
        value: row.wh,
        sub: `avg ${pieWatts(row.avg_w)}`
      })),
      {
        format: pieEnergy,
        totalSub: `avg ${pieWatts(sum(rows, row => row.avg_w))}`,
        note: covers(sources ? data.sources_covered_seconds : data.consumers_covered_seconds)
      }
    );
    if (sources) renderShoreTotal(data, covers);
  } else if (historyActiveTab === 'storage') {
    const rows = data.batteries;
    drawPieCard(
      id,
      rows.map(row => ({
        label: meta(historySeries, row.key).label,
        color: meta(historySeries, row.key).color,
        value: row.discharge_wh,
        sub: `avg ${pieWatts(row.avg_discharge_w)} · charged ${pieEnergy(row.charge_wh)}`
      })),
      {
        format: pieEnergy,
        totalSub: `avg ${pieWatts(sum(rows, row => row.avg_discharge_w))} · charged ${pieEnergy(sum(rows, row => row.charge_wh))}`,
        note: `${covers(Math.max(...rows.map(row => row.covered_seconds)))} · energy taken in while charging is listed per battery`
      }
    );
  } else if (historyActiveTab === 'alarms') {
    const rows = data.alarms;
    drawPieCard(
      id,
      rows.map(row => ({
        label: meta(alarmBatteryMeta, row.key).label,
        color: meta(alarmBatteryMeta, row.key).color,
        value: row.episodes,
        sub: `${row.samples} alarm sample${row.samples === 1 ? '' : 's'}`
      })),
      {
        format: pieCount,
        centerLabel: 'alarms',
        totalSub: `${sum(rows, row => row.samples)} alarm samples`,
        note: 'An alarm is a run of consecutive alarm samples of one battery'
      }
    );
  }
}
async function fetchContributions(key) {
  const seq = ++contribSeq;
  pieMessage('Calculating…');
  try {
    const url = `/api/history/contributions?start=${encodeURIComponent(new Date(historyView().start).toISOString())}&end=${encodeURIComponent(new Date(historyView().end).toISOString())}`,
      r = await fetch(url, { cache: 'no-store' }),
      data = await r.json();
    if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Could not load the totals');
    if (seq !== contribSeq) return;
    contribData = data;
    contribKey = key;
    renderPies();
  } catch (e) {
    if (seq === contribSeq) pieMessage(e.message, true);
  }
}
function scheduleContributions() {
  if (historyRangeStart == null || historyRangeEnd == null || !pieTabs[historyActiveTab]) return;
  const view = historyView(),
    key = `${Math.round(view.start / 1000)}-${Math.round(view.end / 1000)}`;
  if (contribData && key === contribKey) {
    renderPies();
    return;
  }
  clearTimeout(contribTimer);
  contribTimer = setTimeout(() => fetchContributions(key), 300);
}
