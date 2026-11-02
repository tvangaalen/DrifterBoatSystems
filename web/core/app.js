// Drifter Boat Systems — app core: modules, routing, polling, themes, the overview and the system page.
// The page only displays and sends commands; every decision (Float, anchor alarm, arming, washer schedule) is made
// by the module's own server. Times are always 24-hour.
import {$, esc, pad, hm, hms, day, dayTime, dur, ago, num, W, icon} from "./format.js";
import {api} from "./api.js";
import {sheet, closeSheet, confirm, toast} from "./dialogs.js";
import {downCard, sw} from "./ui.js";

// ---------------------------------------------------------------- modules & polling
const mods = [], byId = {};
let current = null, started = false;
function register(m) {
  m.state = {data: null, err: null, t: 0, loading: false}; mods.push(m); byId[m.id] = m;
  m.timer = null; m.el = null;
}
function visibleIs(id) { return current === id; }
function rate(m) {
  if (document.hidden) return null;
  if (current === m.id) return m.every || 5000;
  if (current === "overview" || m.always) return m.background || 6000;
  return 30000;                                 // keeps the nav badges current
}
async function poll(m, force) {
  clearTimeout(m.timer); m.timer = null;
  if (!m.load || switchedOff) return;
  if (!m.state.loading || force) {
    m.state.loading = true;
    try { await m.load(); m.state.err = null; }
    catch (e) { m.state.err = e; }
    finally { m.state.loading = false; m.state.t = Date.now(); }
    paint(m);
  }
  const ms = rate(m); if (ms) m.timer = setTimeout(() => poll(m), ms);
}
function paint(m) {
  if (m.el && current === m.id && m.render) { try { m.render(); } catch (e) { console.error(m.id, e); } }
  if (current === "overview") renderOverview();
  renderBadges(); renderAlarm();
}
function reschedule() { for (const m of mods) { if (!m.timer && !m.state.loading) poll(m); } }
document.addEventListener("visibilitychange", () => {
  if (document.hidden) mods.forEach(m => { clearTimeout(m.timer); m.timer = null; });
  else mods.forEach(m => poll(m, false));
});

