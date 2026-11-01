// The Control panel: tiles for sources, storage and loads, the SOC gauge, and the refresh/post helpers.
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

function icon(k) {
  const icons = {
    shore: `<svg viewBox="0 0 24 24"><path d="M8 3v6m8-6v6M6 9h12v2a6 6 0 0 1-6 6v4M9 21h6"/></svg>`,
    charger_house: `<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="16" rx="2"/><path d="M9 8h6m-6 4h6m-2 4h2"/><path d="M7 16h2"/></svg>`,
    alternator: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4M5 5l3 3m8 8 3 3m0-14-3 3M8 16l-3 3"/></svg>`,
    solar: `<svg viewBox="0 0 24 24"><circle cx="7" cy="6" r="2.5"/><path d="M7 1v2m0 6v2M2 6h2m6 0h2M3.5 2.5 5 4m4 4 1.5 1.5M10.5 2.5 9 4M5 8 3.5 9.5"/><path d="M8 13h12l-2 8H6zM8 17h10m-6-4-1 8m5-8-1 8"/></svg>`,
    house: `<svg class="fillable" viewBox="0 0 24 24"><rect x="4" y="7" width="16" height="13" rx="2"/><path d="M9 4v3m6-3v3"/><path class="fill" d="M7 11h10v6H7z"/></svg>`,
    start: `<svg class="fillable" viewBox="0 0 24 24"><rect x="4" y="7" width="16" height="13" rx="2"/><path d="M9 4v3m6-3v3"/><path class="fill" d="M7 11h10v6H7z"/></svg>`,
    bow: `<svg class="fillable" viewBox="0 0 24 24"><rect x="4" y="7" width="16" height="13" rx="2"/><path d="M9 4v3m6-3v3"/><path class="fill" d="M7 11h10v6H7z"/></svg>`,
    house_ac: `<svg viewBox="0 0 24 24"><path d="M4 12 12 5l8 7v8H4z"/><path d="M8 15c1.4-2 2.6 2 4 0s2.6-2 4 0"/></svg>`,
    inverter: `<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M7 12h3l1.5-3 2.5 6 1.5-3H18"/></svg>`,
    charger_start: `<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="16" rx="2"/><path d="M9 8h6m-6 4h6m-2 4h2M7 16h2"/></svg>`,
    charger_bow: `<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="16" rx="2"/><path d="M9 8h6m-6 4h6m-2 4h2M7 16h2"/></svg>`,
    engine_ecu: `<svg viewBox="0 0 24 24"><path d="M4 9h2l2-3h7l2 3h3v7h-3l-2 3H8l-2-3H4z"/><path d="M2 10v5m20-5v5M10 3v3m4-3v3"/></svg>`,
    other_dc: `<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18" cy="12" r="1.5"/></svg>`
  };
  return k === 'alternator_field' ? icons.alternator : icons[k] || icons.other_dc;
}
function signedWatts(v) {
  if (v == null) return '—';
  v = Number(v);
  const sign = v > 0 ? '+' : '';
  return sign + (Math.abs(v) >= 1000 ? (Math.abs(v) / 1000).toFixed(2) + ' kW' : Math.round(v) + ' W');
}
function elecCols(x, forceDC = false, signedPower = false, highDischarge = false) {
  const kind = forceDC ? 'DC' : x.kind || '';
  const v = x.voltage == null ? '—' : num(x.voltage, 2) + ' V';
  const a = x.current == null ? '—' : num(x.current, 1) + ' A';
  const w = x.power == null ? '—' : signedPower ? signedWatts(x.power) : watts(x.power);
  const alertClass = highDischarge ? ' high-discharge-alert' : '';
  return `<div class="kindcol">${kind}</div><div class="elec vcol">${v}</div><div class="elec acol${alertClass}">${a}</div><div class="wcol${alertClass}">${w}</div>`;
}
function card(k, x) {
  const ctlMap = { charger_start: 'charger_start', charger_bow: 'charger_bow', engine_ecu: 'engine_ecu', solar: 'solar' };
  const ctl = ctlMap[k];
  let button = '<div class="controlslot"></div>';
  let device = `<div class="device"><div class="name">${x.label}</div><div class="subline"></div></div>`;
  if (k === 'shore') {
    const current = +state.combimaster?.ac_support_enabled >= 0.5;
    const supporting = +state.combimaster?.supporting >= 0.5;
    const shoreState = x.connected ? 'Connected' : 'Not connected';
    const inputFrequency = x.connected ? `<span class="temp-state">f ${frequency(x.input_frequency)}</span>` : '';
    device = `<div class="device shore-device"><div class="name">${x.label}</div><div class="shore-limit-stack"><input aria-label="AC limit (A), whole number 3 to 15" class="shore-limit" id="limit" type="text" inputmode="numeric" pattern="(?:[3-9]|1[0-5])" maxlength="2" autocomplete="off" enterkeyhint="done" onchange="setLimit()" onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur()}"><span class="shore-limit-label">AC limit (A)</span></div><div class="shore-status"><span class="state">● ${shoreState}</span>${inputFrequency}</div></div>`;
    button = `<button title="AC IN support ${current ? 'ON' : 'OFF'}" class="mini ${current ? 'on' : ''} ${current && supporting ? 'supporting-blink' : ''}" onclick="event.stopPropagation();toggleSupport()">SUP</button>`;
  } else if (k === 'inverter') {
    const current = +state.combimaster?.inverter_enabled >= 0.5;
    button = `<button title="Inverter ${current ? 'ON' : 'OFF'}" class="mini ${current ? 'on' : ''}" onclick="event.stopPropagation();toggleInv()">INV</button>`;
  } else if (k === 'charger_house') {
    const current = +state.combimaster?.charger_enabled >= 0.5;
    button = `<button title="CombiMaster Charger" class="mini ${current ? 'on' : ''}" onclick="event.stopPropagation();toggleChg()">${current ? 'ON' : 'OFF'}</button>`;
  } else if (k === 'alternator' || k === 'alternator_field') {
    const current = !!x.control_on;
    button = `<button title="Alpha Pro charging: ${current ? 'ON' : 'OFF'}" class="mini ${current ? 'on' : ''}" onclick="event.stopPropagation();toggleAlternator()">${current ? 'ON' : 'OFF'}</button>`;
  } else if (ctl) {
    const cfg = (state.controls || {})[ctl];
    const available = cfg && cfg.verified;
    const current = cfg && cfg.current;
    const label = available ? (current ? 'ON' : 'OFF') : 'N/A';
    const tip = cfg ? cfg.reason || (cfg.options || []).map(o => o.index + ': ' + o.label).join(' | ') : 'Control not mapped';
    button = `<button title="${tip.replace(/"/g, '&quot;')}" class="mini ${current ? 'on' : ''} ${available ? '' : 'na'}" ${available ? '' : 'disabled'} onclick="event.stopPropagation();toggleDevice('${ctl}')">${label}</button>`;
  }
  const controlState =
    k === 'engine_ecu' && (state.controls || {}).engine_ecu
      ? state.controls.engine_ecu.current
        ? 'On'
        : 'Off'
      : k === 'inverter'
        ? x.enabled
          ? 'On'
          : 'Off'
        : '';
  const acLoadState = k === 'house_ac' ? (Number(x.power) > 0 ? 'Active' : 'Inactive') : '';
  const displayState = acLoadState || x.charge_state || x.state || controlState;
  const temp =
    k === 'alternator' && x.temperature != null ? `<span class="temp-state">Temp ${Math.round(Number(x.temperature))}°C</span>` : '';
  const pv = k === 'solar' && x.panel_voltage != null ? `<span class="temp-state">PV ${Math.round(Number(x.panel_voltage))}V</span>` : '';
  const acFrequency = k === 'house_ac' ? `<span class="temp-state frequency-line">f ${frequency(x.output_frequency)}</span>` : '';
  const inverterStatus =
    k === 'inverter'
      ? `${x.inverting ? 'Inverting' : ''}${x.inverting && x.supporting ? ' · ' : ''}${x.supporting ? '<span class="supporting-status">Supporting</span>' : ''}`
      : '';
  const inverterDetail = inverterStatus ? `<span class="temp-state">${inverterStatus}</span>` : '';
  if (k !== 'shore')
    device = `<div class="device"><div class="name">${x.label}</div><div class="subline">${displayState ? `<span class="state">● ${displayState}</span>` : ''}${temp}${pv}${acFrequency}${inverterDetail}</div></div>`;
  return `<div class="card ${k === 'shore' ? 'shore-card' : ''}"><div class="icon">${icon(k)}</div>${device}${elecCols(x)}${button}</div>`;
}
function gaugeDial(soc, label) {
  const arcs =
    '<path class="bms-gauge-zone bms-gauge-red" d="M10 50 A40 40 0 0 1 37.64 11.96"/><path class="bms-gauge-zone bms-gauge-amber" d="M37.64 11.96 A40 40 0 0 1 62.36 11.96"/><path class="bms-gauge-zone bms-gauge-green" d="M62.36 11.96 A40 40 0 0 1 90 50"/>';
  if (soc == null)
    return `<div class="bms-dial" aria-label="No SOC data"><svg viewBox="0 0 100 60" aria-hidden="true">${arcs}</svg><span class="bms-dial-value">${label ?? '—'}</span></div>`;
  const pct = Math.max(0, Math.min(100, Number(soc))),
    angle = -90 + pct * 1.8;
  return `<div class="bms-dial" style="--angle:${angle}deg" aria-label="SOC ${Math.round(pct)} percent"><svg viewBox="0 0 100 60" aria-hidden="true">${arcs}<line class="bms-gauge-needle" x1="50" y1="50" x2="50" y2="17"/><circle class="bms-gauge-hub" cx="50" cy="50" r="4"/></svg><span class="bms-dial-value">${label ?? Math.round(pct) + '%'}</span></div>`;
}
function battery(k, x) {
  const s = x.soc == null ? 0 : Math.max(0, Math.min(100, +x.soc));
  const capacity = x.capacity == null ? '' : ` ${Math.round(Number(x.capacity))}A`;
  const batteryType = `${x.battery_type || 'Unknown'}${capacity}`;
  const socLabel = x.soc == null ? '—' : Math.round(s) + '%';
  const highDischarge = k === 'house' && x.current != null && Number(x.current) <= -100;
  return `<div class="card card-battery"><div class="icon">${icon(k)}</div><div class="device"><div class="name">${x.label}</div><div class="subline">${batteryType}</div></div>${elecCols(x, true, true, highDischarge)}${gaugeDial(x.soc == null ? null : s, socLabel)}</div>`;
}
function showErr(m) {
  $('err').style.display = m ? 'block' : 'none';
  $('err').textContent = m || '';
}
function render(d) {
  const editingLimit = document.activeElement === $('limit');
  state = d;
  lastGood = d;
  // Replacing Sources also replaces the AC-limit input. Keep its actual DOM
  // node alive while focused so desktop focus and the iOS keyboard stay open.
  if (!editingLimit)
    $('sources').innerHTML = Object.entries(d.sources)
      .map(([k, x]) => card(k, x))
      .join('');
  $('storage').innerHTML = Object.entries(d.storage)
    .map(([k, x]) => battery(k, x))
    .join('');
  $('loads').innerHTML = Object.entries(d.consumers)
    .map(([k, x]) => card(k, x))
    .join('');
  $('tdc').textContent = watts(d.totals.dc_input_power);
  $('tout').textContent = watts(d.totals.consumer_power);
  const houseW = +d.storage.house.power || 0;
  $('hflow').textContent = houseW > 0 ? 'Charging' : houseW < 0 ? 'Discharging' : 'Idle';
  $('hv').textContent = signedWatts(d.storage.house.power);
  activateMode(d.active_mode || null);
  let c = d.combimaster;
  if (document.activeElement !== $('limit') && c.ac_input_limit != null) $('limit').value = Math.round(c.ac_input_limit);
  $('sys').textContent = c.alarms && +c.alarms !== 0 ? 'Alarm ' + c.alarms : 'System OK';
  const floatEvent = Number(d.high_soc_float_policy?.event_id || 0);
  const bulkEvent = Number(d.high_soc_float_policy?.bulk_event_id || 0);
  const cellTrigger = Number(d.settings?.float_cell_trigger_mv ?? d.high_soc_float_policy?.cell_trigger_mv ?? 3500);
  const cellResume = Number(d.settings?.float_cell_resume_mv ?? d.high_soc_float_policy?.cell_resume_mv ?? 3420);
  if (lastFloatEvent === null) lastFloatEvent = floatEvent;
  else if (floatEvent > lastFloatEvent) {
    lastFloatEvent = floatEvent;
    const trigger = d.high_soc_float_policy?.trigger,
      cellBattery = d.high_soc_float_policy?.max_cell_battery;
    const reason =
      trigger === 'held'
        ? 'Cell-voltage data is unavailable, so Float protection is being held on'
        : `${cellBattery || 'A battery'} reached ${cellTrigger} mV on one cell`;
    $('floatInfoText').textContent = `${reason}. Charger House, Alternator, and Solar have been switched to Float.`;
    showFloatInfo();
  }
  if (lastBulkEvent === null) lastBulkEvent = bulkEvent;
  else if (bulkEvent > lastBulkEvent) {
    lastBulkEvent = bulkEvent;
    $('floatInfoText').textContent =
      `Every cell is at or below ${cellResume} mV. Charger House, Alternator, and Solar have been switched to Bulk.`;
    showFloatInfo();
  }
  $('disc').textContent = `Cache ${d.cache_items} values · verified fixed field map${appVersion ? ' · v' + appVersion : ''}`;
}
async function refresh() {
  if (busy) return;
  try {
    let r = await fetch('/api/energy', { cache: 'no-store' }),
      d = await r.json();
    if (!r.ok) throw Error(d.detail || 'request failed');
    render(d);
    $('offline').style.display = 'none';
    $('dot').className = 'dot';
    showErr('');
  } catch (e) {
    if (lastGood) render(lastGood);
    $('offline').style.display = 'block';
    $('dot').className = 'dot off';
    showErr(e.message);
  }
}
async function post(u, p) {
  busy = true;
  try {
    let r = await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) }),
      d = await r.json();
    if (!r.ok) throw Error(d.detail || 'control failed');
  } catch (e) {
    showErr(e.message);
  } finally {
    busy = false;
    refresh();
  }
}
