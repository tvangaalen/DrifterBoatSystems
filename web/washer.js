// Washer module: VIOMI W1. Commands and the schedule run on the VIOMI controller; this page validates settings the
// same way as the controller's own page (program first, then temperature and rinses, then wait for the washer to
// report the requested values back).
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, hm, hms, icon} = D;
const PROGRAMS = [[0, "Golden Wash"], [16, "Antibacterial"], [4, "Spin"], [13, "Underwear"], [22, "Rinse + Spin"], [23, "Drum Clean"], [29, "Boil Wash"],
  [31, "Delicate"], [36, "New Clothes"], [37, "Socks"], [38, "Bra"], [39, "Towel Boil Wash"], [40, "Gloves"]];
const CAP = {
  0: {temperatures: [40], spin: 700, rinses: [2]}, 16: {temperatures: [60], spin: 700, rinses: [1, 2, 3, 4]},
  4: {temperatures: [0], spin: 700, rinses: [0]}, 13: {temperatures: [0, 30, 40, 60], spin: 700, rinses: [1, 2, 3, 4]},
  22: {temperatures: [0], spin: 700, rinses: [1, 2, 3, 4]}, 23: {temperatures: [80], spin: 700, rinses: [2]},
  29: {temperatures: [80], spin: 700, rinses: [1, 2, 3, 4]}, 31: {temperatures: [0, 30, 40], spin: 600, rinses: [1, 2, 3, 4]},
  36: {temperatures: [0, 30, 40], spin: 700, rinses: [1, 2, 3, 4]}, 37: {temperatures: [0, 30, 40, 60], spin: 700, rinses: [1, 2, 3, 4]},
  38: {temperatures: [0, 30, 40], spin: 400, rinses: [1, 2, 3, 4]}, 39: {temperatures: [80], spin: 700, rinses: [1, 2, 3, 4]},
  40: {temperatures: [0, 30, 40, 60], spin: 700, rinses: [1, 2, 3, 4]},
};
const ACTIVE = [7, 9, 11, 25], IDLE = [0, 1, 17, 26];
let pending = false, editing = false, lastGood = null, lastSeen = null, events = [], evT = 0, diag = null;

function display(d) {
  if (Number(d.fault) === 3) return {text: "Close the door", cls: "warn"};
  if (!d.power) return {text: "Off", cls: ""};
  const s = Number(d.status);
  const t = {0: "Ready", 1: "Ready", 4: "Delay", 7: "Washing", 9: "Rinsing", 11: "Spinning", 17: "Finished", 25: "Weighing", 26: "Paused", 27: "Fault"}[s] || `Status ${s}`;
  return {text: t, cls: [7, 9, 11, 25].includes(s) ? "ok" : s === 17 ? "ok" : s === 26 ? "warn" : s === 27 ? "bad" : ""};
}
const offline = () => m.state.err && !m.state.err.down && m.state.err.status === 503;   // controller up, washer not answering

