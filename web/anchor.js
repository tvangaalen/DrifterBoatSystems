// Anchor watch module: Orca Core 2 anchor alarm. All alarm logic (drag, frozen GPS, Core, AIS, depth, wind) runs on
// the anchor watch server; this page shows the state, sends commands, and sounds the alarm on this device while the
// server says it sounds (or while the watch cannot be reached with the anchor set). Not for navigation.
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, num, hm, hms, dayTime, icon} = D;
/** @type {[string, string, string, number?, number?, number?, string?, string?][]} */
const SET = [   // [key, label, hint, min, max, step, unit, group]; bools have no limits. Limits = the server's SETTING_LIMITS.
  ["confirm_s", "Drag confirmation", "Outside the circle this long before the alarm", 0, 600, 1, "s", "Alarms"],
  ["gps_timeout_s", "GPS alarm after", "No usable position for this long", 5, 600, 1, "s", "Alarms"],
  ["core_timeout_s", "Core alarm after", "No data from the Orca Core for this long", 5, 600, 1, "s", "Alarms"],
  ["min_depth", "Shallow water alarm", "0 = off", 0, 500, 0.1, "m", "Alarms"],
  ["max_wind_kn", "Wind alarm", "True wind speed, 0 = off", 0, 150, 1, "kn", "Alarms"],
  ["min_ais_dist", "AIS proximity alarm", "While anchored, 0 = off", 0, 2000, 1, "m", "Alarms"],
  ["pc_sound", "Beep on the watch PC", "While an alarm sounds", , , , , "Alarms"],
  ["push_alerts", "Phone alerts (Pushover)", "Anchor drag is an emergency alert that repeats until acknowledged", , , , , "Alarms"],
  ["alive_minutes", "Still-alive check", "Alert from outside after this long without a sign of life, 0 = off", 0, 1440, 5, "min", "Alarms"],
  ["loa", "Length over all", "For chain formulas that use LOA", 0, 100, 0.1, "m", "Boat"],
  ["draught", "Draught", "Keel below the waterline; shows the clearance, 0 = off", 0, 10, 0.05, "m", "Boat"],
  ["bow_height", "Bow height above water", "For the chain advice and the scope", 0, 10, 0.1, "m", "Boat"],
  ["bow_offset", "GPS → bow roller", "Distance forward from the GPS antenna", -50, 50, 0.5, "m", "Boat"],
  ["transducer_depth", "Transducer below waterline", "", 0, 5, 0.05, "m", "Boat"],
  ["default_radius", "Default radius", "Used when dropping", 5, 2000, 1, "m", "Other"],
  ["track_hours", "Track kept", "", 1, 72, 1, "h", "Other"],
  ["internet_ais", "Internet AIS (aisstream.io)", "The own AIS receiver always wins; internet ships are drawn hollow", , , , , "Other"],
  ["nfl_tracking", "Position to noforeignland.com", "Every 10 min under way, once a day at anchor", , , , , "Other"],
  ["nfl_on_anchor", "Track to noforeignland.com when the anchor drops", "", , , , , "Other"],
  ["nmea_port", "NMEA port (phone GPS)", "Network GPS, e.g. GPS2IP, over UDP and TCP", 1024, 65535, 1, "", "GPS"],
];
const GPS_ST = {in_use: ["ok", "Active, in use"], in_use_hold: ["warn", "Active, in use, on hold (within 10 m)"], active: ["ok", "Active, standby"], hold: ["warn", "Active, on hold (within 10 m)"], raw: ["warn", "Active, own GNSS fix"],
  frozen: ["bad", "Frozen, skipped"], away: ["bad", "Far from the other GPS, skipped (off the boat?)"], inactive: ["", "Not active"], never: ["", "Never seen"]};
const card = d => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(d / 45) % 8];
const f0 = v => v == null ? "–" : String(Math.round(v)), f1 = v => v == null ? "–" : (+v).toFixed(1), f2 = v => v == null ? "–" : (+v).toFixed(2);
const ago = s => s == null ? "–" : s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h";
const cssv = n => getComputedStyle(document.body).getPropertyValue(n).trim();
// Priority and sound per push alert (settings push_prio_<key> / push_sound_<key>); anchor drag is always an emergency.
const PUSH_EV = {drag: ["Anchor drag", "Repeats until acknowledged in Pushover"], gps: "GPS position lost", core: "No data from Orca Core", depth: "Shallow water",
  wind: "Wind limit", ais: "AIS target close", cleared: ["Alarm cleared", "When an alarm condition has ended"]};
const pushPrefs = v => Object.fromEntries(Object.keys(PUSH_EV).map(k => [k, {priority: k === "drag" ? 2 : v[`push_prio_${k}`] ?? 1, sound: v[`push_sound_${k}`] ?? ""}]));
const COLS = [["track", "Track"], ["limit", "Anchor circle"], ["swing", "Max swing"]];   // map colours, per light and dark
/** A map colour for the theme in use: the user's choice (Settings) in light and dark; Night keeps its own reds.
 * @param {string} name track, limit or swing */
function mapCol(name) {
  const t = document.documentElement.dataset.theme, s = (m.state.data || {}).settings || {}, own = cssv(name === "limit" ? "--ok" : "--trk");
  if (t === "night") return own;
  const th = t === "dark" || ((!t || t === "auto") && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  return s[`col_${name}_${th}`] || own;
}
const M_LAT = 180 / Math.PI / 6371008.8;          // degrees latitude per metre (same earth as the server)
let L = null, map = null, layers = {}, base = "osm", follow = true, draft = null, lastOk = Date.now();
let ly = {}, track = [], trackGen = -1, trackDrawn = -1, trackCol = "", setDirty = false, setBuilt = false, view = "watch", dropMode = "here";

// ---------------------------------------------------------------- device alarm sound (this phone or tablet)
// WebAudio needs a tap to start; while sound is on the screen is kept awake (iOS stops audio on lock).
let ac = null, soundOn = false, beepT = null, wake = null;
function tone(f, d) { if (!ac) return; const o = ac.createOscillator(), g = ac.createGain(); o.type = "square"; o.frequency.value = f;
  g.gain.setValueAtTime(.0001, ac.currentTime); g.gain.exponentialRampToValueAtTime(.4, ac.currentTime + .02); g.gain.exponentialRampToValueAtTime(.0001, ac.currentTime + d);
  o.connect(g).connect(ac.destination); o.start(); o.stop(ac.currentTime + d + .02); }
async function keepAwake() { try { if ("wakeLock" in navigator && !wake) { wake = await navigator.wakeLock.request("screen"); wake.addEventListener("release", () => wake = null); } } catch (e) {} }
function setSound(on) {
  if (on) { try { ac = ac || new (window.AudioContext || window.webkitAudioContext)(); ac.resume(); soundOn = true; tone(880, .12); keepAwake(); } catch (e) { soundOn = false; } }
  else { soundOn = false; if (wake) { wake.release().catch(() => {}); wake = null; } }
  document.querySelectorAll("[data-sound]").forEach(b => { b.setAttribute("aria-pressed", soundOn); b.innerHTML = `${icon("alert")} ${soundOn ? "Sound on" : "Sound off"}`; });
  alarmTick();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && soundOn) keepAwake(); });
document.addEventListener("click", e => { if (e.target.closest("[data-sound]")) setSound(!soundOn); });
function alarmState() {      // what should sound on this device: the server's alarm, or the watch gone while anchored
  const s = m.state.data, gone = m.state.err && (Date.now() - lastOk) / 1000 > 15;
  if (gone && s && s.anchor) return "unreachable";
  return s && s.sounding ? "alarm" : null;
}
function alarmTick() {
  const st = alarmState();
  if (st && !beepT) beepT = setInterval(() => { if (soundOn) { tone(1800, .3); setTimeout(() => tone(1200, .3), 350); } try { navigator.vibrate && navigator.vibrate([400, 200, 400]); } catch (e) {} }, 1100);
  if (!st && beepT) { clearInterval(beepT); beepT = null; }
}

