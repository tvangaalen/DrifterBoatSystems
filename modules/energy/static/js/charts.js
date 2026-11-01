// History: canvas drawing - time axis, line and stacked-area charts, cell-voltage charts and the alarm timeline.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function timeAxisTicks(minX, maxX, pw) {
  // Whole time units only: hours (half hours minor) up to a day or two, days (half days minor) beyond that, weeks (days minor)
  // for very long periods, and 10 minutes (5 minutes minor) when zoomed in far.
  const HOUR = 3600000,
    DAY = 86400000,
    span = maxX - minX,
    major = [],
    minor = [];
  if (!(span > 0) || !Number.isFinite(span)) return { major, minor, level: 'hour', unit: HOUR };
  const level = span <= 5400000 ? 'min' : (pw * HOUR) / span >= 8 ? 'hour' : (pw * DAY) / span >= 8 ? 'day' : 'week',
    unit = { min: 600000, hour: HOUR, day: DAY, week: 7 * DAY }[level],
    first = new Date(minX);
  const push = (t, isMajor) => {
    if (t >= minX && t <= maxX) (isMajor ? major : minor).push(t);
  };
  if (level === 'min') {
    first.setMinutes(Math.floor(first.getMinutes() / 5) * 5, 0, 0);
    for (let t = first.getTime(); t <= maxX; t += 300000) push(t, new Date(t).getMinutes() % 10 === 0);
  } else if (level === 'hour') {
    first.setMinutes(first.getMinutes() >= 30 ? 30 : 0, 0, 0);
    for (let t = first.getTime(); t <= maxX; t += 1800000) push(t, new Date(t).getMinutes() === 0);
  } else if (level === 'day') {
    const d = new Date(first.getFullYear(), first.getMonth(), first.getDate(), first.getHours() >= 12 ? 12 : 0);
    for (; d.getTime() <= maxX; d.setHours(d.getHours() + 12)) push(d.getTime(), d.getHours() === 0);
  } else {
    const d = new Date(first.getFullYear(), first.getMonth(), first.getDate());
    for (; d.getTime() <= maxX; d.setDate(d.getDate() + 1)) push(d.getTime(), d.getDay() === 1);
  }
  const minorGap = { min: 300000, hour: 1800000, day: DAY / 2, week: DAY }[level];
  return { major, minor: (pw * minorGap) / span >= 3.5 ? minor : [], level, unit };
}
function timeAxisLabel(t, level) {
  const d = new Date(t),
    p = n => String(n).padStart(2, '0');
  return level === 'day' || level === 'week' || (level === 'hour' && d.getHours() === 0 && d.getMinutes() === 0)
    ? `${p(d.getDate())}/${p(d.getMonth() + 1)}`
    : `${p(d.getHours())}:${p(d.getMinutes())}`;
}
function drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height) {
  const color = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim(),
    span = maxX - minX,
    { major, minor, level, unit } = timeAxisTicks(minX, maxX, pw),
    base = plot.top + ph,
    xAt = t => plot.left + ((t - minX) / (span || 1)) * pw;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1;
  ctx.font = '9px system-ui';
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  ctx.beginPath();
  minor.forEach(t => {
    const px = Math.round(xAt(t)) + 0.5;
    ctx.moveTo(px, base);
    ctx.lineTo(px, base + 3);
  });
  major.forEach(t => {
    const px = Math.round(xAt(t)) + 0.5;
    ctx.moveTo(px, base);
    ctx.lineTo(px, base + 6);
  });
  ctx.stroke();
  const steps = { min: [1, 3, 6], hour: [1, 2, 3, 4, 6, 12, 24], day: [1, 2, 3, 5, 7, 10, 14, 30], week: [1, 2, 4, 8] }[level],
    need = Math.ceil(46 / Math.max(1e-6, (pw * unit) / (span || 1))),
    step = steps.find(s => s >= need) || steps.at(-1);
  const wanted = major.filter((t, index) => {
    const d = new Date(t);
    return level === 'min'
      ? (d.getMinutes() / 10) % step === 0
      : level === 'hour'
        ? d.getHours() % step === 0
        : level === 'day'
          ? Math.floor((t - d.getTimezoneOffset() * 60000) / 86400000) % step === 0
          : index % step === 0;
  });
  let edge = -1e9;
  const put = (t, label) => {
    const w = ctx.measureText(label).width,
      left = Math.max(2, Math.min(width - 2 - w, xAt(t) - w / 2));
    if (left < edge + 5) return;
    ctx.fillText(label, left, base + 8);
    edge = left + w;
  };
  if (major.length === 0 && minor.length === 0) {
    [minX, maxX].forEach(t => {
      const d = new Date(t);
      put(t, `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`);
    });
  } else wanted.forEach(t => put(t, timeAxisLabel(t, level)));
  ctx.restore();
}
function niceStep(raw) {
  const magnitude = 10 ** Math.floor(Math.log10(raw || 1)),
    n = raw / magnitude;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * magnitude;
}
// `right` (optional) puts a second set of series on a right-hand axis: { series, meta, min, max, ticks, unit }.
function drawHistoryChart(canvas, series, unit, meta = historySeries, axis = null, zeroBase = false, right = null) {
  const box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    line = styles.getPropertyValue('--line').trim(),
    plot = { left: 48, right: right ? 44 : 8, top: 9, bottom: 27 },
    all = meta.flatMap(s => series[s.key] || []);
  if (!all.length) return;
  let minX = Infinity,
    maxX = -Infinity,
    rawMin = Infinity,
    rawMax = -Infinity;
  all.forEach(point => {
    minX = Math.min(minX, point[0]);
    maxX = Math.max(maxX, point[0]);
    rawMin = Math.min(rawMin, point[1]);
    rawMax = Math.max(rawMax, point[1]);
  });
  const zeroStep = zeroBase ? niceStep(Math.max(1, rawMax) / 4) : 1,
    pad = (rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.1, 1)) * 0.12,
    minY = axis ? axis.min : zeroBase ? Math.min(0, rawMin) : unit === ' W' && rawMin >= 0 ? 0 : rawMin - pad,
    maxY = axis ? axis.max : zeroBase ? Math.max(1, Math.ceil((rawMax * 1.02) / zeroStep) * zeroStep) : rawMax + pad,
    pw = width - plot.left - plot.right,
    ph = height - plot.top - plot.bottom,
    x = v => plot.left + ((v - minX) / (maxX - minX || 1)) * pw,
    y = v => plot.top + ((maxY - v) / (maxY - minY || 1)) * ph,
    decimals = zeroBase ? (zeroStep < 1 ? 1 : 0) : unit === ' V' ? 1 : 0;
  ctx.font = axis ? '8px system-ui' : '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  const ticks = axis
    ? axis.ticks
    : zeroBase
      ? Array.from({ length: Math.round((maxY - minY) / zeroStep) + 1 }, (_, i) => maxY - i * zeroStep)
      : Array.from({ length: 5 }, (_, i) => maxY - ((maxY - minY) * i) / 4);
  ticks.forEach(value => {
    const py = y(value);
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(axis?.labels?.[value] ?? `${value.toFixed(decimals)}${unit}`, plot.left - 5, py);
  });
  const y2 = v => plot.top + ((right.max - Math.min(right.max, Math.max(right.min, v))) / (right.max - right.min)) * ph;
  if (right) {
    ctx.save();
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    right.ticks.forEach(value => {
      const py = y2(value);
      ctx.beginPath();
      ctx.moveTo(width - plot.right, py);
      ctx.lineTo(width - plot.right + 3, py);
      ctx.stroke();
      ctx.fillText(`${value}${right.unit}`, width - plot.right + 5, py);
    });
    ctx.restore();
  }
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.left, plot.top - 3, pw, ph + 6);
  ctx.clip();
  meta.forEach(item => {
    const points = historySample(series[item.key] || [], Math.max(300, Math.floor(pw * 2)));
    if (!points.length) return;
    ctx.beginPath();
    points.forEach((point, i) => {
      const px = x(point[0]),
        py = y(point[1]);
      if (!i) ctx.moveTo(px, py);
      else {
        if (axis?.step) ctx.lineTo(px, y(points[i - 1][1]));
        ctx.lineTo(px, py);
      }
    });
    ctx.strokeStyle = item.color;
    ctx.lineWidth = item.width || 1.5;
    ctx.globalAlpha = item.key === 'total' ? 1 : 0.82;
    ctx.stroke();
  });
  if (right)
    right.meta.forEach(item => {
      const points = historySample(right.series[item.key] || [], Math.max(300, Math.floor(pw * 2)));
      if (!points.length) return;
      ctx.beginPath();
      points.forEach((point, i) => (i ? ctx.lineTo(x(point[0]), y2(point[1])) : ctx.moveTo(x(point[0]), y2(point[1]))));
      ctx.strokeStyle = item.color;
      ctx.lineWidth = item.width || 1.5;
      ctx.globalAlpha = 0.9;
      ctx.stroke();
    });
  ctx.restore();
  ctx.globalAlpha = 1;
}
function smoothPoints(points, steps = 5) {
  // Samples the same mid-point quadratic curve the canvas would draw, so area edges and the total line coincide.
  if (points.length < 3) return points.slice();
  const out = [points[0]];
  let from = points[0];
  for (let i = 1; i < points.length - 1; i++) {
    const control = points[i],
      next = points[i + 1],
      mid = [(control[0] + next[0]) / 2, (control[1] + next[1]) / 2];
    for (let s = 1; s <= steps; s++) {
      const t = s / steps,
        a = (1 - t) * (1 - t),
        b = 2 * (1 - t) * t,
        c = t * t;
      out.push([a * from[0] + b * control[0] + c * mid[0], a * from[1] + b * control[1] + c * mid[1]]);
    }
    from = mid;
  }
  out.push(points[points.length - 1]);
  return out;
}
function drawStackedHistoryChart(
  canvas,
  snapshots,
  unit,
  meta = historySeries.slice(1),
  selectedKey = 'total',
  showAverage = false,
  axis = null
) {
  const box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  if (!snapshots.length) return;
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    grid = styles.getPropertyValue('--line').trim(),
    plot = { left: 48, right: axis && axis.right ? 44 : 8, top: 9, bottom: 27 },
    pw = width - plot.left - plot.right,
    ph = height - 9 - 27,
    columns = historySample(snapshots, Math.max(40, Math.floor(pw / 4))),
    minX = columns[0].time,
    maxX = columns[columns.length - 1].time;
  const selectedIndex = meta.findIndex(item => item.key === selectedKey),
    visibleValues = point => (selectedIndex >= 0 ? [point.values[selectedIndex] ?? 0] : point.values);
  let minY = 0,
    maxY = 0;
  columns.forEach(point => {
    const values = visibleValues(point),
      positive = values.filter(v => v > 0).reduce((a, b) => a + b, 0),
      negative = values.filter(v => v < 0).reduce((a, b) => a + b, 0),
      total = values.reduce((a, b) => a + b, 0);
    minY = Math.min(minY, negative, total);
    maxY = Math.max(maxY, positive, total);
  });
  const periodTotals = snapshots.map(point => visibleValues(point).reduce((a, b) => a + b, 0)),
    average = periodTotals.reduce((a, b) => a + b, 0) / (periodTotals.length || 1),
    pad = (maxY - minY || 1) * 0.1;
  if (unit === ' Ah' || minY >= 0) minY = 0;
  else minY -= pad;
  maxY += pad;
  if (axis && axis.min != null) minY = axis.min;
  if (axis && axis.max != null) maxY = axis.max;
  const x = v => plot.left + ((v - minX) / (maxX - minX || 1)) * pw,
    y = v => plot.top + ((maxY - v) / (maxY - minY || 1)) * ph,
    decimals = unit === ' V' ? 1 : 0;
  ctx.font = '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  const leftTicks =
      axis && axis.leftStep
        ? (() => {
            const step = axis.leftStep,
              arr = [];
            for (let v = Math.ceil(minY / step) * step; v <= maxY + 1e-6; v += step) arr.push(v);
            return arr;
          })()
        : Array.from({ length: 5 }, (_, i) => maxY - ((maxY - minY) * i) / 4),
    leftScale = axis && axis.leftScale != null ? axis.leftScale : 1,
    leftUnit = axis && axis.leftUnit != null ? axis.leftUnit : unit,
    leftDecimals = axis && axis.leftDecimals != null ? axis.leftDecimals : decimals;
  leftTicks.forEach(value => {
    const py = y(value);
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${(value * leftScale).toFixed(leftDecimals)}${leftUnit}`, plot.left - 5, py);
  });
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  if (axis && axis.right) {
    const right = axis.right,
      ticks =
        right.ticks ||
        (right.step
          ? (() => {
              // whole steps in the right-hand unit from zero (for example every 10 A), converted back to the left axis' unit
              const arr = [];
              for (let a = 0; a / right.scale <= maxY + 1e-6; a += right.step) arr.push(a / right.scale);
              return arr;
            })()
          : Array.from({ length: 5 }, (_, i) => maxY - ((maxY - minY) * i) / 4)),
      digits = right.decimals ?? (right.step ? 0 : Math.abs(maxY * right.scale) < 20 ? 1 : 0);
    ctx.save();
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = text;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    ticks.forEach(value => {
      const py = y(value);
      ctx.beginPath();
      ctx.moveTo(width - plot.right, py);
      ctx.lineTo(width - plot.right + 3, py);
      ctx.stroke();
      ctx.fillText(`${(value * right.scale).toFixed(digits)}${right.unit}`, width - plot.right + 5, py);
    });
    ctx.restore();
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.left, plot.top - 3, pw, ph + 6);
  ctx.clip();
  // Stacked areas: every band is painted as a solid colour on an offscreen layer (top of the stack first, so
  // neighbouring bands overlap instead of touching and no seams appear) and the layer is composited once
  // with a little transparency. Data gaps (for example the server being off) stay empty.
  const spacing = columns
      .slice(1)
      .map((column, index) => column.time - columns[index].time)
      .sort((a, b) => a - b),
    gapLimit = Math.max((spacing[spacing.length >> 1] || 0) * 4, 900000),
    runs = [];
  let run = [];
  columns.forEach((column, index) => {
    if (index && column.time - columns[index - 1].time > gapLimit) {
      runs.push(run);
      run = [];
    }
    run.push(column);
  });
  runs.push(run);
  const layer = document.createElement('canvas');
  layer.width = canvas.width;
  layer.height = canvas.height;
  const layerCtx = layer.getContext('2d');
  layerCtx.scale(dpr, dpr);
  layerCtx.beginPath();
  layerCtx.rect(plot.left, plot.top, pw, ph);
  layerCtx.clip();
  const base = y(0),
    lineRuns = [];
  runs.forEach(part => {
    const single = part.length === 1,
      cols = single ? [part[0], part[0]] : part,
      xs = single ? [x(part[0].time) - 1.5, x(part[0].time) + 1.5] : part.map(column => x(column.time));
    const stacks = cols.map(column => {
      let positive = 0,
        negative = 0;
      const pos = [],
        neg = [];
      meta.forEach((item, k) => {
        const value = selectedIndex >= 0 && k !== selectedIndex ? 0 : (column.values[k] ?? 0);
        if (value >= 0) positive += value;
        else negative += value;
        pos.push(positive);
        neg.push(negative);
      });
      return { pos, neg, total: visibleValues(column).reduce((a, b) => a + b, 0) };
    });
    for (let k = meta.length - 1; k >= 0; k--) {
      if (selectedIndex >= 0 && k !== selectedIndex) continue;
      ['pos', 'neg'].forEach(side => {
        const upper = smoothPoints(xs.map((px, index) => [px, y(stacks[index][side][k])]));
        if (upper.every(point => Math.abs(point[1] - base) < 0.05)) return;
        layerCtx.beginPath();
        layerCtx.moveTo(upper[0][0], base);
        upper.forEach(point => layerCtx.lineTo(point[0], point[1]));
        layerCtx.lineTo(upper[upper.length - 1][0], base);
        layerCtx.closePath();
        layerCtx.fillStyle = (meta[k] || {}).color || '#888';
        layerCtx.fill();
      });
    }
    lineRuns.push(smoothPoints(xs.map((px, index) => [px, y(stacks[index].total)])));
  });
  ctx.globalAlpha = 0.9;
  ctx.drawImage(layer, 0, 0, width, height);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = historySeries[0].color;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  lineRuns.forEach(points => {
    ctx.beginPath();
    points.forEach((point, index) => (index ? ctx.lineTo(point[0], point[1]) : ctx.moveTo(point[0], point[1])));
    ctx.stroke();
  });
  if (axis && axis.guides)
    axis.guides.forEach(value => {
      ctx.save();
      ctx.beginPath();
      ctx.setLineDash([3, 3]);
      ctx.moveTo(plot.left, y(value));
      ctx.lineTo(width - plot.right, y(value));
      ctx.strokeStyle = text;
      ctx.globalAlpha = 0.75;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();
    });
  if (showAverage) {
    ctx.beginPath();
    ctx.setLineDash([6, 4]);
    ctx.moveTo(plot.left, y(average));
    ctx.lineTo(width - plot.right, y(average));
    ctx.strokeStyle = '#e879f9';
    ctx.globalAlpha = 0.95;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#e879f9';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(
      `Avg ${average.toFixed(1)}${unit}${axis && axis.right && axis.right.unit === ' A' ? ` · ${(average * axis.right.scale).toFixed(1)} A` : ''}`,
      width - plot.right - 3,
      y(average) - 2
    );
  }
  ctx.restore();
  ctx.globalAlpha = 1;
}
function bmsCellSnapshots(battery) {
  return historyPoints
    .filter(row => row.battery === battery)
    .map(row => {
      const time = Date.parse(row.captured_at),
        cells = (row.cells || [])
          .map(value => historyNumber(value))
          .filter(value => value != null)
          .map(value => value / 1000),
        spread = historyNumber(row.cell_spread);
      return Number.isFinite(time) && cells.length ? { time, cells, spread } : null;
    })
    .filter(Boolean);
}
function drawCellVoltageChart(canvas, snapshots, selectedKey = 'total') {
  if (selectedKey !== 'total') return drawSelectedCellVoltageChart(canvas, snapshots, Number(selectedKey.slice(4)) - 1);
  const box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  if (!snapshots.length) return;
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    grid = styles.getPropertyValue('--line').trim(),
    colors = ['#60a5fa', '#65d92f', '#f4a631', '#a78bfa'],
    selectedIndex = /^cell[1-4]$/.test(selectedKey) ? Number(selectedKey.slice(4)) - 1 : -1,
    plot = { left: 46, right: 43, top: 9, bottom: 27 },
    pw = width - plot.left - plot.right,
    ph = height - plot.top - plot.bottom,
    points = historySample(snapshots, Math.max(300, Math.floor(pw * 2))),
    minX = points[0].time,
    maxX = points.at(-1).time,
    minV = 0,
    maxV = 15,
    maxMv = 400,
    x = value => plot.left + ((value - minX) / (maxX - minX || 1)) * pw,
    yV = value => plot.top + ((maxV - value) / (maxV - minV)) * ph,
    yMv = value => plot.top + ((maxMv - value) / maxMv) * ph;
  ctx.font = '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const py = plot.top + (ph * i) / 4,
      v = maxV - ((maxV - minV) * i) / 4,
      mv = maxMv * (1 - i / 4);
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${v.toFixed(2)} V`, plot.left - 5, py);
    ctx.textAlign = 'left';
    ctx.fillText(`${Math.round(mv)} mV`, width - plot.right + 5, py);
  }
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  const smoothLine = (linePoints, y, color, width = 1.6) => {
    if (!linePoints.length) return;
    ctx.beginPath();
    ctx.moveTo(x(linePoints[0][0]), y(linePoints[0][1]));
    for (let i = 1; i < linePoints.length - 1; i++) {
      const current = linePoints[i],
        next = linePoints[i + 1],
        mx = (x(current[0]) + x(next[0])) / 2,
        my = (y(current[1]) + y(next[1])) / 2;
      ctx.quadraticCurveTo(x(current[0]), y(current[1]), mx, my);
    }
    if (linePoints.length > 1) {
      const last = linePoints.at(-1);
      ctx.lineTo(x(last[0]), y(last[1]));
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  };
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.left, plot.top, pw, ph);
  ctx.clip();
  for (let cell = 0; cell < 4; cell++) {
    if (selectedIndex >= 0 && cell !== selectedIndex) continue;
    const line = points
      .filter(point => point.cells[cell] != null)
      .map(point => [point.time, selectedIndex >= 0 ? point.cells[cell] : point.cells.slice(0, cell + 1).reduce((a, b) => a + b, 0)]);
    smoothLine(line, yV, colors[cell], 1.5);
  }
  smoothLine(
    points.filter(point => point.spread != null).map(point => [point.time, point.spread]),
    yMv,
    '#ff3b45',
    2
  );
  ctx.restore();
  ctx.globalAlpha = 1;
}
function drawSelectedCellVoltageChart(canvas, snapshots, cellIndex) {
  const box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const points = historySample(
    snapshots.filter(point => point.cells[cellIndex] != null),
    Math.max(300, Math.floor(width * 2))
  );
  if (!points.length) return;
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    grid = styles.getPropertyValue('--line').trim(),
    colors = ['#60a5fa', '#65d92f', '#f4a631', '#a78bfa'],
    plot = { left: 46, right: 43, top: 9, bottom: 27 },
    pw = width - plot.left - plot.right,
    ph = height - plot.top - plot.bottom,
    minX = points[0].time,
    maxX = points.at(-1).time,
    x = value => plot.left + ((value - minX) / (maxX - minX || 1)) * pw,
    yV = value => plot.top + ((4 - value) / 1.5) * ph,
    yMv = value => plot.top + ((400 - value) / 400) * ph;
  ctx.font = '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = grid;
  for (let i = 0; i <= 3; i++) {
    const py = plot.top + (ph * i) / 3,
      v = 4 - 0.5 * i,
      mv = 400 - (400 / 3) * i;
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${v.toFixed(1)} V`, plot.left - 5, py);
    ctx.textAlign = 'left';
    ctx.fillText(`${Math.round(mv)} mV`, width - plot.right + 5, py);
  }
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  const smooth = (data, y, color, widthLine) => {
    if (!data.length) return;
    ctx.beginPath();
    ctx.moveTo(x(data[0][0]), y(data[0][1]));
    for (let i = 1; i < data.length - 1; i++) {
      const current = data[i],
        next = data[i + 1],
        mx = (x(current[0]) + x(next[0])) / 2,
        my = (y(current[1]) + y(next[1])) / 2;
      ctx.quadraticCurveTo(x(current[0]), y(current[1]), mx, my);
    }
    if (data.length > 1) {
      const last = data.at(-1);
      ctx.lineTo(x(last[0]), y(last[1]));
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = widthLine;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  };
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.left, plot.top, pw, ph);
  ctx.clip();
  smooth(
    points.map(point => [point.time, point.cells[cellIndex]]),
    yV,
    colors[cellIndex],
    2
  );
  smooth(
    points.filter(point => point.spread != null).map(point => [point.time, point.spread]),
    yMv,
    '#ff3b45',
    2
  );
  ctx.restore();
}
function alarmRows() {
  return historyPoints.filter(row => Array.isArray(row.alarms) && row.alarms.length);
}
function alarmEpisodes() {
  const result = {},
    previous = {};
  alarmBatteryMeta.forEach(item => (result[item.key] = 0));
  [...historyPoints]
    .sort((a, b) => a.id - b.id)
    .forEach(row => {
      const active = Array.isArray(row.alarms) && row.alarms.length > 0;
      if (active && !previous[row.battery]) result[row.battery] = (result[row.battery] || 0) + 1;
      previous[row.battery] = active;
    });
  return result;
}
function drawAlarmTimeline(canvas) {
  const rows = historyPoints,
    alarms = alarmRows(),
    box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  if (!rows.length) return;
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    grid = styles.getPropertyValue('--line').trim(),
    plot = { left: 40, right: 8, top: 9, bottom: 27 },
    pw = width - plot.left - plot.right,
    ph = height - plot.top - plot.bottom,
    times = rows.map(row => Date.parse(row.captured_at)).filter(Number.isFinite),
    minX = Math.min(...times),
    maxX = Math.max(...times),
    binCount = Math.max(24, Math.min(100, Math.floor(pw / 5))),
    span = Math.max(1, maxX - minX),
    bins = Array.from({ length: binCount }, () => [0, 0, 0]);
  alarms.forEach(row => {
    const time = Date.parse(row.captured_at),
      battery = alarmBatteryMeta.findIndex(item => item.key === row.battery);
    if (!Number.isFinite(time) || battery < 0) return;
    const bin = Math.min(binCount - 1, Math.floor(((time - minX) / span) * binCount));
    bins[bin][battery]++;
  });
  const maxY = Math.max(1, ...bins.map(values => values.reduce((a, b) => a + b, 0))),
    xIndex = index => plot.left + (index / binCount) * pw,
    y = value => plot.top + ((maxY - value) / maxY) * ph,
    barWidth = Math.max(2, (pw / binCount) * 0.8);
  ctx.font = '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = grid;
  for (let i = 0; i <= 4; i++) {
    const py = plot.top + (ph * i) / 4,
      value = maxY * (1 - i / 4);
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(Math.round(value)), plot.left - 5, py);
  }
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  bins.forEach((values, index) => {
    let total = 0;
    values.forEach((value, battery) => {
      if (!value) return;
      const next = total + value;
      ctx.fillStyle = alarmBatteryMeta[battery].color;
      ctx.globalAlpha = 0.82;
      ctx.fillRect(xIndex(index), y(next), barWidth, y(total) - y(next));
      total = next;
    });
  });
  ctx.globalAlpha = 1;
}
function drawAlarmMetric(canvas, field, unit, showMos = false) {
  const box = canvas.parentElement.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2),
    width = Math.max(280, Math.round(box.width)),
    height = Math.max(150, Math.round(box.height));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const rows = historyPoints.filter(row => historyNumber(row[field]) != null),
    all = rows.map(row => [Date.parse(row.captured_at), historyNumber(row[field])]).filter(point => Number.isFinite(point[0]));
  if (!all.length) return;
  const styles = getComputedStyle(document.documentElement),
    text = styles.getPropertyValue('--muted').trim(),
    grid = styles.getPropertyValue('--line').trim(),
    plot = { left: 46, right: 8, top: 9, bottom: 27 },
    pw = width - plot.left - plot.right,
    ph = height - plot.top - plot.bottom,
    minX = Math.min(...all.map(point => point[0])),
    maxX = Math.max(...all.map(point => point[0])),
    rawMin = Math.min(0, ...all.map(point => point[1])),
    rawMax = Math.max(1, ...all.map(point => point[1])),
    pad = Math.max(1, (rawMax - rawMin) * 0.1),
    minY = field === 'cell_spread' ? 0 : rawMin - pad,
    maxY = rawMax + pad,
    x = value => plot.left + ((value - minX) / (maxX - minX || 1)) * pw,
    y = value => plot.top + ((maxY - value) / (maxY - minY || 1)) * ph;
  ctx.font = '9px system-ui';
  ctx.fillStyle = text;
  ctx.strokeStyle = grid;
  for (let i = 0; i <= 4; i++) {
    const py = plot.top + (ph * i) / 4,
      value = maxY - ((maxY - minY) * i) / 4;
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(width - plot.right, py);
    ctx.stroke();
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${Math.round(value)} ${unit}`, plot.left - 5, py);
  }
  drawTimeAxis(ctx, minX, maxX, plot, pw, ph, width, height);
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.left, plot.top, pw, ph);
  ctx.clip();
  alarmBatteryMeta.forEach(meta => {
    const points = historySample(
      rows
        .filter(row => row.battery === meta.key)
        .map(row => [Date.parse(row.captured_at), historyNumber(row[field])])
        .filter(point => Number.isFinite(point[0]) && point[1] != null),
      Math.max(300, Math.floor(pw * 2))
    );
    if (!points.length) return;
    ctx.beginPath();
    points.forEach((point, index) => (index ? ctx.lineTo(x(point[0]), y(point[1])) : ctx.moveTo(x(point[0]), y(point[1]))));
    ctx.strokeStyle = meta.color;
    ctx.globalAlpha = 0.7;
    ctx.lineWidth = 1.2;
    ctx.stroke();
  });
  alarmRows().forEach(row => {
    const time = Date.parse(row.captured_at),
      value = historyNumber(row[field]);
    if (!Number.isFinite(time) || value == null) return;
    ctx.beginPath();
    ctx.arc(x(time), y(value), 2.7, 0, Math.PI * 2);
    ctx.fillStyle = '#ff3344';
    ctx.globalAlpha = 0.95;
    ctx.fill();
  });
  if (showMos) {
    rows
      .filter(row => row.charge_mos === false)
      .forEach(row => {
        const time = Date.parse(row.captured_at);
        if (!Number.isFinite(time)) return;
        ctx.fillStyle = '#ff9f1c';
        ctx.globalAlpha = 0.7;
        ctx.fillRect(x(time) - 1, plot.top + ph - 7, 2, 7);
      });
    rows
      .filter(row => row.discharge_mos === false)
      .forEach(row => {
        const time = Date.parse(row.captured_at);
        if (!Number.isFinite(time)) return;
        ctx.fillStyle = '#22d3ee';
        ctx.globalAlpha = 0.7;
        ctx.fillRect(x(time) - 1, plot.top + ph - 14, 2, 7);
      });
  }
  ctx.restore();
  ctx.globalAlpha = 1;
}
