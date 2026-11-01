// History: legends and the per-tab renderers (Storage, Sources, Loads, Alarms).
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function renderAlarmsHistory() {
  const selected = historyLegendSelection.alarmBattery || 'total',
    label = selected === 'total' ? 'All' : alarmBatteryMeta.find(item => item.key === selected)?.label || selected,
    allRows = historyPoints;
  historyPoints = selected === 'total' ? allRows : allRows.filter(row => row.battery === selected);
  try {
    const alarms = alarmRows(),
      episodes = alarmEpisodes(),
      episodeCount = Object.values(episodes).reduce((sum, value) => sum + value, 0);
    $('historyAlarmSummary').textContent = `${alarms.length} alarm samples · ${episodeCount} alarm episodes`;
    $('historyAlarmTimelineTitle').textContent = `Alarm occurrences - ${label}`;
    $('historyAlarmSpreadTitle').textContent = `Cell imbalance at alarms - ${label}`;
    $('historyAlarmCurrentTitle').textContent = `Charge/discharge consequence - ${label}`;
    drawAlarmTimeline($('historyAlarmTimeline'));
    const items = [{ key: 'total', label: 'All', color: '#11c5c8' }, ...alarmBatteryMeta];
    $('historyAlarmLegend').innerHTML = items
      .map(
        item =>
          `<span class="${item.key === selected ? 'active' : ''}" onclick="selectHistoryLegend('alarmBattery','${item.key}')"><i style="background:${item.color}"></i>${item.label}</span>`
      )
      .join('');
    drawAlarmMetric($('historyAlarmSpread'), 'cell_spread', 'mV');
    drawAlarmMetric($('historyAlarmCurrent'), 'current', 'A', true);
  } finally {
    historyPoints = allRows;
  }
}
function dashboardSnapshots(field, meta) {
  return dashboardHistoryPoints
    .map(row => {
      const time = Date.parse(row.captured_at),
        values = meta.map((item, index) => historyNumber((row[field] || [])[index]) ?? 0);
      return Number.isFinite(time) ? { time, values } : null;
    })
    .filter(Boolean);
}
function dashboardLines(field, meta) {
  const result = {};
  meta.forEach(item => (result[item.key] = []));
  dashboardHistoryPoints.forEach(row => {
    const time = Date.parse(row.captured_at);
    if (!Number.isFinite(time)) return;
    meta.forEach((item, index) => {
      const value = historyNumber((row[field] || [])[index]);
      if (value != null) result[item.key].push([time, value]);
    });
  });
  return result;
}
function dashboardSingle(field, key, label, color, transform = value => value) {
  const meta = [{ key, label, color, width: 2 }],
    series = { [key]: [] };
  dashboardHistoryPoints.forEach(row => {
    const time = Date.parse(row.captured_at),
      value = historyNumber(transform(row[field], row));
    if (Number.isFinite(time) && value != null) series[key].push([time, value]);
  });
  return { meta, series };
}
function busVoltage(powerField, currentField) {
  let watts = 0,
    amps = 0;
  dashboardHistoryPoints.forEach(row => {
    const p = (row[powerField] || []).reduce((a, v) => a + (historyNumber(v) || 0), 0),
      c = (row[currentField] || []).reduce((a, v) => a + (historyNumber(v) || 0), 0);
    if (c > 0.5 && p > 0) {
      watts += p;
      amps += c;
    }
  });
  const volts = amps > 0 ? watts / amps : 13.3;
  return volts > 8 && volts < 32 ? volts : 13.3;
}
function setHistoryLegend(id, chartKey, meta) {
  const selected = historyLegendSelection[chartKey] || 'total',
    items = [historySeries[0], ...meta];
  $(id).innerHTML = items
    .map(
      item =>
        `<span class="${item.key === selected ? 'active' : ''}" onclick="selectHistoryLegend('${chartKey}','${item.key}')"><i style="background:${item.color}"></i>${item.label}</span>`
    )
    .join('');
}
function setCellVoltageLegend(id, chartKey) {
  const selected = historyLegendSelection[chartKey] || 'total',
    items = [
      { key: 'total', label: 'Total', color: '#11c5c8' },
      { key: 'cell1', label: 'Cell 1', color: '#60a5fa' },
      { key: 'cell2', label: 'Cell 2', color: '#65d92f' },
      { key: 'cell3', label: 'Cell 3', color: '#f4a631' },
      { key: 'cell4', label: 'Cell 4', color: '#a78bfa' }
    ];
  $(id).innerHTML = items
    .map(
      item =>
        `<span class="${item.key === selected ? 'active' : ''}" onclick="selectHistoryLegend('${chartKey}','${item.key}')"><i style="background:${item.color}"></i>${item.label}</span>`
    )
    .join('');
}
function selectHistoryLegend(chartKey, itemKey) {
  historyLegendSelection[chartKey] = itemKey;
  renderHistory();
}
function renderSourcesHistory() {
  if (!dashboardHistoryPoints.length) return;
  const powerKey = historyLegendSelection.sourcePower || 'total',
    veff = busVoltage('source_power', 'source_current');
  $('historySourcePowerSub').textContent =
    `Stacked DC source output with a smooth total line · right axis in amps at ${veff.toFixed(1)} V (average bus voltage of the period)`;
  drawStackedHistoryChart(
    $('historySourcePower'),
    dashboardSnapshots('source_power', sourcePowerMeta),
    ' W',
    sourcePowerMeta,
    powerKey,
    true,
    { leftStep: 250, right: { unit: ' A', scale: 1 / veff, step: 10 } }
  );
  setHistoryLegend('historySourcePowerLegend', 'sourcePower', sourcePowerMeta);
  const shore = dashboardSingle('shore_voltage', 'shore', 'Shore AC V', '#7db9ff'),
    solar = dashboardSingle('solar_panel_voltage', 'solar', 'PV V', '#65d92f'),
    alternator = dashboardSingle('alternator_temperature', 'alternator', 'Alternator °C', '#f4a631'),
    shoreAmps = dashboardSingle('shore_current', 'shoreA', 'Shore A', '#f4a631'),
    shoreIntake = dashboardSingle('shore_power', 'intake', 'Shore power W', '#7db9ff');
  // volts on the left, amps on the right: 0-20 A in steps of 5 A
  drawHistoryChart($('historyShoreCondition'), shore.series, ' V', shore.meta, null, true, {
    series: shoreAmps.series,
    meta: shoreAmps.meta,
    min: 0,
    max: 20,
    ticks: [0, 5, 10, 15, 20],
    unit: ' A'
  });
  drawHistoryChart($('historyShoreIntake'), shoreIntake.series, ' W', shoreIntake.meta, null, true);
  drawHistoryChart($('historySolarCondition'), solar.series, ' V', solar.meta, null, true);
  drawHistoryChart($('historyAlternatorCondition'), alternator.series, '°C', alternator.meta, null, true);
}
function renderLoadsHistory() {
  if (!dashboardHistoryPoints.length) return;
  const powerKey = historyLegendSelection.loadPower || 'total',
    veff = busVoltage('load_power', 'load_current');
  $('historyLoadPowerSub').textContent =
    `Stacked consumers with a smooth total-load line · right axis in amps at ${veff.toFixed(1)} V (average bus voltage of the period)`;
  drawStackedHistoryChart($('historyLoadPower'), dashboardSnapshots('load_power', loadMeta), ' W', loadMeta, powerKey, true, {
    right: { unit: ' A', scale: 1 / veff }
  });
  setHistoryLegend('historyLoadPowerLegend', 'loadPower', loadMeta);
  const acPower = dashboardSingle('ac_power', 'ac', 'AC power', '#60a5fa'),
    inverterState = dashboardSingle('inverting', 'state', 'Inverter state', '#a78bfa', (value, row) =>
      row.supporting ? 2 : value ? 1 : 0
    );
  drawHistoryChart($('historyAcPower'), acPower.series, ' W', acPower.meta);
  drawHistoryChart($('historyInverterState'), inverterState.series, '', inverterState.meta, {
    min: -0.15,
    max: 2.15,
    ticks: [0, 1, 2],
    labels: { 0: 'Off', 1: 'Inverting', 2: 'Supporting' },
    step: true
  });
}
function showHistoryTab(tab) {
  historyActiveTab = tab;
  ['storage', 'sources', 'loads', 'alarms', 'reports'].forEach(name => {
    $(`history${name[0].toUpperCase() + name.slice(1)}`).hidden = name !== tab;
    $(`historyTab${name[0].toUpperCase() + name.slice(1)}`).classList.toggle('active', name === tab);
  });
  $('historyPage').classList.toggle('reports-active', tab === 'reports');
  if (tab === 'reports') loadReportsTab();
  requestAnimationFrame(renderHistory);
}