// ---------------------------------------------------------------- router
const pages = {};
function page(id) {
  if (!pages[id]) { const el = document.createElement("section"); el.dataset.page = id; el.hidden = true; $("pages").appendChild(el); pages[id] = el; }
  return pages[id];
}
function go() {
  let id = (location.hash || "#overview").slice(1).split("/")[0];
  if (id !== "overview" && id !== "system" && !byId[id]) id = "overview";
  const prev = current; current = id;
  const el = page(id);
  for (const k in pages) pages[k].hidden = k !== id;
  if (id === "overview") { $("title").firstChild.textContent = "Overview"; renderOverview(); }
  else if (id === "system") { $("title").firstChild.textContent = "System"; renderSystem(el); }
  else {
    const m = byId[id]; $("title").firstChild.textContent = m.title;
    if (!m.el) { m.el = el; m.mount(el); }
    paint(m);
  }
  $("subtitle").textContent = "";
  document.querySelectorAll("a[data-page]").forEach(a => a.dataset.page === id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  if (prev !== id) { window.scrollTo(0, 0); mods.forEach(m => { clearTimeout(m.timer); m.timer = null; }); mods.forEach(m => poll(m, false)); }
}
function setSubtitle(text) { $("subtitle").textContent = text || ""; }

function buildNav() {
  const items = [{id: "overview", title: "Overview", short: "Overview", icon: "home"}, ...mods.map(m => ({id: m.id, title: m.title, short: m.short || m.title, icon: m.icon}))];
  $("sideNav").innerHTML = items.map(i => `<a href="#${i.id}" data-page="${i.id}">${icon(i.icon)}<span>${esc(i.title)}</span><i class="dotbadge" data-badge="${i.id}"></i></a>`).join("");
  $("tabbar").innerHTML = items.map(i => `<a href="#${i.id}" data-page="${i.id}">${icon(i.icon)}<span>${esc(i.short)}</span><i class="dotbadge" data-badge="${i.id}"></i></a>`).join("");
}
function renderBadges() {
  for (const m of mods) {
    const b = m.badge ? m.badge() : null;
    document.querySelectorAll(`[data-badge="${m.id}"]`).forEach(el => { el.className = "dotbadge" + (b ? " on" : "") + (b === "warn" ? " warn" : ""); });
  }
}

// ---------------------------------------------------------------- global anchor alarm (shown on every page)
function renderAlarm() {
  const a = byId.anchor, bar = $("alarmbar"), s = a && a.state.data;
  const alarms = (s && s.alarms) || [];
  if (a && a.alarmState && a.alarmState() === "unreachable") {        // anchor set, but the watch does not answer
    bar.classList.add("on"); bar.classList.remove("silenced");
    $("alarmTitle").textContent = "Anchor watch not reachable"; $("alarmSub").textContent = a.state.err ? a.state.err.message : "";
    $("alarmSilence").textContent = "Open"; return;
  }
  if (!alarms.length) { bar.classList.remove("on"); return; }
  const silenced = s.silenced_until && s.silenced_until * 1000 > Date.now();
  bar.classList.add("on"); bar.classList.toggle("silenced", !!silenced);
  $("alarmTitle").textContent = alarms.map(x => x.text).join(" · ");
  $("alarmSub").textContent = silenced ? `Silenced until ${hm(s.silenced_until)}` : (alarms[0].detail || `since ${hms(alarms[0].since)}`);
  $("alarmSilence").textContent = silenced ? "Open" : "Silence 5 min";
}
$("alarmSilence").addEventListener("click", async () => {
  const s = byId.anchor && byId.anchor.state.data;
  const a = byId.anchor;
  if ((s && s.silenced_until && s.silenced_until * 1000 > Date.now()) || (a.alarmState && a.alarmState() === "unreachable")) { location.hash = "#anchor"; return; }
  try { await api("anchor", "/api/command", {action: "silence", minutes: 5}); toast("Alarm silenced for 5 min"); }
  catch (e) { toast(e.message, true); }
  poll(byId.anchor, true);
});

// ---------------------------------------------------------------- themes
const THEMES = [["auto", "Auto"], ["light", "Light"], ["dark", "Dark"], ["night", "Night"]];
function getTheme() { try { return localStorage.getItem("drifter-theme") || "auto"; } catch (e) { return "auto"; } }
function setTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { t === "auto" ? localStorage.removeItem("drifter-theme") : localStorage.setItem("drifter-theme", t); } catch (e) {}
  document.querySelectorAll("[data-theme-btn]").forEach(b => b.setAttribute("aria-pressed", b.dataset.themeBtn === t));
  const bg = getComputedStyle(document.body).getPropertyValue("--bg").trim();
  /** @type {HTMLMetaElement} */ (document.querySelector('meta[name="theme-color"]')).content = bg || "#0c1014";
  const ic = t === "night" ? "moon" : t === "dark" ? "moon" : "sun";
  $("themeBtn").innerHTML = icon(ic);
  window.dispatchEvent(new CustomEvent("drifter-theme", {detail: t}));
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTheme(getTheme()));
const themeSeg = () => `<div class="seg" role="group" aria-label="Theme">${THEMES.map(([k, l]) => `<button type="button" data-theme-btn="${k}" aria-pressed="${getTheme() === k}">${l}</button>`).join("")}</div>`;
document.addEventListener("click", e => { const b = e.target.closest("[data-theme-btn]"); if (b) setTheme(b.dataset.themeBtn); });
$("themeBtn").addEventListener("click", () => sheet(`<h3 id="dlgTitle">Display</h3><p>Auto follows the iPhone or iPad (light or dark). Night is dim red on black, to keep your night vision.</p>
  <div style="margin-top:14px">${themeSeg()}</div><div class="acts"><button class="btn" data-close>Done</button></div>`));