const m = {
  id: "anchor", title: "Anchor watch", short: "Anchor", icon: "anchor", every: 1500, background: 4000, always: true,
  async load() {
    try { m.state.data = await D.api("anchor", "/api/state"); lastOk = Date.now(); }
    finally { alarmTick(); }
    const s = m.state.data;
    if ((D.visibleIs("anchor") && map) || s.anchor) {             // the map, and the Overview tile's swing radar
      if (s.track_gen !== trackGen || Date.now() - (m._tt || 0) > 8000) {
        m._tt = Date.now();
        const since = s.track_gen === trackGen && track.length ? track[track.length - 1][0] : 0;
        try { const t = await D.api("anchor", `/api/track?since=${since}&gen=${trackGen}`); if (t.gen !== trackGen) { track = []; trackGen = t.gen; } track.push(...t.points); } catch (e) {}
      }
    }
  },
  alarmState: () => alarmState(),
  badge() {
    const s = m.state.data; if (!s) return null;
    if ((s.alarms || []).length || alarmState() === "unreachable") return "bad";
    if (s.anchor && (!s.core.connected || s.gps_age == null || s.gps_age > 10 || s.pending && s.pending.drag != null)) return "warn";
    return null;
  },
  tile() {
    const s = m.state.data; if (!s) return `<div class="line">${esc(m.state.err.message)}</div>`;
    const a = s.anchor, b = s.boat || {}, h = hero(s);
    return `<div class="radar-row"><div>${a ? `<div class="u-fs-22 big ${h.cls === "warn" ? "warnc" : h.cls === "bad" ? "badc" : "good"}">${esc(h.title)}</div>
      ${s.distance != null ? `<div class="big ${h.cls === "bad" ? "badc" : ""}">${f0(s.distance)} <small>/ ${f0(a.radius)} m</small></div>` : ""}<div class="line">max ${f0(s.max_dist)} m</div>`
      : `<div class="u-fs-22 big ${h.cls === "bad" ? "badc" : ""}">${esc(h.title)}</div><div class="line">${esc(h.sub)}</div>`}</div>${radar(s, h)}</div>
      <div class="minis"><div class="mini"><div class="l">Depth</div><div class="n">${b.depth != null ? f1(b.depth) + " m" : "–"}</div></div>
      <div class="mini"><div class="l">Wind</div><div class="n">${b.tws != null ? f0(b.tws) + " kn" : "–"}</div></div>
      <div class="mini"><div class="l">GPS</div><div class="n ${s.gps_age == null || s.gps_age > 10 ? "warnc" : ""}">${s.gps_age == null ? "none" : s.gps_age < 5 ? "live" : ago(s.gps_age)}</div></div></div>`;
  },
  mount(el) {
    el.innerHTML = `<div id="aDown"></div>
      <div class="histhead" id="aHead"><div class="u-d-flex u-gap-8 u-ai-center u-m-4-0-14 u-fw-wrap">
        <div class="u-flex-1 u-minw-250 u-maxw-460 seg" id="aViews"><button type="button" data-aview="watch" aria-pressed="true">Watch</button><button type="button" data-aview="gps" aria-pressed="false">GPS &amp; links</button><button type="button" data-aview="settings" aria-pressed="false">Settings</button></div>
        <button class="btn sec sm" type="button" data-sound aria-pressed="false" title="Sound alarms on this device (keeps the screen on)">${icon("alert")} Sound off</button></div>
        <div class="hero" id="aHero"><div class="lamp"></div><div class="grow"><b id="aHeroT">Loading…</b><span id="aHeroS"></span></div><div class="herobig num" id="aHeroBig"></div></div></div>
      <div id="aWatch"><div class="grid g2l">
        <div class="stack">
          <div class="map no-swipe" id="aMap">
            <div class="mapbtns"><div class="seg" id="aBase"><button type="button" data-base="osm" aria-pressed="true">Map</button><button type="button" data-base="satellite" aria-pressed="false">Sat</button><button type="button" data-base="plain" aria-pressed="false">Plain</button></div>
              <button class="btn" type="button" id="aSea" aria-pressed="true">Seamarks</button>
              <button class="btn" type="button" id="aFit" title="Fit circle and boat, and follow">${icon("anchor")} Fit</button>
              <button class="btn" type="button" id="aWindy" title="Weather forecast on Windy.com for the boat's position">${icon("wave")} Windy</button></div>
            <button class="mapinfo" type="button" id="aCreditsBtn" aria-label="Map credits" title="Map credits">i</button>
            <div class="movebar" id="aMovebar" hidden><div class="u-c-fg hint">Tap the map or nudge 1 m: <b id="aMoveOff">not moved yet</b></div>
              <div class="btns"><button class="btn sec sm" type="button" data-nudge="W" aria-label="West 1 m">←</button><button class="btn sec sm" type="button" data-nudge="N" aria-label="North 1 m">↑</button>
              <button class="btn sec sm" type="button" data-nudge="S" aria-label="South 1 m">↓</button><button class="btn sec sm" type="button" data-nudge="E" aria-label="East 1 m">→</button>
              <span class="u-flex-1"></span><button class="btn sm" type="button" id="aMoveSave">Save</button><button class="btn sec sm" type="button" id="aMoveCancel">Cancel</button></div></div>
          </div>
          <div class="trackbar"><span class="hint" id="aTrackInfo">Track: –</span><button class="btn ghost sm" type="button" id="aNewTrack">Start new track</button></div>
        </div>
        <div class="stack">
          <div class="card pad" id="aCtl"></div>
        </div></div>
        <div class="tiles" id="aTiles"></div>
        <details class="secfold" id="aLogFold"><summary><h2 class="sec">Events<span class="r" id="aLogSum"></span></h2></summary>
          <div class="card"><div class="log" id="aLog"></div></div></details>
        <p class="u-ta-center u-m-14-0 hint" id="aFoot">Not for navigation.</p></div>
      <div id="aGps" hidden></div><div id="aSet" hidden></div>`;
    el.addEventListener("click", onClick);
    el.addEventListener("input", e => { if (e.target.closest("#aSetForm")) { setDirty = true; validate(); } else if (e.target.matches("#aRode,#aFree")) scope(); });
    el.addEventListener("change", e => {
      if (e.target.closest("#aSetForm")) { setDirty = true; validate(); }
      if (e.target.matches("#aRode,#aFree")) { try { localStorage.setItem("drifter-" + e.target.id, e.target.value); } catch (x) {} }
    });
    el.addEventListener("submit", e => { if (e.target.id === "aSetForm") { e.preventDefault(); save(); } });
    // a colour picker is a window of its own: the input may lose focus while it is open, so mark the form until it closes
    el.addEventListener("pointerdown", e => { const f = e.target.closest(".colpick") && $("aSetForm"); if (f) f.dataset.picking = "1"; });
    el.addEventListener("change", e => { if (e.target.closest(".colpick")) delete $("aSetForm").dataset.picking; });
    el.addEventListener("focusout", e => { if (e.target.closest(".colpick")) setTimeout(() => { const f = $("aSetForm"); if (f && !f.contains(document.activeElement)) delete f.dataset.picking; }, 400); });
    loadLeaflet().then(initMap).catch(e => { $("aMap").insertAdjacentHTML("beforeend", `<div class="empty">Map not available: ${esc(e.message)}</div>`); });
    window.addEventListener("drifter-theme", () => { if (map) { trackDrawn = -1; map.invalidateSize(); if (m.state.data) drawMap(m.state.data); } });
    document.addEventListener("keydown", e => {
      if (!draft || /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "")) return;
      const dir = {ArrowUp: "N", ArrowDown: "S", ArrowLeft: "W", ArrowRight: "E"}[e.key];
      if (dir) { e.preventDefault(); nudge(dir, e.shiftKey ? 10 : 1); } else if (e.key === "Enter") { e.preventDefault(); saveMove(); } else if (e.key === "Escape") setMove(false);
    });
  },
  enter() { view = "watch"; },     // from the Overview or the navigation: always the Watch view
  render() {
    $("aDown").innerHTML = m.state.err ? D.downCard(m) + '<div class="u-h-12"></div>' : "";
    document.querySelectorAll("#aViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.aview === view));
    $("aWatch").hidden = view !== "watch"; $("aGps").hidden = view !== "gps"; $("aSet").hidden = view !== "settings";
    // Watch keeps the tabs and the Holding tile at the top; the other views scroll as before
    $("aHero").hidden = view !== "watch"; $("aHead").classList.toggle("fixed", view === "watch"); $("aHead").style.top = $("top").offsetHeight + "px";
    const s = m.state.data; if (!s) return;
    if (view === "watch") renderWatch(s); else if (view === "gps") renderGps(s); else renderSettings(s);
  },
};

/** The tile's swing radar: the limit circle, the max swing (dashed), the track and the boat, around the anchor; north up.
 * Grey and dashed without an anchor. The colour follows hero(): holding, close to the limit or outside, alarm. */
