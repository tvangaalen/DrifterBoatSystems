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
    ["bms_popup_seconds", "BMS pop-up (classic page)", "Only used by the classic Energy page", 1, 60, 1, "s"],
  ];
  let view = "now", bms = null, bal = null, settings = null, setDirty = false, limitDraft = null, coord = null, bleEv = null, hstat = null, report = null, reportT = null, hours = 24, chart = null, contrib = null, chartT = 0, chartFor = null;
  const busy = new Set();
  const on = v => v != null && +v >= .5;
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
                    D.api("power", `/api/history/contributions?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`, undefined, {timeout: 45000}).then(d => contrib = d).catch(() => {}));
        }
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
        <div class="minis m4"><div class="mini"><div class="l">Charger house</div><div class="n">${W((s.charger_house || {}).power)}</div></div>
        <div class="mini"><div class="l">Alternator</div><div class="n">${W((s.alternator || {}).power)}</div></div>
        <div class="mini"><div class="l">Solar</div><div class="n">${W(s.solar.power)}</div></div>
        <div class="mini"><div class="l">DC load</div><div class="n">${outW(t.consumer_power)}</div></div></div>`;
    },
    mount(el) {
      el.innerHTML = `<div id="eDown"></div>
        <div class="seg" role="tablist" style="margin:4px 0 14px;max-width:460px" id="eViews">
          <button type="button" data-view="now" aria-pressed="true">Now</button><button type="button" data-view="batt" aria-pressed="false">Batteries</button><button type="button" data-view="history" aria-pressed="false">History</button><button type="button" data-view="settings" aria-pressed="false">Settings</button></div>
        <div id="eNow"></div><div id="eBatt" hidden></div><div id="eHist" hidden></div><div id="eSet" hidden></div>`;
      el.addEventListener("click", onClick); el.addEventListener("change", onChange);
      el.addEventListener("input", e => { if (e.target.closest("#eSetForm")) { setDirty = true; validateSettings(); } });
      el.addEventListener("submit", e => { if (e.target.id === "eSetForm") { e.preventDefault(); saveSettings(); } });
    },
    render() {
      $("eDown").innerHTML = m.state.err ? D.downCard(m) + '<div style="height:12px"></div>' : "";
      document.querySelectorAll("#eViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === view));
      $("eNow").hidden = view !== "now"; $("eBatt").hidden = view !== "batt"; $("eHist").hidden = view !== "history"; $("eSet").hidden = view !== "settings";
      if (view === "now") renderNow(); else if (view === "batt") renderBatt(); else if (view === "history") renderHistory(); else renderSettings();
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
    if (f.active) return ["warn", `Float active${f.trigger ? ` (${f.trigger})` : ""} · Bulk resumes when the highest cell is below ${num(f.cell_resume_mv)} mV`];
    return ["ok", `Bulk allowed · Float when a cell reaches ${num(f.cell_trigger_mv)} mV${f.max_cell_mv != null ? ` (now ${num(f.max_cell_mv)} mV)` : ""}`];
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
      <div class="card pad" style="margin-bottom:12px"><div class="btns eq">${Object.keys(MODES).map(k => `<button class="btn sec" type="button" data-mode="${k}" aria-pressed="${d.active_mode === k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div>
        <p class="hint" style="margin:8px 2px 0">${d.active_mode ? `${esc(d.active_mode[0].toUpperCase() + d.active_mode.slice(1))} mode is active (until a single control changes). ` : ""}Modes switch several devices at once. Engine ECU is never switched off by a mode.</p></div>
      <div class="grid g2l">
        <div class="stack">
          <div class="card pad" style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
            <div class="gauge" style="--p:${h.soc ?? 0};--c:${h.soc != null && h.soc < 20 ? "var(--bad)" : h.soc != null && h.soc < 35 ? "var(--warn)" : "var(--batt)"}"><b>${num(h.soc)}<small>%</small></b></div>
            <div style="flex:1;min-width:180px"><div class="muted" style="font-weight:600;font-size:13px">House battery · ${esc(h.battery_type || h.chemistry || "LiFePO4")}${h.capacity ? ` · ${num(h.capacity)} ${esc(h.capacity_unit || "Ah")}` : ""}</div>
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
            ${["start", "bow"].map(k => { const b = d.storage[k]; return `<div class="flow"><span class="ic batt ${b.current > 0.2 ? "on" : ""}">${icon("batt")}</span><div class="nm"><b>${esc(b.label)}</b><small>${b.soc != null ? num(b.soc) + "% · " : ""}${esc(b.battery_type || b.chemistry || "")}${b.capacity ? ` · ${num(b.capacity)} ${esc(b.capacity_unit || "Ah")}` : ""}</small></div><div class="w">${num(b.voltage, 2)} V<small>${num(b.current, 1)} A</small></div></div>`; }).join("")}</div></div>
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
          <p class="hint" style="margin:0 4px">History charts and reports are under History; Bluetooth diagnostics and SOC calibration under Batteries.</p>
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
          <div class="row"><span class="k">State of charge</span><span class="v">${num(b.state_of_charge_percent, 1)}%<small>${num(b.remaining_capacity_ah, 1)} Ah left</small></span>
            <button class="btn sec sm" type="button" data-soc="${n}" ${cs.busy || b.state !== "connected" ? "disabled" : ""}>Set SOC</button></div>
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
      const v = dv.status || {}, cells = v.cells_mv || [], hi = cells.length ? Math.max(...cells) : null, lo = cells.length ? Math.min(...cells) : null;
      const n = name.replace(/\D/g, "");
      const st = dv.stale ? ["warn", "stale"] : dv.error ? ["bad", "error"] : dv.state === "connected" || cells.length ? ["ok", dv.last_success_age_seconds != null ? `${D.dur(dv.last_success_age_seconds)} ago` : "ok"] : ["", dv.state || "–"];
      return `<div class="card"><div class="hd">${icon("refresh")}<h3>${esc(name)}</h3><span class="badge ${st[0]}">${esc(st[1])}</span>
          <button class="iconbtn" type="button" data-bal-refresh="${n}" aria-label="Read ${esc(name)} now">${icon("refresh")}</button></div>
        ${dv.error ? `<div class="err" style="padding:0 16px 8px">${esc(dv.error)}</div>` : ""}
        <div class="rows"><div class="row"><span class="k">Balancing</span><span class="v">${v.balance_active ? `<span class="warnc">active</span>${v.balance_position != null ? `<small>position ${esc(v.balance_position)}</small>` : ""}` : v.valid_frame_count ? "idle" : "–"}</span></div>
          <div class="row"><span class="k">Pack</span><span class="v">${num(v.pack_voltage_v, 2)} V${v.reported_current_a != null ? ` · ${num(v.reported_current_a, 2)} A` : ""}<small>${(v.temperatures_c || []).map(x => num(x, 0) + " °C").join(" · ")}</small></span></div>
          <div class="row"><span class="k">Cell delta</span><span class="v ${v.cell_delta_mv > 50 ? "warnc" : ""}">${num(v.cell_delta_mv ?? (hi != null ? hi - lo : null))} mV<small>${v.average_cell_mv != null ? `average ${num(v.average_cell_mv)} mV` : ""}</small></span></div>
          ${(v.alarms || []).length ? `<div class="row"><span class="k badc">Alarms</span><span class="v badc">${v.alarms.map(esc).join("<br>")}</span></div>` : ""}</div>
        ${cells.length ? `<div class="cells">${cells.map((x, i) => `<div class="cell ${x === hi && hi !== lo ? "hi" : x === lo && hi !== lo ? "lo" : ""}"><div class="cn">${i + 1}</div><div class="cv">${(x / 1000).toFixed(3)}</div></div>`).join("")}</div>` : ""}</div>`;
    };
    box.innerHTML = `
      <div class="card pad" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn sec sm" type="button" id="bms-all-refresh">${icon("refresh")} Read all</button>
        <button class="btn sec sm" type="button" data-all="charge-on">All charge ON</button><button class="btn sec sm" type="button" data-all="charge-off">All charge OFF</button>
        <button class="btn sec sm" type="button" data-all="discharge-on">All discharge ON</button><button class="btn sec sm" type="button" data-all="discharge-off">All discharge OFF</button>
        <button class="btn sec sm" type="button" data-soc="all" ${cs.busy ? "disabled" : ""}>Set all SOC</button>
        <span class="hint" style="flex:1;min-width:160px">${cs.busy ? `<span class="warnc">${esc(cs.message || cs.phase || "Bluetooth busy…")}</span>` : `${bms.connected_count ?? "–"} connected · read every ${bms.refresh_interval_seconds ?? "–"} s`}</span></div>
      <div class="grid g3">${names.map(bcard).join("")}</div>
      <h2 class="sec">Balancers</h2><div class="grid g3">${Object.entries(devs).map(balcard).join("") || `<div class="empty">No balancer data</div>`}</div>
      ${bleCard()}`;
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
    return `<h2 class="sec">Bluetooth</h2><div class="grid g2"><div class="card"><div class="rows">
        <div class="row"><span class="k">Radio</span><span class="v">${c.degraded ? '<span class="warnc">degraded</span>' : c.active ? esc(String(c.active)) : "idle"}<small>${c.active_for_seconds != null ? `for ${num(c.active_for_seconds, 1)} s · ` : ""}${esc(waiting)}</small></span></div>
        <div class="row"><span class="k">BMS</span><span class="v">${c.connected_bms ?? "–"} connected · ${c.refreshed_bms ?? "–"} read<small>${c.bms_stable_seconds != null ? "stable for " + D.dur(c.bms_stable_seconds) : ""}${c.forced_releases ? ` · ${c.forced_releases} forced releases` : ""}</small></span></div>
        <div class="row"><span class="k">Balancers</span><span class="v">${c.balancers_allowed ? "allowed" : '<span class="warnc">paused for the BMS</span>'}</span></div>
        ${Object.entries(counters).filter(([n]) => n !== "balancers").map(dev).join("")}</div></div>
      <div class="card"><div class="hd"><h3>Recent Bluetooth events</h3></div><div class="log">${((bleEv && bleEv.events) || []).slice().reverse().slice(0, 40).map(e => `<div class="${/fail|error|timeout/i.test(e.kind) ? "warn" : ""}"><time>${esc(D.dayTime(Date.parse(e.time)))}</time><span class="msg"><b>${esc(e.device)}</b> ${esc(e.kind.replace(/_/g, " "))}${e.detail ? " · " + esc(e.detail) : ""}</span></div>`).join("") || `<div class="empty">No events</div>`}</div></div></div>`;
  }

  // ------------------------------------------------------------------ History (reports, manual, database; charts follow)
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
  // come from /api/history/contributions, which integrates the full-resolution data. Stacked bands are opaque areas.
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
  function drawChart(canvas, opt) {      // opt: {t0, t1, stacked, unit, series:[{label, color, pts:[{t, v}]}]}
    const dpr = window.devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W) return;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const g = canvas.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const css = n => getComputedStyle(document.body).getPropertyValue(n).trim(), muted = css("--muted"), line = css("--line");
    const L = 44, R = W - 8, T = 8, B = H - 22;
    let lo = Infinity, hi = -Infinity;
    if (opt.stacked) {     // stack on a shared time axis: the first series' timestamps
      const base = opt.series[0] ? opt.series[0].pts.map(p => p.t) : [];
      opt.stackTops = base.map((t, i) => opt.series.reduce((acc, s) => acc + Math.max(0, (s.pts[i] || {}).v || 0), 0));
      lo = 0; hi = Math.max(1, ...opt.stackTops);
    } else for (const s of opt.series) for (const p of s.pts) if (p.v != null) { lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (opt.zero) lo = Math.min(lo, 0);
    if (hi - lo < 1e-6) { hi += 1; lo -= opt.zero ? 0 : 1; }
    const pad = (hi - lo) * .06; hi += pad; if (!opt.stacked && lo !== 0) lo -= pad;
    const X = t => L + (t - opt.t0) / (opt.t1 - opt.t0) * (R - L), Y = v => B - (v - lo) / (hi - lo) * (B - T);
    g.font = "11px -apple-system, Segoe UI, sans-serif"; g.fillStyle = muted; g.strokeStyle = line; g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4, y = Y(v); g.beginPath(); g.moveTo(L, y); g.lineTo(R, y); g.stroke();
      g.textAlign = "right"; g.fillText(Math.abs(hi - lo) >= 20 ? Math.round(v) : v.toFixed(1), L - 6, y + 4); }
    const span = opt.t1 - opt.t0, step = [3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3, 48 * 3600e3, 7 * 864e5].find(s => span / s <= 6) || 7 * 864e5;
    g.textAlign = "center";
    for (let t = Math.ceil(opt.t0 / step) * step; t <= opt.t1; t += step) { const d = new Date(t), x = X(t);
      const lab = step >= 864e5 ? `${D.pad(d.getDate())}-${D.pad(d.getMonth() + 1)}` : `${D.pad(d.getHours())}:00`;
      g.beginPath(); g.moveTo(x, B); g.lineTo(x, B + 4); g.stroke(); g.fillText(lab, x, H - 6); }
    if (opt.zero && lo < 0) { g.strokeStyle = muted; g.beginPath(); g.moveTo(L, Y(0)); g.lineTo(R, Y(0)); g.stroke(); }
    g.save(); g.beginPath(); g.rect(L, T, R - L, B - T); g.clip();
    if (opt.stacked) {
      const base = opt.series[0] ? opt.series[0].pts : [], acc = base.map(() => 0);
      opt.series.forEach((s, k) => {     // opaque bands, drawn once each: no stripes
        g.fillStyle = colorOf(s.color, k); g.beginPath();
        base.forEach((p, i) => { const top = acc[i] + Math.max(0, (s.pts[i] || {}).v || 0); g[i ? "lineTo" : "moveTo"](X(p.t), Y(top)); });
        for (let i = base.length - 1; i >= 0; i--) g.lineTo(X(base[i].t), Y(acc[i]));
        g.closePath(); g.fill();
        base.forEach((p, i) => acc[i] += Math.max(0, (s.pts[i] || {}).v || 0));
      });
    } else opt.series.forEach((s, k) => {
      g.strokeStyle = colorOf(s.color, k); g.lineWidth = s.width || 1.6; g.beginPath(); let on = false, last = null;
      for (const p of s.pts) { if (p.v == null || (last && p.t - last > Math.max(600e3, span / 150))) { on = false; } if (p.v == null) { last = null; continue; }
        g[on ? "lineTo" : "moveTo"](X(p.t), Y(p.v)); on = true; last = p.t; }
      g.stroke();
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
    tip.innerHTML = `<b>${D.dayTime(t)}</b> ${mp.opt.unit ? `<small>${esc(mp.opt.unit)}</small>` : ""}<div class="tiprows">${rows}</div>`;
    tip.hidden = false; tip.style.left = Math.min(r.width - tip.offsetWidth - 4, Math.max(4, x - tip.offsetWidth / 2)) + "px";
    const cur = canvas.parentElement.querySelector(".cross"); cur.style.left = x + "px"; cur.hidden = false;
  }
  function renderCharts() {
    const box = $("eCharts"); if (!box) return;
    document.querySelectorAll("#eRange button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.hours === hours));
    if (!chart) { box.innerHTML = `<div class="empty">Loading history…</div>`; delete box.dataset.built; if ($("eContrib")) $("eContrib").innerHTML = `<div class="empty">Loading…</div>`; return; }
    const S = seriesFrom(chart), t1 = Date.parse(chart.latest), t0 = Date.parse(chart.cutoff);
    const defs = [
      ["eChSoc", "State of charge", "%", {series: [{label: "Total", color: BAT_META[0][2], width: 2.4, pts: S.tot},
        ...BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.rem != null ? p.rem / S.perAh * 100 : null}))}))]}],
      ["eChSrc", "Sources", "W", {stacked: true, series: SRC_META.map(([k, l, c], i) => ({label: l, color: c, pts: S.dash.map(r => ({t: r.t, v: r.sp[i]}))}))}],
      ["eChLoad", "DC consumers", "W", {stacked: true, series: LOAD_META.map(([k, l, c], i) => ({label: l, color: c, pts: S.dash.map(r => ({t: r.t, v: r.lp[i]}))}))}],
      ["eChCur", "Battery current", "A", {zero: true, series: BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.cur}))}))}],
      ["eChSpread", "Cell spread", "mV", {series: BAT_META.slice(1).map(([k, l, c]) => ({label: l, color: c, pts: (S.byBat[k] || []).map(p => ({t: p.t, v: p.spread}))}))}],
    ];
    if (!box.dataset.built) {
      box.dataset.built = "1";
      box.innerHTML = defs.map(([id, title, unit]) => `<div class="card chartcard"><div class="hd"><h3>${title}</h3><span class="muted">${unit}</span></div>
        <div class="legend" id="${id}Leg"></div><div class="chartwrap no-swipe"><canvas id="${id}"></canvas><div class="cross" hidden></div><div class="charttip" hidden></div></div></div>`).join("");
      for (const [id] of defs) { const cv = $(id), tip = cv.parentElement.querySelector(".charttip");
        const move = e => crosshair(cv, tip, e), leave = () => { tip.hidden = true; cv.parentElement.querySelector(".cross").hidden = true; };
        cv.addEventListener("pointermove", move); cv.addEventListener("pointerdown", move); cv.addEventListener("pointerleave", leave); }
    }
    for (const [id, , unit, o] of defs) {
      $(id + "Leg").innerHTML = o.series.map((s, k) => `<span><i style="background:${colorOf(s.color, k)}"></i>${esc(s.label)}</span>`).join("");
      drawChart($(id), {...o, unit, t0, t1});
    }
    const c = contrib;
    const bars = (items, unitLabel) => { const max = Math.max(1, ...items.map(x => x.wh));
      return items.map(x => `<div class="ebar"><span class="el">${esc(x.label)}</span><span class="eb"><i style="width:${(x.wh / max * 100).toFixed(1)}%;background:${colorOf(x.color, x.i)}"></i></span><span class="ev">${(x.wh / 1000).toFixed(2)} kWh${x.avg != null ? `<small>${num(x.avg, 0)} W avg</small>` : ""}</span></div>`).join(""); };
    $("eContrib").innerHTML = !c ? `<div class="empty">Loading…</div>` : `
      <div class="ebars"><h4>Sources</h4>${bars([...c.sources.map(x => { const i = SRC_META.findIndex(m => m[0] === x.key); return {label: (SRC_META[i] || [, x.key])[1], color: (SRC_META[i] || [, , "#888"])[2], i, wh: x.wh, avg: x.avg_w}; }),
        ...(c.shore ? [{label: "Shore (AC in)", color: "#0b62c4", i: 4, wh: c.shore.wh, avg: c.shore.avg_w}] : [])])}</div>
      <div class="ebars"><h4>DC consumers</h4>${bars(c.consumers.map(x => { const i = LOAD_META.findIndex(m => m[0] === x.key); return {label: (LOAD_META[i] || [, x.key])[1], color: (LOAD_META[i] || [, , "#888"])[2], i, wh: x.wh, avg: x.avg_w}; }))}</div>
      <div class="ebars"><h4>Batteries</h4>${(c.batteries || []).map((x, i) => `<div class="ebar"><span class="el">${esc(x.key[0] + x.key.slice(1).toLowerCase())}</span><span class="ev" style="flex:1;text-align:left">charged ${(x.charge_wh / 1000).toFixed(2)} kWh · discharged ${(x.discharge_wh / 1000).toFixed(2)} kWh</span></div>`).join("")}</div>
      <p class="hint" style="margin:6px 0 0">${D.dayTime(Date.parse(c.start))} – ${D.dayTime(Date.parse(c.end))} · from the full-resolution history on the server${c.sources_covered_seconds != null && c.span_seconds ? ` · data for ${Math.round(c.sources_covered_seconds / c.span_seconds * 100)} % of the time` : ""}</p>`;
  }
  window.addEventListener("resize", () => { if (view === "history" && D.visibleIs("power")) renderCharts(); });
  window.addEventListener("drifter-theme", () => { if (view === "history") renderCharts(); });

  function renderHistory() {
    const box = $("eHist"), r = report || {}, h = hstat || {}, MB = v => v == null ? "–" : v >= 1e9 ? (v / 1e9).toFixed(2) + " GB" : (v / 1e6).toFixed(0) + " MB";
    if (!box.dataset.built) {
      box.dataset.built = "1";
      box.innerHTML = `<div class="seg" id="eRange" style="max-width:460px;margin-bottom:12px">${RANGES.map(([h, l]) => `<button type="button" data-hours="${h}" aria-pressed="${h === hours}">${l}</button>`).join("")}</div>
        <div class="grid g2 charts" id="eCharts"></div>
        <h2 class="sec">Energy in this period</h2><div class="card pad" id="eContrib"></div>
        <h2 class="sec">Reports and data</h2>
        <div class="grid g2l"><div class="stack">
          <div class="card"><div class="hd">${icon("batt")}<h3>Battery health report</h3></div><div class="rows">
            <div class="row"><div class="k"><small>Analyses the stored battery history: cell connection resistance, current sharing, alarms, cell balance, balancers and usage. Runs in a separate low-priority process on the boat PC.</small></div></div>
            <div class="row"><span class="k">Days to analyse</span><div style="display:flex;gap:8px;align-items:center"><label class="numf"><input class="field" type="number" id="eRepDays" min="1" max="365" step="1" value="7" inputmode="numeric"><span class="u">days</span></label>
              <button class="btn sm" type="button" id="eRepRun">Run report</button></div></div>
            <div class="row" id="eRepStatus"></div></div>
            <div class="mdreport" id="eRepOut" hidden></div></div></div>
        <div class="stack"><div class="card"><div class="hd"><h3>History database</h3></div><div class="rows" id="eHStat"></div></div>
          <div class="card pad"><a class="btn sec" href="api/power/manual" target="_blank" rel="noopener">${icon("ext")} Open the manual</a>
            <p class="hint" style="margin:8px 0 0">The complete MasterVolt user manual, in a new window.</p></div></div></div>`;
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
    if (b.dataset.soc) return setSoc(b.dataset.soc, b);
    if (b.dataset.hours) { hours = +b.dataset.hours; chart = null; contrib = null; renderCharts(); D.poll(m, true); return; }
    if (b.id === "eRepRun") {
      const days = +$("eRepDays").value;
      if (!Number.isInteger(days) || days < 1 || days > 365) return D.toast("Days: a whole number from 1 to 365", true);
      return D.run(m, b, () => D.api("power", "/api/reports/battery-health", {days}), "Report started").catch(() => {});
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
  // SOC calibration writes the BMS's state of charge (the server queues it on the Bluetooth radio and reads it back).
  // Charge % / Discharge %: worked out by the BMS server from the cell voltages along the charging or discharging curve.
  async function setSoc(target, btn) {
    const who = target === "all" ? "all batteries" : `Battery ${target}`;
    const v = await D.sheet(`<h3 id="dlgTitle"><span class="warnicon">%</span>Set SOC – ${esc(who)}</h3><p>Choose the state of charge to write to ${esc(who)}. Cancel is selected by default.</p>
      <div class="btns eq" style="flex-direction:column;margin-top:10px"><button class="btn sec" data-value="charge">Set SOC – Charge % (from the cell voltages)</button>
      <button class="btn sec" data-value="discharge">Set SOC – Discharge % (from the cell voltages)</button><button class="btn sec" data-value="100">Set SOC 100%</button></div>
      <div class="row" style="border:0;padding:10px 0 0"><span class="k">Manual value</span><div style="display:flex;gap:6px;align-items:center"><label class="numf"><input class="field" id="socManual" type="number" min="0" max="100" step="0.1" inputmode="decimal"><span class="u">%</span></label>
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
})();
