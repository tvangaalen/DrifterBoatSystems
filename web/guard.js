// BoatGuard module: arms the EZVIZ camera when the iPhone leaves the boat Wi-Fi (logic stays on the BoatGuard server).
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, hms, dur, icon} = D;
const PRIO_HINT = {"-2": "No alert: only listed in the Pushover app", "-1": "No sound or vibration", "0": "Sound per your iPhone settings",
  "1": "Sounds even during Pushover quiet hours"};
const label = s => s === "" ? "App default" : s === "none" ? "Silent" : s === "vibrate" ? "Vibrate only" : s[0].toUpperCase() + s.slice(1);
let dirty = false, built = false, logLines = [], logT = 0, tickT = null;

/** The tile's ceiling dome camera: ceiling plate, smoked glass dome and lens; colours from the --cam-* tokens (red in Night). */
const domeCam = () => `<svg class="dome" viewBox="14 1 92 92" aria-hidden="true"><defs>
  <linearGradient id="gCamS" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="c1"/><stop offset="1" class="c2"/></linearGradient>
  <linearGradient id="gCamT" x1="0" y1="0" x2="1" y2="1"><stop offset="0" class="c0"/><stop offset="1" class="c1"/></linearGradient>
  <radialGradient id="gCamG" cx=".4" cy=".3" r=".8"><stop offset="0" class="g0"/><stop offset="1" class="g1"/></radialGradient>
  <radialGradient id="gCamL" cx=".4" cy=".35" r=".7"><stop offset="0" class="l0"/><stop offset=".35" class="l1"/><stop offset=".75" class="l2"/><stop offset="1" class="l3"/></radialGradient></defs>
  <ellipse class="edge" cx="60" cy="28" rx="44" ry="10" fill="url(#gCamT)"/><path d="M16 28v8a44 10 0 0 0 88 0v-8" fill="url(#gCamS)"/>
  <ellipse class="edge" cx="60" cy="36" rx="44" ry="10" fill="none" stroke-width=".8"/><path d="M26 40a34 34 0 0 0 68 0z" fill="url(#gCamG)"/>
  <circle class="dark" cx="60" cy="58" r="11.5"/><circle cx="60" cy="58" r="9" fill="url(#gCamL)"/><circle class="dark" cx="60" cy="58" r="3.4"/>
  <ellipse class="shine" cx="56.8" cy="54.4" rx="2.5" ry="1.6" opacity=".85"/><path class="gloss" d="M34 46a28 28 0 0 0 12 22"/></svg>`;