function radar(s, h) {
  const a = s.anchor, S = 110, c = S / 2, R = c - 8;
  if (!a) return `<svg class="radar off" viewBox="0 0 ${S} ${S}" aria-hidden="true"><circle class="lim" cx="${c}" cy="${c}" r="${R}"/>
    <use href="#i-anchor" class="anc" x="${c - 11}" y="${c - 11}" width="22" height="22"/></svg>`;
  const k = Math.cos(a.lat * Math.PI / 180) * 111320, sc = R / a.radius, far = R * 1.3;
  const xy = (lat, lon) => { let x = (lon - a.lon) * k * sc, y = (a.lat - lat) * 111320 * sc; const d = Math.hypot(x, y);
    if (d > far) { x *= far / d; y *= far / d; } return [c + x, c + y]; };
  const step = Math.max(1, Math.ceil(track.length / 160)), pts = track.filter((_, i) => i % step === 0 || i === track.length - 1);
  const line = s.track_gen === trackGen && pts.length > 1 ? `<polyline class="trk" points="${pts.map(t => xy(t[1], t[2]).map(v => v.toFixed(1)).join(",")).join(" ")}"/>` : "";
  const p = (s.boat || {}).pos, [bx, by] = p ? xy(p.lat, p.lon) : [c, c], f = v => v.toFixed(1);
  return `<svg class="radar ${h.cls || "ok"}" viewBox="0 0 ${S} ${S}" role="img" aria-label="${esc(h.title)}"><circle class="lim" cx="${c}" cy="${c}" r="${R}"/>
    <circle class="max" cx="${c}" cy="${c}" r="${f(Math.min(s.max_dist * sc, far))}"/>${line}<use href="#i-anchor" class="anc" x="${c - 7}" y="${c - 7}" width="14" height="14"/>
    ${p ? `<line class="rode" x1="${c}" y1="${c}" x2="${f(bx)}" y2="${f(by)}"/>${h.cls === "bad" ? `<circle class="ping" cx="${f(bx)}" cy="${f(by)}" r="7"/>` : ""}<circle class="boat" cx="${f(bx)}" cy="${f(by)}" r="5.5"/>` : ""}</svg>`;
}

// ---------------------------------------------------------------- status line (same wording as the classic page)
function hero(s) {
  const a = s.anchor, p = (s.boat || {}).pos, gone = alarmState() === "unreachable";
  if (gone) return {cls: "bad", title: "Anchor watch not reachable", sub: `No answer for ${ago((Date.now() - lastOk) / 1000)} – check Wi-Fi and the watch PC`};
  if ((s.alarms || []).length) {
    const sil = s.silenced_until && !s.sounding;
    return {cls: "bad", title: s.alarms.map(x => x.text).join(" · "), sub: s.alarms.map(x => x.detail).filter(Boolean).join(" · ") + (sil ? ` · silenced until ${hm(s.silenced_until)}` : ""), big: true};
  }
  if (a) {
    const frac = s.distance != null ? s.distance / a.radius : 0, pend = (s.pending || {}).drag;
    return {cls: pend != null || frac > .9 ? "warn" : "ok", big: true,
      title: pend != null ? `Outside the circle – alarm in ${Math.max(0, Math.ceil(s.settings.confirm_s - pend))} s` : frac > .9 ? "Close to the limit" : "Holding",
      sub: p ? `${f0(s.distance)} m ${s.bearing != null ? card(s.bearing) : ""} of the anchor · max ${f0(s.max_dist)} m · limit ${f0(a.radius)} m` : "Waiting for GPS…"};
  }
  return {cls: "", title: "Anchor not set", sub: p ? "Drop the anchor to start the watch" : "Waiting for a GPS position…"};
}

// ---------------------------------------------------------------- map
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "vendor/leaflet/leaflet.css"; document.head.appendChild(css);
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = "vendor/leaflet/leaflet.js";
    s.onload = () => res(window.L); s.onerror = () => rej(new Error("Leaflet could not be loaded")); document.head.appendChild(s); });
}
function initMap(lib) {
  L = lib;
  // the credits are on the GPS & links view; the map only has an info button that opens them
  map = L.map("aMap", {zoomControl: true, attributionControl: false, tap: true, maxZoom: 21, zoomSnap: 0.05}).setView([39, 1.5], 9);
  L.control.scale({imperial: false, position: "bottomleft"}).addTo(map);
  const tl = (l, ext, maxN, attr) => L.tileLayer(`api/anchor/tiles/${l}/{z}/{x}/{y}.${ext}`, {maxZoom: 21, maxNativeZoom: maxN, attribution: attr});
  layers.osm = tl("osm", "png", 19, '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>');
  layers.satellite = tl("satellite", "jpg", 19, "Imagery © Esri, Maxar, Earthstar Geographics");
  layers.plain = L.layerGroup();
  layers.seamark = tl("seamark", "png", 18, 'Seamarks © <a href="https://www.openseamap.org" target="_blank" rel="noopener">OpenSeaMap</a>').setZIndex(3);
  layers.osm.addTo(map);
  let sea = true; try { sea = localStorage.getItem("drifter-seamarks") !== "0"; } catch (e) {}
  if (sea) layers.seamark.addTo(map); $("aSea").setAttribute("aria-pressed", sea);
  ly.circle = L.circle([0, 0], {radius: 1, weight: 2, dashArray: "8 6", interactive: false});
  ly.maxc = L.circle([0, 0], {radius: 1, weight: 1, dashArray: "2 5", fill: false, interactive: false});
  ly.rode = L.polyline([], {weight: 1.5, interactive: false});
  ly.anchor = L.marker([0, 0], {icon: L.divIcon({className: "boaticon", html: `<svg viewBox="0 0 24 24" class="u-w-26 u-h-26 i"><use href="#i-anchor"/></svg>`, iconSize: [26, 26], iconAnchor: [13, 13]}), interactive: false, keyboard: false});
  ly.boat = L.marker([0, 0], {icon: L.divIcon({className: "boaticon", html: "", iconSize: [36, 36], iconAnchor: [18, 18]}), interactive: false, keyboard: false, zIndexOffset: 1000});
  ly.track = L.layerGroup().addTo(map); ly.ais = L.layerGroup().addTo(map);
  map.on("dragstart zoomstart", () => { if (!m._fitting) follow = false; });
  map.on("click", e => { if (draft) { draft = {lat: e.latlng.lat, lon: e.latlng.lng}; showDraft(); } });
  L.DomEvent.disableClickPropagation(document.querySelector("#aMap .mapbtns")); L.DomEvent.disableClickPropagation($("aMovebar")); L.DomEvent.disableClickPropagation($("aCreditsBtn"));
  // Leaflet measures its box only on a window resize: hidden (another page or tab) it measures 0 x 0 and then draws from the
  // top-left corner. Measure again whenever the box itself changes size, which includes being shown again.
  new ResizeObserver(() => { const c = $("aMap");
    if (c.clientWidth && c.clientHeight) { map.invalidateSize({pan: false}); if (follow && m.state.data) fit(m.state.data); } }).observe($("aMap"));
  if (m.state.data) drawMap(m.state.data);
  D.poll(m, true);
}
const show = (l, on) => { if (on && !map.hasLayer(l)) l.addTo(map); if (!on && map.hasLayer(l)) map.removeLayer(l); };
function drawMap(s) {
  if (!map) return;
  const a = draft && s.anchor ? {...s.anchor, lat: draft.lat, lon: draft.lon} : s.anchor, b = s.boat || {}, p = b.pos;
  const alarm = (s.alarms || []).length > 0, c = alarm ? cssv("--bad") : draft ? cssv("--warn") : mapCol("limit");
  show(ly.circle, !!a); show(ly.maxc, !!a && s.max_dist > 0); show(ly.anchor, !!a); show(ly.rode, !!(a && p)); show(ly.boat, !!p);
  if (a) {
    ly.circle.setLatLng([a.lat, a.lon]).setRadius(a.radius).setStyle({color: c, fillColor: c, fillOpacity: alarm ? .18 : .07});
    ly.maxc.setLatLng([a.lat, a.lon]).setRadius(Math.max(s.max_dist, .1)).setStyle({color: mapCol("swing"), weight: 2});
    ly.anchor.setLatLng([a.lat, a.lon]); const el = ly.anchor.getElement(); if (el) el.style.color = c;
  }
  if (p) {
    ly.boat.setLatLng([p.lat, p.lon]);
    const hd = b.heading, html = `<div style="transform:rotate(${hd ?? 0}deg);width:36px;height:36px">${hd == null ? '<svg viewBox="-18 -18 36 36" width="36" height="36"><circle r="6" fill="currentColor" stroke="var(--card)" stroke-width="2"/></svg>'
      : '<svg viewBox="-18 -18 36 36" width="36" height="36"><path d="M0-16C6-9 6 2 4.5 12H-4.5C-6 2-6-9 0-16Z" fill="currentColor" stroke="var(--card)" stroke-width="2"/><circle r="2.6" fill="var(--card)"/></svg>'}</div>`;
    const el = ly.boat.getElement(); if (el && el.innerHTML !== html) el.innerHTML = html;
    if (a) ly.rode.setLatLngs([[a.lat, a.lon], [p.lat, p.lon]]).setStyle({color: cssv("--muted")});
  }
  const tc = mapCol("track");
  if (track.length !== trackDrawn || tc !== trackCol) {      // older parts fainter; rebuilt only when points were added
    trackDrawn = track.length; trackCol = tc; ly.track.clearLayers();
    if (track.length > 1) {
      const now = Date.now() / 1000, span = Math.max(600, now - track[0][0]), B = 8, buckets = Array.from({length: B}, () => []);
      for (let i = 1; i < track.length; i++) { const [ta, la, lo] = track[i - 1], [tb, lb, lob] = track[i]; if (tb - ta > 120) continue;
        buckets[Math.min(B - 1, Math.floor(Math.max(0, 1 - (now - tb) / span) * B))].push([[la, lo], [lb, lob]]); }
      buckets.forEach((segs, k) => { if (segs.length) L.polyline(segs, {color: tc, weight: 3, opacity: .2 + .8 * (k + 1) / B, interactive: false}).addTo(ly.track); });
    }
  }
  ly.ais.clearLayers();
  for (const t of s.ais || []) {
    const hd = t.heading ?? t.cog, net = t.src !== "local";
    const html = `<div class="aisic${net ? " net" : ""}"><svg viewBox="-7 -7 14 14" width="16" height="16" style="transform:rotate(${hd ?? 0}deg)">${hd == null ? '<circle r="4"/>' : '<path d="M0-6L4 5H-4Z"/>'}</svg><span>${esc(t.name || t.mmsi)}${net ? " · " + ago(t.age) : ""}</span></div>`;
    L.marker([t.lat, t.lon], {icon: L.divIcon({className: "", html, iconSize: [16, 16], iconAnchor: [8, 8]}), keyboard: false,
      title: `${t.name || ""} ${t.mmsi} · ${f0(t.dist)} m${t.sog != null ? " · " + t.sog + " kn" : ""} · ${net ? "internet AIS, " + ago(t.age) + " old" : "own AIS receiver"}`}).addTo(ly.ais);
  }
  if (follow) fit(s);
}
function fit(s) {
  const a = s.anchor, p = (s.boat || {}).pos; if (!a && !p) return;
  // the largest circle (alarm radius or max swing) just inside the map, about 10 px to spare (the user's choice of 2026-11-06);
  // the map zooms in steps of 0.05 for this. A boat outside the circle stays in view.
  let bb = a ? L.latLng(a.lat, a.lon).toBounds(2 * Math.max(a.radius, s.max_dist || 0)) : L.latLng(p.lat, p.lon).toBounds(160);
  if (a && p) bb = bb.extend(L.latLng(p.lat, p.lon));
  const z = Math.min(20, map.getBoundsZoom(bb, false, L.point(16, 16))), c = bb.getCenter();
  if (Math.abs(z - map.getZoom()) > .04 || map.getCenter().distanceTo(c) > 2) { m._fitting = true; map.setView(c, z, {animate: false}); m._fitting = false; }
}
function setMove(on) {
  const s = m.state.data; if (on && !(s && s.anchor)) return;
  draft = on ? {lat: s.anchor.lat, lon: s.anchor.lon} : null; $("aMovebar").hidden = !on;
  if (map) { on ? map.keyboard.disable() : map.keyboard.enable(); }
  showDraft(); renderWatch(m.state.data);
}
function nudge(dir, mtr) {
  if (!draft) return;
  if (dir === "N") draft.lat += mtr * M_LAT; if (dir === "S") draft.lat -= mtr * M_LAT;
  const dl = mtr * M_LAT / Math.cos(draft.lat * Math.PI / 180); if (dir === "E") draft.lon += dl; if (dir === "W") draft.lon -= dl;
  showDraft();
}
function showDraft() {
  const s = m.state.data;
  if (draft && s && s.anchor) {
    const dn = (draft.lat - s.anchor.lat) / M_LAT, de = (draft.lon - s.anchor.lon) / M_LAT * Math.cos(s.anchor.lat * Math.PI / 180);
    const part = (v, pos, neg) => Math.round(Math.abs(v)) ? `${Math.round(Math.abs(v))} m ${v > 0 ? pos : neg}` : "";
    $("aMoveOff").textContent = [part(dn, "N", "S"), part(de, "E", "W")].filter(Boolean).join(", ") || "not moved yet";
  }
  if (s) drawMap(s);
}
async function saveMove() {
  if (!draft) return; const {lat, lon} = draft;
  try { await D.run(m, $("aMoveSave"), () => D.api("anchor", "/api/command", {action: "move", lat, lon}), "Anchor position moved"); setMove(false); follow = true; } catch (e) {}
}

