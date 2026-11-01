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
    if (!m.load) return;
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
    if (!alarms.length) { bar.classList.remove("on"); return; }
    const silenced = s.silenced_until && s.silenced_until * 1000 > Date.now();
    bar.classList.add("on"); bar.classList.toggle("silenced", !!silenced);
    $("alarmTitle").textContent = alarms.map(x => x.text).join(" · ");
    $("alarmSub").textContent = silenced ? `Silenced until ${hm(s.silenced_until)}` : (alarms[0].detail || `since ${hms(alarms[0].since)}`);
    $("alarmSilence").textContent = silenced ? "Open" : "Silence 5 min";
  }
  $("alarmSilence").addEventListener("click", async () => {
    const s = byId.anchor && byId.anchor.state.data;
    if (s && s.silenced_until && s.silenced_until * 1000 > Date.now()) { location.hash = "#anchor"; return; }
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
      $("dlgSheet").innerHTML = html; $("dialog").classList.add("open"); $("dialog").setAttribute("aria-hidden", "false");
      requestAnimationFrame(() => { const f = $("dlgSheet").querySelector(focusSel || "[data-default]") || $("dlgSheet").querySelector("button"); f && f.focus(); });
    });
  }
  function closeSheet(v) {
    $("dialog").classList.remove("open"); $("dialog").setAttribute("aria-hidden", "true");
    const r = dlgResolve; dlgResolve = null; if (r) r(v); if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $("dialog").addEventListener("click", e => {
    if (e.target === $("dialog")) return closeSheet(null);              // tap outside = the safe choice (cancel)
    const b = e.target.closest("[data-close],[data-value]"); if (b) closeSheet(b.dataset.value ?? null);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && dlgResolve) closeSheet(null); });
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
  let sysInfo = null;
  async function renderSystem(el) {
    el.innerHTML = `<h2 class="sec">Display</h2><div class="card pad">${themeSeg()}<p class="hint" style="margin:10px 2px 0">Auto follows the device (light or dark). Night is dim red on black, to keep your night vision. Remembered on this device.</p></div>
      <h2 class="sec">Systems</h2><div class="card"><div class="rows" id="sysRows"><div class="empty">Loading…</div></div></div>
      <h2 class="sec">Install on iPhone or iPad</h2><div class="card pad"><p class="hint" style="margin:0">Open this page in Safari → Share → <b>Add to Home Screen</b>. It then opens full screen like an app. The phone or tablet must trust the boat's local certificate (the same one used for Energy, Anchor watch and BoatGuard).</p></div>
      <p class="hint" style="text-align:center;margin:18px 0" id="sysVer"></p>`;
    try { sysInfo = await (await fetch("api/systems", {cache: "no-store"})).json(); } catch (e) { sysInfo = null; }
    const rows = mods.map(m => {
      const u = sysInfo && sysInfo.upstream[m.id], c = sysInfo && sysInfo.systems[m.id] && sysInfo.systems[m.id].classic;
      const st = m.state.err ? `<span class="badc">Not reachable</span><small>${esc(m.state.err.message)}</small>`
        : m.state.data ? `<span class="good">Connected</span><small>${u && u.ms != null ? `${u.ms} ms · ` : ""}${hms(m.state.t)}</small>` : "–";
      return `<div class="row"><div class="k"><b>${esc(m.title)}</b>${c ? `<a href="${esc(c)}" target="_blank" rel="noopener" class="hint">Open classic page ↗</a>` : ""}</div><div class="v">${st}</div></div>`;
    });
    $("sysRows").innerHTML = rows.join("");
    $("sysVer").textContent = `Drifter Boat Systems ${sysInfo ? "v" + sysInfo.version : ""}`;
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