// Runs a command: busy state on the control, toast with the result, then a fresh read from the server.
async function run(m, el, fn, okMsg) {
  if (el) { el.disabled = true; el.classList && el.classList.add("busy"); }
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
  catch (e) { toast(e.message || String(e), true); throw e; }
  finally { if (el) { el.disabled = false; el.classList && el.classList.remove("busy"); } if (m) poll(m, true); }
}

// ---------------------------------------------------------------- overview
function renderOverview() {
  const el = page("overview");
  if (!el.dataset.built) {
    el.dataset.built = "1";
    el.innerHTML = `<div class="grid g2" id="ovTiles"></div>`;
  }
  $("ovTiles").innerHTML = mods.map(m => {
    let body = `<div class="line muted">Loading…</div>`;
    try { if (m.tile && (m.state.data || m.state.err)) body = m.tile(); } catch (e) { body = `<div class="err">${esc(e.message)}</div>`; }
    const b = m.badge ? m.badge() : null;
    return `<a class="card tile" href="#${m.id}"><div class="th"><span class="ic">${icon(m.icon)}</span><h3>${esc(m.title)}</h3>
      ${m.state.err ? '<span class="badge warn">offline</span>' : b === "bad" ? '<span class="badge bad">alarm</span>' : b === "warn" ? '<span class="badge warn">check</span>' : ""}
      ${icon("chev", "i chev")}</div>${body}</a>`;
  }).join("");
  setSubtitle(new Intl.DateTimeFormat("en-GB", {weekday: "long", day: "numeric", month: "long"}).format(new Date()));
}