const m = {
  id: "washer", title: "Washer", short: "Washer", icon: "washer", every: 5000, background: 10000,
  async load() {
    const d = await D.api("washer", "/api/status");
    if (!pending) { m.state.data = d; lastGood = d; lastSeen = Date.now(); }
    if (D.visibleIs("washer") && Date.now() - evT > 15000) {
      evT = Date.now();
      try { events = (await D.api("washer", "/diagnostics/export")).recent_events || []; } catch (e) {}
      try { diag = await D.api("washer", "/api/diagnostics"); } catch (e) {}
    }
  },
  badge() {
    const d = m.state.data; if (!d || m.state.err) return null;
    if (Number(d.fault) !== 0 || Number(d.status) === 27) return "bad";
    if (Number(d.status) === 17) return "warn";
    return null;
  },
  tile() {
    const d = m.state.data;
    if (offline() || !d) return `<div class="u-fs-22 big">Offline</div><div class="line">${lastSeen ? `Last seen ${hm(lastSeen)}` : esc(m.state.err ? m.state.err.message : "")}</div>`;
    const s = display(d), act = ACTIVE.includes(Number(d.status)) || Number(d.status) === 26, sc = d.schedule;
    return `<div class="u-fs-22 big">${esc(s.text)}${act && d.left_time != null ? ` <small>· ${d.left_time} min left</small>` : ""}</div>
      <div class="line">${esc(d.mode_text || "")}${sc && sc.status === "pending" ? ` · starts ${hm(sc.start_at)}` : ""}</div>
      <div class="minis"><div class="mini"><div class="l">Temperature</div><div class="n">${d.temperature == null ? "–" : d.temperature === 0 ? "Cold" : d.temperature + " °C"}</div></div>
      <div class="mini"><div class="l">Spin</div><div class="n">${d.spin ?? "–"}</div></div><div class="mini"><div class="l">Ready at</div><div class="n">${act && d.left_time != null ? hm(Date.now() + d.left_time * 60000) : "–"}</div></div></div>`;
  },
  mount(el) {
    el.innerHTML = `<div id="wDown"></div>
    <div class="grid g2">
      <div class="stack">
        <div class="hero" id="wHero"><div class="lamp"></div><div class="grow"><b id="wHeroT">Loading…</b><span id="wHeroS"></span></div>
          <label class="switch onoff"><input type="checkbox" role="switch" id="wPower" aria-label="Washer power"><i></i></label></div>
        <div class="card"><div class="hd"><h3>Select program</h3></div><div class="rows">
          <div class="row"><span class="k">Program</span><select class="u-maxw-62pc field" id="wProg">${PROGRAMS.map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join("")}</select></div>
          <div class="row"><span class="k">Temperature</span><select class="field" id="wTemp"></select></div>
          <div class="row"><span class="k">Rinses</span><select class="field" id="wRinse"></select></div>
          <div class="row"><span class="k">Spin <small>set by the program</small></span><span class="v" id="wSpin">–</span></div>
          <div class="row"><span class="hint" id="wSetMsg"></span><button class="btn" id="wSet" type="button">Set</button></div></div></div>
        <div class="card"><div class="hd"><h3>Active program</h3></div><div class="stats" id="wStats"></div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="hd"><h3>Schedule</h3></div><div class="rows">
          <div id="wSchedEdit"><div class="row"><select class="field" id="wSchedMode" aria-label="Schedule type"><option value="finish">Finish at</option><option value="start">Start at</option></select>
            <span class="u-d-flex u-ai-center u-gap-4"><select class="field" id="wSchedH" aria-label="Hour">${Array.from({length: 24}, (_, i) => `<option>${D.pad(i)}</option>`).join("")}</select>:<select class="field" id="wSchedM" aria-label="Minutes">${Array.from({length: 12}, (_, i) => `<option>${D.pad(i * 5)}</option>`).join("")}</select></span></div>
            <div class="row"><span class="hint">Uses the program set on the washer now. The washer must be on and idle.</span><button class="btn" id="wSched" type="button">Schedule</button></div></div>
          <div class="row" id="wSchedSum" hidden><span class="k" id="wSchedText"></span><button class="btn sec sm" id="wSchedCancel" type="button">Cancel</button></div></div></div>
        <div class="card pad"><div class="btns eq">
          <button class="btn" id="wStart" type="button">Start now</button><button class="btn sec" id="wPause" type="button">Pause</button></div>
          <p class="u-m-10-2-0 hint" id="wMsg"></p></div>
      </div>
    </div>
    <div class="u-h-12"></div>
    <div class="card"><div class="hd"><h3>Diagnostics</h3><span id="wDiagSum"></span>
          <button class="iconbtn" type="button" id="wRefresh" aria-label="Read the washer now">${icon("refresh")}</button></div>
          <div class="rows" id="wChecks"><div class="empty">Loading…</div></div>
          <div class="u-m-4-16-12 stats" id="wInfo"></div>
          <div class="u-p-0-16-14 btns"><button class="btn sec sm" id="wDiag" type="button">${icon("refresh")} Recheck</button>
            <a class="btn sec sm" href="api/washer/diagnostics/export" download="viomi_diagnostics.json">Export</a></div></div>
    <h2 class="sec">Events</h2>
    <div class="card"><div class="log" id="wLog"></div></div>`;
    const now = new Date(Date.now() + 10 * 60000); now.setMinutes(Math.ceil(now.getMinutes() / 5) * 5);
    $("wSchedH").value = D.pad(now.getHours()); $("wSchedM").value = D.pad(now.getMinutes());   // own 24-hour fields: <input type=time> follows the device (AM/PM)
    $("wProg").addEventListener("change", () => { editing = true; const c = CAP[+$("wProg").value]; fillCaps(+$("wProg").value, c.temperatures[0], c.rinses[0]); });
    $("wTemp").addEventListener("change", () => editing = true);
    $("wRinse").addEventListener("change", () => editing = true);
    $("wSet").addEventListener("click", applySettings);
    $("wStart").addEventListener("click", start);
    $("wPause").addEventListener("click", e => cmd(e.target, "/api/pause", "Paused"));
    $("wPower").addEventListener("change", async e => {
      const el = /** @type {HTMLInputElement} */ (e.target), want = el.checked;
      if (want) return cmd(el, "/api/power/on", "Power on", {}, false);
      const d = m.state.data, sc = d && d.schedule;
      if (sc && ["pending", "starting", "started", "running"].includes(sc.status) &&
        !(await D.confirm({title: "Power off the washer?", text: "This also cancels or interrupts the schedule.", ok: "Power off", cancel: "Keep on"}))) { el.checked = true; return; }
      cmd(el, "/api/power/off", "Power off", {}, false);
    });
    $("wSched").addEventListener("click", schedule);
    $("wSchedCancel").addEventListener("click", e => cmd(e.target, "/api/schedule/cancel", "Schedule cleared", {}));
    // Recheck re-reads the controller's config and re-creates the device connection (as the old diagnostics page did).
    $("wDiag").addEventListener("click", async e => {
      try { diag = await D.run(null, e.currentTarget, () => D.api("washer", "/api/diagnostics?recheck=1", undefined, {timeout: 45000}), r => r.summary); evT = 0; } catch (x) {}
      D.poll(m, true);
    });
    $("wRefresh").addEventListener("click", e => { evT = 0; D.run(m, e.currentTarget, async () => {}, null).catch(() => {}); });
  },
  render() {
    const down = m.state.err && !offline() ? D.downCard(m) : "";
    $("wDown").innerHTML = down ? down + '<div class="u-h-12"></div>' : "";
    const d = lastGood;
    if (offline() || !d) {
      $("wHero").className = "hero warn"; $("wHeroT").textContent = offline() ? "Washer offline" : "Not connected";
      $("wHeroS").textContent = offline() ? `${m.state.err.message}${lastSeen ? ` · last seen ${hm(lastSeen)}` : ""}` : "";
      for (const id of ["wStart", "wPause", "wPower", "wSet", "wSched", "wProg", "wTemp", "wRinse"]) $(id).disabled = true;
      renderEvents(); renderDiag(); if (!d) { $("wStats").innerHTML = ""; return; }
    } else {
      const s = display(d), st = Number(d.status);
      $("wHero").className = "hero " + s.cls; $("wHeroT").textContent = s.text + ([7, 9, 11, 25, 26].includes(st) && d.left_time != null ? ` · ${d.left_time} min left` : "");
      $("wHeroS").textContent = Number(d.fault) && Number(d.fault) !== 3 ? d.fault_text : `${d.mode_text}${d.locked ? " · door locked" : ""}`;
      actions(d);
    }
    $("wStats").innerHTML = [["Program", esc(d.mode_text || "–")], ["Temperature", d.temperature == null ? "–" : d.temperature === 0 ? "Cold" : `${d.temperature}<small>°C</small>`],
      ["Time left", d.left_time == null ? "–" : `${d.left_time}<small>min</small>`], ["Spin", d.spin == null ? "–" : `${d.spin}<small>rpm</small>`]]
      .map(([l, n]) => `<div class="stat"><div class="l">${l}</div><div class="n">${n}</div></div>`).join("");
    $("wSpin").textContent = d.spin == null ? "–" : `${d.spin} rpm`;
    if (!editing && !pending) { $("wProg").value = d.mode; fillCaps(d.mode, d.temperature, d.rinses); }
    renderSchedule(d.schedule);
    renderEvents(); renderDiag();
  },
};

