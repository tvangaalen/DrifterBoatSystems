// The BMS page: battery matrix, tiles with the balancer bars, dialogs, Charge/Discharge/Set SOC controls and refresh buttons.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
function alarmLines(value) {
  const alarms = Array.isArray(value) ? value : value && value !== 'None' ? [value] : [];
  return alarms.length ? alarms.map(alarm => `<span class="alarm-line">${esc(alarm)}</span>`).join('') : 'None';
}
function bmsNumber(value, digits = 1, suffix = '') {
  return value == null ? '—' : Number(value).toFixed(suffix === ' V' ? 3 : digits) + suffix;
}
function voltageReading(value, digits = 3) {
  if (value == null) return '—';
  const [whole, fraction] = Number(value).toFixed(digits).split('.');
  return `<span class="voltage-reading"><span class="voltage-whole">${whole}</span><span class="voltage-point">.</span><span class="voltage-fraction">${fraction}</span><span class="voltage-unit"> V</span></span>`;
}
function bmsCard(item) {
  if (item.state === 'scanning' || item.state === 'reading') item = { ...item, state: 'connecting' };
  else if (item.state === 'disconnected') item = { ...item, state: 'error' };
  const connected = item.state === 'connected',
    connecting = item.state === 'connecting';
  const stateLabel = connected
    ? '● Connected'
    : connecting
      ? '● Connecting…'
      : item.state === 'error'
        ? '● Connection failed'
        : '● Not read';
  const temps = (item.temperatures_c || []).map(v => `${Math.round(Number(v))}°C`).join(', ') || '—';
  const cells =
    (item.cells_mv || [])
      .map((mv, i) => `<div class="bms-cell">Cell ${i + 1}<strong>${(Number(mv) / 1000).toFixed(3)} V</strong></div>`)
      .join('') || '<div class="bms-cell">Cells<strong>—</strong></div>';
  const balancing = (item.balancing_cells || []).length ? `Cells ${(item.balancing_cells || []).join(', ')}` : 'Inactive';
  const updated = item.captured_at ? new Date(item.captured_at).toLocaleString() : 'Never';
  const current = item.current_a == null ? '—' : (Number(item.current_a) >= 0 ? '+' : '') + Number(item.current_a).toFixed(1) + ' A';
  const mos = value => (value == null ? '—' : value ? 'On' : 'Off');
  const cellRows =
    (item.cells_mv || [])
      .map((mv, i) => `<div class="bms-row"><span>Cell ${i + 1}</span><strong>${(Number(mv) / 1000).toFixed(3)} V</strong></div>`)
      .join('') || '<div class="bms-row"><span>Cells</span><strong>—</strong></div>';
  return `<article class="bms-card"><div class="bms-card-head"><div class="bms-name">${esc(item.battery)}</div><div class="bms-device">${esc(item.device_name || 'DALY Bluetooth')}</div><div class="bms-connection ${esc(item.state)}">${stateLabel}</div></div><div class="bms-rows"><div class="bms-row"><span>Voltage</span><strong>${bmsNumber(item.pack_voltage_v, 1, ' V')}</strong></div><div class="bms-row"><span>Current</span><strong>${current}</strong></div><div class="bms-row"><span>SOC</span><strong>${bmsNumber(item.state_of_charge_percent, 1, '%')}</strong></div><div class="bms-row"><span>Temperature</span><strong>${temps}</strong></div><div class="bms-row"><span>Remaining</span><strong>${bmsNumber(item.remaining_capacity_ah, 3, ' Ah')}</strong></div><div class="bms-row"><span>Max difference</span><strong>${bmsNumber(item.cell_spread_mv, 0, ' mV')}</strong></div><div class="bms-row bms-section">CELL VOLTAGES</div>${cellRows}<div class="bms-row"><span>Charge MOS</span><strong>${mos(item.charge_mosfet_on)}</strong></div><div class="bms-row"><span>Discharge MOS</span><strong>${mos(item.discharge_mosfet_on)}</strong></div><div class="bms-row"><span>Balancing</span><strong>${balancing}</strong></div><div class="bms-row"><span>Alarms</span><strong>${esc(item.alarms || '—')}</strong></div><div class="bms-row"><span>Cycles</span><strong>${item.cycles ?? '—'}</strong></div><div class="bms-row bms-updated-row"><span>Updated</span><strong>${esc(updated)}</strong></div></div>${item.error ? `<div class="bms-error">${esc(item.error)}</div>` : ''}</article>`;
}
function bmsIndividualButton(batteryId, action, enabled, normalHtml, stateClass, disabled, title) {
  const key = `${batteryId}:${action}`,
    active = bmsIndividualControl && bmsIndividualControl.key === key,
    queued = bmsIndividualQueue.some(task => task.key === key),
    pending = active || queued,
    label = active
      ? bmsIndividualControl.phase === 'waiting'
        ? 'Waiting for Bluetooth'
        : 'Action in progress'
      : queued
        ? 'Queued'
        : normalHtml,
    enabledArg = enabled === undefined ? 'undefined' : String(!!enabled);
  return `<button class="bms-action ${stateClass}" type="button" data-bms-key="${key}" ${disabled || pending ? 'disabled' : ''} aria-label="${esc(pending ? label : title)}" title="${esc(pending ? label : title)}" onclick="bmsControl(${batteryId},'${action}',${enabledArg},this)">${label}</button>`;
}
function bmsSocButton(batteryId, disabled) {
  const active = bmsIndividualControl && bmsIndividualControl.batteryId === batteryId && bmsIndividualControl.action.startsWith('set-soc-'),
    queuedTask = bmsIndividualQueue.find(task => task.batteryId === batteryId && task.action.startsWith('set-soc-')),
    task = active ? bmsIndividualControl : queuedTask,
    pending = !!task,
    label = active ? (task.phase === 'waiting' ? 'Waiting for Bluetooth' : 'Action in progress') : queuedTask ? 'Queued' : 'Set SOC',
    key = task?.key || `${batteryId}:soc-choice`;
  return `<button class="bms-action" type="button" data-bms-key="${key}" ${disabled || pending ? 'disabled' : ''} onclick="chooseBmsSoc(${batteryId},this)">${label}</button>`;
}
async function chooseBmsSoc(batteryId, button) {
  const choice = await showBmsSocChoice(batteryId ? `Set SOC - Battery ${batteryId}` : 'Set all SOC');
  if (!choice) return;
  const mode = typeof choice === 'object' ? 'value' : choice,
    percent = typeof choice === 'object' ? choice.percent : undefined;
  if (batteryId) {
    const action = mode === '100' ? 'set-soc-100' : `set-soc-${mode}`;
    button.dataset.bmsKey = `${batteryId}:${action}`;
    bmsControl(batteryId, action, percent, button);
  } else bmsControlAll(mode, true, percent);
}
$('bmsSocManualValue').addEventListener('input', () => {
  $('bmsSocManualValue').value = $('bmsSocManualValue').value.replace(/[^0-9.]/g, '');
});
$('bmsSocManualValue').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    $('bmsSocManual').click();
  }
});
function bmsMatrix(data, balData) {
  const names = ['BATTERY 1', 'BATTERY 2', 'BATTERY 3'],
    items = names.map(name => data.batteries[name] || { battery: name, state: 'not_read' });
  const maxCells = Math.max(4, ...items.map(x => (x.cells_mv || []).length));
  // Balancer n (DL-BALn) belongs to battery n. The CELLS section shows the BMS's own cell voltages only (the ones Float protection
  // uses); the balancer's readings are in the tile bars and the BALANCING section.
  const bals = ['DL-BAL1', 'DL-BAL2', 'DL-BAL3'].map(name => balData?.devices?.[name] || null),
    balHas = bal => !!(bal && bal.status && bal.status.valid_frame_count);
  const cellList = cells =>
    cells.length === 1
      ? String(cells[0])
      : cells.length === 2
        ? `${cells[0]} and ${cells[1]}`
        : `${cells.slice(0, -1).join(', ')}, and ${cells.at(-1)}`;
  const balVal = (index, fn) => {
    const bal = bals[index];
    return balHas(bal) ? `<span class="${bal.stale ? 'bal-stale' : ''}">${fn(bal.status)}</span>` : '—';
  };
  const balHead = (bal, index) => {
    const has = balHas(bal),
      text = bal?.stale
        ? `Balancer ${Math.max(1, Math.round((bal.last_success_age_seconds || 0) / 60))} min old`
        : bal?.state === 'connected'
          ? 'Balancer OK'
          : bal?.state === 'error'
            ? 'Balancer failed'
            : has
              ? 'Balancer …'
              : 'Balancer —',
      cls = bal?.stale ? 'waiting' : bal?.state === 'connected' ? 'connected' : bal?.state === 'error' ? 'error' : 'waiting';
    return `<div class="bms-connection bms-balancer-state ${cls}" data-bms-balancer-refresh="${index + 1}" role="button" tabindex="0" title="Refresh balancer ${index + 1}" onclick="event.stopPropagation();refreshBalancer(${index + 1})" onkeydown="if(event.key==='Enter'||event.key===' '){event.stopPropagation();event.preventDefault();refreshBalancer(${index + 1})}">${text}</div>`;
  };
  const cellBars = (item, bal) => {
    // The bars are the balancer's own cell voltages drawn as the deviation from the balancer's own average (the horizontal line,
    // value on its left; up = above, down = below), so one instrument is compared with itself and at least one bar always lies
    // below and one above (mixing it with the BMS cells showed the offset between the two instruments instead, changelog 1.21.1).
    // Without a fresh balancer reading the BMS cells and the BMS average are used instead (dimmed value). Lowest cell blue,
    // highest red, the rest green. Float protection runs on the BMS only, so a bar blinks bright red when the BMS reading of
    // that same cell is at or above the Float cell trigger, whichever instrument drew the bar.
    const bmsCells = (item.cells_mv || []).map(Number),
      balCells = balHas(bal) && !bal.stale ? (bal.status.cells_mv || []).map(Number) : [],
      useBal = balCells.length > 0 && balCells.every(Number.isFinite),
      cells = useBal ? balCells : bmsCells.filter(Number.isFinite);
    if (!cells.length) return '';
    const max = Math.max(...cells),
      min = Math.min(...cells),
      mean = cells.reduce((a, b) => a + b, 0) / cells.length,
      balAvg = useBal
        ? bal.status.average_cell_mv != null && Number.isFinite(Number(bal.status.average_cell_mv))
          ? Number(bal.status.average_cell_mv)
          : mean
        : null,
      ref = balAvg ?? mean,
      diff =
        useBal && bal.status.cell_delta_mv != null && Number.isFinite(Number(bal.status.cell_delta_mv))
          ? Number(bal.status.cell_delta_mv)
          : max - min,
      range = Math.max(20, ...cells.map(mv => Math.abs(mv - ref))),
      trigger = Number(state.settings?.float_cell_trigger_mv ?? 3550),
      active = balHas(bal) && !bal.stale && !!bal.status.balance_active,
      positions = active ? (bal.status.balance_position || []).map(Number) : [],
      step = 12;
    const bars = cells
      .map((mv, i) => {
        const dev = mv - ref,
          bms = bmsCells[i],
          cls = `${Number.isFinite(bms) && bms >= trigger ? 'hot' : max !== min && mv === max ? 'hi' : max !== min && mv === min ? 'lo' : ''} ${positions.includes(i + 1) ? 'bal' : ''}`;
        return `<i class="cb ${cls}" style="left:${i * step}px;height:${Math.max(2, Math.round((Math.abs(dev) / range) * 18))}px;${dev >= 0 ? 'bottom' : 'top'}:50%" title="${useBal ? 'Balancer' : 'BMS'} cell ${i + 1}: ${(mv / 1000).toFixed(3)} V (${dev >= 0 ? '+' : ''}${Math.round(dev)} mV)"></i>`;
      })
      .join('');
    const bolts = cells
      .map((mv, i) => (positions.includes(i + 1) ? `<span class="cb-bolt" style="left:${i * step - 1}px">⚡</span>` : ''))
      .join('');
    const amps = balHas(bal) && bal.status.reported_current_a != null ? `${Number(bal.status.reported_current_a).toFixed(1)} A` : '—';
    const foot = !balHas(bal)
      ? ''
      : bal.stale
        ? `<div class="bms-balfoot stale">Balancer ${Math.max(1, Math.round((bal.last_success_age_seconds || 0) / 60))} min old</div>`
        : active
          ? `<div class="bms-balfoot on">${positions.length ? `cell ${positions.join(', ')}` : 'balancing'} · ${amps}</div>`
          : '<div class="bms-balfoot">Balancer idle</div>';
    return `<div class="bms-balchart" role="img" aria-label="Cell voltages as deviation from the average"><span class="bc-ref${balAvg == null ? ' bms' : ''}" title="${balAvg == null ? 'BMS average (no fresh balancer reading)' : 'Balancer average voltage'}">${(ref / 1000).toFixed(3)} V</span><div class="bc-plot" style="width:${cells.length * step - 4}px">${bolts}<i class="bc-line"></i>${bars}</div><span class="bc-diff" title="Max difference between the cells">${Math.round(diff)} mV</span></div>${foot}`;
  };
  const stateText = item =>
    item.state === 'connected'
      ? '● Connected'
      : item.state === 'reading'
        ? '● Updating…'
        : item.state === 'connecting' || item.state === 'scanning'
          ? '● Connecting…'
          : item.state === 'error'
            ? '● Connection failed'
            : '● Not connected';
  const valueRow = (label, values, rowClass = '') =>
    `<div class="bms-matrix-cell bms-matrix-label">${esc(label)}</div>${values.map((value, index) => `<div class="bms-matrix-cell ${rowClass} ${index === values.length - 1 ? 'last' : ''}">${value}</div>`).join('')}`;
  const interpolateSoc = (volts, points) => {
    if (!Number.isFinite(volts)) return null;
    if (volts <= points[0][0]) return 0;
    if (volts >= points.at(-1)[0]) return 100;
    for (let i = 1; i < points.length; i++) {
      const [highV, highSoc] = points[i],
        [lowV, lowSoc] = points[i - 1];
      if (volts <= highV) return lowSoc + ((volts - lowV) * (highSoc - lowSoc)) / (highV - lowV);
    }
    return 100;
  };
  // LiFePO4 reference estimates. Charging uses Renogy's charge-voltage table
  // converted from a four-cell 12 V pack to one cell. Discharging uses its
  // resting/discharge SOC table. Linear interpolation is deliberately bounded.
  const SOC_CHARGING_POINTS = [
    [2.75, 0],
    [3.0, 10],
    [3.1, 20],
    [3.2, 30],
    [3.25, 40],
    [3.3, 50],
    [3.35, 60],
    [3.4, 70],
    [3.45, 80],
    [3.5, 90],
    [3.6, 100]
  ];
  const SOC_DISCHARGING_POINTS = [
    [2.5, 0],
    [3.0, 10],
    [3.2, 20],
    [3.22, 30],
    [3.25, 40],
    [3.26, 50],
    [3.27, 60],
    [3.3, 70],
    [3.32, 80],
    [3.35, 90],
    [3.4, 100]
  ];
  const socFromCellVoltage = volts => interpolateSoc(volts, SOC_CHARGING_POINTS);
  const averageCellVolts = item => {
    const cells = item.cells_mv || [];
    return cells.length ? cells.reduce((sum, mv) => sum + Number(mv), 0) / cells.length / 1000 : null;
  };
  const referenceSoc = (item, points) => {
    const volts = averageCellVolts(item);
    return volts == null ? '—' : `${Math.round(interpolateSoc(volts, points))}%`;
  };
  const socCircle = item => gaugeDial(item.state_of_charge_percent);
  const mos = value => (value == null ? '—' : value ? 'On' : 'Off');
  const summary =
    '<div class="bms-summary">' +
    items
      .map((item, index) => {
        const current = item.current_a == null ? '—' : `${Number(item.current_a).toFixed(1)} A`,
          temp = (item.temperatures_c || [])[0],
          batteryId = index + 1;
        return `<article class="bms-summary-card" data-bms-refresh="${batteryId}" role="button" tabindex="0" aria-label="Refresh ${esc(item.battery)}" onclick="refreshBmsBattery(${batteryId})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();refreshBmsBattery(${batteryId})}"><div class="bms-name">${esc(item.battery)}</div><div class="bms-connection ${esc(item.state)}">${stateText(item)}</div>${socCircle(item)}<div class="bms-summary-values"><span>${item.pack_voltage_v == null ? '—' : Number(item.pack_voltage_v).toFixed(2) + ' V'}</span><span>${current}</span><span>${temp == null ? '—' : Math.round(Number(temp)) + '°C'}</span></div>${cellBars(item, bals[index])}</article>`;
      })
      .join('') +
    '</div>';
  let html = '<div class="bms-matrix"><div class="bms-matrix-cell bms-matrix-label bms-matrix-head" aria-hidden="true"></div>';
  html += items
    .map(
      (item, index) =>
        `<div class="bms-matrix-cell bms-matrix-head bms-head-click ${index === items.length - 1 ? 'last' : ''}" data-bms-head="${index + 1}" role="button" tabindex="0" aria-label="Refresh ${esc(item.battery)}" title="Refresh ${esc(item.battery)}" onclick="refreshBmsBattery(${index + 1})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();refreshBmsBattery(${index + 1})}"><div class="bms-name">${esc(item.battery)}</div>${balHead(bals[index], index)}</div>`
    )
    .join('');
  html += '<div class="bms-matrix-cell bms-matrix-section">STATUS</div>';
  html += valueRow(
    'Ah remaining',
    items.map(x => bmsNumber(x.remaining_capacity_ah, 0, ' Ah'))
  );
  html += valueRow(
    'kWh remaining',
    items.map(x =>
      x.remaining_capacity_ah == null ? '—' : `${((Number(x.remaining_capacity_ah) * NOMINAL_BANK_VOLTAGE_V) / 1000).toFixed(2)} kWh`
    )
  );
  html += valueRow(
    'Alarms',
    items.map(x => alarmLines(x.alarms))
  );
  html += valueRow(
    'Cycles',
    items.map(x => x.cycles ?? '—')
  );
  html += valueRow(
    'SOC - Charging',
    items.map(x => referenceSoc(x, SOC_CHARGING_POINTS))
  );
  html += valueRow(
    'SOC - Discharging',
    items.map(x => referenceSoc(x, SOC_DISCHARGING_POINTS))
  );
  html +=
    `<div class="bms-matrix-cell bms-matrix-actions bms-all-actions"><button id="bmsAllSoc" class="bms-action" type="button" disabled onclick="chooseBmsSoc(0,this)">Set all SOC</button></div>` +
    items
      .map(
        (item, index) =>
          `<div class="bms-matrix-cell bms-matrix-actions ${index === items.length - 1 ? 'last' : ''}">${bmsSocButton(index + 1, !['connected', 'reading'].includes(item.state))}</div>`
      )
      .join('');
  html += '<div class="bms-matrix-cell bms-matrix-section">BALANCING</div>';
  html += valueRow(
    'Balance status',
    items.map((x, i) => balVal(i, s => (s.balance_active ? 'Active' : 'Inactive')))
  );
  html += valueRow(
    'Balance current',
    items.map((x, i) => balVal(i, s => (s.reported_current_a == null ? '—' : `${Number(s.reported_current_a).toFixed(1)} A`)))
  );
  html += valueRow(
    'Balance position',
    items.map((x, i) => balVal(i, s => ((s.balance_position || []).length ? `Cells ${cellList(s.balance_position)}` : '—')))
  );
  html += valueRow(
    'Temperature',
    items.map((x, i) => balVal(i, s => (s.temperatures_c || []).map(v => `${Math.round(Number(v))}°C`).join(', ') || '—'))
  );
  html += '<div class="bms-matrix-cell bms-matrix-section">CELLS</div>';
  html += valueRow(
    'Average',
    items.map(x => {
      const avg = averageCellVolts(x);
      return voltageReading(avg);
    }),
    'voltage-cell'
  );
  html += valueRow(
    'Max difference',
    items.map(x => bmsNumber(x.cell_spread_mv, 0, ' mV'))
  );
  for (let cell = 0; cell < maxCells; cell++)
    html += valueRow(
      `Cell ${cell + 1}`,
      items.map(x => {
        const cells = (x.cells_mv || []).map(Number),
          mv = cells[cell];
        if (mv == null) return '—';
        const dots = `${mv === Math.max(...cells) ? '<i class="cell-dot high" title="Highest cell"></i>' : ''}${mv === Math.min(...cells) ? '<i class="cell-dot low" title="Lowest cell"></i>' : ''}`;
        return dots + voltageReading(mv / 1000);
      }),
      'voltage-cell'
    );
  html += '<div class="bms-matrix-cell bms-matrix-section">CONTROL</div>';
  const allChargeOn = items.every(item => item.charge_mosfet_on === true),
    allDischargeOn = items.every(item => item.discharge_mosfet_on === true),
    allChargeState = allChargeOn ? 'ON' : 'OFF',
    allDischargeState = allDischargeOn ? 'ON' : 'OFF',
    allChargeBusy = !!bmsAllChargeControl,
    allDischargeBusy = !!bmsAllDischargeControl,
    phaseLabel = control =>
      control.phase === 'queued' ? 'Queued' : control.phase === 'waiting' ? 'Waiting for Bluetooth' : 'Action in progress',
    allChargeLabel = allChargeBusy
      ? phaseLabel(bmsAllChargeControl)
      : `All charge <span class="bms-power-icon" aria-hidden="true">⏻</span>`,
    allDischargeLabel = allDischargeBusy
      ? phaseLabel(bmsAllDischargeControl)
      : `All discharge <span class="bms-power-icon" aria-hidden="true">⏻</span>`;
  html +=
    `<div class="bms-matrix-cell bms-matrix-actions bms-all-actions"><button id="bmsAllCharge" class="bms-action ${allChargeOn ? 'on' : 'off'}" type="button" disabled aria-label="${allChargeBusy ? allChargeLabel : `All charge ${allChargeState}`}" title="${allChargeBusy ? allChargeLabel : `All charge ${allChargeState}`}" onclick="bmsControlAll('${allChargeOn ? 'charge-off' : 'charge-on'}')">${allChargeLabel}</button><button id="bmsAllDischarge" class="bms-action ${allDischargeOn ? 'on' : 'off'}" type="button" disabled aria-label="${allDischargeBusy ? allDischargeLabel : `All discharge ${allDischargeState}`}" title="${allDischargeBusy ? allDischargeLabel : `All discharge ${allDischargeState}`}" onclick="bmsControlAll('${allDischargeOn ? 'discharge-off' : 'discharge-on'}')">${allDischargeLabel}</button></div>` +
    items
      .map((item, index) => {
        const batteryId = index + 1,
          disabled = !['connected', 'reading'].includes(item.state),
          chargeDisabled = disabled || allChargeBusy || (item.charge_mosfet_on === true && !(Number(item.current_a) >= 0)),
          dischargeDisabled = disabled || allDischargeBusy || (item.discharge_mosfet_on === true && Number(item.current_a) > 0),
          chargeState = item.charge_mosfet_on ? 'ON' : 'OFF',
          dischargeState = item.discharge_mosfet_on ? 'ON' : 'OFF',
          chargeTitle = allChargeBusy
            ? 'All charge action in progress'
            : chargeDisabled && item.charge_mosfet_on
              ? 'Charge OFF is only available while current is zero or positive'
              : `Charge ${chargeState}`,
          dischargeTitle = allDischargeBusy
            ? 'All discharge action in progress'
            : dischargeDisabled && item.discharge_mosfet_on
              ? 'Discharge OFF is only available while current is zero or negative'
              : `Discharge ${dischargeState}`;
        return `<div class="bms-matrix-cell bms-matrix-actions ${index === items.length - 1 ? 'last' : ''}">${bmsIndividualButton(batteryId, 'charge', !item.charge_mosfet_on, 'Charge <span class="bms-power-icon" aria-hidden="true">⏻</span>', item.charge_mosfet_on ? 'on' : 'off', chargeDisabled, chargeTitle)}${bmsIndividualButton(batteryId, 'discharge', !item.discharge_mosfet_on, 'Discharge <span class="bms-power-icon" aria-hidden="true">⏻</span>', item.discharge_mosfet_on ? 'on' : 'off', dischargeDisabled, dischargeTitle)}</div>`;
      })
      .join('');
  return summary + html + '</div>';
}
function bmsRefreshMessage(data) {
  const reading = Object.entries(data.batteries || {}).find(([, item]) => item.state === 'reading');
  if (reading) {
    const index = Number(reading[0].split(' ')[1]);
    return `● Updating Battery ${index}/3…`;
  }
  const active = data.queue?.active,
    reasons = {
      balancer: '● Waiting for the active balancer transaction; refresh is next…',
      bms_read: '● Waiting for the active automatic read; refresh is next…',
      bms: '● Waiting for the active battery reconnect; refresh is next…',
      bms_control: '● Waiting for the active user control; refresh is next…',
      bms_manual_connect: '● Reconnecting a battery for this refresh…'
    };
  return reasons[active] || `● Refresh queued · ${data.refresh_status?.completed ?? 0}/3 complete…`;
}
async function loadBms(triggerInitial = false) {
  try {
    const [r, balRes] = await Promise.all([
        fetch('/api/bms', { cache: 'no-store' }),
        fetch('/api/balancers', { cache: 'no-store' }).catch(() => null)
      ]),
      data = await r.json(),
      balData = balRes && balRes.ok ? await balRes.json().catch(() => null) : null;
    if (!r.ok) throw Error(data.detail || 'Could not load BMS status');
    const captures = Object.values(data.batteries).map(x => Date.parse(x.captured_at || '') || 0),
      latest = Math.max(0, ...captures);
    if (latest > bmsLastCapture) bmsLastCapture = latest;
    const dependencyWarning = data.ble_available
      ? ''
      : '<div class="bms-error">Windows Bluetooth component is unavailable. Restart the server to retry installation.</div>';
    $('bmsCards').innerHTML = dependencyWarning + bmsMatrix(data, balData);
    const updating = !!data.busy;
    bmsManualPending = updating;
    $('bmsRefresh').disabled = updating || !data.ble_available;
    $('bmsRefresh').textContent = updating ? 'Updating…' : 'Refresh BMS';
    const clock = ms => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }),
      balBusy = !!balData?.busy,
      balLatest = balData ? Math.max(0, ...Object.values(balData.devices || {}).map(x => Date.parse(x.captured_at || '') || 0)) : 0;
    $('bmsBalRefresh').disabled = balBusy || !balData || !balData.ble_available;
    $('bmsBalRefresh').textContent = balBusy ? 'Updating…' : 'Refresh BAL';
    $('bmsRefreshState').textContent =
      (updating
        ? bmsRefreshMessage(data)
        : latest
          ? `BMS updated ${clock(latest)} · every ${data.refresh_interval_seconds}s`
          : 'BMS: waiting for first update…') +
      '\n' +
      (balBusy
        ? '● Updating balancers…'
        : balLatest
          ? `BAL updated ${clock(balLatest)} · every ${balData.refresh_interval_seconds}s`
          : 'BAL: waiting for first update…');
    const batteryNames = ['BATTERY 1', 'BATTERY 2', 'BATTERY 3'],
      allReady = batteryNames.every(name => ['connected', 'reading'].includes(data.batteries[name]?.state)),
      allChargeOn = batteryNames.every(name => data.batteries[name]?.charge_mosfet_on === true),
      allDischargeOn = batteryNames.every(name => data.batteries[name]?.discharge_mosfet_on === true),
      allChargeEligible = allReady && (!allChargeOn || batteryNames.every(name => Number(data.batteries[name]?.current_a) >= 0)),
      allDischargeEligible = allReady && (!allDischargeOn || batteryNames.every(name => Number(data.batteries[name]?.current_a) <= 0));
    $('bmsAllSoc').disabled = !allReady;
    $('bmsAllCharge').disabled = !!bmsAllChargeControl || !allChargeEligible;
    $('bmsAllDischarge').disabled = !!bmsAllDischargeControl || !allDischargeEligible;
    if (triggerInitial && data.ble_available && !data.busy && Object.values(data.batteries).every(x => x.state === 'not_read'))
      refreshAllBms();
  } catch (e) {
    bmsManualPending = false;
    $('bmsCards').innerHTML = `<div class="bms-error">${esc(e.message)}</div>`;
  }
}
async function refreshAllBms() {
  bmsManualPending = true;
  $('bmsRefresh').disabled = true;
  $('bmsRefresh').textContent = 'Updating…';
  $('bmsRefreshState').textContent = '● Updating all batteries…';
  try {
    const r = await fetch('/api/bms/refresh', { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Could not start BMS refresh');
    setTimeout(() => loadBms(false), 350);
  } catch (e) {
    bmsManualPending = false;
    $('bmsCards').innerHTML = `<div class="bms-error">${esc(e.message)}</div>`;
    $('bmsRefresh').disabled = false;
    $('bmsRefresh').textContent = 'Refresh BMS';
  }
}
async function refreshAllBalancersFromBms() {
  // The BMS page's "Refresh BAL": refreshes all three balancers.
  $('bmsBalRefresh').disabled = true;
  $('bmsBalRefresh').textContent = 'Updating…';
  try {
    const r = await fetch('/api/balancers/refresh', { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Could not refresh balancers');
    setTimeout(() => loadBms(false), 350);
  } catch (e) {
    showBmsInfo('Balancer refresh failed', e.message, 0);
    $('bmsBalRefresh').disabled = false;
    $('bmsBalRefresh').textContent = 'Refresh BAL';
  }
}
async function refreshBmsBattery(batteryId) {
  const card = document.querySelector(`[data-bms-refresh="${batteryId}"]`),
    status = card?.querySelector('.bms-connection');
  if (status) status.textContent = '● Updating…';
  try {
    const r = await fetch(`/api/bms/${batteryId}/refresh`, { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Could not refresh battery');
    setTimeout(() => loadBms(false), 350);
  } catch (e) {
    showBmsInfo('BMS refresh failed', e.message, 0);
    loadBms(false);
  }
}
function closeBmsDialog(result = false) {
  if (bmsDialogTimer) {
    clearTimeout(bmsDialogTimer);
    bmsDialogTimer = null;
  }
  const dialog = $('bmsDialog');
  dialog.classList.remove('open');
  dialog.setAttribute('aria-hidden', 'true');
  if (bmsDialogResolve) {
    const resolve = bmsDialogResolve;
    bmsDialogResolve = null;
    resolve(result);
  }
}
function showBmsConfirm(title, text) {
  closeBmsDialog(false);
  $('bmsDialogTitle').textContent = title;
  $('bmsDialogText').textContent = text;
  $('bmsDialogNote').textContent = 'A status backup is saved before the BMS is changed.';
  $('bmsDialogIcon').textContent = '!';
  $('bmsDialogConfirmActions').style.display = 'grid';
  $('bmsDialogInfoActions').style.display = 'none';
  $('bmsDialogSocActions').style.display = 'none';
  $('bmsDialog').classList.add('open');
  $('bmsDialog').setAttribute('aria-hidden', 'false');
  return new Promise(resolve => {
    bmsDialogResolve = resolve;
    $('bmsDialogConfirm').onclick = () => closeBmsDialog(true);
    $('bmsDialogCancel').onclick = () => closeBmsDialog(false);
  });
}
function showBmsSocChoice(title) {
  closeBmsDialog(false);
  $('bmsDialogTitle').textContent = title;
  $('bmsDialogText').textContent = 'Choose the SOC value to write.';
  $('bmsDialogNote').textContent = 'Cancel is selected by default.';
  $('bmsDialogIcon').textContent = '%';
  $('bmsDialogConfirmActions').style.display = 'none';
  $('bmsDialogInfoActions').style.display = 'none';
  $('bmsDialogSocActions').style.display = 'grid';
  $('bmsSocManualValue').value = '';
  $('bmsSocManualError').hidden = true;
  $('bmsDialog').classList.add('open');
  $('bmsDialog').setAttribute('aria-hidden', 'false');
  return new Promise(resolve => {
    bmsDialogResolve = resolve;
    $('bmsSocCharge').onclick = () => closeBmsDialog('charge');
    $('bmsSocDischarge').onclick = () => closeBmsDialog('discharge');
    $('bmsSoc100').onclick = () => closeBmsDialog('100');
    $('bmsSocManual').onclick = () => {
      const raw = $('bmsSocManualValue').value.trim(),
        value = Number(raw),
        error = $('bmsSocManualError');
      if (raw === '' || !Number.isFinite(value) || value < 0 || value > 100) {
        error.textContent = 'Enter a percentage between 0 and 100';
        error.hidden = false;
        $('bmsSocManualValue').focus();
        return;
      }
      error.hidden = true;
      closeBmsDialog({ percent: value });
    };
    $('bmsSocCancel').onclick = () => closeBmsDialog(false);
    requestAnimationFrame(() => $('bmsSocCancel').focus());
  });
}
function showBmsProgress(text) {
  closeBmsDialog(false);
  $('bmsDialogTitle').textContent = 'Updating BMS';
  $('bmsDialogText').textContent = text;
  $('bmsDialogNote').textContent = 'All three batteries will be refreshed.';
  $('bmsDialogIcon').textContent = '↻';
  $('bmsDialogConfirmActions').style.display = 'none';
  $('bmsDialogInfoActions').style.display = 'none';
  $('bmsDialogSocActions').style.display = 'none';
  $('bmsDialog').classList.add('open');
  $('bmsDialog').setAttribute('aria-hidden', 'false');
}
async function syncBmsControlProgress() {
  try {
    const r = await fetch('/api/bms', { cache: 'no-store' }),
      data = await r.json(),
      progress = data.control_status;
    if (!r.ok) return;
    if (bmsIndividualControl) {
      const waiting = progress?.busy && progress.phase === 'waiting';
      bmsIndividualControl.phase = waiting ? 'waiting' : 'progress';
      const button = document.querySelector(`[data-bms-key="${bmsIndividualControl.key}"]`);
      if (button) {
        button.textContent = waiting ? 'Waiting for Bluetooth' : 'Action in progress';
        button.setAttribute('aria-label', button.textContent);
        button.title = button.textContent;
      }
      return;
    }
    const allControl = bmsAllChargeControl || bmsAllDischargeControl;
    if (allControl) {
      const waiting = progress?.busy && progress.phase === 'waiting';
      allControl.phase = waiting ? 'waiting' : 'progress';
      const button = $(bmsAllChargeControl ? 'bmsAllCharge' : 'bmsAllDischarge');
      if (button) {
        button.textContent = waiting ? 'Waiting for Bluetooth' : 'Action in progress';
        button.setAttribute('aria-label', button.textContent);
        button.title = button.textContent;
      }
      return;
    }
    if (progress?.busy && progress.phase === 'waiting') {
      const active = data.queue?.active,
        reasons = {
          balancer: 'Waiting for the current balancer transaction to finish; your action is next',
          bms_read: 'Waiting for the current automatic battery read to finish; your action is next',
          bms_manual_read: 'Waiting for the current manual battery refresh to finish; your action is next',
          bms: 'Waiting for the current battery reconnect to finish; your action is next',
          bms_manual_connect: 'Waiting for the requested battery reconnect to finish; your action is next',
          bms_control: 'Waiting for another user control to finish; your action is next'
        },
        message = reasons[active] || 'Waiting for Bluetooth queue to become available';
      if (!$('bmsDialog').classList.contains('open')) showBmsProgress(message);
      else $('bmsDialogText').textContent = message;
    } else if ($('bmsDialog').classList.contains('open') && $('bmsDialogTitle').textContent === 'Updating BMS') closeBmsDialog(false);
  } catch (e) {}
}
function showBmsInfo(title, text, durationSeconds = null) {
  closeBmsDialog(false);
  $('bmsDialogTitle').textContent = title;
  $('bmsDialogText').textContent = text;
  $('bmsDialogNote').textContent = '';
  $('bmsDialogIcon').textContent = 'i';
  $('bmsDialogConfirmActions').style.display = 'none';
  $('bmsDialogInfoActions').style.display = 'grid';
  $('bmsDialogSocActions').style.display = 'none';
  $('bmsDialogOk').onclick = () => closeBmsDialog(false);
  $('bmsDialog').classList.add('open');
  $('bmsDialog').setAttribute('aria-hidden', 'false');
  const seconds = durationSeconds ?? Number(state.settings?.bms_popup_seconds ?? 3);
  if (seconds > 0) bmsDialogTimer = setTimeout(() => closeBmsDialog(false), seconds * 1000);
}
function bmsControl(batteryId, action, enabled, button) {
  const key = `${batteryId}:${action}`;
  if ((bmsIndividualControl && bmsIndividualControl.key === key) || bmsIndividualQueue.some(task => task.key === key)) return;
  bmsIndividualQueue.push({ batteryId, action, enabled, key });
  button.disabled = true;
  button.textContent = bmsIndividualProcessing ? 'Queued' : 'Waiting for Bluetooth';
  button.setAttribute('aria-label', button.textContent);
  button.title = button.textContent;
  processBmsIndividualQueue();
}
async function processBmsIndividualQueue() {
  if (
    bmsIndividualProcessing ||
    (bmsAllChargeControl && bmsAllChargeControl.phase !== 'queued') ||
    (bmsAllDischargeControl && bmsAllDischargeControl.phase !== 'queued') ||
    !bmsIndividualQueue.length
  )
    return;
  bmsIndividualProcessing = true;
  const task = bmsIndividualQueue.shift(),
    battery = `BATTERY ${task.batteryId}`;
  bmsIndividualControl = { ...task, phase: 'waiting' };
  let queueBusy = false;
  try {
    const q = await fetch('/api/bluetooth-coordinator', { cache: 'no-store' }),
      queue = await q.json();
    queueBusy = !!queue.active || Number(queue.waiting_bms) > 0;
  } catch (e) {}
  bmsIndividualControl.phase = queueBusy ? 'waiting' : 'progress';
  let button = document.querySelector(`[data-bms-key="${task.key}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = queueBusy ? 'Waiting for Bluetooth' : 'Action in progress';
    button.setAttribute('aria-label', button.textContent);
    button.title = button.textContent;
  }
  const progressTimer = setInterval(syncBmsControlProgress, 400);
  try {
    const options = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
    if (task.action === 'charge' || task.action === 'discharge') options.body = JSON.stringify({ enabled: !!task.enabled });
    else if (task.action === 'set-soc-value') options.body = JSON.stringify({ percent: Number(task.enabled) });
    const r = await fetch(`/api/bms/${task.batteryId}/${task.action}`, options),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || `BMS control failed (HTTP ${r.status})`);
  } catch (e) {
    showBmsInfo('BMS update failed', `${battery}: ${e.message}`, 0);
  } finally {
    clearInterval(progressTimer);
    bmsIndividualControl = null;
    bmsIndividualProcessing = false;
    await loadBms(false);
    processBmsIndividualQueue();
  }
}
async function bmsControlAll(mode, confirmed = false, percent) {
  const descriptions = {
    100: 'Set all three battery SOC values to 100%?',
    charge: 'Set all three SOC values from the SOC - Charging row?',
    discharge: 'Set all three SOC values from the SOC - Discharging row?',
    value: `Set all three battery SOC values to ${percent}%?`,
    'charge-on': 'Turn charging ON for all three batteries?',
    'charge-off': 'Turn charging OFF for all three batteries?',
    'discharge-on': 'Turn discharging ON for all three batteries?',
    'discharge-off': 'Turn discharging OFF for all three batteries?'
  };
  if (!confirmed && !(await showBmsConfirm('Confirm all BMS changes', descriptions[mode]))) return;
  if (mode === 'charge-on' || mode === 'charge-off') {
    runBmsAllCharge(mode);
    return;
  }
  if (mode === 'discharge-on' || mode === 'discharge-off') {
    runBmsAllDischarge(mode);
    return;
  }
  let queueBusy = false;
  try {
    const q = await fetch('/api/bluetooth-coordinator', { cache: 'no-store' }),
      queue = await q.json();
    queueBusy = !!queue.active || Number(queue.waiting_bms) > 0;
  } catch (e) {}
  if (queueBusy) showBmsProgress('Waiting for Bluetooth queue to become available');
  document.querySelectorAll('.bms-action').forEach(button => (button.disabled = true));
  const progressTimer = setInterval(syncBmsControlProgress, 400);
  try {
    const url = `/api/bms/set-all-soc/${mode}`,
      options =
        mode === 'value'
          ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ percent }) }
          : { method: 'POST' },
      r = await fetch(url, options),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || `BMS control failed (HTTP ${r.status})`);
    closeBmsDialog(false);
    await loadBms(false);
  } catch (e) {
    await loadBms(false);
    showBmsInfo('BMS update failed', e.message, 0);
  } finally {
    clearInterval(progressTimer);
  }
}
async function runBmsAllCharge(mode) {
  if (bmsAllChargeControl) return;
  bmsAllChargeControl = { mode, phase: 'queued' };
  await loadBms(false);
  processBmsIndividualQueue();
  while (bmsIndividualProcessing || bmsIndividualQueue.length) await new Promise(resolve => setTimeout(resolve, 200));
  bmsAllChargeControl.phase = 'waiting';
  await loadBms(false);
  let queueBusy = false;
  try {
    const q = await fetch('/api/bluetooth-coordinator', { cache: 'no-store' }),
      queue = await q.json();
    queueBusy = !!queue.active || Number(queue.waiting_bms) > 0;
  } catch (e) {}
  bmsAllChargeControl.phase = queueBusy ? 'waiting' : 'progress';
  await loadBms(false);
  const progressTimer = setInterval(syncBmsControlProgress, 400);
  try {
    const r = await fetch(`/api/bms/set-all/${mode}`, { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || `BMS control failed (HTTP ${r.status})`);
    bmsAllChargeControl = null;
    await loadBms(false);
  } catch (e) {
    bmsAllChargeControl = null;
    await loadBms(false);
    showBmsInfo('BMS update failed', e.message, 0);
  } finally {
    clearInterval(progressTimer);
    processBmsIndividualQueue();
  }
}
async function runBmsAllDischarge(mode) {
  if (bmsAllDischargeControl) return;
  bmsAllDischargeControl = { mode, phase: 'queued' };
  await loadBms(false);
  processBmsIndividualQueue();
  while (bmsIndividualProcessing || bmsIndividualQueue.length) await new Promise(resolve => setTimeout(resolve, 200));
  bmsAllDischargeControl.phase = 'waiting';
  await loadBms(false);
  let queueBusy = false;
  try {
    const q = await fetch('/api/bluetooth-coordinator', { cache: 'no-store' }),
      queue = await q.json();
    queueBusy = !!queue.active || Number(queue.waiting_bms) > 0;
  } catch (e) {}
  bmsAllDischargeControl.phase = queueBusy ? 'waiting' : 'progress';
  await loadBms(false);
  const progressTimer = setInterval(syncBmsControlProgress, 400);
  try {
    const r = await fetch(`/api/bms/set-all/${mode}`, { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || `BMS control failed (HTTP ${r.status})`);
    bmsAllDischargeControl = null;
    await loadBms(false);
  } catch (e) {
    bmsAllDischargeControl = null;
    await loadBms(false);
    showBmsInfo('BMS update failed', e.message, 0);
  } finally {
    clearInterval(progressTimer);
    processBmsIndividualQueue();
  }
}
async function refreshBalancer(balancerId) {
  // The balancer status line in a BMS-page column header: refreshes that balancer, not the battery.
  const status = document.querySelector(`[data-bms-balancer-refresh="${balancerId}"]`);
  if (status) status.textContent = '● Queued…';
  try {
    const r = await fetch(`/api/balancers/${balancerId}/refresh`, { method: 'POST' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Could not refresh balancer');
    setTimeout(() => loadBms(false), 350);
  } catch (e) {
    showBmsInfo('Balancer refresh failed', e.message, 0);
    loadBms(false);
  }
}