// ---------------------------------------------------------------- watch view
function renderWatch(s) {
  const a = s.anchor, b = s.boat || {}, h = hero(s);
  $("aHero").className = "hero " + h.cls; $("aHeroT").textContent = h.title; $("aHeroS").textContent = h.sub;
  $("aHeroBig").innerHTML = h.big && s.distance != null ? `${f0(s.distance)}<small> m</small>` : "";
  const silenced = s.silenced_until && !s.sounding;
  if (!$("aCtl").dataset.mode || $("aCtl").dataset.mode !== (a ? "watch" : "drop")) {
    $("aCtl").dataset.mode = a ? "watch" : "drop";
    $("aCtl").innerHTML = a ? `
      <div class="u-b-0 u-pt-0 row"><div class="k"><b>Watching</b><small id="aSetAt"></small></div>
        <div class="stepper"><button type="button" data-rad="-5" aria-label="Smaller radius">−5</button><output class="num" id="aRad"></output><button type="button" data-rad="5" aria-label="Larger radius">+5</button></div></div>
      <div class="u-mt-6 btns eq"><button class="btn sec" type="button" id="aMove">Move anchor</button><button class="btn sec" type="button" data-silence="5" id="aSil">Silence 5 min</button></div>
      <div class="u-mt-8 btns eq"><button class="btn danger" type="button" id="aRaise">Anchor up – stop watch</button></div>`
    : `<div class="seg" id="aDropMode"><button type="button" data-dmode="here" aria-pressed="true">Dropping now</button><button type="button" data-dmode="ahead" aria-pressed="false">Already lying to it</button></div>
      <div class="u-p-0 rows">
        <div class="row" id="aAheadRow" hidden><span class="k">Anchor ahead of the bow</span><label class="numf"><input class="field" type="number" id="aAhead" min="0" max="2000" step="1" value="30" inputmode="decimal"><span class="u">m</span></label></div>
        <div class="row"><span class="k">Alarm radius</span><label class="numf"><input class="field" type="number" id="aDropRad" min="5" max="2000" step="1" inputmode="decimal" value="${f0(s.settings.default_radius)}"><span class="u">m</span></label></div></div>
      <details class="scope"><summary>Work out the radius from the rode</summary>
        <div class="u-p-0 rows"><div class="row"><span class="k">Rode out</span><label class="numf"><input class="field" type="number" id="aRode" min="0" step="1" inputmode="decimal"><span class="u">m</span></label></div>
        <div class="row"><span class="k">Bow height above water</span><label class="numf"><input class="field" type="number" id="aFree" min="0" step="0.1" inputmode="decimal"><span class="u">m</span></label></div></div>
        <p class="hint" id="aScope"></p><button class="btn sec sm" type="button" id="aUseScope">Use this radius</button></details>
      <div class="u-mt-12 btns eq"><button class="btn" type="button" id="aDrop">${icon("anchor")} Drop anchor &amp; start watch</button></div>`;
    if (!a) { let /** @type {number | string} */ r = 40, /** @type {number | string} */ f = s.settings.bow_height ?? 1.2; try { r = localStorage.getItem("drifter-aRode") || r; f = localStorage.getItem("drifter-aFree") || f; } catch (e) {} $("aRode").value = r; $("aFree").value = f; }
  }
  if (a) {
    $("aSetAt").textContent = "since " + dayTime(a.set_at); $("aRad").textContent = f0(a.radius) + " m";
    $("aSil").disabled = !(s.alarms || []).length || silenced; $("aSil").textContent = silenced ? `Silenced until ${hm(s.silenced_until)}` : "Silence 5 min";
    $("aMove").setAttribute("aria-pressed", !!draft); $("aMove").textContent = draft ? "Moving…" : "Move anchor";
  } else { $("aDrop").disabled = !b.pos; scope(); }
  $("aTiles").innerHTML = tiles(s);
  $("aTrackInfo").textContent = s.track_points ? `Track since ${dayTime(s.track_start)} · ${s.track_points.toLocaleString("en-GB")} points` : "Track: empty, recording starts with the next position";
  const evs = s.events || [], last = evs[evs.length - 1], nBad = evs.filter(e => e.kind === "alarm").length;     // folded: a one-line summary
  $("aLogSum").innerHTML = `${last ? `${evs.length} · last ${esc(dayTime(last.t))}` : "none"}${nBad ? ` · <span class="badc">${nBad} alarm${nBad === 1 ? "" : "s"}</span>` : ""} ${icon("chev", "i chev")}`;
  $("aLog").innerHTML = (s.events || []).slice().reverse().map(e => `<div class="${e.kind === "alarm" ? "bad" : e.kind === "warn" ? "warn" : ""}"><time>${dayTime(e.t)}</time><span class="msg">${esc(e.text)}</span></div>`).join("") || `<div class="empty">Nothing yet</div>`;
  $("aFoot").textContent = `Anchor watch ${s.version || ""} · not for navigation`;
  drawMap(s);
}
function scope() {
  const s = m.state.data; if (!s || !$("aScope")) return;
  const rode = +$("aRode").value, fb = +$("aFree").value, d = (s.boat || {}).depth;
  if (d == null) { $("aScope").textContent = "No depth reading."; $("aUseScope").disabled = true; return; }
  const h = d + fb, reach = rode > h ? Math.sqrt(rode * rode - h * h) : 0, off = Math.max(0, +(s.settings.bow_offset || 0)), sugg = Math.ceil((reach + off) * 1.1 + 5);
  $("aScope").innerHTML = `Depth ${f2(d)} m + bow ${f2(fb)} m → scope ${h ? (rode / h).toFixed(1) : "–"}:1${rode / h < 3 ? ' <b class="badc">(short)</b>' : ""}. Rode reaches ~${f0(reach)} m; with the GPS→bow offset, 10 % and 5 m GPS margin: <b>${sugg} m</b>.`;
  $("aUseScope").dataset.r = sugg; $("aUseScope").disabled = false;
}

