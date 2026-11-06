// Energy module: Mastervolt (MasterBus) and DALY BMS/balancers through the MasterVolt YMS server.
// Every control is written and read back by that server; Float protection runs there, not here.
// Engine ECU OFF always needs the confirmation whose default is "Keep ECU ON"; no mode switches the ECU off.
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, num, W, icon, hms, ago} = D;
const MODES = {   // what each mode does, as applied by the server (masterbus_service.set_operating_mode)
  motor: ["Inverter OFF", "Engine ECU ON", "Solar ON", "Charger Start ON", "Charger Bowthruster ON", "Alternator ON", "Charger House OFF"],
  anchor: ["Inverter OFF", "Charger House OFF", "Alternator OFF", "Solar ON", "Charger Start OFF", "Charger Bowthruster OFF"],
  generator: ["Inverter OFF", "Charger House ON", "Alternator OFF", "Solar ON", "Charger Start OFF", "Charger Bowthruster OFF"],
  marina: ["Inverter ON", "AC IN support ON", "AC limit = default", "Alternator OFF", "Solar ON", "Charger Start ON", "Charger Bowthruster ON", "Charger House ON"],
  sail: ["Inverter OFF", "Charger House OFF", "Alternator OFF", "Solar ON", "Charger Start OFF", "Charger Bowthruster OFF", "Engine ECU ON"],
};
const SRC_IC = {shore: ["plug", "shore"], charger_house: ["plug", "shore"], alternator: ["engine", "alt"], solar: ["sun", "solar"]};
const LOAD_IC = {house_ac: "load", inverter: "power", charger_start: "batt", charger_bow: "batt", engine_ecu: "engine", alternator_field: "engine", other_dc: "load"};
/** @type {[string, string, string, number?, number?, number?, string?][]} */
const SETTINGS = [   // [key, label, hint, min, max, step, unit] — the server's settings table (mastervolt/settings.py)
  ["float_protection_enabled", "Float protection", "Chargers to Float when the highest single cell reaches the trigger; the server checks every 3 s"],
  ["float_cell_trigger_mv", "Float at highest cell", "Any single cell at or above this starts Float", 3300, 3650, 1, "mV"],
  ["float_cell_resume_mv", "Resume Bulk below", "Highest cell back below this; at least 30 mV under the trigger", 3200, 3650, 1, "mV"],
  ["default_ac_limit", "Default AC input limit", "Used by Marina mode", 3, 15, 1, "A"],
  ["bms_refresh_interval", "BMS read interval", "", 5, 300, 1, "s"],
  ["bms_connection_retry_seconds", "BMS reconnect after", "", 1, 300, 1, "s"],
  ["balancer_refresh_interval", "Balancer read interval", "", 5, 300, 1, "s"],
  ["balancer_connection_retry_seconds", "Balancer reconnect after", "", 5, 300, 1, "s"],
  ["history_retention_days", "Keep history", "Lowering this deletes older history", 1, 365, 1, "days"],
];
let notif = null, alarmData = null, view = "now", bms = null, bal = null, settings = null, setDirty = false, limitDraft = null, coord = null, bleEv = null, hstat = null, report = null, reportT = null, hours = 24, chart = null, contrib = null, chartT = 0, chartFor = null;
const busy = new Set();
const zoom = [0, 1000];     // History: the part of the period shown, in thousandths (two-handled slider; all charts)
let zoomRaf = 0;
const solo = {};     // History: per chart the one series a legend tap shows on its own (absent: all of them)
const on = v => v != null && +v >= .5;
const flowW = v => v == null || !isFinite(+v) ? "–" : Math.round(+v) > 0 ? "+" + W(+v) : outW(-v);   // into a battery +, out of it −
const outW = v => v == null || !isFinite(+v) ? "–" : Math.round(Math.abs(+v)) ? "−" + W(Math.abs(+v)) : W(0);   // power going out, shown negative