// ---------------------------------------------------------------- system page
// The supervisor (drifter.py) keeps the servers running; restarting one is the user's call, with a confirmation that
// says what pauses. The server refuses (with the reason) while MasterVolt runs a BMS control or Float is latched, or
// while the anchor watch has an alarm.
let sysInfo = null, sysTimer = null, switchedOff = false;
const SUP_NAME = {power: "energy"};                       // page module id -> supervisor module name
const RESTART_TEXT = {
  energy: ["Float protection and the BMS and balancer connections pause for about a minute.", "Refused while a BMS control runs or Float is latched."],
  anchor: ["The anchor watch pauses for about a minute; the anchor, settings and track are kept.", "Refused while an alarm is active."],
  guard: ["BoatGuard pauses for a few seconds; whether it armed the camera is kept.", ""],
  washer: ["The controller pauses for a few seconds; a running program carries on in the washer.", ""],
};
function supState(s) {
  if (!s) return "";
  if (s.busy === "shutdown") return s.state === "stopped" ? `<span class="badge">switched off</span>` : `<span class="badge warn">switching off…</span>`;
  if (s.busy) return `<span class="badge warn">restarting</span>`;
  if (s.state === "running" && s.health && s.health.ok === false)   // listening, but its health check gets no answer (display only)
    return `<span class="badge warn" title="${esc(s.health.detail || "")}">running · not answering since ${esc(hm(s.health.since))}</span>`;
  return {running: `<span class="badge ok">running${s.uptime_s != null ? " · " + dur(s.uptime_s) : ""}</span>`, starting: `<span class="badge warn">starting…</span>`,
    down: `<span class="badge bad">not running</span>`, failed: `<span class="badge bad">failed · next try in ${dur(s.next_try_in)}</span>`,
    held: `<span class="badge warn">on hold</span>`}[s.state] || `<span class="badge">${esc(s.state)}</span>`;
}
// The nightly back-up of the key files (drifterd runs tools/backup.py): the newest one, the next run, and a failed or missing one in red.
function backupRow(b) {
  const stale = !b.last || Date.now() / 1000 - b.last.t > 30 * 3600;
  const st = b.failed ? `<span class="badc">last run failed</span><small>see its log</small>`
    : b.running ? `<span class="badge warn">running…</span>`
    : b.last ? `<span class="${stale ? "badc" : "good"}">${esc(dayTime(b.last.t))}</span>` : `<span class="badc">none yet</span>`;
  return `<div class="row"><div class="k"><b>Back-up of the keys</b><span class="hint">Pushover, NFL, EZVIZ, washer · every night, ${esc(b.count)} kept in ${esc(b.dest)} · next ${esc(dayTime(b.next))}</span></div>
    <div class="v">${st}</div><span style="display:flex;gap:8px"><button class="btn sec sm" type="button" data-log="backup">Show log</button></span></div>`;
}
async function renderSystem(el) {
  el.innerHTML = `<h2 class="sec">Display</h2><div class="card pad">${themeSeg()}<p class="hint" style="margin:10px 2px 0">Auto follows the device (light or dark). Night is dim red on black, to keep your night vision. Remembered on this device.</p></div>
    <h2 class="sec">Systems</h2><div class="card"><div class="rows" id="sysRows"><div class="empty">Loading…</div></div></div>
    <div id="sysEvWrap" hidden><h2 class="sec">Supervisor events</h2><div class="card"><div class="log" id="sysEvents"></div></div></div>
    <div id="sysOffWrap" hidden><h2 class="sec">Switch off</h2><div class="card pad"><p class="hint" style="margin:0 0 12px">Stops every system's server and this app's server on the boat PC. Switches, chargers and the camera stay as they are. Start everything again with the <b>Drifter Boat Systems</b> icon on the boat PC's desktop.</p>
      <button class="btn danger" type="button" id="sysOff">${icon("off")} Switch all systems off</button></div></div>
    <h2 class="sec">Install on iPhone or iPad</h2><div class="card pad"><p class="hint" style="margin:0">Open this page in Safari → Share → <b>Add to Home Screen</b>. It then opens full screen like an app. The phone or tablet must trust the boat's local certificate (the same one used for Energy, Anchor watch and BoatGuard).</p></div>
    <p class="hint" style="text-align:center;margin:18px 0" id="sysVer"></p>`;
  el.onclick = e => {
    const b = e.target.closest("[data-restart]"); if (b) restartModule(b.dataset.restart, b);
    const l = e.target.closest("[data-log]");
    if (l) {   // a home-screen app has no tabs or back button: open the log in place there (it has its own "Back to Drifter")
      const standalone = navigator.standalone || matchMedia("(display-mode: standalone)").matches;
      if (standalone) location.href = `log.html#${l.dataset.log}`; else window.open(`log.html#${l.dataset.log}`, `drifter-log-${l.dataset.log}`);
    }
    if (e.target.closest("#sysOff")) switchAllOff(e.target.closest("#sysOff"));
  };
  await refreshSystem();
  clearInterval(sysTimer); sysTimer = setInterval(() => { if (current === "system" && !document.hidden) refreshSystem(); else if (current !== "system") clearInterval(sysTimer); }, 5000);
}
async function refreshSystem() {
  if (switchedOff) return;
  try { sysInfo = await (await fetch("api/systems", {cache: "no-store"})).json(); } catch (e) { sysInfo = null; }
  if (!$("sysRows")) return;
  const sup = sysInfo && sysInfo.supervisor && sysInfo.supervisor.enabled ? sysInfo.supervisor : null;
  $("sysRows").innerHTML = mods.map(m => {
    const u = sysInfo && sysInfo.upstream[m.id], c = sysInfo && sysInfo.systems[m.id] && sysInfo.systems[m.id].classic;
    const name = SUP_NAME[m.id] || m.id, s = sup && sup.modules[name];
    const st = m.state.err ? `<span class="badc">Not reachable</span><small>${esc(m.state.err.message)}</small>`
      : m.state.data ? `<span class="good">Connected</span><small>${u && u.ms != null ? `${u.ms} ms · ` : ""}${hms(m.state.t)}</small>` : "–";
    return `<div class="row col"><div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div class="k"><b>${esc(m.title)}</b>${c ? `<a href="${esc(c)}" target="_blank" rel="noopener" class="hint">Open classic page ↗</a>` : ""}</div><div class="v">${st}</div></div>
      ${s ? `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">${supState(s)}
        <span class="hint" style="flex:1;min-width:120px">${s.last_event ? `${esc(dayTime(s.last_event.t))} ${esc(s.last_event.text)}` : ""}</span>
        <span style="display:flex;gap:8px"><button class="btn sec sm" type="button" data-log="${name}">Show log</button>
        <button class="btn sec sm" type="button" data-restart="${name}" ${s.busy || s.held || s.state === "starting" ? "disabled" : ""}>${icon("refresh")} Restart</button></span></div>` : ""}</div>`;
  }).join("") + (sup && sup.error ? `<div class="row"><span class="badc">${esc(sup.error)}</span></div>` : "")
    + (sup ? `<div class="row"><div class="k"><b>Drifter</b><span class="hint">this app's server on the boat PC${sup.drifterd ? ` · service drifterd ${esc(sup.drifterd.version)}, running since ${esc(dayTime(sup.drifterd.started))}` : ""}</span></div>
        <span style="display:flex;gap:8px"><button class="btn sec sm" type="button" data-log="gateway">Show log</button>${sup.drifterd ? `<button class="btn sec sm" type="button" data-log="drifterd">Service log</button>` : ""}</span></div>`
      + (sup.backup ? backupRow(sup.backup) : "")
    : `<div class="row"><span class="hint">The supervisor is off: servers are not restarted automatically.</span></div>`);
  $("sysEvWrap").hidden = !sup || !sup.events.length;
  $("sysOffWrap").hidden = !sup; $("sysOff").disabled = !!(sup && sup.shutdown && sup.shutdown.state === "running");
  if (sup) $("sysEvents").innerHTML = sup.events.slice().reverse().slice(0, 30).map(e => `<div class="${e.kind === "bad" ? "bad" : e.kind === "warn" ? "warn" : ""}"><time>${esc(dayTime(e.t))}</time><span class="msg"><b>${esc(e.module)}</b> ${esc(e.text)}</span></div>`).join("");
  $("sysVer").textContent = `Drifter Boat Systems ${sysInfo ? "v" + sysInfo.version : ""}`;
}
async function restartModule(name, btn) {
  const m = mods.find(x => (SUP_NAME[x.id] || x.id) === name), [what, refused] = RESTART_TEXT[name] || ["", ""];
  if (!(await confirm({title: `Restart ${m ? m.title : name}?`, text: what, note: refused, ok: "Restart", cancel: "Cancel", danger: name === "energy" || name === "anchor"}))) return;
  try { await run(null, btn, () => fetch("api/supervisor/restart", {method: "POST", headers: {"Content-Type": "application/json", "X-Drifter-Request": "1"}, body: JSON.stringify({module: name})})
    .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`); return j; }), `Restarting ${m ? m.title : name}…`); }
  catch (e) {}
  refreshSystem();
}

const sysPost = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-Drifter-Request": "1"}, body: JSON.stringify(body)})
  .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`); return j; });