function fillCaps(program, temperature, rinses) {
  const c = CAP[Number(program)]; if (!c) return;
  const fill = (el, vals, cur, fmt) => { el.innerHTML = vals.map(v => `<option value="${v}">${fmt(v)}</option>`).join(""); el.value = vals.includes(Number(cur)) ? cur : vals[0]; };
  fill($("wTemp"), c.temperatures, temperature, v => v === 0 ? "Cold" : `${v} °C`);
  fill($("wRinse"), c.rinses, rinses, v => v === 0 ? "None" : String(v));
}
function actions(d) {
  const st = Number(d.status), power = d.power === true, active = ACTIVE.includes(st), paused = st === 26, door = Number(d.fault) === 3;
  const faulted = (st === 27 || Number(d.fault) !== 0) && !door, conf = power && !door && IDLE.includes(st);
  const startOk = power && (door || IDLE.includes(st)), sc = d.schedule, hasSched = sc && ["pending", "starting", "started", "running"].includes(sc.status);
  $("wStart").textContent = paused ? "Resume" : "Start now";
  $("wSet").disabled = pending || !conf || active || faulted;
  $("wStart").disabled = pending || !startOk || active || faulted;
  $("wPause").disabled = pending || !active;
  const pw = /** @type {HTMLInputElement} */ ($("wPower"));
  if (!pending) pw.checked = power;
  pw.disabled = pending || (power && active && !door);       // no power off in the middle of a wash (as the old Power off button)
  $("wSched").disabled = pending || !conf || active || faulted || hasSched;
  $("wProg").disabled = !conf;
  const c = CAP[+$("wProg").value] || {temperatures: [], rinses: []};
  $("wTemp").disabled = !conf || c.temperatures.length < 2; $("wRinse").disabled = !conf || c.rinses.length < 2;
}
function renderSchedule(sc) {
  const edit = $("wSchedEdit"), sum = $("wSchedSum"), txt = $("wSchedText"), btn = $("wSchedCancel");
  if (!sc || sc.status === "cancelled") { edit.hidden = false; sum.hidden = true; return; }
  sum.hidden = false; btn.hidden = false; btn.textContent = "Cancel";
  const t = {pending: `Starts ${hm(sc.start_at)} · finishes ~${hm(sc.finish_at)}`, starting: "Starting scheduled program…", started: "Start sent · waiting for washer",
    running: `Running · planned finish ~${hm(sc.finish_at)}`, finished: `Finished · planned ~${hm(sc.finish_at)} · actual ${hm(sc.actual_finish_at)}`,
    missed: `Missed schedule · ${sc.last_error || ""}`, failed: `Schedule failed · ${sc.last_error || ""}`, interrupted: `Schedule interrupted · ${sc.last_error || ""}`}[sc.status] || String(sc.status);
  txt.innerHTML = `<b>${esc(sc.program_name || "")}</b><small>${esc(t)}</small>`;
  edit.hidden = !["interrupted", "finished", "missed", "failed"].includes(sc.status);
  if (["started", "running"].includes(sc.status)) btn.hidden = true;
  if (["interrupted", "finished", "missed", "failed"].includes(sc.status)) btn.textContent = "Clear";
}
function renderDiag() {
  if (!diag) { $("wChecks").innerHTML = `<div class="empty">${m.state.err && !offline() ? "Controller not reachable" : "Loading…"}</div>`; return; }
  $("wDiagSum").innerHTML = `<span class="badge ${diag.summary_class === "ok" ? "ok" : diag.summary_class === "warn" ? "warn" : "bad"}">${esc(diag.summary)}</span>`;
  const row = c => `<div class="row"><div class="k"><b>${c.ok ? '<span class="good">✓</span>' : c.severity === "warning" ? '<span class="warnc">!</span>' : '<span class="badc">×</span>'} ${esc(c.name)}</b>
    <small>${esc(c.detail)}</small></div></div>`;
  const checks = diag.checks || [], ok = checks.filter(c => c.ok), open = $("wChecks").querySelector("details[open]") != null;
  $("wChecks").innerHTML = checks.filter(c => !c.ok).map(row).join("") +   // problems first and always visible; passed checks folded
    (ok.length ? `<details class="row col" ${open ? "open" : ""}><summary class="u-cur-pointer u-minh-28 k"><span class="good">✓</span> ${ok.length} checks OK</summary>${ok.map(row).join("")}</details>` : "");
  $("wInfo").innerHTML = [["Controller", diag.controller_version], ["Uptime", diag.uptime], ["Washer", diag.washer_ip], ["PC", diag.pc_ip], ["Model", diag.model || "unknown"], ["Firmware", diag.firmware || "unknown"]]
    .map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="u-c-fg u-fwt-600 u-fs-14 s">${esc(v ?? "–")}</div></div>`).join("");
}
function renderEvents() {
  $("wLog").innerHTML = events.length ? events.map(e => `<div class="${/FAIL|BLOCKED|OFFLINE/.test(e.event + e.detail) ? "bad" : ""}"><time>${esc(e.time)}</time>
    <span class="msg"><b>${esc(e.event)}</b>${e.detail ? " · " + esc(e.detail) : ""}${e.duration_ms != null ? ` <span class="faint">${e.duration_ms} ms</span>` : ""}</span></div>`).join("")
    : `<div class="empty">No events yet</div>`;
}
function msg(t, bad) { $("wMsg").textContent = t; $("wMsg").className = "hint" + (bad ? " badc" : ""); }
async function cmd(el, path, ok, body = {}, say = true) {   // say: report in the Start/Pause card (not for power: the header shows it)
  if (pending) return; pending = true; if (say) msg("Sending command…");
  try { await D.run(null, el, () => D.api("washer", path, body), ok); if (say) msg(ok + "."); } catch (e) { if (say) msg("Error: " + e.message, true); }
  finally { setTimeout(async () => { pending = false; await D.poll(m, true); }, 700); }
}
async function start(e) {
  if (pending) return; pending = true; msg("Starting…");
  try {
    await D.api("washer", "/api/start", {});
    try { const sd = await D.api("washer", "/api/start-check"); m.state.data = lastGood = sd;
      msg(Number(sd.fault) === 3 ? "Close the door, then press Start now." : "Started."); } catch (x) { msg("Start sent."); }
  } catch (x) { msg("Error: " + x.message, true); D.toast(x.message, true); }
  finally { pending = false; D.poll(m, true); }
}
async function applySettings() {
  const program = +$("wProg").value, temperature = +$("wTemp").value, rinses = +$("wRinse").value, c = CAP[program];
  if (!c || !c.temperatures.includes(temperature) || !c.rinses.includes(rinses)) { $("wSetMsg").textContent = "Invalid settings for this program."; return; }
  pending = true; editing = false; $("wSet").disabled = true; $("wSet").textContent = "…"; $("wSetMsg").textContent = "Applying settings…";
  try {
    await D.api("washer", `/api/program/${program}`, {});            // program first: it reloads the washer's default profile
    await new Promise(r => setTimeout(r, 800));
    if (c.temperatures.length > 1) await D.api("washer", `/api/temperature/${temperature}`, {});
    if (c.rinses.length > 1) await D.api("washer", `/api/rinses/${rinses}`, {});
    $("wSetMsg").textContent = "Waiting for the washer to confirm…";
    const until = Date.now() + 10000; let ok = false, last = null;
    while (Date.now() < until && !ok) {
      try { last = await D.api("washer", "/api/status");
        ok = +last.mode === program && +last.temperature === temperature && +last.rinses === rinses && +last.spin === c.spin; } catch (e) {}
      if (!ok) await new Promise(r => setTimeout(r, 500));
    }
    if (!ok) throw new Error("Washer did not confirm the requested settings");
    m.state.data = lastGood = last; $("wSetMsg").textContent = "Settings applied."; D.toast("Settings applied");
  } catch (e) { $("wSetMsg").textContent = "Update failed: " + e.message; D.toast(e.message, true); }
  finally { pending = false; $("wSet").textContent = "Set"; D.poll(m, true); }
}
async function schedule(e) {
  const v = `${$("wSchedH").value}:${$("wSchedM").value}`;
  if (!/^\d\d:\d\d$/.test(v)) { msg("Choose a time", true); return; }
  const mode = $("wSchedMode").value;
  if (pending) return; pending = true;
  try { const r = await D.run(null, e.target, () => D.api("washer", "/api/schedule", {mode, time: v}));
    D.toast(`Scheduled: starts ${hm(r.schedule.start_at)}, finishes ~${hm(r.schedule.finish_at)}`); }
  catch (x) { msg("Schedule failed: " + x.message, true); }
  finally { pending = false; D.poll(m, true); }
}
D.register(m);
