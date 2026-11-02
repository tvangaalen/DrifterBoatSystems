// Drifter Boat Systems — app core: modules, routing, polling, themes, dialogs and the overview page.
// The page only displays and sends commands; every decision (Float, anchor alarm, arming, washer schedule) is made
// by the module's own server. Times are always 24-hour.
"use strict";
const Drifter = (() => {
  const $ = id => document.getElementById(id);
  const pad = n => String(n).padStart(2, "0");
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const toDate = t => t instanceof Date ? t : new Date(typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : t);
  const hm = t => { if (t == null) return "–"; const d = toDate(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const hms = t => { if (t == null) return "–"; const d = toDate(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
  const day = t => { const d = toDate(t); return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`; };
  const dayTime = t => { if (t == null) return "–"; const d = toDate(t), now = new Date();
    return d.toDateString() === now.toDateString() ? hm(d) : `${pad(d.getDate())}-${pad(d.getMonth() + 1)} ${hm(d)}`; };
  const dur = s => { if (s == null || !isFinite(s)) return "–"; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
    return h ? `${h} h ${pad(m)} min` : m ? `${m} min${r && m < 10 ? ` ${r} s` : ""}` : `${r} s`; };
  const ago = t => t == null ? "–" : dur(Date.now() / 1000 - (t > 1e12 ? t / 1000 : t)) + " ago";
  const num = (v, d = 0) => v == null || v === "" || !isFinite(+v) ? "–" : (+v).toFixed(d);
  const W = v => { if (v == null || !isFinite(+v)) return "–"; v = +v; return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(2)} kW` : `${Math.round(v)} W`; };
  const icon = (id, cls = "i") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;

  // ---------------------------------------------------------------- API
  class ApiError extends Error { constructor(msg, status, down) { super(msg); this.status = status; this.down = down; } }
  async function api(module, path, body, opts = {}) {
    const init = body === undefined ? {cache: "no-store"} :
      {method: "POST", headers: {"Content-Type": "application/json", "X-Drifter-Request": "1"}, body: JSON.stringify(body)};
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), opts.timeout || (body === undefined ? 15000 : 95000));
    init.signal = ctl.signal;
    let r;
    try { r = await fetch(`api/${module}${path}`, init); }
    catch (e) { throw new ApiError(e.name === "AbortError" ? "No answer (timed out)" : "Drifter server not reachable", 0, true); }
    finally { clearTimeout(timer); }
    let j = null; try { j = await r.json(); } catch (e) {}
    if (!r.ok || (j && j.ok === false)) {
      const d = j && (j.detail ?? j.error);
      throw new ApiError(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${r.status}`, r.status, !!(j && j.upstream_down));
    }
    return j;
  }

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
    document.querySelector('meta[name="theme-color"]').content = bg || "#0c1014";
    const ic = t === "night" ? "moon" : t === "dark" ? "moon" : "sun";
    $("themeBtn").innerHTML = icon(ic);
    window.dispatchEvent(new CustomEvent("drifter-theme", {detail: t}));
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTheme(getTheme()));
  const themeSeg = () => `<div class="seg" role="group" aria-label="Theme">${THEMES.map(([k, l]) => `<button type="button" data-theme-btn="${k}" aria-pressed="${getTheme() === k}">${l}</button>`).join("")}</div>`;
  document.addEventListener("click", e => { const b = e.target.closest("[data-theme-btn]"); if (b) setTheme(b.dataset.themeBtn); });
  $("themeBtn").addEventListener("click", () => sheet(`<h3 id="dlgTitle">Display</h3><p>Auto follows the iPhone or iPad (light or dark). Night is dim red on black, to keep your night vision.</p>
    <div style="margin-top:14px">${themeSeg()}</div><div class="acts"><button class="btn" data-close>Done</button></div>`));

  // ---------------------------------------------------------------- dialogs & toast
  let dlgResolve = null, lastFocus = null;
  function sheet(html, focusSel) {
    return new Promise(res => {
      if (dlgResolve) dlgResolve(null);
      dlgResolve = res; lastFocus = document.activeElement;
      delete $("dlgSheet").dataset.lock; $("dlgSheet").innerHTML = html; $("dialog").classList.add("open"); $("dialog").setAttribute("aria-hidden", "false");
      requestAnimationFrame(() => { const f = $("dlgSheet").querySelector(focusSel || "[data-default]") || $("dlgSheet").querySelector("button"); f && f.focus(); });
    });
  }
  function closeSheet(v) {
    $("dialog").classList.remove("open"); $("dialog").setAttribute("aria-hidden", "true");
    const r = dlgResolve; dlgResolve = null; if (r) r(v); if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $("dialog").addEventListener("click", e => {
    if (e.target === $("dialog")) return $("dlgSheet").dataset.lock ? null : closeSheet(null);   // tap outside = the safe choice (cancel)
    const b = e.target.closest("[data-close],[data-value]"); if (b) closeSheet(b.dataset.value ?? null);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && dlgResolve && !$("dlgSheet").dataset.lock) closeSheet(null); });
  // confirm(): the safe answer is the default button, Escape and tapping outside also choose it.
  async function confirm({title, text, note, items, ok = "OK", cancel = "Cancel", danger = false, safeDefault = true}) {
    const v = await sheet(`<h3 id="dlgTitle">${danger ? '<span class="warnicon">!</span>' : ""}${esc(title)}</h3>
      ${text ? `<p style="color:var(--fg)">${esc(text)}</p>` : ""}${items ? `<ul>${items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}${note ? `<p>${esc(note)}</p>` : ""}
      <div class="acts"><button class="btn ${danger ? "danger" : ""}" data-value="ok" ${safeDefault ? "" : "data-default"}>${esc(ok)}</button>
      <button class="btn sec" data-value="cancel" ${safeDefault ? "data-default" : ""}>${esc(cancel)}</button></div>`);
    return v === "ok";
  }
  let toastT = null;
  function toast(msg, bad) {
    const t = $("toast"); t.textContent = msg; t.className = "toast on" + (bad ? " bad" : "");
    clearTimeout(toastT); toastT = setTimeout(() => t.className = "toast" + (bad ? " bad" : ""), bad ? 6000 : 2600);
  }
  // Runs a command: busy state on the control, toast with the result, then a fresh read from the server.
  async function run(m, el, fn, okMsg) {
    if (el) { el.disabled = true; el.classList && el.classList.add("busy"); }
    try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
    catch (e) { toast(e.message || String(e), true); throw e; }
    finally { if (el) { el.disabled = false; el.classList && el.classList.remove("busy"); } if (m) poll(m, true); }
  }

  // ---------------------------------------------------------------- shared fragments
  function downCard(m) {
    const e = m.state.err; if (!e) return "";
    return `<div class="down">${icon("alert")}<div><b>${esc(m.title)} not reachable</b><span>${esc(e.message)}${m.state.data ? ` · showing data from ${hms(m.state.t)}` : ""}</span></div></div>`;
  }
  const sw = (id, on, attrs = "") => `<label class="switch"><input type="checkbox" role="switch" id="${id}" ${on ? "checked" : ""} ${attrs}><i></i></label>`;

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
    return {running: `<span class="badge ok">running${s.uptime_s != null ? " · " + dur(s.uptime_s) : ""}</span>`, starting: `<span class="badge warn">starting…</span>`,
      down: `<span class="badge bad">not running</span>`, failed: `<span class="badge bad">failed · next try in ${dur(s.next_try_in)}</span>`,
      held: `<span class="badge warn">on hold (being moved)</span>`}[s.state] || `<span class="badge">${esc(s.state)}</span>`;
  }
  async function renderSystem(el) {
    el.innerHTML = `<h2 class="sec">Display</h2><div class="card pad">${themeSeg()}<p class="hint" style="margin:10px 2px 0">Auto follows the device (light or dark). Night is dim red on black, to keep your night vision. Remembered on this device.</p></div>
      <h2 class="sec">Systems</h2><div class="card"><div class="rows" id="sysRows"><div class="empty">Loading…</div></div></div>
      <div id="sysEvWrap" hidden><h2 class="sec">Supervisor events</h2><div class="card"><div class="log" id="sysEvents"></div></div></div>
      <div id="sysOffWrap" hidden><h2 class="sec">Switch off</h2><div class="card pad"><p class="hint" style="margin:0 0 12px">Stops every system's server and this app's server on the boat PC. Switches, chargers and the camera stay as they are. Start everything again with the <b>Drifter Boat Systems</b> icon on the boat PC's desktop.</p>
        <button class="btn danger" type="button" id="sysOff">${icon("off")} Switch all systems off</button></div></div>
      <h2 class="sec">Install on iPhone or iPad</h2><div class="card pad"><p class="hint" style="margin:0">Open this page in Safari → Share → <b>Add to Home Screen</b>. It then opens full screen like an app. The phone or tablet must trust the boat's local certificate (the same one used for Energy, Anchor watch and BoatGuard).</p></div>
      <p class="hint" style="text-align:center;margin:18px 0" id="sysVer"></p>`;
    el.onclick = e => { const b = e.target.closest("[data-restart]"); if (b) restartModule(b.dataset.restart, b); if (e.target.closest("#sysOff")) switchAllOff(e.target.closest("#sysOff")); };
    el.onchange = e => { const c = e.target.closest("[data-console]"); if (c) setConsole(c.dataset.console, c.checked, c); };
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
          <button class="btn sec sm" type="button" data-restart="${name}" ${s.busy || s.held || s.state === "starting" ? "disabled" : ""}>${icon("refresh")} Restart</button></div>` : ""}
        ${s && s.console ? `<div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><span class="hint">Console window on the boat PC${s.console.window === false && s.state === "running" ? " (no window found)" : ""}</span>
          ${sw(`con-${name}`, s.console.show, `data-console="${name}" aria-label="${esc(m.title)} console window"`)}</div>` : ""}</div>`;
    }).join("") + (sup ? "" : `<div class="row"><span class="hint">The supervisor is off: servers are not restarted automatically.</span></div>`);
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

  async function setConsole(name, show, el) {
    try { await run(null, el, () => sysPost("api/supervisor/console", {module: name, show}), show ? "Console window shown on the boat PC" : "Console window hidden"); }
    catch (e) { el.checked = !show; }
    refreshSystem();
  }
  const sysPost = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-Drifter-Request": "1"}, body: JSON.stringify(body)})
    .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`); return j; });

  // Switch all systems off: what stops is listed in the confirmation, whose default is "Leave on". The server refuses
  // (with the reason) while a BMS control runs, Float is latched or the anchor watch has an alarm. Then every module
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
    if (!(await confirm({title: "Switch all systems off?", items, note: "Start everything again with the Drifter Boat Systems icon on the boat PC. Refused while a BMS control runs, Float is latched or the anchor watch has an alarm.",
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

  return {register, start, api, poll, run, confirm, sheet, closeSheet, toast, page, setSubtitle, downCard, sw, visibleIs, byId,
          $, esc, pad, hm, hms, day, dayTime, dur, ago, num, W, icon, getTheme};
})();