// Switch all systems off: what stops is listed in the confirmation, whose default is "Leave on". The server refuses
// (with the reason) while a BMS control runs or the anchor watch has an alarm (a latched Float is no reason). Then every module
// server stops and the gateway ends itself; the page stops polling and offers to close.
async function switchAllOff(btn) {
  const a = byId.anchor && byId.anchor.state.data, g = byId.guard && byId.guard.state.data, w = byId.washer && byId.washer.state.data;
  const sched = w && w.schedule && ["pending", "starting"].includes(w.schedule.status);
  const items = [
    "Energy: Float protection and the BMS and balancer connections stop. Inverter, chargers, alternator and Engine ECU stay as they are.",
    a && a.anchor ? "Anchor watch: the anchor is set. The anchor alarm and its push alerts stop." : "Anchor watch: stops (no anchor set).",
    g && g.enabled ? "BoatGuard: monitoring is on, but the camera is no longer armed or disarmed automatically." : "BoatGuard: stops.",
    sched ? "Washer: the scheduled start will not happen while the controller is off." : "Washer: the controller stops; a running program carries on in the washer.",
    "This app's server on the boat PC stops too.",
  ];
  if (!(await confirm({title: "Switch all systems off?", items, note: "Start everything again with the Drifter Boat Systems icon on the boat PC. Refused while a BMS control runs or the anchor watch has an alarm.",
    ok: "Switch off", cancel: "Leave on", danger: true}))) return;
  try { await run(null, btn, () => sysPost("api/supervisor/shutdown", {})); } catch (e) { return; }
  switchedOff = true; clearInterval(sysTimer); mods.forEach(m => { clearTimeout(m.timer); m.timer = null; });
  const total = mods.length, t0 = Date.now(); let last = null, fails = 0;
  sheet(`<h3 id="dlgTitle">Switching off…</h3><p id="offStep">Stopping the systems.</p>`); $("dlgSheet").dataset.lock = "1";
  while (true) {
    await new Promise(r => setTimeout(r, 1000));
    try { const j = await (await fetch("api/systems", {cache: "no-store"})).json(); last = j.supervisor && j.supervisor.shutdown; fails = 0; }
    catch (e) { fails++; }
    const done = last && last.state !== "running", gone = fails >= 3 && last && last.stopped.length >= last.total;
    if ($("offStep") && last) $("offStep").textContent = `${last.stopped.length} of ${last.total || total} stopped${last.stopped.length ? ": " + last.stopped.join(", ") : ""}.`;
    if (done || gone || Date.now() - t0 > 120000) break;
  }
  const failed = last && last.failed && Object.keys(last.failed);
  const msg = failed && failed.length ? `Not everything could be shut down (${failed.map(n => `${n}: ${last.failed[n]}`).join("; ")}). The others are off. Press OK to close the application.`
    : last && last.state === "done" || (last && last.stopped.length >= last.total) ? "All systems have been shut down. Press OK to close the application."
    : "Drifter no longer answers, so not every system could be confirmed off. Press OK to close the application.";
  await sheet(`<h3 id="dlgTitle">${failed && failed.length ? "Partly shut down" : "Shut down"}</h3><p style="color:var(--fg)">${esc(msg)}</p><div class="acts"><button class="btn" data-value="ok" data-default>OK</button></div>`);
  closeApp();
}
function closeApp() {
  try { window.close(); } catch (e) {}
  // Browsers only let a page close a window that a script opened; otherwise (and in a home-screen app) leave a quiet page.
  setTimeout(() => { document.title = "Drifter Boat Systems (off)";
    document.body.innerHTML = `<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;text-align:center;background:var(--bg);color:var(--fg)"><div><h2 style="margin:0 0 8px">Drifter is switched off</h2><p style="color:var(--muted);margin:0">You can close this tab or app now. Start the systems again with the Drifter Boat Systems icon on the boat PC.</p></div></div>`; }, 300);
}

function start() {
  if (started) return; started = true;
  buildNav(); setTheme(getTheme());
  window.addEventListener("hashchange", go);
  window.addEventListener("scroll", () => $("top").classList.toggle("scrolled", window.scrollY > 4), {passive: true});
  go();
  fetch("api/systems", {cache: "no-store"}).then(r => r.json()).then(j => { $("sideFoot").textContent = `v${j.version}`; }).catch(() => {});
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
}


// The API the page modules use (energy.js, anchor.js, guard.js, washer.js): `import Drifter from "./core/app.js"`.
const Drifter = {register, start, api, poll, run, confirm, sheet, closeSheet, toast, page, setSubtitle, downCard, sw, visibleIs, byId, $, esc, pad, hm, hms, day, dayTime, dur, ago, num, W, icon, getTheme};
export default Drifter;
