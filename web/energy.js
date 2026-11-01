// Energy module: Mastervolt (MasterBus) and DALY BMS/balancers through the MasterVolt YMS server.
// Every control is written and read back by that server; Float protection runs there, not here.
// Engine ECU OFF always needs the confirmation whose default is "Keep ECU ON"; no mode switches the ECU off.
"use strict";
(() => {
  const D = Drifter, {$, esc, num, W, icon, hms, ago} = D;
  const MODES = {   // what each mode does, as applied by the server (masterbus_service.set_operating_mode)
    motor: ["Inverter OFF", "Engine ECU ON", "Solar ON", "Charger Start ON", "Charger Bowthruster ON", "Alternator ON", "Charger House OFF"],
    anchor: ["Inverter OFF", "Charger House OFF", "Alternator OFF", "Solar ON", "Charger Start OFF", "Charger Bowthruster OFF"],
    marina: ["Inverter ON", "AC IN support ON", "AC limit = default", "Alternator OFF", "Solar ON", "Charger Start ON", "Charger Bowthruster ON", "Charger House ON"],
    sail: ["Inverter OFF", "Charger House OFF", "Alternator OFF", "Solar ON", "Charger Start OFF", "Charger Bowthruster OFF", "Engine ECU ON"],
  };
  const SRC_IC = {shore: ["plug", "shore"], charger_house: ["plug", "shore"], alternator: ["engine", "alt"], solar: ["sun", "solar"]};
  const LOAD_IC = {house_ac: "load", inverter: "power", charger_start: "batt", charger_bow: "batt", engine_ecu: "engine", alternator_field: "engine", other_dc: "load"};
  const SETTINGS = [   // [key, label, hint, min, max, step, unit] — same limits as the server's SettingsReq
    ["float_protection_enabled", "Float protection", "Switch chargers to Float at a high house SOC or cell voltage"],
    ["house_battery_soc", "Float at house SOC", "Average of the fresh DALY readings", 50, 100, 0.5, "%"],
    ["bulk_resume_soc", "Resume Bulk below SOC", "Must be lower than the Float SOC", 0, 95, 0.5, "%"],
    ["float_cell_trigger_mv", "Float at highest cell", "Any single cell at or above this", 3300, 3650, 1, "mV"],
    ["float_cell_resume_mv", "Resume below highest cell", "Must be lower than the Float cell voltage", 3200, 3650, 1, "mV"],
    ["default_ac_limit", "Default AC input limit", "Used by Marina mode", 3, 15, 1, "A"],
    ["bms_refresh_interval", "BMS read interval", "", 5, 300, 1, "s"],
    ["bms_connection_retry_seconds", "BMS reconnect after", "", 1, 300, 1, "s"],
    ["balancer_refresh_interval", "Balancer read interval", "", 5, 300, 1, "s"],
    ["balancer_connection_retry_seconds", "Balancer reconnect after", "", 5, 300, 1, "s"],
    ["history_retention_days", "Keep history", "Lowering this deletes older history", 1, 365, 1, "days"],
    ["warning_popup_seconds", "Warning pop-up (classic page)", "", 1, 60, 1, "s"],
    ["bms_popup_seconds", "BMS pop-up (classic page)", "", 1, 60, 1, "s"],
  ];
  let view = "now", bms = null, bal = null, settings = null, setDirty = false, limitDraft = null;
  const busy = new Set();
  const on = v => v != null && +v >= .5;

  const m = {
    id: "power", title: "Energy", short: "Energy", icon: "power", every: 3000, background: 6000,
    async load() {
      const jobs = [D.api("power", "/api/energy").then(d => m.state.data = d)];
      if (D.visibleIs("power") && view === "batt") {
        jobs.push(D.api("power", "/api/bms").then(d => bms = d).catch(() => {}), D.api("power", "/api/balancers").then(d => bal = d).catch(() => {}));
      }
      if (D.visibleIs("power") && view === "settings" && !setDirty) jobs.push(D.api("power", "/api/settings").then(d => settings = d).catch(() => {}));
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
      const h = d.storage.house, s = d.sources, t = d.totals;
      return `<div style="display:flex;align-items:center;gap:16px"><div class="gauge sm" style="--p:${h.soc ?? 0}"><b>${num(h.soc)}<small>%</small></b></div>
        <div><div class="big">${W(h.power)}</div><div class="line">House ${num(h.voltage, 2)} V · ${num(h.current, 1)} A ${h.current > 0.3 ? "charging" : h.current < -0.3 ? "discharging" : ""}</div></div></div>
        <div class="minis"><div class="mini"><div class="l">Solar</div><div class="n">${W(s.solar.power)}</div></div>
        <div class="mini"><div class="l">Shore</div><div class="n">${s.shore.connected ? W(s.shore.power) : "–"}</div></div>
        <div class="mini"><div class="l">DC load</div><div class="n">${W(t.consumer_power)}</div></div></div>`;
    },
    mount(el) {
      el.innerHTML = `<div id="eDown"></div>
        <div class="seg" role="tablist" style="margin:4px 0 14px;max-width:460px" id="eViews">
          <button type="button" data-view="now" aria-pressed="true">Now</button><button type="button" data-view="batt" aria-pressed="false">Batteries</button><button type="button" data-view="settings" aria-pressed="false">Settings</button></div>
        <div id="eNow"></div><div id="eBatt" hidden></div><div id="eSet" hidden></div>`;
      el.addEventListener("click", onClick); el.addEventListener("change", onChange);
      el.addEventListener("input", e => { if (e.target.closest("#eSetForm")) { setDirty = true; validateSettings(); } });
      el.addEventListener("submit", e => { if (e.target.id === "eSetForm") { e.preventDefault(); saveSettings(); } });
    },
    render() {
      $("eDown").innerHTML = m.state.err ? D.downCard(m) + '<div style="height:12px"></div>' : "";
      document.querySelectorAll("#eViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === view));
      $("eNow").hidden = view !== "now"; $("eBatt").hidden = view !== "batt"; $("eSet").hidden = view !== "settings";
      if (view === "now") renderNow(); else if (view === "batt") renderBatt(); else renderSettings();
    },
  };

  // ------------------------------------------------------------------ Now
  function flowRow(x, ic, kind, sub, live) {
    const w = x.power, act = live ?? (w != null && w > 2);
    return `<div class="flow"><span class="ic ${kind} ${act ? "on" : ""}">${icon(ic)}</span><div class="nm"><b>${esc(x.label)}</b><small>${sub}</small></div>
      <div class="w">${W(w)}<small>${num(x.voltage, 1)} V · ${num(x.current, 1)} A</small></div></div>`;
  }
  function floatText(f) {
    if (!f) return ["", "–"];
    if (!f.enabled) return ["", "Float protection off"];
    if (f.active) return ["warn", `Float active${f.trigger ? ` (${f.trigger})` : ""} · Bulk resumes below ${num(f.bulk_resume_soc)}% / ${num(f.cell_resume_mv)} mV`];
    return ["ok", `Bulk allowed · Float at ${num(f.threshold_soc)}% or ${num(f.cell_trigger_mv)} mV`];
  }
  function renderNow() {
    const d = m.state.data, box = $("eNow");
    if (!d) { box.innerHTML = m.state.err ? "" : `<div class="empty">Loading…</div>`; return; }
    const h = d.storage.house, s = d.sources, c = d.consumers, t = d.totals, cm = d.combimaster || {}, ctl = d.controls || {}, f = d.high_soc_float_policy;
    const [fc, ft] = floatText(f), charging = h.current != null && h.current > 0.3;
    const socAge = h.soc_age_seconds != null ? ` · DALY ${Math.round(h.soc_age_seconds)} s old` : "";
    const srcSub = {shore: s.shore.connected ? `${num(s.shore.input_frequency, 1)} Hz` : "Not connected", charger_house: s.charger_house.charge_state || "–",
      alternator: `${s.alternator.state || "–"}${s.alternator.estimated ? " · estimated" : ""}`, solar: `${s.solar.state || "–"} · panel ${num(s.solar.panel_voltage, 1)} V`};
    const sw = (id, val, extra = "") => D.sw(id, val, (busy.has(id) ? "disabled " : "") + extra);
    const dev = (name, label, hint) => { const cfg = ctl[name];
      return `<div class="row"><div class="k"><b>${label}</b><small>${cfg && cfg.verified ? hint : "Not mapped/verified yet"}</small></div>${sw("ec-" + name, cfg && cfg.current, cfg && cfg.verified ? "" : "disabled")}</div>`; };
    const lim = limitDraft ?? (cm.ac_input_limit != null ? Math.round(cm.ac_input_limit) : null);
    box.innerHTML = `
      <div class="card pad" style="margin-bottom:12px"><div class="btns eq">${Object.keys(MODES).map(k => `<button class="btn sec" type="button" data-mode="${k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div>
        <p class="hint" style="margin:8px 2px 0">Modes switch several devices at once. Engine ECU is never switched off by a mode.</p></div>
      <div class="grid g2l">
        <div class="stack">
          <div class="card pad" style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
            <div class="gauge" style="--p:${h.soc ?? 0};--c:${h.soc != null && h.soc < 20 ? "var(--bad)" : h.soc != null && h.soc < 35 ? "var(--warn)" : "var(--batt)"}"><b>${num(h.soc)}<small>%</small></b></div>
            <div style="flex:1;min-width:180px"><div class="muted" style="font-weight:600;font-size:13px">House battery · ${esc(h.chemistry || h.type || "LiFePO4")}</div>
              <div style="font-size:30px;font-weight:750;letter-spacing:-.02em" class="num">${h.power != null && h.power > 0 ? "+" : ""}${W(h.power)}</div>
              <div class="muted">${num(h.voltage, 2)} V · ${num(h.current, 1)} A · ${charging ? "charging" : h.current < -0.3 ? "discharging" : "idle"}${h.temperature != null ? ` · ${num(h.temperature, 1)} °C` : ""}</div>
              <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap"><span class="badge wrap ${fc}">${esc(ft)}</span>${h.soc == null ? `<span class="badge warn">SOC: ${esc(h.soc_source || "no fresh DALY data")}</span>` : ""}</div>
              <div class="hint" style="margin-top:6px">Highest cell ${num(h.max_cell_mv)} mV${h.max_cell_battery ? ` (${esc(h.max_cell_battery)})` : ""} · spread ${num(h.max_spread_mv)} mV${socAge}</div></div>
          </div>
          <div class="stats s4">
            <div class="stat"><div class="l">${icon("sun")} Solar</div><div class="n">${W(s.solar.power)}</div><div class="s">${esc(s.solar.state || "–")}</div></div>
            <div class="stat"><div class="l">${icon("plug")} Shore</div><div class="n">${s.shore.connected ? W(s.shore.power) : "–"}</div><div class="s">${s.shore.connected ? num(s.shore.voltage) + " V" : "not connected"}</div></div>
            <div class="stat"><div class="l">DC in</div><div class="n">${W(t.dc_input_power)}</div><div class="s">charging sources</div></div>
            <div class="stat"><div class="l">DC load</div><div class="n">${W(t.consumer_power)}</div><div class="s">AC ${W(t.ac_consumer_power)}</div></div>
          </div>
          <div class="card"><div class="hd">${icon("sun")}<h3>Sources</h3></div><div class="rows">
            ${Object.entries(s).map(([k, x]) => flowRow(x, SRC_IC[k][0], SRC_IC[k][1], esc(srcSub[k]), k === "shore" ? x.connected : k === "alternator" ? x.running : undefined)).join("")}</div></div>
          <div class="card"><div class="hd">${icon("load")}<h3>Consumers</h3><span class="muted num">${W(t.consumer_power)}</span></div><div class="rows">
            ${Object.entries(c).map(([k, x]) => flowRow(x, LOAD_IC[k] || "load", "load", esc(x.charge_state || (x.estimated ? "estimated" : x.kind || "")))).join("")}</div></div>
          <div class="card"><div class="hd">${icon("batt")}<h3>Other batteries</h3></div><div class="rows">
            ${["start", "bow"].map(k => { const b = d.storage[k]; return `<div class="flow"><span class="ic batt ${b.current > 0.2 ? "on" : ""}">${icon("batt")}</span><div class="nm"><b>${esc(b.label)}</b><small>${b.soc != null ? num(b.soc) + "% · " : ""}${esc(b.chemistry || b.type || "")}</small></div><div class="w">${num(b.voltage, 2)} V<small>${num(b.current, 1)} A</small></div></div>`; }).join("")}</div></div>
        </div>
        <div class="stack">
          <div class="card"><div class="hd">${icon("power")}<h3>CombiMaster</h3>${on(cm.alarms) ? '<span class="badge bad">alarm</span>' : ""}</div><div class="rows">
            <div class="row"><div class="k"><b>Inverter</b><small>${on(cm.inverting) ? "Inverting" : on(cm.supporting) ? "Supporting" : "Not inverting"}</small></div>${sw("ec-inverter", on(cm.inverter_enabled))}</div>
            <div class="row"><div class="k"><b>Charger House</b><small>${esc(s.charger_house.charge_state || "–")}</small></div>${sw("ec-charger", on(cm.charger_enabled))}</div>
            <div class="row"><div class="k"><b>AC IN support</b><small>Inverter helps when shore power is limited</small></div>${sw("ec-support", on(cm.ac_support_enabled))}</div>
            <div class="row"><div class="k"><b>AC input limit</b><small>Now ${cm.ac_input_limit != null ? num(cm.ac_input_limit) + " A" : "–"} · 3–15 A</small></div>
              <div style="display:flex;gap:6px;align-items:center"><div class="stepper no-swipe"><button type="button" data-limit="-1" aria-label="Lower">−</button><output class="num">${lim ?? "–"} A</output><button type="button" data-limit="1" aria-label="Higher">+</button></div>
              <button class="btn sm" type="button" id="ec-limit" ${limitDraft == null || limitDraft === Math.round(cm.ac_input_limit) || busy.has("ec-limit") ? "disabled" : ""}>Set</button></div></div>
          </div></div>
          <div class="card"><div class="hd">${icon("engine")}<h3>Charging &amp; engine</h3></div><div class="rows">
            <div class="row"><div class="k"><b>Alternator</b><small>${esc(s.alternator.state || "–")}${s.alternator.shaft_running ? " · shaft turning" : ""}</small></div>${sw("ec-alternator", !!s.alternator.control_on)}</div>
            ${dev("solar", "Solar", "SCM solar charger")}${dev("charger_start", "Charger Start", "Mass charger to start battery")}${dev("charger_bow", "Charger Bowthruster", "Mass charger to bow battery")}
            ${dev("engine_ecu", "Engine ECU", "Switching off stops a running engine")}
          </div></div>
          <p class="hint" style="margin:0 4px">History charts, battery reports and Bluetooth diagnostics are on the <a href="#system">classic Energy page</a> for now.</p>
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ Batteries
  function renderBatt() {
    const box = $("eBatt");
    if (!bms) { box.innerHTML = `<div class="empty">Loading batteries…</div>`; return; }
    const cs = bms.control_status || {}, names = Object.keys(bms.batteries || {}).sort();
    const bcard = name => {
      const b = bms.batteries[name], n = name.replace(/\D/g, ""), cells = b.cells_mv || [];
      const hi = cells.length ? Math.max(...cells) : null, lo = cells.length ? Math.min(...cells) : null, bal_ = new Set(b.balancing_cells || []);
      const age = b.captured_at ? (Date.now() - Date.parse(b.captured_at)) / 1000 : null;
      const st = b.state === "connected" ? (age != null && age > 120 ? ["warn", `stale · ${D.dur(age)}`] : ["ok", age != null ? `${D.dur(age)} ago` : "connected"]) : [b.error ? "bad" : "", b.state.replace(/_/g, " ")];
      return `<div class="card"><div class="hd">${icon("batt")}<h3>${esc(name[0] + name.slice(1).toLowerCase())}</h3><span class="badge ${st[0]}">${esc(st[1])}</span>
          <button class="iconbtn" type="button" data-bms-refresh="${n}" aria-label="Read ${esc(name)} now">${icon("refresh")}</button></div>
        ${b.error ? `<div class="err" style="padding:0 16px 8px">${esc(b.error)}</div>` : ""}
        <div class="rows">
          <div class="row"><span class="k">State of charge</span><span class="v">${num(b.state_of_charge_percent, 1)}%<small>${num(b.remaining_capacity_ah, 1)} Ah left</small></span></div>
          <div class="row"><span class="k">Pack</span><span class="v">${num(b.pack_voltage_v, 2)} V · ${num(b.current_a, 1)} A<small>${b.cycles != null ? b.cycles + " cycles" : ""}</small></span></div>
          <div class="row"><span class="k">Temperature</span><span class="v">${(b.temperatures_c || []).map(x => num(x, 0) + " °C").join(" · ") || "–"}</span></div>
          <div class="row"><span class="k">Cell spread</span><span class="v ${b.cell_spread_mv > 50 ? "warnc" : ""}">${num(b.cell_spread_mv)} mV<small>${bal_.size ? `balancing ${[...bal_].join(", ")}` : ""}</small></span></div>
          <div class="row"><div class="k"><b>Charge MOSFET</b></div>${D.sw(`bms-c-${n}`, b.charge_mosfet_on, busy.has(`bms-c-${n}`) || cs.busy || b.charge_mosfet_on == null ? "disabled" : "")}</div>
          <div class="row"><div class="k"><b>Discharge MOSFET</b><small>Off cuts the house loads on this battery</small></div>${D.sw(`bms-d-${n}`, b.discharge_mosfet_on, busy.has(`bms-d-${n}`) || cs.busy || b.discharge_mosfet_on == null ? "disabled" : "")}</div>
          ${(b.alarms || []).length ? `<div class="row"><span class="k badc">Alarms</span><span class="v badc">${b.alarms.map(esc).join("<br>")}</span></div>` : ""}
        </div>
        ${cells.length ? `<div class="cells">${cells.map((v, i) => `<div class="cell ${v === hi && hi !== lo ? "hi" : v === lo && hi !== lo ? "lo" : ""} ${bal_.has(i + 1) ? "bal" : ""}"><div class="cn">${i + 1}</div><div class="cv">${(v / 1000).toFixed(3)}</div></div>`).join("")}</div>` : ""}
      </div>`;
    };
    const devs = (bal && bal.devices) || {};
    const balcard = ([name, dv]) => {
      const v = dv.values || dv, cells = v.cells_mv || [], hi = cells.length ? Math.max(...cells) : null, lo = cells.length ? Math.min(...cells) : null;
      const n = name.replace(/\D/g, "");
      const st = dv.stale ? ["warn", "stale"] : dv.error ? ["bad", "error"] : dv.state === "connected" || cells.length ? ["ok", dv.last_success_age_seconds != null ? `${D.dur(dv.last_success_age_seconds)} ago` : "ok"] : ["", dv.state || "–"];
      return `<div class="card"><div class="hd">${icon("refresh")}<h3>${esc(name)}</h3><span class="badge ${st[0]}">${esc(st[1])}</span>
          <button class="iconbtn" type="button" data-bal-refresh="${n}" aria-label="Read ${esc(name)} now">${icon("refresh")}</button></div>
        ${dv.error ? `<div class="err" style="padding:0 16px 8px">${esc(dv.error)}</div>` : ""}
        <div class="rows"><div class="row"><span class="k">Pack</span><span class="v">${num(v.pack_voltage_v, 2)} V${v.reported_current_a != null ? ` · ${num(v.reported_current_a, 2)} A` : ""}</span></div>
          <div class="row"><span class="k">Cell delta</span><span class="v">${num(v.cell_delta_mv ?? (hi != null ? hi - lo : null))} mV</span></div></div>
        ${cells.length ? `<div class="cells">${cells.map((x, i) => `<div class="cell ${x === hi && hi !== lo ? "hi" : x === lo && hi !== lo ? "lo" : ""}"><div class="cn">${i + 1}</div><div class="cv">${(x / 1000).toFixed(3)}</div></div>`).join("")}</div>` : ""}</div>`;
    };
    box.innerHTML = `
      <div class="card pad" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn sec sm" type="button" id="bms-all-refresh">${icon("refresh")} Read all</button>
        <button class="btn sec sm" type="button" data-all="charge-on">All charge ON</button><button class="btn sec sm" type="button" data-all="charge-off">All charge OFF</button>
        <button class="btn sec sm" type="button" data-all="discharge-on">All discharge ON</button><button class="btn sec sm" type="button" data-all="discharge-off">All discharge OFF</button>
        <span class="hint" style="flex:1;min-width:160px">${cs.busy ? `<span class="warnc">${esc(cs.message || cs.phase || "Bluetooth busy…")}</span>` : `${bms.connected_count ?? "–"} connected · read every ${bms.refresh_interval_seconds ?? "–"} s`}</span></div>
      <div class="grid g3">${names.map(bcard).join("")}</div>
      <h2 class="sec">Balancers</h2><div class="grid g3">${Object.entries(devs).map(balcard).join("") || `<div class="empty">No balancer data</div>`}</div>`;
  }

  // ------------------------------------------------------------------ Settings
  function renderSettings() {
    const box = $("eSet");
    if (!settings) { box.innerHTML = `<div class="empty">Loading settings…</div>`; return; }
    if (box.dataset.built && setDirty) return;
    box.dataset.built = "1";
    box.innerHTML = `<form class="card" id="eSetForm" novalidate style="max-width:720px"><div class="rows">
      ${SETTINGS.map(([k, l, h, lo, hi, step, u]) => lo === undefined
        ? `<div class="row"><div class="k"><b>${l}</b><small>${h}</small></div>${D.sw("es-" + k, settings[k])}</div>`
        : `<div class="row"><div class="k"><b>${l}</b>${h ? `<small>${h}</small>` : ""}</div><label class="numf"><input class="field" type="number" inputmode="decimal" id="es-${k}" min="${lo}" max="${hi}" step="${step}" value="${settings[k] ?? ""}" required><span class="u">${u}</span></label></div>`).join("")}
      <div class="row"><span class="hint" id="eSetMsg"></span><button class="btn" type="submit" id="eSetSave" disabled>Save</button></div></div></form>`;
    validateSettings();
  }
  function readSettings() {
    const o = {};
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
    if (!msg && o.bulk_resume_soc >= o.house_battery_soc) msg = "Resume Bulk SOC must be below the Float SOC";
    if (!msg && o.float_cell_resume_mv >= o.float_cell_trigger_mv) msg = "Resume cell voltage must be below the Float cell voltage";
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
    if (b.dataset.view) { view = b.dataset.view; m.render(); D.poll(m, true); return; }
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
    if (b.dataset.bmsRefresh) return D.run(null, b, () => D.api("power", `/api/bms/${b.dataset.bmsRefresh}/refresh`, {}), "Reading battery…").then(() => setTimeout(() => D.poll(m, true), 2500)).catch(() => {});
    if (b.dataset.balRefresh) return D.run(null, b, () => D.api("power", `/api/balancers/${b.dataset.balRefresh}/refresh`, {}), "Reading balancer…").then(() => D.poll(m, true)).catch(() => {});
    if (b.id === "bms-all-refresh") return D.run(null, b, () => Promise.all([D.api("power", "/api/bms/refresh", {}), D.api("power", "/api/balancers/refresh", {})]), "Reading all…").then(() => setTimeout(() => D.poll(m, true), 3000)).catch(() => {});
    if (b.dataset.all) {
      const a = b.dataset.all, off = a.endsWith("off"), what = a.split("-")[0];
      if (!(await D.confirm({title: `${what[0].toUpperCase() + what.slice(1)} ${off ? "OFF" : "ON"} on all batteries?`,
        text: off ? (what === "discharge" ? "All batteries stop supplying the house: the house loses power." : "All batteries stop accepting charge.") : "",
        ok: off ? "Switch OFF" : "Switch ON", cancel: "Cancel", danger: off}))) return;
      return D.run(null, b, () => D.api("power", `/api/bms/set-all/${a}`, {}), "Done").then(async () => { bms = await D.api("power", "/api/bms").catch(() => bms); renderBatt(); }).catch(() => {});
    }
  }
  D.register(m);
})();