// ---------------------------------------------------------------- tiles (as on the classic page)
const tile = (l, v, u, sub, cls = "") => `<div class="stat ${cls}"><div class="l">${l}</div><div class="n">${v}<small>${u}</small></div><div class="s">${sub || "&nbsp;"}</div></div>`;
const aisDown = s => { const a = s.ais_stream; return a && (!a.connected || a.last_message_age == null || a.last_message_age > 30); };
function tiles(s) {
  const a = s.anchor, b = s.boat || {}, ais = s.ais || [], nNet = ais.filter(t => t.src !== "local").length, netOk = s.net_ais && s.net_ais.connected && s.settings.internet_ais;
  const warn = t => `<span class="warnc">${t}</span>`;
  const normal = [
    a ? tile("From anchor", f0(s.distance), "m", s.bearing != null ? `bearing ${f0(s.bearing)}° ${card(s.bearing)}` : "") : "",
    a ? tile("Max swing", f0(s.max_dist), "m", `limit ${f0(a.radius)} m`) : "",
    tile("Depth", f2(b.depth), "m", b.depth == null && s.settings.min_depth > 0 ? warn("no depth data: depth alarm inactive") : a && a.depth != null ? `at drop ${f2(a.depth)} m` : "water depth"),
    tile("True wind", f0(b.tws), "kn", b.tws == null && s.settings.max_wind_kn > 0 ? warn("no wind data: wind alarm inactive") : b.twd != null ? `from ${f0(b.twd)}° ${card(b.twd)}` : ""),
    aisDown(s) && !netOk ? tile("AIS nearby", "–", "", warn(`AIS feed down · ${s.ais_stream.last_message_age != null ? "last data " + ago(s.ais_stream.last_message_age) + " ago" : "no data yet"}`))
      : tile("AIS closest", ais[0] ? f0(ais[0].dist) : "–", ais[0] ? "m" : "", (ais[0] ? `${esc(ais[0].name || ais[0].mmsi)} · ${ais.length} within 600 m` : "none within 600 m")
        + (s.settings.min_ais_dist > 0 ? ` · alarm < ${f0(s.settings.min_ais_dist)} m` : "") + (nNet ? ` · ${nNet} internet` : "") + (aisDown(s) ? " · " + warn("local feed down") : "")),
    tile("SOG", f1(b.sog), "kn", ""),
    tile("Heading", b.heading != null ? f0(b.heading) : "–", "°T", ""),
  ].filter(Boolean);
  if (normal.length % 2) normal[normal.length - 1] = normal[normal.length - 1].replace('class="stat ', 'class="stat wide ');   // no empty cell on a phone
  return `<div class="stats tilegrid">` + normal.join("") + sunTile(s) + positionTile(s) + `</div>` + tideCard(s);
}
function sunTimes(lat, lon, date) {     // the usual solar formulas (as in SunCalc; refraction -0.833°), local time
  const rad = Math.PI / 180, dayMs = 864e5, J1970 = 2440588, J2000 = 2451545, J0 = 0.0009, e = rad * 23.4397;
  const days = date.valueOf() / dayMs - 0.5 + J1970 - J2000, lw = -lon * rad, phi = lat * rad;
  const n = Math.round(days - J0 - lw / (2 * Math.PI)), transit = ht => J0 + (ht + lw) / (2 * Math.PI) + n;
  const ds = transit(0), M = rad * (357.5291 + 0.98560028 * ds);
  const Lm = M + rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + rad * 102.9372 + Math.PI;
  const dec = Math.asin(Math.sin(Lm) * Math.sin(e)), J = x => J2000 + x + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * Lm);
  const w = Math.acos((Math.sin(-0.833 * rad) - Math.sin(phi) * Math.sin(dec)) / (Math.cos(phi) * Math.cos(dec)));
  if (isNaN(w)) return null;
  const noon = J(ds), set = J(transit(w)), rise = noon - (set - noon), toDate = j => new Date((j + 0.5 - J1970) * dayMs);
  return {rise: toDate(rise), set: toDate(set)};
}
function sunTile(s) {
  const q = (s.boat || {}).pos || s.anchor; if (!q) return tile("Sun", "–", "", "no position", "wide");
  const now = new Date(), t = sunTimes(q.lat, q.lon, now); if (!t) return tile("Sun", "–", "", "no sunrise or sunset today", "wide");
  const tom = now >= t.set ? sunTimes(q.lat, q.lon, new Date(+now + 864e5)) : null;
  /** @type {[string, Date] | null} */
  const next = now < t.rise ? ["rise", t.rise] : now < t.set ? ["set", t.set] : tom ? ["rise", tom.rise] : null;
  const left = next ? Math.round((+next[1] - +now) / 60000) : 0;
  const sub = next ? `sun${next[0]} in ${left >= 60 ? Math.floor(left / 60) + " h " + D.pad(left % 60) + " min" : left + " min"}${tom ? " (tomorrow " + hm(tom.rise) + ")" : ""}` : "";
  return tile("Sun", `↑ ${hm(t.rise)} &nbsp;↓ ${hm(t.set)}`, "", sub, "wide");
}
function fmtPos(lat, lon, f) {
  const one = (v, pos, neg, w) => { const hemi = v >= 0 ? pos : neg, a = Math.abs(v);
    if (f === "dd") return `${a.toFixed(5)}° ${hemi}`;
    let d = Math.floor(a), mn = (a - d) * 60;
    if (f === "dms") { let mi = Math.floor(mn), sc = (mn - mi) * 60; if (+sc.toFixed(1) >= 60) { sc = 0; mi++; } if (mi >= 60) { mi = 0; d++; }
      return `${String(d).padStart(w, "0")}° ${D.pad(mi)}′ ${sc.toFixed(1).padStart(4, "0")}″ ${hemi}`; }
    if (+mn.toFixed(3) >= 60) { mn = 0; d++; }
    return `${String(d).padStart(w, "0")}° ${mn.toFixed(3).padStart(6, "0")}′ ${hemi}`; };
  return [one(lat, "N", "S", 2), one(lon, "E", "W", 3)];
}
function positionTile(s) {
  const p = (s.boat || {}).pos;
  const badge = !p ? `<span class="badge bad">No GPS${s.gps_age != null ? " · " + ago(s.gps_age) : ""}</span>` : p.hold ? `<span class="badge warn" title="The Orca Core keeps its fix while the boat lies still: within about 10 m">GPS hold</span>`
    : p.hdop != null && p.hdop > 2 ? `<span class="badge warn">GPS poor</span>` : `<span class="badge ok">GPS OK</span>`;
  if (!p) return `<div class="stat wide"><div class="l">Position ${badge}</div><div class="n">–</div><div class="s">no GPS position</div></div>`;
  const [la, lo] = fmtPos(p.lat, p.lon, s.settings.pos_format || "dmm");
  return `<div class="stat wide"><div class="l">Position ${badge}</div><div class="n pos">${la}<br>${lo}</div><div class="s">GPS ${esc(p.name || p.source)}${p.sats != null ? " · " + p.sats + " sats" : ""}${p.hdop != null ? " · HDOP " + p.hdop : ""}</div></div>`;
}
function tideChart(c, now, lv, P) {   // depth (or sea level) 6 h back to 24 h ahead; lowest/highest next 24 h dashed; "now" dotted
  const W = Math.max(280, Math.round(($("aTiles") && $("aTiles").clientWidth || 340) - 34)), H = 130, Lx = 42, R = W - 6, TOP = 12, BOT = 96, t0 = c[0][0], t1 = c[c.length - 1][0];
  const vs = c.map(q => q[1]); let lo = Math.min(...vs), hi = Math.max(...vs); if (hi - lo < 0.04) { lo -= .02; hi += .02; }
  const pad = (hi - lo) * .12; lo -= pad; hi += pad;
  const X = t => Lx + (t - t0) / (t1 - t0) * (R - Lx), Y = v => BOT - (v - lo) / (hi - lo) * (BOT - TOP);
  const line = c.map((q, i) => `${i ? "L" : "M"}${X(q[0]).toFixed(1)} ${Y(q[1]).toFixed(1)}`).join("");
  let g = "";
  if (P) {
    for (const v of [P.max, P.min]) g += `<line class="lim" x1="${Lx}" x2="${R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text x="${Lx - 5}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${(+v).toFixed(2)}</text>`;
    for (const [tt, v, nm] of [[P.min_t, P.min, "low"], [P.max_t, P.max, "high"]]) { if (tt == null) continue; const x = X(tt), anc = x < Lx + 40 ? "start" : x > R - 40 ? "end" : "middle";
      g += `<circle cx="${x.toFixed(1)}" cy="${Y(v).toFixed(1)}" r="3.2"/><text x="${x.toFixed(1)}" y="${H - 14}" text-anchor="${anc}">${nm} ${hm(tt)}</text>`; }
  }
  const xn = X(now);
  g += `<line class="now" x1="${xn.toFixed(1)}" x2="${xn.toFixed(1)}" y1="${TOP - 4}" y2="${BOT}"/><circle cx="${xn.toFixed(1)}" cy="${Y(lv).toFixed(1)}" r="3.6"/><text x="${(xn + 5).toFixed(1)}" y="${TOP + 5}">now</text>`;
  return `<svg class="tchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${P ? "depth" : "sea level"} from 6 hours ago to 24 hours ahead"><path class="area" d="${line}L${X(t1).toFixed(1)} ${BOT}L${X(t0).toFixed(1)} ${BOT}Z"/><path class="curve" d="${line}"/>${g}</svg>`;
}
function tideCard(s) {
  const T = s.tide || {}, P = s.depth_plan || {};
  if (!T.available) return `<div class="card pad tidecard"><div class="u-fwt-600 u-fs-12 l muted">Tide</div><div class="hint">${esc(T.error ? "no tide data: " + T.error : "no tide data yet")}</div></div>`;
  const dp = P.available && P.curve && P.curve.length > 1, curve = dp ? P.curve : T.curve;
  const chart = curve && curve.length > 1 ? tideChart(curve, s.time, dp ? P.now : T.level, dp ? P : null) : "";
  const range = T.range != null ? ` · range ${Math.round(T.range * 100)} cm` : "";
  const from = !dp ? "" : P.source === "sounder" ? "from the sounder" : `from the last reading ${dayTime(P.reading_t)}, tide-corrected`;
  let keel = "";
  if (dp && P.draught) {
    const cl = P.clearance_min, tot = Math.max(P.min, P.draught), kp = Math.min(100, P.draught / tot * 100), cls = cl < .5 ? "bad" : cl < 1 ? "warn" : "ok";
    keel = `<div class="keel ${cls}"><div class="kl"><span>Under the keel, min next 24 h</span><b>${cl.toFixed(2)} m</b></div>
      <div class="kbar"><i class="hull" style="width:${kp.toFixed(1)}%"></i><i class="clear" style="width:${(100 - kp).toFixed(1)}%"></i></div>
      <div class="kl hint"><span>draught ${P.draught.toFixed(2)} m</span><span>water ${f2(P.min)} m at ${P.min_t ? hm(P.min_t) : "–"}</span></div></div>`;
  }
  return `<div class="card pad tidecard" title="Marine model sea level incl. tide and weather; not for navigation">
    <div class="thead"><span class="l">Tide${dp ? " · depth next 24 h" : ""}</span><b class="num">${dp ? `now ${f2(P.now)} m` : `sea level ${f2(T.level)} m`}</b></div>${chart}
    <div class="trow"><span>${T.trend === "falling" ? "↓ Falling" : T.trend === "rising" ? "↑ Rising" : "–"}<small class="muted">${range}${(T.next || []).length ? " · " + T.next.map(e => `${e.type} ${hm(e.t)}`).join(" · ") : ""}</small></span>
    ${dp && P.chain != null ? `<span class="badge plain" title="${esc(P.formula)} with D ${f2(P.max)} m (deepest in 24 h), B ${f2(P.bow_height)} m, LOA ${f2(P.loa)} m, rounded up">Minimum chain ${P.chain} m</span>` : ""}</div>
    ${dp ? "" : `<div class="hint warnc">No depth for the chart: ${esc(P.reason || "no depth reading")}</div>`}${keel}
    <div class="hint">${from ? esc(from) + " · " : ""}${T.error ? '<span class="warnc">offline copy</span> · ' : ""}tide by Open-Meteo.com</div></div>`;
}