const m = {
  id: "guard", title: "BoatGuard", short: "Guard", icon: "guard", every: 4000, background: 8000,
  async load() {
    m.state.data = await D.api("guard", "/api/status");
    if (D.visibleIs("guard") && Date.now() - logT > 8000) {
      logT = Date.now();
      try { logLines = (await D.api("guard", "/api/log?n=300")).lines || []; } catch (e) {}
    }
  },
  badge() {
    const s = m.state.data; if (!s) return null;
    if (s.enabled && (s.router_ok === false || s.arm_at)) return "warn";
    if ((s.camera || {}).error) return "warn";
    return null;
  },
  hero(s) {
    const now = Date.now() / 1000;
    if (!s.enabled) return {cls: "", title: "Monitoring off", sub: "BoatGuard will not arm the camera"};
    let r;
    if (s.test_running) r = {cls: "warn", title: "Camera test running…", sub: ""};
    else if (s.armed_by_us) r = {cls: "ok", title: "Camera armed", sub: `Phone away since ${hms(s.last_seen)}`};
    else if (s.arm_at) r = {cls: "warn", title: `Arming at ${hms(s.arm_at)}`, sub: `in ${dur(s.arm_at - now)} · phone away since ${hms(s.last_seen)}`};
    else if (s.present) r = {cls: "ok", title: "Monitoring active", sub: "The camera is armed once the phone leaves the boat"};
    else r = {cls: "warn", title: "Waiting for the first check…", sub: ""};
    if (s.router_ok === false) r = {cls: "warn", title: r.title, sub: `${s.router_error || "Router not readable"}: nothing will be changed`};
    return r;
  },
  tile() {
    const s = m.state.data; if (!s) return `<div class="line">${esc(m.state.err.message)}</div>`;
    const h = m.hero(s), cam = s.camera || {};
    const tone = !s.enabled ? "" : s.arm_at && !s.armed_by_us ? "badc" : "good";   // off: plain; on: green; arming: red
    return `<div class="guard-row"><div><div class="u-fs-22 big ${tone}">${esc(h.title)}</div><div class="line">${esc(h.sub || (s.enabled ? "Monitoring on" : ""))}</div></div>
      <span class="guard-cam ${cam.armed ? "armed" : ""}" title="${cam.armed ? "Camera armed" : "Camera disarmed"}">${domeCam()}</span></div>
      <div class="minis"><div class="mini"><div class="l">Phone</div><div class="n ${s.present == null ? "" : s.present ? "good" : "badc"}">${s.present == null ? "–" : s.present ? "On board" : "Away"}</div></div>
      <div class="mini"><div class="l">Camera</div><div class="n ${cam.armed ? "badc" : ""}">${cam.armed == null ? "–" : cam.armed ? "Armed" : "Disarmed"}</div></div>
      <div class="mini"><div class="l">Battery</div><div class="n">${cam.battery == null ? "–" : cam.battery + "%"}</div></div></div>`;
  },
  mount(el) {
    el.innerHTML = `<div id="gDown"></div>
    <div class="grid g2l">
      <div class="stack">
        <div class="hero" id="gHero"><div class="lamp"></div><div class="grow"><b id="gHeroT">Loading…</b><span id="gHeroS"></span></div></div>
        <div class="card"><div class="rows"><div class="row"><div class="k"><b>Monitoring</b><small id="gEnSub"></small></div>${D.sw("gEnabled", false, 'aria-label="Monitoring on/off"')}</div></div></div>
        <div class="card"><div class="rows">
          <div class="row"><span class="k">${icon("phone")} Phone</span><span class="v" id="gPhone">–</span></div>
          <div class="row"><span class="k">${icon("cam")} Camera</span><span class="v" id="gCam">–</span></div>
          <div class="row"><span class="k">Camera battery</span><span class="v" id="gBatt">–</span></div>
          <div class="row"><span class="k">Router</span><span class="v" id="gRouter">–</span></div>
          <div class="row"><span class="k">Notifications</span><span class="v" id="gNotif">–</span></div>
        </div></div>
        <div class="card"><div class="rows"><div class="row"><div class="k"><b>Test camera</b><small>Arm, confirm, disarm, confirm (about 15 s)</small></div><button class="btn" id="gTest" type="button">Test</button></div>
          <div class="row" id="gTestRes" hidden></div></div></div>
      </div>
      <div class="stack">
        <h2 class="u-mt-0 sec">Settings</h2>
        <form class="card" id="gSet" novalidate><div class="rows">
          <div class="row"><div class="k"><b>Arming delay</b><small>Phone away this long before the camera is armed</small></div>
            <label class="numf"><input class="field" type="number" inputmode="numeric" id="g_away_after_s" required step="1"><span class="u">s</span></label></div>
          <div class="row"><div class="k"><b>Router check interval</b><small>How often the router's Wi-Fi clients are read</small></div>
            <label class="numf"><input class="field" type="number" inputmode="numeric" id="g_poll_s" required step="1"><span class="u">s</span></label></div>
          <div id="gSounds"></div>
          <div class="row"><span class="hint" id="gSetMsg"></span><button class="btn" id="gSave" type="submit" disabled>Save</button></div>
        </div></form>
      </div>
    </div>
    <h2 class="sec">Log <span class="r" id="gLogN"></span></h2><div class="card"><div class="log" id="gLog"></div></div>`;
    $("gEnabled").addEventListener("change", async e => {
      const want = e.target.checked;
      if (!want && !(await D.confirm({title: "Switch monitoring off?", text: "BoatGuard will not arm the camera when the phone leaves. A camera BoatGuard armed is disarmed.",
        ok: "Switch off", cancel: "Keep monitoring", danger: true}))) { e.target.checked = true; return; }
      D.run(m, e.target, () => D.api("guard", "/api/enabled", {enabled: want}), want ? "Monitoring on" : "Monitoring off").catch(() => {});
    });
    $("gTest").addEventListener("click", e => D.run(m, e.target, () => D.api("guard", "/api/test", {}), "Camera test started").catch(() => {}));
    $("gSet").addEventListener("input", () => { dirty = true; validate(); });
    $("gSet").addEventListener("submit", save);
    built = true;
  },
  render() {
    const s = m.state.data; $("gDown").innerHTML = D.downCard(m) ? D.downCard(m) + '<div class="u-h-12"></div>' : "";
    if (!s) return;
    const now = Date.now() / 1000, cam = s.camera || {}, h = m.hero(s);
    $("gHero").className = "hero " + h.cls; $("gHeroT").textContent = h.title; $("gHeroS").textContent = h.sub;
    $("gEnabled").checked = s.enabled;
    $("gEnSub").textContent = s.enabled ? `Camera armed after ${dur(s.away_after_s)} without the phone` : "The camera is never armed automatically";
    $("gPhone").innerHTML = s.present == null ? "unknown" : s.present ? `<span class="good">On board</span><small>seen ${hms(s.last_seen)}</small>`
      : `<span class="warnc">Away</span><small>last seen ${dur(now - s.last_seen)} ago</small>`;
    const armed = a => a ? '<span class="badc">Armed</span>' : '<span class="good">Disarmed</span>';
    $("gCam").innerHTML = cam.error ? `<span class="badc">Error</span><small>${esc(cam.error)}</small>` : cam.armed == null ? "unknown"
      : cam.pending ? `${armed(cam.armed)}<small>by BoatGuard ${hms(cam.checked)} · waiting for EZVIZ to confirm</small>`
      : `${armed(cam.armed)}<small>${cam.online === false ? "offline · " : ""}EZVIZ ${hms(cam.checked)}${!s.armed_by_us && cam.armed ? " · not by BoatGuard" : ""}</small>`;
    $("gBatt").innerHTML = cam.battery == null ? "–" : `<span class="${cam.battery < 20 ? "badc" : cam.battery < 40 ? "warnc" : ""}">${cam.battery}%</span>`;
    $("gRouter").innerHTML = s.router_ok == null ? "–" : s.router_ok ? `<span class="good">OK</span><small>checked ${hms(s.last_poll)}, every ${s.poll_s} s</small>`
      : `<span class="badc">${esc(s.router_error || "Not readable")}</span><small>since ${hms(s.router_down_since || s.last_poll)}, last try ${hms(s.last_poll)}</small>`;
    $("gNotif").innerHTML = s.notifications ? '<span class="good">Pushover on</span><small>armed · disarmed · left with monitoring off</small>'
      : '<span class="warnc">Not set up</span><small>run boatguard.py pushover on the PC</small>';
    $("gTest").disabled = s.test_running || s.armed_by_us; $("gTest").textContent = s.test_running ? "Running…" : "Test";
    const t = s.last_test, tr = $("gTestRes");
    if (s.test_running) { tr.hidden = false; tr.innerHTML = `<span class="hint">Arming and disarming the camera…</span>`; }
    else if (t) { tr.hidden = false; tr.innerHTML = t.ok ? `<span class="good">✓ Passed at ${hms(t.finished)}: arming and disarming confirmed by the camera</span>`
      : `<span class="badc">✗ Failed at ${hms(t.finished)}: ${t.error ? esc(t.error) : `camera did not confirm (armed: ${esc(t.armed_read)}, then: ${esc(t.disarmed_read)})`}</span>`; }
    else if (s.armed_by_us) { tr.hidden = false; tr.innerHTML = `<span class="hint">Not possible while BoatGuard has the camera armed.</span>`; }
    else tr.hidden = true;
    for (const k of ["away_after_s", "poll_s"]) { const el = $("g_" + k), [lo, hi] = s.limits[k]; el.min = lo; el.max = hi; if (!dirty) el.value = s[k]; }
    buildSounds(s);
    for (const e in s.events) {
      if (!dirty) { $("gsnd-" + e).value = s.sounds[e]; $("gpri-" + e).value = s.priorities[e]; }
      $("gtry-" + e).disabled = !s.notifications; prioHint(s, e);
    }
    validate();
    renderLog();
    clearTimeout(tickT);                            // the arming countdown ticks every second while it runs
    if (s.arm_at && D.visibleIs("guard")) tickT = setTimeout(() => D.visibleIs("guard") && m.render(), 1000);
  },
};