const m = {
  id: "power", title: "Energy", short: "Energy", icon: "power", every: 3000, background: 6000,
  async load() {
    const jobs = [D.api("power", "/api/energy").then(d => m.state.data = d)];
    if (D.visibleIs("power") && view === "batt") {
      jobs.push(D.api("power", "/api/bms").then(d => bms = d).catch(() => {}), D.api("power", "/api/balancers").then(d => bal = d).catch(() => {}),
                D.api("power", "/api/bluetooth-coordinator").then(d => coord = d).catch(() => {}), D.api("power", "/api/bluetooth-events?limit=40").then(d => bleEv = d).catch(() => {}));
    }
    if (D.visibleIs("power") && view === "history") {
      jobs.push(D.api("power", "/api/history/status").then(d => hstat = d).catch(() => {}), D.api("power", "/api/reports/battery-health").then(d => report = d).catch(() => {}));
      if (chartFor !== hours || Date.now() - chartT > 60000) {      // the chart sample changes slowly: once a minute is plenty
        chartT = Date.now(); chartFor = hours;
        const end = new Date(), start = new Date(+end - hours * 3600e3);
        jobs.push(D.api("power", `/api/history/chart-data?hours=${hours}`, undefined, {timeout: 45000}).then(d => chart = d).catch(e => D.toast(e.message, true)),
                  D.api("power", `/api/history/contributions?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`, undefined, {timeout: 45000}).then(d => contrib = d).catch(() => {}),
                  D.api("power", `/api/history/alarms?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`, undefined, {timeout: 45000}).then(d => alarmData = d).catch(() => {}));
      }
    }
    if (D.visibleIs("power") && view === "settings" && !setDirty) jobs.push(D.api("power", "/api/settings").then(d => settings = d).catch(() => {}),
      D.api("power", "/api/notifications").then(d => notif = d).catch(() => {}));
    await Promise.all(jobs);
  },
  badge() {
    const d = m.state.data; if (!d) return null;
    const soc = d.storage && d.storage.house && d.storage.house.soc;
    if (soc != null && soc < 20) return "bad";
    if (on((d.combimaster || {}).alarms)) return "warn";
    if (soc != null && soc < 35) return "warn";
    return null;
  },
  tile() {
    const d = m.state.data; if (!d) return `<div class="line">${esc(m.state.err.message)}</div>`;
    return bankBody(d, "eT", true);
  },
  enter() { view = "now"; },     // from the Overview or the navigation: always the Control view
  tag() { const d = m.state.data; return d ? floatTag(d.high_soc_float_policy) : ""; },     // the Float status in the tile's header
  mount(el) {
    el.innerHTML = `<div id="eDown"></div>
      <div class="u-m-4-0-14 u-maxw-460 seg" role="tablist" id="eViews">
        <button type="button" data-view="now" aria-pressed="true">Control</button><button type="button" data-view="batt" aria-pressed="false">Batteries</button><button type="button" data-view="history" aria-pressed="false">History</button><button type="button" data-view="settings" aria-pressed="false">Settings</button></div>
      <div id="eNow"></div><div id="eBatt" hidden></div><div id="eHist" hidden></div><div id="eSet" hidden></div>`;
    el.addEventListener("click", onClick); el.addEventListener("change", onChange);
    el.addEventListener("input", e => { if (e.target.closest("#eSetForm")) { setDirty = true; validateSettings(); }
      else if (e.target.closest(".dual")) zoomInput(e.target); });
    el.addEventListener("submit", e => { if (e.target.id === "eSetForm") { e.preventDefault(); saveSettings(); } });
  },
  render() {
    $("eDown").innerHTML = m.state.err ? D.downCard(m) + '<div class="u-h-12"></div>' : "";
    document.querySelectorAll("#eViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === view));
    $("eNow").hidden = view !== "now"; $("eBatt").hidden = view !== "batt"; $("eHist").hidden = view !== "history"; $("eSet").hidden = view !== "settings";
    if (view === "now") renderNow(); else if (view === "batt") renderBatt(); else if (view === "history") renderHistory(); else renderSettings();
    // History keeps the view tabs, periods and zoom slider at the top: the tabs move into its fixed head while it is shown
    const tabs = $("eViews"), head = $("eHistHead");
    if (view === "history" && head) { if (tabs.parentElement !== head) head.prepend(tabs); head.style.top = $("top").offsetHeight + "px"; }
    else if (tabs.parentElement !== m.el) m.el.insertBefore(tabs, $("eNow"));
  },
};

/** House SOC as a half arc, red (empty) → orange → green (full), with a needle; no needle without a SOC. `id` keeps the
 * gradients apart: the Overview tile and the Control view are both in the page, and a hidden copy would blank the other.
 * @param {number | null | undefined} soc @param {string} id @param {string} [label] @param {string} [cls] "sm" for the smaller one */
function meter(soc, id, label = "House bank", cls = "") {
  const s = soc == null || !isFinite(+soc) ? null : Math.min(100, Math.max(0, +soc)), cx = 62, cy = 64, r = 48, f = v => v.toFixed(1);
  const arc = rr => `M ${cx - rr} ${cy} A ${rr} ${rr} 0 0 1 ${cx + rr} ${cy}`;
  let needle = "";
  if (s != null) {
    const a = Math.PI * (1 - s / 100), ux = Math.cos(a), uy = -Math.sin(a), vx = -uy, vy = ux;
    const P = (d, w) => `${f(cx + ux * d + vx * w)},${f(cy + uy * d + vy * w)}`;
    const i = cls === "sm" ? 39 : 28;   // the small one's pill is relatively larger: its needle starts further out
    needle = `<g class="needle"><polygon points="${P(i, 4.5)} ${P(r + 10, 1.2)} ${P(r + 10, -1.2)} ${P(i, -4.5)}"/></g>`;   // only the tip: clear of the pill
  }
  return `<div class="meter${cls ? " " + cls : ""}" role="img" aria-label="${esc(label)} ${s == null ? "unknown" : num(s) + " %"}"><svg viewBox="0 0 124 76" aria-hidden="true">
    <defs><linearGradient id="${id}Band" x1="0" x2="1"><stop offset="0" class="s0"/><stop offset=".5" class="s1"/><stop offset="1" class="s2"/></linearGradient>
      <linearGradient id="${id}Sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="g0"/><stop offset=".55" class="g1"/></linearGradient></defs>
    <path class="track" d="${arc(r)}"/><path class="band glow" d="${arc(r)}" stroke="url(#${id}Band)"/><path class="band" d="${arc(r)}" stroke="url(#${id}Band)"/>
    <path class="sheen" d="${arc(r - 4)}" stroke="url(#${id}Sheen)"/><path class="rim" d="${arc(r + 11)}"/>${needle}</svg>
    <span class="pill">${num(s)}<small>%</small></span></div>`;
}

// ------------------------------------------------------------------ Now
/** One provider or consumer: icon, name, power (`out`: a consumer, shown with a minus sign) and its switch, if it has one. */
function flowRow(x, ic, kind, sub, live, ctl = undefined, out = false) {
  const w = x.power, act = live ?? (w != null && w > 2);
  return `<div class="flow"><span class="ic ${kind} ${act ? "on" : ""}">${icon(ic)}</span><div class="nm"><b>${esc(x.label)}</b><small>${sub}</small></div>
    <div class="w">${out ? outW(w) : W(w)}<small>${num(x.voltage, 1)} V · ${num(x.current, 1)} A</small></div>${ctl ?? ""}</div>`;
}
const NOSW = `<span class="sw-gap"></span>`;   // in place of a switch: keeps the values in line
/** The House bank tile: the same on the Overview and the Control view (that one with its own header, without the title).
 * @param {any} d @param {string} id the meter's id @param {boolean} title */
function bankBody(d, id, title) {
  const h = d.storage.house, s = d.sources, t = d.totals;
  const state = h.current > 0.3 ? "charging" : h.current < -0.3 ? "discharging" : "idle";
  return `<div class="meter-row"><div>${title ? `<div class="u-fs-22 big">House bank</div>` : ""}<div class="big">${flowW(h.power)}</div>
      <div class="line">${num(h.voltage, 2)} V · ${num(h.current, 1)} A${h.temperature != null ? ` · ${num(h.temperature, 1)} °C` : ""}</div>
      <div class="line">${esc(h.battery_type || h.chemistry || "LiFePO4")}${h.capacity ? ` · ${num(h.capacity)} ${esc(h.capacity_unit || "Ah")}` : ""} · ${state}</div></div>${meter(h.soc, id)}</div>
    <div class="minis m4"><div class="mini"><div class="l">Charger</div><div class="n">${W((s.charger_house || {}).power)}</div></div>
      <div class="mini"><div class="l">Alternator</div><div class="n">${W((s.alternator || {}).power)}</div></div>
      <div class="mini"><div class="l">Solar</div><div class="n">${W(s.solar.power)}</div></div>
      <div class="mini"><div class="l">DC load</div><div class="n">${outW(t.consumer_power)}</div></div></div>
    ${h.soc == null ? `<div class="u-mt-8"><span class="badge warn wrap">SOC: ${esc(h.soc_source || "no fresh DALY data")}</span></div>` : ""}`;
}
/** The Float status, short, for a tile header; the full text is its title. @param {any} f */
function floatTag(f) {
  if (!f) return "";
  const [c, full] = floatText(f);
  const short = !f.enabled ? "Float protection off" : f.active ? `Float · Bulk below ${num(f.cell_resume_mv)} mV`
    : f.max_cell_mv != null ? `Bulk · now ${num(f.max_cell_mv)} / ${num(f.cell_trigger_mv)} mV` : `Bulk · Float at ${num(f.cell_trigger_mv)} mV`;
  return `<span class="badge tag ${c}" title="${esc(full)}">${esc(short)}</span>`;
}
function floatText(f) {
  if (!f) return ["", "–"];
  if (!f.enabled) return ["", "Float protection off"];
  if (f.active) return ["warn", `Float active${f.trigger ? ` (${f.trigger})` : ""} · Bulk resumes when the highest cell is below ${num(f.cell_resume_mv)} mV`];
  return ["ok", `Bulk allowed · Float when a cell reaches ${num(f.cell_trigger_mv)} mV${f.max_cell_mv != null ? ` (now ${num(f.max_cell_mv)} mV)` : ""}`];
}
function renderNow() {
  const d = m.state.data, box = $("eNow");
  if (!d) { box.innerHTML = m.state.err ? "" : `<div class="empty">Loading…</div>`; return; }
  const h = d.storage.house, s = d.sources, c = d.consumers, t = d.totals, cm = d.combimaster || {}, ctl = d.controls || {}, f = d.high_soc_float_policy;
  const srcSub = {shore: s.shore.connected ? `${num(s.shore.input_frequency, 1)} Hz` : "Not connected", charger_house: s.charger_house.charge_state || "–",
    alternator: `${s.alternator.state || "–"}${s.alternator.estimated ? " · estimated" : ""}`, solar: `${s.solar.state || "–"} · panel ${num(s.solar.panel_voltage, 1)} V`};
  const sw = (id, val, extra = "") => D.sw(id, val, (busy.has(id) ? "disabled " : "") + extra);
  const dev = (name, label) => { const cfg = ctl[name], ok = cfg && cfg.verified;
    return sw("ec-" + name, cfg && cfg.current, `aria-label="${label}"` + (ok ? "" : ' disabled title="Not mapped/verified yet"')); };
  const srcCtl = {charger_house: sw("ec-charger", on(cm.charger_enabled), 'aria-label="Charger House"'),
    alternator: sw("ec-alternator", !!s.alternator.control_on, 'aria-label="Alternator"'), solar: dev("solar", "Solar")};
  const loadCtl = {inverter: sw("ec-inverter", on(cm.inverter_enabled), 'aria-label="Inverter"'), charger_start: dev("charger_start", "Charger Start"),
    charger_bow: dev("charger_bow", "Charger Bowthruster"), engine_ecu: dev("engine_ecu", "Engine ECU")};
  srcSub.alternator += s.alternator.shaft_running ? " · shaft turning" : "";
  const loadSub = (k, x) => k === "inverter" ? (on(cm.inverting) ? "Inverting" : on(cm.supporting) ? "Supporting" : "Not inverting")
    : x.charge_state || (x.estimated ? "estimated" : x.kind || "");
  const lim = limitDraft ?? (cm.ac_input_limit != null ? Math.round(cm.ac_input_limit) : null);
  box.innerHTML = `
    <div class="u-mb-12 card pad"><div class="btns eq">${Object.keys(MODES).map(k => `<button class="btn sec" type="button" data-mode="${k}" aria-pressed="${d.active_mode === k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div>
      <p class="u-m-8-2-0 hint">${d.active_mode ? `${esc(d.active_mode[0].toUpperCase() + d.active_mode.slice(1))} mode is active (until a single control changes). ` : ""}Modes switch several devices at once. Engine ECU is never switched off by a mode.</p></div>
    <div class="grid g2l">
      <div class="stack">
        <div class="card tile bank"><div class="th"><span class="ic">${icon("batt")}</span><h3>House bank</h3>${floatTag(f)}</div>${bankBody(d, "eP", false)}</div>
        <div class="card"><div class="hd">${icon("sun")}<h3>Energy providers</h3><span class="muted num">Total DC in ${W(t.dc_input_power)}</span></div><div class="rows">
          ${Object.entries(s).map(([k, x]) => flowRow(x, SRC_IC[k][0], SRC_IC[k][1], esc(srcSub[k]), k === "shore" ? x.connected : k === "alternator" ? x.running : undefined, srcCtl[k] ?? NOSW)).join("")}</div></div>
        <div class="card"><div class="hd">${icon("load")}<h3>Energy consumers</h3><span class="muted num">Total DC out ${outW(t.consumer_power)}</span></div><div class="rows">
          ${Object.entries(c).map(([k, x]) => flowRow(x, LOAD_IC[k] || "load", "load", esc(loadSub(k, x)), undefined, loadCtl[k] ?? NOSW, true)).join("")}</div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="hd">${icon("power")}<h3>CombiMaster</h3>${on(cm.alarms) ? '<span class="badge bad">alarm</span>' : ""}</div><div class="rows">
          <div class="row"><div class="k"><b>AC IN support</b><small>Inverter helps when shore power is limited</small></div>${sw("ec-support", on(cm.ac_support_enabled))}</div>
          <div class="row"><div class="k"><b>AC input limit</b><small>Now ${cm.ac_input_limit != null ? num(cm.ac_input_limit) + " A" : "–"} · 3–15 A</small></div>
            <div class="u-d-flex u-gap-6 u-ai-center"><div class="stepper no-swipe"><button type="button" data-limit="-1" aria-label="Lower">−</button><output class="num">${lim ?? "–"} A</output><button type="button" data-limit="1" aria-label="Higher">+</button></div>
            <button class="btn sm" type="button" id="ec-limit" ${limitDraft == null || limitDraft === Math.round(cm.ac_input_limit) || busy.has("ec-limit") ? "disabled" : ""}>Set</button></div></div>
        </div></div>
        <p class="u-m-0-4 hint">History charts and reports are under History; Bluetooth diagnostics and SOC calibration under Batteries.</p>
      </div>
    </div>`;
}

// ------------------------------------------------------------------ Batteries
function renderBatt() {
  const box = $("eBatt");
  if (!bms) { box.innerHTML = `<div class="empty">Loading batteries…</div>`; return; }
  const cs = bms.control_status || {}, names = Object.keys(bms.batteries || {}).sort();
  // Pack details: one table, a column per pack plus the house bank (sums, averages, the extremes over all cells)
  const details = () => {
    const P = names.map(name => bms.batteries[name]), all = P.flatMap(b => b.cells_mv || []), h = m.state.data && m.state.data.storage.house;
    const avg = c => c.length ? (c.reduce((x, y) => x + y, 0) / c.length / 1000).toFixed(3) + " V" : "–";
    const sum = k => P.some(b => b[k] != null) ? P.reduce((x, b) => x + (+b[k] || 0), 0) : null;
    const temps = b => (b.temperatures_c || []).length ? Math.max(...b.temperatures_c) : null, tAll = P.map(temps).filter(t => t != null);
    const row = (label, cells, house = "–", cls = "") => `<tr${cls ? ` class="${cls}"` : ""}><th>${label}</th>${cells.map(c => `<td>${c}</td>`).join("")}<td class="hb">${house}</td></tr>`;
    const nCells = Math.max(0, ...P.map(b => (b.cells_mv || []).length));
    const cellRows = Array.from({length: nCells}, (_, i) => `<tr><th>Cell ${i + 1}</th>${P.map(b => { const c = b.cells_mv || [], v = c[i], hi = Math.max(...c), lo = Math.min(...c), bl = new Set(b.balancing_cells || []);
      return `<td class="${v === hi && hi !== lo ? "hi" : v === lo && hi !== lo ? "lo" : ""}${bl.has(i + 1) ? " bal" : ""}">${v != null ? (v / 1000).toFixed(3) : "–"}</td>`; }).join("")}<td class="hb">–</td></tr>`).join("");
    const read = b => { const age = b.captured_at ? (Date.now() - Date.parse(b.captured_at)) / 1000 : null, live = b.state === "connected" || b.state === "reading";
      return !live ? `<span class="${b.error ? "badc" : "warnc"}">${esc(b.state.replace(/_/g, " "))}</span>` : `<span class="${age != null && age > 120 ? "warnc" : ""}">${age != null ? D.dur(age) + " ago" : "–"}</span>`; };
    const spread = c => c.length ? Math.max(...c) - Math.min(...c) : null, warn = v => v != null && v > 50 ? "warnc" : "";
    const alarms = b => [b.error, ...(b.alarms || [])].filter(Boolean), nAlarm = P.filter(b => alarms(b).length).length;
    const curve = k => P.map(b => b[k] != null ? num(b[k], 1) + " %" : "–");
    // folds to one line (the open state survives the re-render on every poll)
    return `<details class="card fold ptab-card" id="ePackFold" ${($("ePackFold") || {}).open ? "open" : ""}><summary class="hd">${icon("batt")}<h3>Pack details</h3>
      <span class="muted num">Max diff ${num(spread(all))} mV · ${nAlarm ? `<span class="badc">${nAlarm} with alarms</span>` : "no alarms"}</span>${icon("chev", "i chev")}</summary><div class="ptab-wrap"><table class="ptab">
      <thead><tr><th></th>${names.map(name => { const n = name.replace(/\D/g, "");
        return `<th><span class="nm"><span class="wide">Battery </span>${n}</span><button class="iconbtn" type="button" data-bms-refresh="${n}" aria-label="Read ${esc(name)} now">${icon("refresh")}</button></th>`; }).join("")}<th class="hb">House</th></tr></thead>
      <tbody>${row("Read", P.map(read))}
      ${row("SOC", P.map(b => num(b.state_of_charge_percent, 1) + " %"), h && h.soc != null ? num(h.soc, 1) + " %" : "–")}
      ${row("Left", P.map(b => num(b.remaining_capacity_ah, 1) + " Ah"), sum("remaining_capacity_ah") != null ? num(sum("remaining_capacity_ah"), 1) + " Ah" : "–")}
      ${row("Voltage", P.map(b => num(b.pack_voltage_v, 2) + " V"), h && h.voltage != null ? num(h.voltage, 2) + " V" : "–", "strong")}
      ${row("Current", P.map(b => num(b.current_a, 1) + " A"), sum("current_a") != null ? num(sum("current_a"), 1) + " A" : "–")}
      ${row("Temp", P.map(b => temps(b) != null ? num(temps(b), 0) + " °C" : "–"), tAll.length ? num(Math.max(...tAll), 0) + " °C" : "–")}
      ${row("Cycles", P.map(b => b.cycles ?? "–"))}
      ${cellRows}
      ${row("Avg cell", P.map(b => avg(b.cells_mv || [])), avg(all), "strong")}
      ${row("Max diff", P.map(b => `<span class="${warn(b.cell_spread_mv)}">${num(b.cell_spread_mv)} mV</span>`), `<span class="${warn(spread(all))}">${num(spread(all))} mV</span>`, "strong")}
      ${row("Alarms", P.map(b => alarms(b).length ? alarms(b).map(x => `<span class="badc">${esc(x)}</span>`).join("<br>") : `<span class="good">none</span>`), "–", "wrap")}
      ${row("SOC curve<small>charging</small>", curve("soc_charge_curve_percent"), "–", "two")}
      ${row("SOC curve<small>discharging</small>", curve("soc_discharge_curve_percent"), "–", "two")}
      </tbody></table></div><p class="hint ptab-note">Cells: highest orange, lowest blue, a dot when it balances. House: the house SOC and voltage, the sum of Ah left and current, the hottest pack, average and difference over all cells.
        SOC curve: what the average cell voltage means on the LiFePO4 charging and discharging curve (the values <i>Set SOC</i> offers).</p></details>`;
  };
  const devs = (bal && bal.devices) || {};
  const balOf = n => Object.entries(devs).find(([k]) => k.replace(/\D/g, "") === n)?.[1];
  // the overview (one iPhone screen): the start and bow batteries, then the house bank with a tile per pack (its balancer,
  // MOSFET switches and Set SOC). Every line is always there, so a read in progress never changes a tile's height.
  const pack = name => {
    const b = bms.batteries[name], n = name.replace(/\D/g, ""), cells = b.cells_mv || [], dv = balOf(n), v = (dv && dv.status) || {};
    const age = b.captured_at ? (Date.now() - Date.parse(b.captured_at)) / 1000 : null;
    const live = b.state === "connected" || b.state === "reading";
    const st = !live ? [b.error ? "badc" : "warnc", b.state.replace(/_/g, " ")] : [age != null && age > 120 ? "warnc" : "", age != null ? `Read ${D.dur(age)} ago` : "Read –"];
    const bl = !dv ? ["", "no balancer"] : dv.stale ? ["warn", "bal stale"] : dv.error ? ["bad", "bal error"] : v.balance_active ? ["warn", `balancing${v.balance_position != null ? " " + v.balance_position : ""}`] : ["", "bal idle"];
    const fet = (k, on, l, what) => `<div class="fet"><span>${l}</span>${D.sw(`bms-${k}-${n}`, on, `aria-label="${esc(name)} ${what} MOSFET"` + (busy.has(`bms-${k}-${n}`) || cs.busy || on == null ? " disabled" : ""), "onoff sm")}</div>`;
    const avg = cells.length ? cells.reduce((x, y) => x + y, 0) / cells.length / 1000 : null;
    const t = (b.temperatures_c || []).length ? Math.max(...b.temperatures_c) : null;
    return `<div class="card pack"><b>${esc(name[0] + name.slice(1).toLowerCase())}</b>${meter(b.state_of_charge_percent, "eK" + n, name, "sm")}
      <b class="num">${num(b.pack_voltage_v, 2)} V</b><small>${num(b.current_a, 1)} A${t != null ? ` · ${num(t, 0)} °C` : ""}</small>
      ${cellBars(cells)}<small>Avg ${avg != null ? avg.toFixed(3) : "–"} V</small><small class="${b.cell_spread_mv > 50 ? "warnc" : ""}">Δ ${num(b.cell_spread_mv)} mV</small>
      <small class="${st[0]}">${esc(st[1])}</small><span class="badge ${bl[0]}">${esc(bl[1])}</span>
      ${fet("c", b.charge_mosfet_on, "C", "charge")}${fet("d", b.discharge_mosfet_on, "D", "discharge")}
      <button class="btn sec sm" type="button" data-soc="${n}" ${cs.busy || !live ? "disabled" : ""}>Set SOC</button></div>`;
  };
  const d = m.state.data, other = d ? ["start", "bow"].map(k => { const b = d.storage[k];
    return `<div class="card other">${meter(b.soc, "eB" + k, b.label, "sm")}<div class="k"><b>${esc(b.label)}</b><small>${esc(b.battery_type || b.chemistry || "")}${b.capacity ? ` · ${num(b.capacity)} ${esc(b.capacity_unit || "Ah")}` : ""}</small></div>
      <div class="v"><b>${flowW(b.power)}</b><small>${num(b.voltage, 2)} V · ${num(b.current, 1)} A</small></div></div>`; }).join("") : "";
  const hb = d && d.storage.house;
  box.innerHTML = `
    <div class="others">${other}</div>
    <div class="card bankbox"><div class="hd">${icon("batt")}<h3>House bank</h3>${hb ? `<span class="muted num">${esc(hb.battery_type || hb.chemistry || "LiFePO4")}${hb.capacity ? ` · ${num(hb.capacity)} ${esc(hb.capacity_unit || "Ah")}` : ""}</span><b class="num">${flowW(hb.power)}</b>` : ""}</div>
      <div class="packs">${names.map(pack).join("")}</div></div>
    <div class="u-mb-12 card pad"><div class="allbtns">
      <button class="btn sec sm" type="button" id="bms-all-refresh">${icon("refresh")} Read all</button>
      <button class="btn sec sm" type="button" data-all="charge-on">All charge ON</button><button class="btn sec sm" type="button" data-all="charge-off">All charge OFF</button>
      <button class="btn sec sm" type="button" data-all="discharge-on">All discharge ON</button><button class="btn sec sm" type="button" data-all="discharge-off">All discharge OFF</button>
      <button class="btn sec sm" type="button" data-soc="all" ${cs.busy ? "disabled" : ""}>Set all SOC</button></div>
      <span class="u-mt-8 hint">${cs.busy ? `<span class="warnc">${esc(cs.message || cs.phase || "Bluetooth busy…")}</span>` : `${bms.connected_count ?? "–"} connected · read every ${bms.refresh_interval_seconds ?? "–"} s`}</span></div>
    ${details()}
    ${bleCard()}`;
}

/** A pack's cells as small bars: the highest one warn, the lowest one accent; a 40 mV window above the lowest cell. */
function cellBars(cells) {
  if (!cells.length) return "";
  const hi = Math.max(...cells), lo = Math.min(...cells);
  return `<div class="cellbars" aria-hidden="true">${cells.map(c => `<i class="${c === hi && hi !== lo ? "hi" : c === lo && hi !== lo ? "lo" : ""}" style="height:${Math.round(6 + Math.min(1, (c - lo) / 40) * 16)}px"></i>`).join("")}</div>`;
}

// Bluetooth diagnostics: the coordinator (who has the radio, who waits) and per device the counters and timings.
function bleCard() {
  if (!coord && !bleEv) return "";
  const c = coord || {}, counters = (bleEv && bleEv.counters) || {}, wait = c.waiting || {};
  const waiting = Object.entries(wait).filter(([, v]) => v).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "nothing waiting";
  const dev = ([n, x]) => {
    if (!x || !x.timings) return "";
    const t = x.timings.connect || {}, rw = x.timings.radio_wait || {}, ev = x.events || {};
    return `<div class="row"><div class="k"><b>${esc(n)}</b><small>${x.last_success_epoch ? "last OK " + D.dayTime(x.last_success_epoch) : "never OK"}${x.consecutive_failures ? ` · <span class="warnc">${x.consecutive_failures} failures in a row</span>` : ""}
      · reads ${ev.read_ok || 0}${x.signal && x.signal.rssi != null ? ` · ${x.signal.rssi} dBm` : ""}${x.last_error ? `<br><span class="badc">${esc(x.last_error)}</span>` : ""}</small></div>
      <span class="v">${t.count ? `${num(t.avg_ok_seconds, 1)} s` : "–"}<small>connect avg · radio wait p95 ${rw.count ? num(rw.p95_ok_seconds, 1) + " s" : "–"}</small></span></div>`;
  };
  // both fold to one line (open state survives the re-render on every poll)
  const open = id => ($(id) || {}).open ? "open" : "", chev = icon("chev", "i chev");
  const failing = Object.entries(counters).filter(([n, x]) => n !== "balancers" && x && x.consecutive_failures).length;
  const evs = ((bleEv && bleEv.events) || []).slice().reverse().slice(0, 40), evFail = evs.filter(e => /fail|error|timeout/i.test(e.kind)).length;
  return `<details class="secfold" id="eBleFold" ${open("eBleFold")}><summary><h2 class="sec">Bluetooth status<span class="r">${c.degraded ? '<span class="warnc">degraded</span>' : c.active ? "busy" : "idle"} · ${c.connected_bms ?? "–"} BMS${failing ? ` · <span class="warnc">${failing} failing</span>` : ""} ${chev}</span></h2></summary>
    <div class="card"><div class="rows">
      <div class="row"><span class="k">Radio</span><span class="v">${c.degraded ? '<span class="warnc">degraded</span>' : c.active ? esc(String(c.active)) : "idle"}<small>${c.active_for_seconds != null ? `for ${num(c.active_for_seconds, 1)} s · ` : ""}${esc(waiting)}</small></span></div>
      <div class="row"><span class="k">BMS</span><span class="v">${c.connected_bms ?? "–"} connected · ${c.refreshed_bms ?? "–"} read<small>${c.bms_stable_seconds != null ? "stable for " + D.dur(c.bms_stable_seconds) : ""}${c.forced_releases ? ` · ${c.forced_releases} forced releases` : ""}</small></span></div>
      <div class="row"><span class="k">Balancers</span><span class="v">${c.balancers_allowed ? "allowed" : '<span class="warnc">paused for the BMS</span>'}</span></div>
      ${Object.entries(counters).filter(([n]) => n !== "balancers").map(dev).join("")}</div></div></details>
    <details class="secfold" id="eBleEvFold" ${open("eBleEvFold")}><summary><h2 class="sec">Bluetooth events<span class="r">${evs.length ? `last ${esc(D.hm(Date.parse(evs[0].time)))}` : "none"}${evFail ? ` · <span class="warnc">${evFail} failed</span>` : ""} ${chev}</span></h2></summary>
    <div class="card"><div class="log">${evs.map(e => `<div class="${/fail|error|timeout/i.test(e.kind) ? "warn" : ""}"><time>${esc(D.dayTime(Date.parse(e.time)))}</time><span class="msg"><b>${esc(e.device)}</b> ${esc(e.kind.replace(/_/g, " "))}${e.detail ? " · " + esc(e.detail) : ""}</span></div>`).join("") || `<div class="empty">No events</div>`}</div></div></details>`;
}

// ------------------------------------------------------------------ History (reports, database; charts follow)
function md(text) {     // the battery report is Markdown: headings, lists, tables, bold, code
  const inline = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = []; let list = false, table = [];
  const flush = () => { if (list) { out.push("</ul>"); list = false; }
    if (table.length) { const rows = table.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r)).map(r => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|"));
      out.push(`<div class="mdtable"><table>${rows.map((c, i) => `<tr>${c.map(x => i ? `<td>${inline(x.trim())}</td>` : `<th>${inline(x.trim())}</th>`).join("")}</tr>`).join("")}</table></div>`); table = []; } };
  for (const line of String(text || "").split(/\r?\n/)) {
    if (/^\s*\|/.test(line)) { if (list) { out.push("</ul>"); list = false; } table.push(line); continue; }
    if (table.length) flush();
    const h = line.match(/^(#{1,4})\s+(.*)/), li = line.match(/^\s*[-*]\s+(.*)/);
    if (h) { flush(); out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`); }
    else if (li) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(li[1])}</li>`); }
    else if (!line.trim()) flush();
    else { flush(); out.push(`<p>${inline(line)}</p>`); }
  }
  flush(); return out.join("");
}
// ---- history charts. The server sends a sample of the history for drawing only (about 2,500 points); totals always
// come from /api/history/contributions, which integrates the full-resolution data. Stacked bands are opaque areas; the
// state of charge is smooth stacked areas (time bins, each battery its share of the bank) under a smooth total line.
const SRC_META = [["charger_house", "Charger House", "#a78bfa"], ["alternator", "Alternator", "#f4a631"], ["solar", "Solar", "#65d92f"]];
const LOAD_META = [["inverter", "Inverter", "#a78bfa"], ["charger_start", "Charger Start", "#65d92f"], ["charger_bow", "Charger Bow", "#34d399"],
  ["engine_ecu", "Engine ECU", "#f4a631"], ["alternator_field", "Alt. field", "#fb7185"], ["other_dc", "Other DC", "#60a5fa"]];
const BAT_META = [["total", "Total", "#11c5c8"], ["BATTERY 1", "Battery 1", "#f4a631"], ["BATTERY 2", "Battery 2", "#65d92f"], ["BATTERY 3", "Battery 3", "#ff6262"]];
const RANGES = [[6, "6 h"], [24, "24 h"], [72, "3 d"], [168, "7 d"], [744, "31 d"]];
const night = () => document.documentElement.dataset.theme === "night";
const colorOf = (c, i) => night() ? `rgba(210,50,35,${[1, .75, .5, .35, .22, .14][i % 6]})` : c;   // night: shades of red only
function seriesFrom(c) {
  const dash = (c.dashboard || []).map(r => ({t: Date.parse(r.captured_at), sp: r.source_power || [], lp: r.load_power || [], shore: r.shore_power})).sort((a, b) => a.t - b.t);
  const cap = ((m.state.data || {}).storage || {}).house || {}, bankAh = cap.capacity || 960, perAh = bankAh / 3;
  const byBat = {}; for (const r of c.bms || []) (byBat[r.battery] = byBat[r.battery] || []).push({t: Date.parse(r.captured_at), cur: r.current, rem: r.remaining, spread: r.cell_spread});
  for (const k in byBat) byBat[k].sort((a, b) => a.t - b.t);
  // total SOC: the three batteries' remaining Ah at each battery-1 sample time (nearest earlier reading of the others)
  const tot = (byBat["BATTERY 1"] || []).map(p => { let sum = 0, n = 0;
    for (const k of ["BATTERY 1", "BATTERY 2", "BATTERY 3"]) { const arr = byBat[k] || []; let j = arr.length - 1; while (j > 0 && arr[j].t > p.t) j--; if (arr[j] && arr[j].rem != null) { sum += arr[j].rem; n++; } }
    return {t: p.t, v: n === 3 ? sum / bankAh * 100 : null}; });
  return {dash, byBat, tot, perAh};
}
/** A smooth line through the points without overshoot (monotone cubic, Fritsch-Carlson); join: continue the current path.
 * @param {any} g @param {number[][]} P @param {boolean} [join] */
function smoothPath(g, P, join) {
  const n = P.length, d = [], m = [];
  for (let i = 0; i < n - 1; i++) d[i] = (P[i + 1][1] - P[i][1]) / (P[i + 1][0] - P[i][0]);
  for (let i = 0; i < n; i++) m[i] = i === 0 ? d[0] : i === n - 1 ? d[n - 2] : d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) { if (d[i] === 0) { m[i] = m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], q = a * a + b * b; if (q > 9) { const k = 3 / Math.sqrt(q); m[i] = k * a * d[i]; m[i + 1] = k * b * d[i]; } }
  g[join ? "lineTo" : "moveTo"](P[0][0], P[0][1]);
  for (let i = 0; i < n - 1; i++) { const h = (P[i + 1][0] - P[i][0]) / 3;
    g.bezierCurveTo(P[i][0] + h, P[i][1] + m[i] * h, P[i + 1][0] - h, P[i + 1][1] - m[i + 1] * h, P[i + 1][0], P[i + 1][1]); }
}
// left: {mul}: the left labels are the value times `mul` (amps → watts); tip: the unit of the touched values when it differs
// step: a scale for the data in whole steps (W); right.step: the right scale in its own steps (A)
// right: {unit, per}: a second scale on the right, the left value divided by `per` (watts → amps at the bank voltage)
// opt: {t0, t1, unit, stacked (areas) | columns (binned smooth stacked areas, part = a series' share; line = a smooth line over them),
//   fixed: [lo, hi], zero, series:[{label, color, pts:[{t, v}], part, line, width}]}
function drawChart(canvas, opt) {
  const dpr = window.devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
  if (!W) return;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const g = canvas.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const css = n => getComputedStyle(document.body).getPropertyValue(n).trim(), muted = css("--muted"), line = css("--line");
  const L = 44, R = W - (opt.right ? 36 : 8), T = 8, B = H - 22;
  let lo = Infinity, hi = -Infinity;
  if (opt.columns) {     // average every series per time bin (about every 7 px); the line is the bands' total
    const n = Math.max(24, Math.min(120, Math.floor((R - L) / 7))), dt = (opt.t1 - opt.t0) / n;
    const bin = pts => { const sum = new Array(n).fill(0), cnt = new Array(n).fill(0);
      for (const p of pts) { if (p.v == null) continue; const i = Math.floor((p.t - opt.t0) / dt); if (i >= 0 && i < n) { sum[i] += p.v; cnt[i]++; } }
      const out = sum.map((v, i) => ({t: opt.t0 + (i + .5) * dt, v: cnt[i] ? v / cnt[i] : null}));
      // zoomed in, a bin can be shorter than the spacing of the samples: fill it between its neighbours, but keep real gaps
      const ts = pts.filter(p => p.v != null).map(p => p.t), d = []; for (let i = 1; i < ts.length; i += Math.max(1, ts.length >> 8)) d.push(ts[i] - ts[i - 1]);
      d.sort((a, b) => a - b); const maxGap = Math.max(600e3, 3 * (d[d.length >> 1] || 0));
      for (let i = 0, prev = -1; i < n; i++) if (out[i].v != null) {
        if (prev >= 0 && i - prev > 1 && (i - prev) * dt <= maxGap) for (let j = prev + 1; j < i; j++) out[j].v = out[prev].v + (out[i].v - out[prev].v) * (j - prev) / (i - prev);
        prev = i; }
      return out; };
    const cols = opt.series.filter(s => !s.line).map(s => ({...s, pts: bin(s.pts)}));
    const lines = opt.series.filter(s => s.line).map(s => { const own = bin(s.pts);
      return {...s, pts: own.map((p, i) => cols.length && cols.every(c => c.pts[i].v != null) ? {t: p.t, v: cols.reduce((a, c) => a + c.pts[i].v * (c.part ?? 1), 0)} : p)}; });
    opt = {...opt, series: opt.series.map(s => (s.line ? lines : cols).find(x => x.label === s.label)), bins: {n, dt}};
  }
  if (opt.fixed) [lo, hi] = opt.fixed;
  else if (opt.columns) { lo = 0; hi = 1;     // the highest stack (or line) in any bin
    for (let i = 0; i < opt.bins.n; i++) { let sum = 0; for (const s of opt.series) { const v = s.pts[i].v; if (v == null) continue;
      if (s.line) hi = Math.max(hi, v); else sum += Math.max(0, v) * (s.part ?? 1); } hi = Math.max(hi, sum); }
    if (opt.right && opt.right.step) hi = Math.max(hi, opt.right.step * opt.right.per);     // at least one step on the right scale
  }
  else if (opt.stacked) {     // stack on a shared time axis: the first series' timestamps
    const base = opt.series[0] ? opt.series[0].pts.map(p => p.t) : [];
    opt.stackTops = base.map((t, i) => opt.series.reduce((acc, s) => acc + Math.max(0, (s.pts[i] || {}).v || 0), 0));
    lo = 0; hi = Math.max(1, ...opt.stackTops);
  } else for (const s of opt.series) for (const p of s.pts) if (p.v != null) { lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); }
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  if (opt.zero) lo = Math.min(lo, 0);
  if (hi - lo < 1e-6) { hi += 1; lo -= opt.zero ? 0 : 1; }
  let ticks = null;
  if (opt.step && !opt.fixed) {     // a scale for the data shown, in whole steps (at most about six lines)
    const st = opt.step * Math.ceil(Math.max(hi, opt.step) / opt.step / 6); lo = 0; hi = Math.max(st, Math.ceil(hi / st) * st);
    ticks = []; for (let v = 0; v <= hi + 1e-9; v += st) ticks.push(v);
  } else if (!opt.fixed) { const pad = (hi - lo) * .06; hi += pad; if (!opt.stacked && !opt.columns && lo !== 0) lo -= pad; }
  if (!ticks) ticks = [0, 1, 2, 3, 4].map(i => lo + (hi - lo) * i / 4);
  const X = t => L + (t - opt.t0) / (opt.t1 - opt.t0) * (R - L), Y = v => B - (v - lo) / (hi - lo) * (B - T);
  g.font = "11px -apple-system, Segoe UI, sans-serif"; g.fillStyle = muted; g.strokeStyle = line; g.lineWidth = 1;
  ticks.forEach((v, i) => { const y = Y(v); g.beginPath(); g.moveTo(L, y); g.lineTo(R, y); g.stroke();
    g.textAlign = "right"; g.fillText(opt.left ? Math.round(v * opt.left.mul) : Math.abs(hi - lo) >= 20 ? Math.round(v) : v.toFixed(1), L - 6, y + 4);
    if (opt.right && !opt.right.step) { g.textAlign = "left"; g.fillText(Math.round(v / opt.right.per) + (i === ticks.length - 1 ? " " + opt.right.unit : ""), R + 6, y + 4); } });
  if (opt.right && opt.right.step) {     // its own steps (amps): a short tick and the value at each
    const top = hi / opt.right.per, st = opt.right.step * Math.max(1, Math.ceil(top / opt.right.step / 6)); g.textAlign = "left";
    for (let a = 0; a <= top + 1e-9; a += st) { const y = Y(a * opt.right.per); g.beginPath(); g.moveTo(R, y); g.lineTo(R + 4, y); g.stroke();
      g.fillText(Math.round(a) + (a + st > top + 1e-9 ? " " + opt.right.unit : ""), R + 6, y + 4); } }
  const span = opt.t1 - opt.t0, step = [3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3, 48 * 3600e3, 7 * 864e5].find(s => span / s <= 6) || 7 * 864e5;
  g.textAlign = "center";
  for (let t = Math.ceil(opt.t0 / step) * step; t <= opt.t1; t += step) { const d = new Date(t), x = X(t);
    const lab = step >= 864e5 ? D.dm(d) : `${D.pad(d.getHours())}:00`;
    g.beginPath(); g.moveTo(x, B); g.lineTo(x, B + 4); g.stroke(); g.fillText(lab, x, H - 6); }
  if (opt.zero && lo < 0) { g.strokeStyle = muted; g.beginPath(); g.moveTo(L, Y(0)); g.lineTo(R, Y(0)); g.stroke(); }
  g.save(); g.beginPath(); g.rect(L, T, R - L, B - T); g.clip();
  if (opt.columns) {
    // one continuous band per series, its edges smooth curves through the bin averages; a bin without every value is a gap
    const {n, dt} = opt.bins, bands = opt.series.map((s, k) => [s, k]).filter(([s]) => !s.line);
    const ok = i => bands.every(([s]) => s.pts[i].v != null), runs = [];
    for (let i = 0, a = -1; i <= n; i++) { if (i < n && ok(i)) { if (a < 0) a = i; } else if (a >= 0) { runs.push([a, i - 1]); a = -1; } }
    for (const [a, z] of runs) {
      const xs = [X(opt.t0 + a * dt)]; for (let i = a; i <= z; i++) xs.push(X(opt.t0 + (i + .5) * dt)); xs.push(X(opt.t0 + (z + 1) * dt));
      const idx = [a, ...Array.from({length: z - a + 1}, (_, j) => a + j), z];     // the run's ends reach the bin edges
      let below = idx.map(() => 0);
      for (const [s, k] of bands) {
        const top = idx.map((i, j) => below[j] + Math.max(0, s.pts[i].v) * (s.part ?? 1));     // a band never goes below the one under it
        g.fillStyle = colorOf(s.color, k); g.beginPath();
        smoothPath(g, xs.map((x, j) => [x, Y(top[j])]));
        smoothPath(g, xs.map((x, j) => [x, Y(below[j])]).reverse(), true);
        g.closePath(); g.fill(); below = top;
      }
    }
    opt.series.forEach((s, k) => { if (!s.line) return;
      g.strokeStyle = colorOf(s.color, k); g.lineWidth = s.width || 2.4; g.lineJoin = "round"; g.beginPath();
      let run = []; const flush = () => { if (run.length > 1) smoothPath(g, run); run = []; };
      for (const p of s.pts) { if (p.v == null) flush(); else run.push([X(p.t), Y(p.v)]); }
      flush(); g.stroke(); });
  } else if (opt.stacked) {
    const base = opt.series[0] ? opt.series[0].pts : [], acc = base.map(() => 0);
    opt.series.forEach((s, k) => {     // opaque bands, drawn once each: no stripes
      g.fillStyle = colorOf(s.color, k); g.beginPath();
      base.forEach((p, i) => { const top = acc[i] + Math.max(0, (s.pts[i] || {}).v || 0); g[i ? "lineTo" : "moveTo"](X(p.t), Y(top)); });
      for (let i = base.length - 1; i >= 0; i--) g.lineTo(X(base[i].t), Y(acc[i]));
      g.closePath(); g.fill();
      base.forEach((p, i) => acc[i] += Math.max(0, (s.pts[i] || {}).v || 0));
    });
  } else opt.series.forEach((s, k) => {     // smooth lines, broken where data is missing
    g.strokeStyle = colorOf(s.color, k); g.lineWidth = s.width || 1.6; g.lineJoin = "round"; g.beginPath(); let run = [], last = null;
    const flush = () => { if (run.length > 1) smoothPath(g, run); run = []; };
    for (const p of s.pts) { if (p.v == null || (last && p.t - last > Math.max(600e3, span / 150))) flush(); if (p.v == null) { last = null; continue; }
      run.push([X(p.t), Y(p.v)]); last = p.t; }
    flush(); g.stroke();
  });
  g.restore();
  canvas._map = {X, Y, L, R, T, B, opt};
}
function crosshair(canvas, tip, ev) {      // the values at the touched time
  const mp = canvas._map; if (!mp) return;
  const r = canvas.getBoundingClientRect(), x = Math.max(mp.L, Math.min(mp.R, ev.clientX - r.left));
  const t = mp.opt.t0 + (x - mp.L) / (mp.R - mp.L) * (mp.opt.t1 - mp.opt.t0);
  const near = pts => { let lo = 0, hi = pts.length - 1; while (lo < hi) { const mid = (lo + hi) >> 1; if (pts[mid].t < t) lo = mid + 1; else hi = mid; } return pts[lo]; };
  const rows = mp.opt.series.map((s, k) => { const p = s.pts.length ? near(s.pts) : null;
    return `<span><i style="background:${colorOf(s.color, k)}"></i>${esc(s.label)} <b>${p && p.v != null ? num(p.v, Math.abs(p.v) < 20 ? 1 : 0) : "–"}</b></span>`; }).join("");
  tip.innerHTML = `<b>${D.dayTime(t)}</b> ${mp.opt.tip || mp.opt.unit ? `<small>${esc(mp.opt.tip || mp.opt.unit)}</small>` : ""}<div class="tiprows">${rows}</div>`;
  tip.hidden = false; tip.style.left = Math.min(r.width - tip.offsetWidth - 4, Math.max(4, x - tip.offsetWidth / 2)) + "px";
  const cur = canvas.parentElement.querySelector(".cross"); cur.style.left = x + "px"; cur.hidden = false;
}
// ---- Alarms: per battery its episodes, time in alarm and the share of each alarm type; a lane per battery, coloured by type.
// The episodes come from the server's full-resolution history (/api/history/alarms), for the period; the zoom shows a part.
/** @type {[RegExp, string][]} */
const ALARM_COL = [[/^cell voltage high/i, "#ef5b5b"], [/^cell voltage low/i, "#60a5fa"], [/^pack voltage/i, "#f472b6"], [/temperature/i, "#a78bfa"],
  [/overcurrent/i, "#f4a631"], [/^soc/i, "#fbbf24"]];
const alarmColor = (/** @type {string} */ t, /** @type {number} */ i) => colorOf((ALARM_COL.find(([r]) => r.test(t)) || [, "#94a3b8"])[1], i);
const dur = (/** @type {number} */ s) => s >= 3600 ? `${(s / 3600).toFixed(1)} h` : s > 0 && s < 60 ? "<1 min" : `${Math.round(s / 60)} min`;
/** @param {number} t0 @param {number} t1 the part of the period shown */
function renderAlarms(t0, t1) {
  const box = $("eAlarmBody"); if (!box) return;
  if (!alarmData) { box.innerHTML = `<div class="empty">Loading…</div>`; return; }
  const span = t1 - t0, at = (/** @type {number} */ t) => (t - t0) / span * 100;
  const eps = alarmData.episodes.map(e => ({...e, a: Math.max(t0, Date.parse(e.start)), b: Math.min(t1, Date.parse(e.end))})).filter(e => e.b >= e.a);
  const types = [...new Set(eps.map(e => e.type))].sort();
  const per = BAT_META.slice(1).map(([k, l]) => { const mine = eps.filter(e => e.battery === k);
    return {k, l, mine, sec: mine.reduce((s, e) => s + (e.b - e.a) / 1000, 0), byType: types.map(t => mine.filter(e => e.type === t).reduce((s, e) => s + Math.max(1, (e.b - e.a) / 1000), 0))}; });
  const step = [3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3, 48 * 3600e3, 7 * 864e5].find(s => span / s <= 6) || 7 * 864e5, ticks = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) { const d = new Date(t); ticks.push([at(t), step >= 864e5 ? D.dm(d) : `${D.pad(d.getHours())}:00`]); }
  box.innerHTML = `<div class="minis">${per.map(p => { const tot = p.byType.reduce((s, v) => s + v, 0);
      return `<div class="mini"><div class="l">${esc(p.l)}</div><div class="n">${p.mine.length}<small> episode${p.mine.length === 1 ? "" : "s"}</small></div><div class="l">${dur(p.sec)}</div>
        <div class="tbar">${tot ? types.map((t, i) => `<i style="width:${(p.byType[i] / tot * 100).toFixed(1)}%;background:${alarmColor(t, i)}"></i>`).join("") : ""}</div></div>`; }).join("")}</div>
    <div class="alanes">${per.map(p => `<div class="alane"><span class="an">${esc(p.l.replace("Battery ", "B"))}</span><div class="at">${p.mine.map(e =>
      `<i style="left:${at(e.a).toFixed(2)}%;width:${Math.max(0, at(e.b) - at(e.a)).toFixed(2)}%;background:${alarmColor(e.type, types.indexOf(e.type))}" title="${esc(`${e.type} (level ${e.level}) · ${p.l} · ${D.dayTime(Date.parse(e.start))} – ${D.hm(Date.parse(e.end))}`)}"></i>`).join("")}</div></div>`).join("")}
      <div class="aaxis">${ticks.map(([x, l]) => `<span style="left:${x.toFixed(2)}%">${l}</span>`).join("")}</div></div>
    <div class="alegend">${types.length ? types.map((t, i) => `<span><i style="background:${alarmColor(t, i)}"></i>${esc(t)}</span>`).join("") : "<span>No alarms in this period</span>"}</div>`;
}
/** The zoom slider: its handles, the band between them and the times at both ends. @param {number} t0 @param {number} t1 */
function zoomShow(t0, t1) {
  const a = $("eZA"), b = $("eZB"); if (!a) return;
  a.value = String(zoom[0]); b.value = String(zoom[1]);
  $("eZFill").style.left = zoom[0] / 10 + "%"; $("eZFill").style.width = (zoom[1] - zoom[0]) / 10 + "%";
  $("eZFrom").textContent = D.dayTime(t0); $("eZTo").textContent = D.dayTime(t1);
  $("eZReset").disabled = zoom[0] === 0 && zoom[1] === 1000;
}
/** A handle moved: keep the handles apart (at least 2 % of the period) and redraw once per frame. @param {any} el */
function zoomInput(el) {
  let a = +$("eZA").value, b = +$("eZB").value;
  if (b - a < 20) { if (el.id === "eZA") a = b - 20; else b = a + 20; }
  zoom[0] = Math.max(0, Math.min(980, a)); zoom[1] = Math.min(1000, Math.max(20, b));
  cancelAnimationFrame(zoomRaf); zoomRaf = requestAnimationFrame(renderCharts);
}
/** The house bank voltage now, for the amps scale (12 V system: 13.2 V when unknown). */
function houseV() { const v = ((((m.state.data || {}).storage || {}).house) || {}).voltage; return v > 9 && v < 16 ? v : 13.2; }
function renderCharts() {
  const box = $("eCharts"); if (!box) return;
  document.querySelectorAll("#eRange button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.hours === hours));
  if (!chart) { if ($("eZA")) { $("eZA").value = String(zoom[0]); $("eZB").value = String(zoom[1]); }
    box.innerHTML = `<div class="empty">Loading history…</div>`; delete box.dataset.built; if ($("eContrib")) $("eContrib").innerHTML = `<div class="empty">Loading…</div>`; return; }
  const S = seriesFrom(chart), p1 = Date.parse(chart.latest), p0 = Date.parse(chart.cutoff);
  const t0 = p0 + (p1 - p0) * zoom[0] / 1000, t1 = p0 + (p1 - p0) * zoom[1] / 1000;     // the zoomed part of the period
  zoomShow(t0, t1);
  /** @type {[string, string, string, any][]} */
  const defs = [
    ["eChSoc", "State of charge", "%", {columns: true, fixed: [0, 100], series: [{label: "Total", color: BAT_META[0][2], width: 2.6, line: true, pts: S.tot},
      ...BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, part: 1 / 3, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.rem != null ? p.rem / S.perAh * 100 : null}))}))]}],
    ["eChSrc", "Sources", "W · A", {columns: true, step: 250, right: {unit: "A", per: houseV(), step: 25}, series: SRC_META.map(([k, l, c], i) => ({label: l, color: c, pts: S.dash.map(r => ({t: r.t, v: r.sp[i]}))}))}],
    ["eChLoad", "DC consumers", "W · A", {columns: true, step: 100, right: {unit: "A", per: houseV(), step: 5}, series: LOAD_META.map(([k, l, c], i) => ({label: l, color: c, pts: S.dash.map(r => ({t: r.t, v: r.lp[i]}))}))}],
    ["eChCur", "Battery current", "W · A", {columns: true, fixed: [0, 100], tip: "A", left: {mul: houseV()}, right: {unit: "A", per: 1}, series: BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.cur}))}))}],
    ["eChSpread", "Cell spread", "mV", {series: BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.spread}))}))}],
  ];
  if (!box.dataset.built) {
    box.dataset.built = "1";
    box.innerHTML = defs.map(([id, title, unit]) => `<div class="card chartcard"><div class="hd"><h3>${title}</h3><span class="muted">${unit}</span></div>
      <div class="legend" id="${id}Leg"></div><div class="chartwrap no-swipe"><canvas id="${id}"></canvas><div class="cross" hidden></div><div class="charttip" hidden></div></div></div>`).join("")
      + `<div class="card chartcard"><div class="hd"><h3>Alarms</h3><span class="muted">per battery</span></div><div class="alarmbody" id="eAlarmBody"></div></div>`;
    for (const [id] of defs) { const cv = $(id), tip = cv.parentElement.querySelector(".charttip");
      const move = e => crosshair(cv, tip, e), leave = () => { tip.hidden = true; cv.parentElement.querySelector(".cross").hidden = true; };
      cv.addEventListener("pointermove", move); cv.addEventListener("pointerdown", move); cv.addEventListener("pointerleave", leave); }
  }
  for (const [id, , unit, o] of defs) {
    const one = solo[id] && o.series.some(s => s.label === solo[id]) ? solo[id] : null;
    $(id + "Leg").innerHTML = o.series.map((s, k) => `<button type="button" data-solo="${id}" data-label="${esc(s.label)}" aria-pressed="${s.label === one}" class="${one && s.label !== one ? "off" : ""}"
      title="${s.label === one ? "Show all" : `Show only ${esc(s.label)}`}"><i style="background:${colorOf(s.color, k)}"></i>${esc(s.label)}</button>`).join("");
    // one series on its own: a battery's band is then its whole state of charge, not its share of the bank
    drawChart($(id), {...o, unit, t0, t1, series: one ? o.series.filter(s => s.label === one).map(s => ({...s, part: 1})) : o.series});
  }
  renderAlarms(t0, t1);
  const c = contrib;
  // shore power is not in the DC balance: it reaches the bank through the Charger House, so it is shown on its own
  const src = c ? c.sources.map(x => { const i = SRC_META.findIndex(m => m[0] === x.key); return {label: (SRC_META[i] || [, x.key])[1], color: (SRC_META[i] || [, , "#888"])[2], i, wh: x.wh}; }) : [];
  const load = c ? c.consumers.map(x => { const i = LOAD_META.findIndex(m => m[0] === x.key); return {label: (LOAD_META[i] || [, x.key])[1], color: (LOAD_META[i] || [, , "#888"])[2], i, wh: x.wh}; }) : [];
  $("eContrib").innerHTML = !c ? `<div class="empty">Loading…</div>` : `
    <div class="ebars"><h4>Energy flow</h4>${sankey(src, load)}${flowFoot(src, load, c.shore)}</div>
    <div class="ebars"><h4>Batteries</h4>${battFlow(c.batteries || [])}</div>
    <p class="u-m-6-0-0 hint">${D.dayTime(Date.parse(c.start))} – ${D.dayTime(Date.parse(c.end))} · from the full-resolution history on the server${c.sources_covered_seconds != null && c.span_seconds ? ` · data for ${Math.round(c.sources_covered_seconds / c.span_seconds * 100)} % of the time` : ""}</p>`;
}
window.addEventListener("resize", () => { if (view === "history" && D.visibleIs("power")) renderCharts(); });
window.addEventListener("drifter-theme", () => { if (view === "history") renderCharts(); });

// ---- Energy in this period: sources → house bank → DC consumers. Band widths are each side's share; the values are that
// share of the total in (or out) with the energy in brackets.
const kwh = wh => (wh / 1000).toFixed(2);
const pct = (wh, tot) => { const p = tot > 0 ? wh / tot * 100 : 0; return p > 0 && p < 1 ? "<1 %" : Math.round(p) + " %"; };
/** @param {{label: string, color: string, i: number, wh: number}[]} src @param {{label: string, color: string, i: number, wh: number}[]} load */
function sankey(src, load) {
  const W = 360, bankH = 150, top = 22, gap = 6, xL = 118, xB0 = 168, xB1 = 192, xR = 242, fg = "var(--fg)", mu = "var(--muted)";
  const tin = src.reduce((a, x) => a + Math.max(0, x.wh), 0), tout = load.reduce((a, x) => a + Math.max(0, x.wh), 0);
  // each item is as tall as its band (at least room for its two lines); the bands stack on the house bank
  const lay = (items, tot) => { let y = 0; const out = items.map(x => { const th = tot > 0 ? Math.max(0, x.wh) / tot * bankH : 0, h = Math.max(th, 29), r = {x, th, cy: y + h / 2}; y += h + gap; return r; });
    return {out, h: y - gap}; };
  const L = lay(src, tin), R = lay(load, tout), H = Math.max(L.h, R.h, bankH) + top + 16, bankY = top + (H - top - 16 - bankH) / 2;
  const side = (S, left) => { const off = top + (H - top - 16 - S.h) / 2; let acc = bankY;
    return S.out.map(({x, th, cy}) => { cy += off; const y = cy - th / 2, yb = acc; acc += th;
      const [a, b] = left ? [xL, xB0] : [xR, xB1], m = (a + b) / 2, col = colorOf(x.color, x.i);
      const band = th > .3 ? `<path d="M${a} ${y}C${m} ${y} ${m} ${yb} ${b} ${yb}L${b} ${yb + th}C${m} ${yb + th} ${m} ${y + th} ${a} ${y + th}Z" fill="${col}" opacity=".78"/>` : "";
      const tx = left ? xL - 7 : xR + 7, an = left ? "end" : "start", nh = Math.max(th, 3);
      return `${band}<rect x="${left ? xL - 3 : xR}" y="${cy - nh / 2}" width="3" height="${nh}" rx="1.5" fill="${col}"/>
        <text x="${tx}" y="${cy - 2}" text-anchor="${an}" fill="${fg}" font-size="12">${esc(x.label)}</text>
        <text x="${tx}" y="${cy + 12}" text-anchor="${an}" fill="${mu}" font-size="11.5"><tspan fill="${fg}" font-weight="600">${pct(x.wh, left ? tin : tout)}</tspan> (${kwh(x.wh)} kWh)</text>`; }).join(""); };
  return `<svg class="sankey" viewBox="0 0 ${W} ${H}" role="img" aria-label="Energy flow: ${kwh(tin)} kWh in, ${kwh(tout)} kWh out">
    <text x="0" y="11" fill="${mu}" font-size="10.5">In ${kwh(tin)} kWh</text><text x="${W}" y="11" text-anchor="end" fill="${mu}" font-size="10.5">Out ${kwh(tout)} kWh</text>
    ${side(L, true)}${side(R, false)}
    <rect x="${xB0}" y="${bankY}" width="${xB1 - xB0}" height="${bankH}" rx="5" fill="${colorOf(BAT_META[0][2], 0)}"/>
    <text transform="translate(${(xB0 + xB1) / 2 + 4} ${bankY + bankH / 2}) rotate(-90)" text-anchor="middle" fill="#0c1014" font-size="11" font-weight="700" letter-spacing=".06em">HOUSE BANK</text></svg>`;
}
/** Under the flow: shore power on its own (not in the balance) and the net of DC in and out. */
function flowFoot(src, load, shore) {
  const net = src.reduce((a, x) => a + Math.max(0, x.wh), 0) - load.reduce((a, x) => a + Math.max(0, x.wh), 0);
  return `<div class="flowfoot">${shore ? `<span class="chip" title="Not in the balance: it reaches the bank through the Charger House"><i style="background:${colorOf("#0b62c4", 4)}"></i>Shore (AC in) <b>${kwh(shore.wh)} kWh</b></span>` : "<span></span>"}
    <span class="chip">Net <b style="color:var(${net >= 0 ? "--ok" : "--bad"})">${net >= 0 ? "+" : "−"}${kwh(Math.abs(net))} kWh</b></span></div>`;
}
/** Per battery: charged (in) to the left in green, discharged (out) to the right in red, on one scale. @param {any[]} bats */
function battFlow(bats) {
  const max = Math.max(1, ...bats.map(x => Math.max(x.charge_wh || 0, x.discharge_wh || 0)));
  return bats.map(x => `<div class="bflow"><span class="el">${esc(x.key[0] + x.key.slice(1).toLowerCase())}</span>
      <span class="bv">${kwh(x.charge_wh || 0)}</span><span class="bl"><i style="width:${((x.charge_wh || 0) / max * 100).toFixed(1)}%"></i></span>
      <span class="bz"></span><span class="br"><i style="width:${((x.discharge_wh || 0) / max * 100).toFixed(1)}%"></i></span><span class="bv">${kwh(x.discharge_wh || 0)}</span></div>`).join("")
    + `<div class="bflow hint"><span class="el"></span><span class="u-flex-1 u-ta-right">← charged (in)</span><span class="bz"></span><span class="u-flex-1">discharged (out) →</span></div>`;
}
function renderHistory() {
  const box = $("eHist"), r = report || {}, h = hstat || {}, MB = v => v == null ? "–" : v >= 1e9 ? (v / 1e9).toFixed(2) + " GB" : (v / 1e6).toFixed(0) + " MB";
  if (!box.dataset.built) {
    box.dataset.built = "1";
    box.innerHTML = `<div class="histhead" id="eHistHead"><div class="u-d-flex u-gap-8 u-ai-center u-mb-12"><div class="u-maxw-460 u-flex-1 seg" id="eRange">${RANGES.map(([h, l]) => `<button type="button" data-hours="${h}" aria-pressed="${h === hours}">${l}</button>`).join("")}</div>
        <button class="btn sec" type="button" id="eHistUpd" title="Read the latest history now">${icon("refresh")} Update</button></div>
      <div class="zoomrow"><span class="num" id="eZFrom"></span><div class="dual no-swipe"><div class="track"></div><div class="fill" id="eZFill"></div>
        <input type="range" id="eZA" min="0" max="1000" step="1" value="${zoom[0]}" aria-label="Zoom: start of the part shown">
        <input type="range" id="eZB" min="0" max="1000" step="1" value="${zoom[1]}" aria-label="Zoom: end of the part shown"></div><span class="num u-ta-right" id="eZTo"></span>
        <button class="btn sec sm" type="button" id="eZReset" title="Show the whole period">Reset</button></div></div>
      <div class="grid g2 charts" id="eCharts"></div>
      <h2 class="sec">Energy in this period</h2><div class="card pad" id="eContrib"></div>
      <h2 class="sec">Reports and data</h2>
      <div class="grid g2l"><div class="stack">
        <div class="card"><div class="hd">${icon("batt")}<h3>Battery health report</h3></div><div class="rows">
          <div class="row"><div class="k"><small>Analyses the stored battery history: cell connection resistance, current sharing, alarms, cell balance, balancers and usage. Runs in a separate low-priority process on the boat PC.</small></div></div>
          <div class="row"><span class="k">Days to analyse</span><div class="u-d-flex u-gap-8 u-ai-center"><label class="numf"><input class="field" type="number" id="eRepDays" min="1" max="365" step="1" value="7" inputmode="numeric"><span class="u">days</span></label>
            <button class="btn sm" type="button" id="eRepRun">Run report</button></div></div>
          <div class="row" id="eRepStatus"></div></div>
          <div class="mdreport" id="eRepOut" hidden></div></div></div>
      <div class="stack"><div class="card"><div class="hd"><h3>History database</h3></div><div class="rows" id="eHStat"></div></div></div></div>`;
  }
  const running = r.state === "running";
  $("eRepRun").disabled = running;
  $("eRepStatus").innerHTML = running ? `<span class="warnc">Running since ${D.hms(Date.parse(r.started_at))} (${esc(r.days)} days)…</span>`
    : r.error ? `<span class="badc">Report failed: ${esc(r.error)}</span>` : r.markdown ? `<span class="hint">Report of ${esc(r.days)} days, finished ${D.dayTime(Date.parse(r.finished_at))}${r.duration_seconds != null ? ` in ${num(r.duration_seconds, 0)} s` : ""}</span>` : `<span class="hint">No report yet</span>`;
  const out = $("eRepOut");
  if (r.markdown && out.dataset.src !== r.finished_at) { out.innerHTML = md(r.markdown); out.dataset.src = r.finished_at; }
  out.hidden = !r.markdown;
  $("eHStat").innerHTML = hstat ? `
    <div class="row"><span class="k">Records</span><span class="v">${(h.records || 0).toLocaleString("en-GB")}<small>${num(h.records_per_day, 0)} per day</small></span></div>
    <div class="row"><span class="k">Covers</span><span class="v">${num(h.span_days, 1)} days<small>${h.oldest ? D.dayTime(Date.parse(h.oldest)) : "–"} – ${h.newest ? D.dayTime(Date.parse(h.newest)) : "–"} · kept ${h.retention_days} days</small></span></div>
    <div class="row"><span class="k">File size</span><span class="v">${MB(h.size_bytes)}<small>at full retention ~${MB(h.projected_bytes_at_retention)} · reusable ${MB(h.reusable_bytes)}</small></span></div>
    <div class="row"><span class="k">Free disk</span><span class="v">${MB(h.disk_free_bytes)}</span></div>` : `<div class="empty">Loading…</div>`;
  clearTimeout(reportT); if (running && D.visibleIs("power")) reportT = setTimeout(() => D.poll(m, true), 3000);
  renderCharts();
}

// ------------------------------------------------------------------ Settings
function renderSettings() {
  const box = $("eSet");
  if (!settings) { box.innerHTML = `<div class="empty">Loading settings…</div>`; return; }
  if (box.dataset.built && setDirty) return;
  box.dataset.built = "1";
  box.innerHTML = `<form class="u-maxw-720 card" id="eSetForm" novalidate><div class="rows">
    ${SETTINGS.map(([k, l, h, lo, hi, step, u]) => lo === undefined
      ? `<div class="row"><div class="k"><b>${l}</b><small>${h}</small></div>${D.sw("es-" + k, settings[k])}</div>`
      : `<div class="row"><div class="k"><b>${l}</b>${h ? `<small>${h}</small>` : ""}</div><label class="numf"><input class="field" type="number" inputmode="decimal" id="es-${k}" min="${lo}" max="${hi}" step="${step}" value="${settings[k] ?? ""}" required><span class="u">${u}</span></label></div>`).join("")}
    <div class="row"><span class="hint" id="eSetMsg"></span><button class="btn" type="submit" id="eSetSave" disabled>Save</button></div></div></form>
    <div class="u-maxw-720 u-mt-12 card"><div class="hd"><h3>Notifications</h3>${notif && !notif.pushover_configured ? '<span class="warnc">Pushover is not set up on the boat PC</span>' : ""}</div><div class="rows">
      <div class="row"><div class="k"><b>Float protection notification</b><small>A Pushover message "Chargers switched to float" when Float protection starts</small></div>
        ${D.sw("en-float", notif ? notif.float_notification : false, notif ? "" : "disabled")}</div>
      <div class="row"><div class="k"><b>Shore power notification</b><small>"Shore power ON" or "Shore power OFF" when shore power has been connected or disconnected for 30 s</small></div>
        ${D.sw("en-shore", notif ? notif.shore_notification : false, notif ? "" : "disabled")}</div></div></div>`;
  validateSettings();
}
function readSettings() {
  const o = {...settings};     // settings the page does not show (bms_popup_seconds) keep their saved value: the server wants them all
  for (const [k, , , lo, , step] of SETTINGS) { const el = $("es-" + k); o[k] = lo === undefined ? el.checked : (step >= 1 ? parseInt(el.value, 10) : parseFloat(el.value)); }
  return o;
}
function validateSettings() {
  let msg = "";
  for (const [k, l, , lo, hi, step] of SETTINGS) {
    if (lo === undefined) continue; const el = $("es-" + k), v = +el.value;
    const bad = el.value === "" || !isFinite(v) || v < lo || v > hi || (step >= 1 && !Number.isInteger(v));
    el.classList.toggle("invalid", bad); if (bad && !msg) msg = `${l}: ${lo}–${hi}`;
  }
  const o = readSettings();
  if (!msg && o.float_cell_resume_mv > o.float_cell_trigger_mv - 30) msg = "Resume Bulk must be at least 30 mV below the Float trigger";
  $("eSetMsg").textContent = msg || (setDirty ? "Unsaved changes" : ""); $("eSetMsg").className = "hint" + (msg ? " badc" : "");
  $("eSetSave").disabled = !setDirty || !!msg; return !msg;
}
async function saveSettings() {
  if (!validateSettings()) return;
  const o = readSettings();
  if (o.history_retention_days < settings.history_retention_days && !(await D.confirm({title: "Keep less history?",
    text: `History older than ${o.history_retention_days} days will be deleted. This cannot be undone.`, ok: "Delete older history", cancel: "Keep it", danger: true}))) return;
  try { settings = await D.run(m, $("eSetSave"), () => D.api("power", "/api/settings", o), "Settings saved"); setDirty = false; $("eSet").dataset.built = ""; renderSettings(); } catch (e) {}
}

// ------------------------------------------------------------------ events
async function control(id, fn, okMsg) {
  busy.add(id); m.render();
  try { await D.run(null, null, fn, okMsg); } catch (e) {}
  finally { busy.delete(id); await D.poll(m, true); }
}
async function onChange(e) {
  const el = e.target; if (!el.matches('input[type="checkbox"]') || el.closest("#eSetForm")) return;
  const want = el.checked; el.checked = !want;                 // keep showing the real state until the server reads it back
  const id = el.id, d = m.state.data;
  if (id === "en-shore") return control(id, async () => { notif = await D.api("power", "/api/notifications", {shore_notification: want}); $("eSet").dataset.built = ""; },
    `Shore power notification ${want ? "on" : "off"}`);
  if (id === "en-float") return control(id, async () => { notif = await D.api("power", "/api/notifications", {float_notification: want}); $("eSet").dataset.built = ""; },
    `Float protection notification ${want ? "on" : "off"}`);
  if (id === "ec-inverter") return control(id, () => D.api("power", "/api/control/inverter", {enabled: want}), `Inverter ${want ? "ON" : "OFF"}`);
  if (id === "ec-charger") return control(id, () => D.api("power", "/api/control/charger", {enabled: want}), `Charger House ${want ? "ON" : "OFF"}`);
  if (id === "ec-support") return control(id, () => D.api("power", "/api/control/ac-support", {enabled: want}), `AC IN support ${want ? "ON" : "OFF"}`);
  if (id === "ec-alternator") {
    if (!want && !(await D.confirm({title: "Switch off Alternator?", text: "This will put the Alpha Pro alternator regulator into Stop Charge mode.",
      ok: "Switch OFF", cancel: "Keep Alternator ON", danger: true}))) return;
    return control(id, () => D.api("power", "/api/control/alternator", {enabled: want}), `Alternator ${want ? "ON" : "OFF"}`);
  }
  if (id.startsWith("ec-")) {
    const name = id.slice(3), cfg = (d.controls || {})[name];
    if (!cfg || !cfg.verified) return D.toast(`${name} control is not mapped/verified yet`, true);
    if (name === "engine_ecu" && !want && !(await D.confirm({title: "Switch off Engine ECU?", text: "Switching off the Engine ECU will STOP the engine immediately if it is running!",
      note: "The safe default is to leave the Engine ECU switched on.", ok: "Switch OFF", cancel: "Keep ECU ON", danger: true}))) return;
    return control(id, () => D.api("power", `/api/control/device/${name}`, {enabled: want}), `${name.replace(/_/g, " ")} ${want ? "ON" : "OFF"}`);
  }
  const mm = id.match(/^bms-([cd])-(\d)$/);
  if (mm) {
    const what = mm[1] === "c" ? "charge" : "discharge";
    if (!want && !(await D.confirm({title: `Switch off ${what} on Battery ${mm[2]}?`,
      text: what === "discharge" ? "The battery stops supplying the house: loads on it lose power." : "The battery stops accepting charge.", ok: "Switch OFF", cancel: "Keep ON", danger: true}))) return;
    busy.add(id); renderBatt();
    try { await D.run(null, null, () => D.api("power", `/api/bms/${mm[2]}/${what}`, {enabled: want}), `Battery ${mm[2]} ${what} ${want ? "ON" : "OFF"}`); } catch (x) {}
    finally { busy.delete(id); bms = await D.api("power", "/api/bms").catch(() => bms); renderBatt(); }
  }
}
async function onClick(e) {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.view) { const was = view; view = b.dataset.view; m.render(); if (was !== view) window.scrollTo(0, 0); D.poll(m, true); return; }
  if (b.dataset.solo) { const id = b.dataset.solo; solo[id] = solo[id] === b.dataset.label ? null : b.dataset.label; renderCharts(); return; }
  if (b.dataset.mode) {
    const k = b.dataset.mode;
    if (!(await D.confirm({title: `Apply ${k[0].toUpperCase() + k.slice(1)} mode?`, items: MODES[k], ok: "Apply", cancel: "Cancel", safeDefault: false}))) return;
    return control("mode", () => D.api("power", "/api/control/mode", {mode: k}), `${k[0].toUpperCase() + k.slice(1)} mode applied`);
  }
  if (b.dataset.limit) {
    const cur = limitDraft ?? Math.round((m.state.data.combimaster || {}).ac_input_limit ?? 10);
    limitDraft = Math.max(3, Math.min(15, cur + +b.dataset.limit)); renderNow(); return;
  }
  if (b.id === "ec-limit" && limitDraft != null) {
    const a = limitDraft; await control("ec-limit", () => D.api("power", "/api/control/ac-limit", {amps: a}), `AC limit ${a} A`); limitDraft = null; m.render(); return;
  }
  if (b.dataset.soc) return setSoc(b.dataset.soc, b);
  if (b.id === "eZReset") { zoom[0] = 0; zoom[1] = 1000; renderCharts(); return; }
  if (b.id === "eHistUpd") {     // the latest history now, instead of at the next minute
    b.disabled = true; b.lastChild.textContent = " Updating…"; chartT = 0;
    D.poll(m, true).finally(() => { b.disabled = false; b.lastChild.textContent = " Update"; }); return; }
  if (b.dataset.hours) { hours = +b.dataset.hours; zoom[0] = 0; zoom[1] = 1000; chartT = 0; chart = null; alarmData = null; contrib = null; renderCharts(); D.poll(m, true); return; }
  if (b.id === "eRepRun") {
    const days = +$("eRepDays").value;
    if (!Number.isInteger(days) || days < 1 || days > 365) return D.toast("Days: a whole number from 1 to 365", true);
    return D.run(m, b, () => D.api("power", "/api/reports/battery-health", {days}), "Report started").catch(() => {});
  }
  if (b.dataset.bmsRefresh) return D.run(null, b, () => D.api("power", `/api/bms/${b.dataset.bmsRefresh}/refresh`, {}), "Reading battery…").then(() => setTimeout(() => D.poll(m, true), 2500)).catch(() => {});
  if (b.id === "bms-all-refresh") return D.run(null, b, () => Promise.all([D.api("power", "/api/bms/refresh", {}), D.api("power", "/api/balancers/refresh", {})]), "Reading all…").then(() => setTimeout(() => D.poll(m, true), 3000)).catch(() => {});
  if (b.dataset.all) {
    const a = b.dataset.all, off = a.endsWith("off"), what = a.split("-")[0];
    if (!(await D.confirm({title: `${what[0].toUpperCase() + what.slice(1)} ${off ? "OFF" : "ON"} on all batteries?`,
      text: off ? (what === "discharge" ? "All batteries stop supplying the house: the house loses power." : "All batteries stop accepting charge.") : "",
      ok: off ? "Switch OFF" : "Switch ON", cancel: "Cancel", danger: off}))) return;
    return D.run(null, b, () => D.api("power", `/api/bms/set-all/${a}`, {}), "Done").then(async () => { bms = await D.api("power", "/api/bms").catch(() => bms); renderBatt(); }).catch(() => {});
  }
}
// SOC calibration writes the BMS's state of charge (the server queues it on the Bluetooth radio and reads it back).
// Charge % / Discharge %: worked out by the BMS server from the cell voltages along the charging or discharging curve.
async function setSoc(target, btn) {
  const who = target === "all" ? "all batteries" : `Battery ${target}`;
  const v = await D.sheet(`<h3 id="dlgTitle"><span class="warnicon">%</span>Set SOC – ${esc(who)}</h3><p>Choose the state of charge to write to ${esc(who)}. Cancel is selected by default.</p>
    <div class="u-fd-column u-mt-10 btns eq"><button class="btn sec" data-value="charge">Set SOC – Charge % (from the cell voltages)</button>
    <button class="btn sec" data-value="discharge">Set SOC – Discharge % (from the cell voltages)</button><button class="btn sec" data-value="100">Set SOC 100%</button></div>
    <div class="u-b-0 u-p-10-0-0 row"><span class="k">Manual value</span><div class="u-d-flex u-gap-6 u-ai-center"><label class="numf"><input class="field" id="socManual" type="number" min="0" max="100" step="0.1" inputmode="decimal"><span class="u">%</span></label>
      <button class="btn sm" id="socManualSet" type="button">Set</button></div></div><p class="err" id="socErr" hidden></p>
    <div class="acts"><button class="btn sec" data-value="cancel" data-default>Cancel</button></div>`);
  if (!v || v === "cancel") return;
  let mode = v, body = {};
  if (v.startsWith("manual:")) { mode = "value"; body = {percent: +v.slice(7)}; }
  const path = target === "all" ? `/api/bms/set-all-soc/${mode}` : `/api/bms/${target}/set-soc-${mode}`;
  try { await D.run(null, btn, () => D.api("power", path, body), `SOC written to ${who}`); } catch (e) {}
  bms = await D.api("power", "/api/bms").catch(() => bms); renderBatt();
}
document.addEventListener("click", e => {          // the manual SOC field lives in the dialog: validate before closing it
  if (!e.target.closest("#socManualSet")) return;
  const raw = $("socManual").value.trim(), val = Number(raw);
  if (raw === "" || !isFinite(val) || val < 0 || val > 100) { $("socErr").textContent = "Enter a percentage between 0 and 100"; $("socErr").hidden = false; return; }
  D.closeSheet("manual:" + val);
});
D.register(m);