// ---------------------------------------------------------------- GPS & links view
function renderGps(s) {
  const rows = s.gps_rows || [], use = rows.find(r => r.status === "in_use"), pos = (s.boat || {}).pos;
  const held = r => r.status === "in_use" && pos && pos.hold && String(pos.source) === String(r.source);   // in use outranks hold in the server's row status
  const status = (on, ok, bad, note) => !on ? `<span class="warnc">Not set up</span><small>${note}</small>` : bad ? `<span class="badc">Problem</span><small>${esc(bad)}</small>` : `<span class="good">OK</span><small>${ok}</small>`;
  const ps = s.push || {}, al = s.alive || {}, na = s.net_ais || {}, nf = s.nfl || {}, nm = s.nmea || {}, mins = +s.settings.alive_minutes;
  $("aGps").innerHTML = `<div class="grid g2"><div class="stack">
    <div class="card"><div class="hd">${icon("anchor")}<h3>GPS sources</h3><button class="btn ghost sm" type="button" id="aGpsDefault">Default order</button></div>
      <div class="rows"><div class="row"><span class="hint">${use ? `In use: <b>${esc(use.name)}</b>${held(use) ? ' <span class="badge warn">hold</span>' : ""}${use.sats ? " · " + use.sats + " sats" : ""}${use.hdop != null ? " · HDOP " + use.hdop : ""}` : '<span class="badc">No usable GPS</span>'} · tried from top to bottom; changes are saved at once</span></div>
      ${rows.map((r, i) => { const [cls, txt] = GPS_ST[held(r) ? "in_use_hold" : r.status] || GPS_ST.inactive, act = !["inactive", "never"].includes(r.status);
        const det = act ? [r.sats ? r.sats + " sats" : "", r.hdop != null ? "HDOP " + r.hdop : ""].filter(Boolean).join(" · ") : r.last_seen != null ? "last seen " + ago(r.last_seen) + " ago" : "";
        return `<div class="row gpsrow"><span class="gnum">${i + 1}</span><div class="u-flex-1 k"><b>${esc(r.name)}</b><small>source ${esc(r.source)} · <span class="${cls ? cls === "ok" ? "good" : cls === "warn" ? "warnc" : "badc" : ""}">${txt}</span>${det ? " · " + esc(det) : ""}</small></div>
          <div class="u-fw-nowrap btns">${act ? "" : `<button class="btn sec sm" type="button" data-forget="${esc(r.source)}" aria-label="Remove ${esc(r.name)}">✕</button>`}
          <button class="btn sec sm" type="button" data-gmove="${i}" data-d="-1" aria-label="Move ${esc(r.name)} up" ${i ? "" : "disabled"}>▲</button><button class="btn sec sm" type="button" data-gmove="${i}" data-d="1" aria-label="Move ${esc(r.name)} down" ${i < rows.length - 1 ? "" : "disabled"}>▼</button></div></div>`; }).join("") || `<div class="empty">No GPS seen yet</div>`}
      <div class="row"><span class="hint">A GPS whose position has not changed for 60 s is skipped as frozen (the Orca Core's own GPS, 254, keeps its fix while the boat lies still and moves it on after about 10 m: shown as hold). A phone with GPS2IP shows up as Network GPS and is skipped when it is more than 100 m from the other GPS. Only a GPS that is not active can be removed; it comes back when it is seen again.</span></div></div></div>
    <div class="card"><div class="hd"><h3>AIS targets</h3><span class="muted">${(s.ais || []).length}</span></div><div class="rows">
      ${(s.ais || []).slice().sort((x, y) => x.dist - y.dist).slice(0, 40).map(t => `<div class="row"><div class="k"><b>${esc(t.name || t.mmsi)}</b><small>${esc(t.mmsi)}${t.length ? ` · ${f0(t.length)} m` : ""} · ${t.src === "local" ? "own receiver" : "internet, " + ago(t.age) + " old"}</small></div>
        <span class="v">${f0(t.dist)} m<small>${f0(t.bearing)}°${t.sog != null ? ` · ${t.sog} kn` : ""}</small></span></div>`).join("") || `<div class="empty">No AIS targets within 600 m</div>`}</div></div></div>
    <div class="stack"><div class="card"><div class="hd"><h3>Connections</h3></div><div class="rows">
      <div class="row"><span class="k">Orca Core</span><span class="v">${s.core.connected ? `<span class="good">Connected</span><small>last data ${ago(s.core.last_message_age)} ago</small>` : `<span class="badc">Not connected</span><small>${esc(s.core.last_error || "")}</small>`}</span></div>
      <div class="row"><span class="k">AIS (Core)</span><span class="v">${aisDown(s) ? `<span class="warnc">Down</span><small>${s.ais_stream.last_message_age != null ? "last data " + ago(s.ais_stream.last_message_age) + " ago" : "no data yet"}</small>` : '<span class="good">Connected</span>'}</span></div>
      <div class="row col"><div class="u-d-flex u-jc-between u-gap-8"><span class="k">Push alerts (Pushover)</span><span class="v">${status(ps.configured, ps.last_sent ? "last sent " + hm(ps.last_sent) : "ready", ps.last_error, "pushover.json on the watch PC")}</span></div>
        <span class="hint">Anchor drag = emergency alert that repeats every 30 s (up to 3 h) until acknowledged in Pushover; GPS/Core lost, depth and wind = high priority.</span>
        <div class="btns"><button class="btn sec sm" data-act="push_test" type="button">Send test</button><button class="btn sec sm" id="aAlarmTest" type="button">Test alarm</button><button class="btn sec sm" data-act="push_alarm_stop" type="button">Stop test alarm</button></div></div>
      <div class="row col"><div class="u-d-flex u-jc-between u-gap-8"><span class="k">Still-alive check</span><span class="v">${!al.configured ? status(false, "", "", "still_alive.json on the watch PC") : !mins ? "Off" : status(true, `pings every ${Math.round((al.every_s || 300) / 60)} min${al.last_ok ? ", last " + hm(al.last_ok) : ""}`, al.last_error)}</span></div>
        ${al.note ? `<span class="hint warnc">To do: ${esc(al.note)}</span>` : ""}<div class="btns"><button class="btn sec sm" data-act="alive_check" type="button">Ping now</button></div></div>
      <div class="row col"><div class="u-d-flex u-jc-between u-gap-8"><span class="k">Internet AIS</span><span class="v">${!na.configured ? status(false, "", "", "aisstream.json on the watch PC") : !s.settings.internet_ais ? "Off" : status(true, na.connected ? `${na.ships} ships${na.last_message ? " · last " + hm(na.last_message) : ""}` : "connecting…", na.last_error)}</span></div>
        <div class="btns"><button class="btn sec sm" data-act="net_ais_check" type="button">Reconnect</button></div></div>
      <div class="row col"><div class="u-d-flex u-jc-between u-gap-8"><span class="k">noforeignland.com</span><span class="v">${!nf.configured ? status(false, "", "", "nfl.json on the watch PC") : !s.settings.nfl_tracking && !s.settings.nfl_on_anchor ? "Off" : status(true, nf.sent_t ? `last position ${dayTime(nf.sent_t)}${nf.last_ok ? ` (${nf.last_count} points)` : ""}` : "ready", nf.last_error)}</span></div>
        <div class="btns"><button class="btn sec sm" data-act="nfl_send" type="button">Send now</button></div></div>
      <div class="row"><span class="k">Network GPS</span><span class="v">${!nm.on ? "Off on this server" : nm.error ? `<span class="badc">${esc(nm.error)}</span>` : nm.port ? `<span class="good">Listening</span><small>port ${nm.port}, UDP and TCP</small>` : "opening…"}</span></div>
      <div class="row"><span class="k">Anchor watch</span><span class="v">v${esc(s.version)}<small>${(s.track_points || 0).toLocaleString("en-GB")} track points</small></span></div>
    </div></div>
    <div class="card pad" id="aCredits"><h3 class="u-m-0-0-6 u-fs-15">Credits</h3><ul class="u-m-0 u-pl-18 hint">
      <li>Street map © OpenStreetMap contributors (ODbL)</li><li>Satellite imagery © Esri, Maxar, Earthstar Geographics and the GIS User Community</li>
      <li>Seamarks © OpenSeaMap contributors (CC BY-SA)</li><li>Tide: weather data by Open-Meteo.com (CC BY 4.0)</li><li>Internet AIS: aisstream.io</li><li>Map library: Leaflet © Vladimir Agafonkin (BSD-2-Clause)</li></ul>
      <p class="u-m-8-0-0 hint">Charts, tide and AIS are not for navigation.</p></div></div></div>`;
}