function prioHint(s, e) {
  const p = $("gpri-" + e).value, h = $("ghint-" + e);
  h.textContent = p === "2" ? `Repeats every ${s.emergency.retry_s} s until you acknowledge it in Pushover (max ${dur(s.emergency.expire_s)})` : PRIO_HINT[p];
  h.className = p === "2" ? "hint warnc" : "hint";
}
function buildSounds(s) {
  const box = $("gSounds"); if (box.childElementCount) return;
  const prios = Object.entries(s.priority_options).sort((a, b) => +a[0] - +b[0]);
  for (const [e, title] of Object.entries(s.events)) {
    const row = document.createElement("div"); row.className = "row col";
    row.innerHTML = `<div class="k"><b>${esc(title)}</b><small id="ghint-${e}"></small></div>
      <div class="u-d-flex u-gap-6"><select class="u-flex-1 field" id="gsnd-${e}" aria-label="Sound for ${esc(title)}">${s.sound_options.map(o => `<option value="${esc(o)}">${esc(label(o))}</option>`).join("")}</select>
      <select class="u-flex-1 field" id="gpri-${e}" aria-label="Priority for ${esc(title)}">${prios.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("")}</select>
      <button class="btn sec" type="button" id="gtry-${e}" aria-label="Send a test notification">▶</button></div>`;
    box.appendChild(row);
    $("gpri-" + e).addEventListener("change", () => prioHint(m.state.data, e));
    $("gtry-" + e).addEventListener("click", async ev => {
      const btn = ev.currentTarget, p = +$("gpri-" + e).value;
      if (p === 2 && !(await D.confirm({title: "Send an emergency test?", text: "An emergency notification repeats every minute until you acknowledge it in Pushover (a test stops after at most 2 minutes).",
        ok: "Send test", cancel: "Cancel"}))) return;
      D.run(null, btn, () => D.api("guard", "/api/notify-test", {event: e, sound: $("gsnd-" + e).value, priority: p}),
        r => r.sent ? `Test sent (${label($("gsnd-" + e).value)}, ${s.priority_options[p]})` : "Not sent (see log)").catch(() => {});
    });
  }
}
function validate() {
  const s = m.state.data; if (!s) return false;
  const a = $("g_away_after_s"), p = $("g_poll_s"); let msg = "";
  for (const el of [a, p]) el.classList.toggle("invalid", !el.checkValidity() || !Number.isInteger(+el.value));
  if (!a.checkValidity()) msg = `Arming delay: ${a.min}–${a.max} s`;
  else if (!p.checkValidity()) msg = `Check interval: ${p.min}–${p.max} s`;
  else if (+p.value > +a.value) { msg = "The check interval may not be longer than the arming delay"; p.classList.add("invalid"); }
  $("gSetMsg").textContent = msg || (dirty ? "Unsaved changes" : ""); $("gSetMsg").className = msg ? "hint badc" : "hint";
  $("gSave").disabled = !dirty || !!msg; return !msg;
}
async function save(ev) {
  ev.preventDefault(); if (!validate()) return;
  const s = m.state.data, body = {away_after_s: +$("g_away_after_s").value, poll_s: +$("g_poll_s").value, sounds: {}, priorities: {}};
  for (const e in s.events) { body.sounds[e] = $("gsnd-" + e).value; body.priorities[e] = +$("gpri-" + e).value; }
  try { await D.run(m, $("gSave"), () => D.api("guard", "/api/settings", body), "Settings saved"); dirty = false; } catch (e) {}
}
/** @type {[RegExp, string][]} */
const MARK = [[/camera ARMED$/, "bad"], [/camera disarmed$/, "good"], [/test OK/, "good"]];
function renderLog() {
  const box = $("gLog"); if (!box) return;
  let last = "", html = "";
  const lines = logLines.slice().reverse();
  for (const ln of lines) {
    const mm = ln.match(/^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\S* (\w+) (.*)$/);
    if (!mm) { html += `<div><time></time><span class="msg">${esc(ln)}</span></div>`; continue; }
    const [, d, t, lvl, msg] = mm;
    if (d !== last) { last = d; html += `<div class="day">${d.split("-").reverse().join("-")}</div>`; }
    const cls = (MARK.find(([rx]) => rx.test(msg)) || [, lvl === "ERROR" ? "bad" : lvl === "WARNING" ? "warn" : ""])[1];
    html += `<div class="${cls}"><time>${t}</time><span class="msg">${esc(msg)}</span></div>`;
  }
  box.innerHTML = html || `<div class="empty">No log lines yet</div>`; $("gLogN").textContent = lines.length ? `${lines.length} lines` : "";
}
D.register(m);
