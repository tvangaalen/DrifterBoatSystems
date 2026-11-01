// History: shared series definitions and the helpers that turn server points into chart snapshots.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

let historyPoints = [],
  dashboardHistoryPoints = [],
  historyAllPoints = [],
  dashboardHistoryAllPoints = [],
  historyBmsCount = 0,
  historyDashboardCount = 0,
  historyLoaded = false,
  historyUpdating = false,
  historyResizeTimer = null,
  historyActiveTab = 'sources',
  historyRangeStart = null,
  historyRangeEnd = null,
  historyRangeMin = null,
  historyRangeMax = null;
let historyZoomHours = null,
  historyMaxHours = null;
const historyLegendSelection = {};
const historySeries = [
  { key: 'total', label: 'Total', color: '#11c5c8', width: 2.5 },
  { key: 'BATTERY 1', label: 'Battery 1', color: '#f4a631', width: 1.4 },
  { key: 'BATTERY 2', label: 'Battery 2', color: '#65d92f', width: 1.4 },
  { key: 'BATTERY 3', label: 'Battery 3', color: '#ff6262', width: 1.4 }
];
const BANK_CAPACITY_AH = 960;
const NOMINAL_BANK_VOLTAGE_V = 13.2;
const alarmBatteryMeta = historySeries.slice(1);
const sourcePowerMeta = [
    { key: 'charger_house', label: 'Charger House', color: '#a78bfa' },
    { key: 'alternator', label: 'Alternator', color: '#f4a631' },
    { key: 'solar', label: 'Solar', color: '#65d92f' }
  ],
  sourceCurrentMeta = sourcePowerMeta,
  loadMeta = [
    { key: 'inverter', label: 'Inverter', color: '#a78bfa' },
    { key: 'charger_start', label: 'Charger Start', color: '#65d92f' },
    { key: 'charger_bow', label: 'Charger Bow', color: '#34d399' },
    { key: 'engine_ecu', label: 'Engine ECU', color: '#f4a631' },
    { key: 'alternator_field', label: 'Alt. field', color: '#fb7185' },
    { key: 'other_dc', label: 'Other DC', color: '#60a5fa' }
  ];
function historyNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function historyData() {
  const rows = [...historyPoints].sort((a, b) => a.id - b.id),
    latest = {},
    result = { voltage: {}, current: {}, remaining: {} };
  historySeries.forEach(s => {
    result.voltage[s.key] = [];
    result.current[s.key] = [];
    result.remaining[s.key] = [];
  });
  rows.forEach(row => {
    const time = Date.parse(row.captured_at),
      battery = row.battery;
    if (!Number.isFinite(time) || !result.voltage[battery]) return;
    const values = { voltage: historyNumber(row.voltage), current: historyNumber(row.current), remaining: historyNumber(row.remaining) };
    latest[battery] = { ...(latest[battery] || {}), ...values };
    Object.keys(values).forEach(metric => {
      if (values[metric] != null) result[metric][battery].push([time, values[metric]]);
    });
    const all = ['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].map(name => latest[name]);
    if (all.every(Boolean))
      Object.keys(values).forEach(metric => {
        const nums = all.map(item => item[metric]);
        if (nums.every(n => n != null))
          result[metric].total.push([time, metric === 'voltage' ? nums.reduce((a, b) => a + b, 0) / 3 : nums.reduce((a, b) => a + b, 0)]);
      });
  });
  return result;
}
function historySnapshots(metric) {
  const latest = {},
    result = [];
  [...historyPoints]
    .sort((a, b) => a.id - b.id)
    .forEach(row => {
      const time = Date.parse(row.captured_at),
        value = historyNumber(row[metric]);
      if (!Number.isFinite(time) || value == null || !['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].includes(row.battery)) return;
      latest[row.battery] = value;
      if (['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].every(name => latest[name] != null))
        result.push({ time, values: ['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].map(name => latest[name]) });
    });
  return result;
}
function historySnapshotsPower() {
  // Per-battery power (V x A) from the same BMS rows historySnapshots() uses, gated the same way: a combined
  // point is only emitted once all three batteries have a known voltage and current.
  const latestV = {},
    latestC = {},
    result = [];
  [...historyPoints]
    .sort((a, b) => a.id - b.id)
    .forEach(row => {
      const time = Date.parse(row.captured_at);
      if (!Number.isFinite(time) || !['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].includes(row.battery)) return;
      const v = historyNumber(row.voltage),
        c = historyNumber(row.current);
      if (v != null) latestV[row.battery] = v;
      if (c != null) latestC[row.battery] = c;
      if (['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].every(name => latestV[name] != null && latestC[name] != null))
        result.push({ time, values: ['BATTERY 1', 'BATTERY 2', 'BATTERY 3'].map(name => latestV[name] * latestC[name]) });
    });
  return result;
}
function bmsEffectiveVoltage() {
  let sum = 0,
    count = 0;
  historySnapshots('voltage').forEach(point =>
    point.values.forEach(v => {
      sum += v;
      count++;
    })
  );
  const v = count ? sum / count : NOMINAL_BANK_VOLTAGE_V;
  return v > 8 && v < 32 ? v : NOMINAL_BANK_VOLTAGE_V;
}
function historySample(points, maxPoints) {
  if (points.length <= maxPoints) return points;
  const step = (points.length - 1) / (maxPoints - 1),
    sample = [];
  for (let i = 0; i < maxPoints; i++) sample.push(points[Math.round(i * step)]);
  return sample;
}