// ---------------------------------------------------------------- settings view
function renderSettings(s) {
  const box = $("aSet"), v = s.settings, oc = s.own_candidate;
  const sug = oc && !v.own_mmsi ? `<div class="row col"><span class="hint">AIS ${esc(oc.name || "")} ${esc(oc.mmsi)} is ${f0(oc.dist)} m from your GPS: probably your own boat.</span><div class="btns"><button class="btn sec sm" type="button" data-mmsi="${esc(oc.mmsi)}">Use as My MMSI</button></div></div>` : "";
  if ($("aMmsiSug")) $("aMmsiSug").innerHTML = sug;
  const bs = s.boat || {}, td = bs.depth_offset_src === "sounder" ? `the sounder reports ${(+bs.depth_offset).toFixed(2)} m` : "used when the sounder does not report it";
  if ($("aTdHint")) $("aTdHint").textContent = td;
  // never rebuild under the user's hands: unsaved changes, or a field (an open colour picker) in use
  const form = $("aSetForm"), busyForm = form && (form.contains(document.activeElement) || form.dataset.picking === "1");
  if (setBuilt && (setDirty || busyForm)) return; setBuilt = true;
  const field = ([k, l, h, lo, hi, step, u]) => lo === undefined ? `<div class="row"><div class="k"><b>${l}</b>${h ? `<small>${h}</small>` : ""}</div>${D.sw("as-" + k, v[k])}</div>`
    : `<div class="row"><div class="k"><b>${l}</b><small ${k === "transducer_depth" ? 'id="aTdHint"' : ""}>${k === "transducer_depth" ? td : h}</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="as-${k}" min="${lo}" max="${hi}" step="${step}" value="${v[k]}" required><span class="u">${u}</span></label></div>`;
  const group = g => SET.filter(x => x[7] === g).map(field).join("");
  box.innerHTML = `<form id="aSetForm" novalidate><div class="grid g2">
    <div class="stack"><div class="card"><div class="hd"><h3>Alarms</h3></div><div class="rows">${group("Alarms")}</div></div>
      <div class="card"><div class="hd"><h3>Push alerts</h3></div><div class="rows">${D.notifyRows("as-push-", PUSH_EV, pushPrefs(v), {fixed: {drag: 2}})}</div></div>
      <div class="card"><div class="hd"><h3>Boat</h3></div><div class="rows">
        <div class="row"><div class="k"><b>My MMSI</b><small>Never shown as an AIS target; 9 digits or empty</small></div><input class="u-w-130 field" id="as-own_mmsi" inputmode="numeric" maxlength="9" value="${esc(v.own_mmsi)}"></div>
        <div id="aMmsiSug">${sug}</div>${group("Boat")}</div></div></div>
    <div class="stack"><div class="card"><div class="hd"><h3>Other</h3></div><div class="rows">${group("Other")}
        <div class="row"><div class="k"><b>Position format</b></div><select class="field" id="as-pos_format"><option value="dmm">DD° MM.mmm′</option><option value="dms">DD° MM′ SS.s″</option><option value="dd">DD.ddddd°</option></select></div>
        <div class="row col"><div class="u-d-flex u-jc-between u-gap-10 u-ai-center"><div class="k"><b>Minimum chain formula</b></div><input class="u-w-150 field" id="as-chain_formula" value="${esc(v.chain_formula)}" autocomplete="off" spellcheck="false"></div>
          <span class="hint">D = max water depth next 24 h, B = bow height, LOA. Numbers, + − * / (or x) and brackets, e.g. 3*D + LOA or 5*(D+B). Rounded up to whole metres.</span></div></div></div>
      <div class="card"><div class="hd"><h3>Network GPS</h3></div><div class="rows">${group("GPS")}</div></div>
      <div class="card"><div class="hd"><h3>Map colours</h3></div><div class="rows">
        <div class="row"><span class="k"></span><span class="colpair"><span class="colhd">Light</span><span class="colhd">Dark</span></span></div>
        ${COLS.map(([k, l]) => `<div class="row"><span class="k"><b>${l}</b></span><span class="colpair">${["light", "dark"].map(t => `<input class="colpick" type="color" id="as-col_${k}_${t}" value="${esc(v[`col_${k}_${t}`] || "#000000")}" aria-label="${l}, ${t}">`).join("")}</span></div>`).join("")}
        <div class="row"><span class="hint">The anchor circle is orange while you move it and red during an alarm. Night keeps its own reds.</span></div></div></div>
      <div class="u-d-flex u-gap-10 u-ai-center card pad"><span class="u-flex-1 hint" id="aSetMsg"></span><button class="btn" type="submit" id="aSetSave" disabled>Save settings</button></div></div>
  </div></form>`;
  $("as-pos_format").value = v.pos_format; validate();
}
function validate() {
  let msg = "";
  for (const [k, l, , lo, hi] of SET) { if (lo === undefined) continue; const el = $("as-" + k), x = +el.value, bad = el.value === "" || !isFinite(x) || x < lo || x > hi;
    el.classList.toggle("invalid", bad); if (bad && !msg) msg = `${l}: ${lo}–${hi}`; }
  const mm = $("as-own_mmsi").value.trim(); if (!msg && mm && !/^\d{9}$/.test(mm)) msg = "My MMSI must be 9 digits (or empty)";
  if (!msg && !$("as-chain_formula").value.trim()) msg = "Chain formula is empty";
  $("aSetMsg").textContent = msg || (setDirty ? "Unsaved changes" : ""); $("aSetMsg").className = "hint" + (msg ? " badc" : "");
  $("aSetSave").disabled = !setDirty || !!msg; return !msg;
}
async function save() {
  if (!validate()) return;
  const cur = m.state.data.settings, out = {};
  for (const [k, , , lo] of SET) { const el = $("as-" + k), v = lo === undefined ? el.checked : +el.value; if (v !== cur[k]) out[k] = v; }
  for (const k of ["pos_format", "own_mmsi", "chain_formula"]) { const v = $("as-" + k).value.trim(); if (v !== cur[k]) out[k] = v; }
  for (const [k] of COLS) for (const t of ["light", "dark"]) { const id = `col_${k}_${t}`, v = $("as-" + id).value.toLowerCase(); if (v !== cur[id]) out[id] = v; }
  for (const [k, p] of Object.entries(D.readNotify("as-push-", PUSH_EV))) {
    if (p.sound !== cur[`push_sound_${k}`]) out[`push_sound_${k}`] = p.sound;
    if (p.priority !== undefined && p.priority !== cur[`push_prio_${k}`]) out[`push_prio_${k}`] = p.priority;
  }
  try { await D.run(m, $("aSetSave"), () => D.api("anchor", "/api/command", {action: "settings", settings: out}), "Settings saved"); setDirty = false; setBuilt = false; } catch (e) {}
}

// ---------------------------------------------------------------- commands
const cmd = (body, ok, el) => D.run(m, el, () => D.api("anchor", "/api/command", body), ok).catch(() => {});
async function onClick(e) {
  const b = e.target.closest("button"); if (!b) return;
  if (b.id === "aCreditsBtn") { view = "gps"; if (draft) setMove(false); m.render(); const c = $("aCredits"); if (c) c.scrollIntoView({block: "center"}); return; }
  if (b.dataset.aview) { view = b.dataset.aview; if (draft) setMove(false); m.render(); return; }
  if (b.dataset.base && map) { map.removeLayer(layers[base]); base = b.dataset.base; layers[base].addTo(map); if (layers[base].bringToBack) layers[base].bringToBack();
    document.querySelectorAll("#aBase button").forEach(x => x.setAttribute("aria-pressed", x.dataset.base === base)); return; }
  if (b.id === "aSea" && map) { const on = !map.hasLayer(layers.seamark); on ? layers.seamark.addTo(map) : map.removeLayer(layers.seamark); b.setAttribute("aria-pressed", on);
    try { localStorage.setItem("drifter-seamarks", on ? "1" : "0"); } catch (x) {} return; }
  if (b.id === "aFit") { follow = true; if (m.state.data) fit(m.state.data); return; }
  if (b.id === "aWindy") { const s = m.state.data, q = s && ((s.boat || {}).pos || s.anchor), c = q ? {lat: q.lat, lng: q.lon} : map.getCenter();
    const la = c.lat.toFixed(4), lo = c.lng.toFixed(4); window.open(`https://www.windy.com/${la}/${lo}?${la},${lo},10`, "_blank", "noopener"); return; }
  if (b.dataset.nudge) return nudge(b.dataset.nudge, 1);
  if (b.id === "aMove") return setMove(!draft);
  if (b.id === "aMoveCancel") return setMove(false);
  if (b.id === "aMoveSave") return saveMove();
  if (b.id === "aNewTrack") { if (await D.confirm({title: "Start a new track?", text: "The recorded track and the max swing are deleted.", ok: "Start new track", cancel: "Keep it", danger: true})) cmd({action: "clear_track"}, "New track started", b); return; }
  if (b.dataset.dmode) { dropMode = b.dataset.dmode; document.querySelectorAll("#aDropMode button").forEach(x => x.setAttribute("aria-pressed", x.dataset.dmode === dropMode)); $("aAheadRow").hidden = dropMode !== "ahead"; return; }
  if (b.id === "aUseScope") { $("aDropRad").value = b.dataset.r; return; }
  if (b.id === "aDrop") {
    const rad = +$("aDropRad").value, dist = +$("aAhead").value;
    if (!(rad >= 5 && rad <= 2000) || (dropMode === "ahead" && !(dist >= 0 && dist <= 2000))) return D.toast("Radius 5–2000 m, distance 0–2000 m", true);
    if (!soundOn) setSound(true);        // the watch is starting: let this device sound too (this tap allows audio)
    follow = true; $("aCtl").dataset.mode = "";
    return cmd({action: "drop", mode: dropMode, distance: dist, radius: rad}, "Anchor down — watch started", b);
  }
  if (b.dataset.rad) { const a = m.state.data.anchor; return cmd({action: "radius", radius: Math.max(5, Math.min(2000, a.radius + +b.dataset.rad))}, null, b); }
  if (b.dataset.silence) return cmd({action: "silence", minutes: +b.dataset.silence}, `Alarm silenced for ${b.dataset.silence} min`, b);
  if (b.id === "aRaise") { if (await D.confirm({title: "Anchor up?", text: "This stops the watch.", ok: "Anchor up – stop watch", cancel: "Keep watching", danger: true})) { $("aCtl").dataset.mode = ""; setMove(false); cmd({action: "raise"}, "Anchor up — watch stopped", b); } return; }
  if (b.id === "aAlarmTest") { if (await D.confirm({title: "Send a real test alarm?", text: "Your phone rings every 30 s until you tap Acknowledge in Pushover or press Stop test alarm (at most 10 minutes).", ok: "Send test alarm", cancel: "Cancel"}))
    cmd({action: "push_alarm_test"}, "Test alarm sent", b); return; }
  if (b.dataset.act) return cmd({action: b.dataset.act}, {push_test: "Test push sent", push_alarm_stop: "Test alarm stopped", alive_check: "Ping sent", net_ais_check: "Reconnecting internet AIS", nfl_send: "Upload requested"}[b.dataset.act] || "Sent", b);
  if (b.dataset.mmsi) { const mm = b.dataset.mmsi; await cmd({action: "settings", settings: {own_mmsi: mm}}, "My MMSI saved", b); if ($("as-own_mmsi")) $("as-own_mmsi").value = mm; return; }
  if (b.id === "aGpsDefault") return saveOrder(m.state.data.gps_default);
  if (b.dataset.gmove) { const rows = m.state.data.gps_rows, i = +b.dataset.gmove, j = i + +b.dataset.d; if (j < 0 || j >= rows.length) return;
    const src = rows.map(r => r.source); [src[i], src[j]] = [src[j], src[i]]; [rows[i], rows[j]] = [rows[j], rows[i]]; renderGps(m.state.data); return saveOrder(src.join(",")); }
  if (b.dataset.forget) { const r = (m.state.data.gps_rows || []).find(x => x.source === b.dataset.forget);
    if (r && await D.confirm({title: `Remove ${r.name}?`, text: "It comes back if it is seen again.", ok: "Remove", cancel: "Keep"})) cmd({action: "gps_forget", source: r.source}, `${r.name} removed`, b); return; }
}
const saveOrder = order => cmd({action: "settings", settings: {gps_sources: order}}, "GPS order saved");
D.register(m);
