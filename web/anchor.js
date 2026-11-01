// Anchor watch module: Orca Core 2 anchor alarm. All alarm logic (drag, frozen GPS, Core, AIS, depth, wind) runs on
// the anchor watch server; this page only shows the state and sends commands (drop, move, radius, raise, silence, settings).
"use strict";
(() => {
  const D = Drifter, {$, esc, num, hm, hms, dayTime, icon} = D;
  const SET = [   // [key, label, hint, min, max, step, unit]; bools have no limits. Limits = the server's SETTING_LIMITS.
    ["default_radius", "Default radius", "Used when dropping without a radius", 5, 2000, 1, "m"],
    ["confirm_s", "Drag confirmation", "Outside the circle this long before the alarm", 0, 600, 1, "s"],
    ["gps_timeout_s", "GPS alarm after", "No usable position for this long", 5, 600, 1, "s"],
    ["core_timeout_s", "Core alarm after", "No data from the Orca Core for this long", 5, 600, 1, "s"],
    ["min_depth", "Shallow water alarm", "0 = off", 0, 500, 0.1, "m"],
    ["max_wind_kn", "Wind alarm", "True wind speed, 0 = off", 0, 150, 1, "kn"],
    ["min_ais_dist", "AIS proximity alarm", "While anchored, 0 = off", 0, 2000, 1, "m"],
    ["bow_offset", "Bow offset", "GPS antenna to bow roller", -50, 50, 0.1, "m"],
    ["track_hours", "Track length", "", 1, 72, 1, "h"],
    ["alive_minutes", "Still-alive check", "Alert from outside after this long without a sign of life, 0 = off", 0, 1440, 1, "min"],
    ["bow_height", "Bow height", "Waterline to bow roller, for the chain advice", 0, 10, 0.1, "m"],
    ["loa", "Length over all", "For chain formulas that use LOA", 0, 100, 0.1, "m"],
    ["draught", "Draught", "Keel below the waterline, 0 = off", 0, 10, 0.1, "m"],
    ["pc_sound", "Sound on the PC", "Beep on the boat PC while an alarm sounds"],
    ["push_alerts", "Push alerts", "Alarms to the phone through Pushover"],
    ["internet_ais", "Internet AIS", "Add targets from aisstream.io (the local receiver always wins)"],
    ["nfl_tracking", "noforeignland tracking", "Send the track to noforeignland.com"],
  ];
  const GPS_ST = {in_use: ["ok", "in use"], active: ["ok", "active"], hold: ["warn", "hold"], raw: ["", "own fix"], frozen: ["bad", "frozen"], away: ["warn", "away"], inactive: ["", "inactive"], never: ["", "not seen"]};
  let L = null, map = null, layers = {}, base = "osm", seamarks = true, follow = true, moving = false;
  let boatMk = null, anchorMk = null, circle = null, trackLine = null, aisLayer = null, track = [], trackGen = -1, trackT = 0, setDirty = false, setBuilt = false, view = "watch";

  const m = {
    id: "anchor", title: "Anchor watch", short: "Anchor", icon: "anchor", every: 2000, background: 5000, always: true,
    async load() {
      m.state.data = await D.api("anchor", "/api/state");
      if (D.visibleIs("anchor") && map) {
        const s = m.state.data;
        if (s.track_gen !== trackGen) { track = []; trackT = 0; }
        if (Date.now() - (m._tt || 0) > 10000 || s.track_gen !== trackGen) {
          m._tt = Date.now();
          try { const t = await D.api("anchor", `/api/track?since=${trackT}&gen=${trackGen}`); if (t.gen !== trackGen) track = [];
            trackGen = t.gen; track.push(...t.points); if (track.length) trackT = track[track.length - 1][0]; } catch (e) {}
        }
      }
    },
    badge() {
      const s = m.state.data; if (!s) return null;
      if ((s.alarms || []).length) return "bad";
      if (s.anchor && (!s.core.connected || s.gps_age == null || s.gps_age > 10)) return "warn";
      return null;
    },
    tile() {
      const s = m.state.data; if (!s) return `<div class="line">${esc(m.state.err.message)}</div>`;
      const a = s.anchor, b = s.boat || {};
      if ((s.alarms || []).length) return `<div class="big badc" style="font-size:22px">${esc(s.alarms.map(x => x.text).join(" · "))}</div><div class="line">${esc(s.alarms[0].detail || "")}</div>`;
      return `<div class="big" style="font-size:22px">${a ? `${num(s.distance)} <small>/ ${num(a.radius)} m</small>` : "Not anchored"}</div>
        <div class="line">${a ? `Watching since ${dayTime(a.set_at)} · max ${num(s.max_dist)} m` : s.core.connected ? "Orca Core connected" : "Orca Core not connected"}</div>
        <div class="minis"><div class="mini"><div class="l">Depth</div><div class="n">${b.depth != null ? num(b.depth, 1) + " m" : "–"}</div></div>
        <div class="mini"><div class="l">Wind</div><div class="n">${b.tws != null ? num(b.tws) + " kn" : "–"}</div></div>
        <div class="mini"><div class="l">GPS</div><div class="n ${s.gps_age == null || s.gps_age > 10 ? "warnc" : ""}">${s.gps_age == null ? "none" : s.gps_age < 5 ? "live" : D.dur(s.gps_age)}</div></div></div>`;
    },
    mount(el) {
      el.innerHTML = `<div id="aDown"></div>
        <div class="seg" style="margin:4px 0 14px;max-width:460px" id="aViews"><button type="button" data-aview="watch" aria-pressed="true">Watch</button><button type="button" data-aview="info" aria-pressed="false">GPS &amp; AIS</button><button type="button" data-aview="settings" aria-pressed="false">Settings</button></div>
        <div id="aWatch"><div class="grid g2l">
          <div class="stack"><div class="map no-swipe" id="aMap"><div class="mapbtns">
            <button class="btn" type="button" id="aFollow" aria-pressed="true">Follow</button><button class="btn" type="button" id="aBase">Satellite</button>
            <button class="btn" type="button" id="aSea" aria-pressed="true">Seamarks</button><button class="btn" type="button" id="aMove" aria-pressed="false" hidden>Move anchor</button></div></div></div>
          <div class="stack">
            <div class="hero" id="aHero"><div class="lamp"></div><div class="grow"><b id="aHeroT">Loading…</b><span id="aHeroS"></span></div></div>
            <div class="stats" id="aStats"></div>
            <div class="card pad" id="aCtl"></div>
            <div class="card"><div class="hd">${icon("wave")}<h3>Depth &amp; tide</h3></div><div class="rows" id="aTide"></div></div>
          </div></div>
          <h2 class="sec">Events</h2><div class="card"><div class="log" id="aLog"></div></div></div>
        <div id="aInfo" hidden></div><div id="aSet" hidden></div>`;
      el.addEventListener("click", onClick);
      el.addEventListener("input", e => { if (e.target.closest("#aSetForm")) { setDirty = true; validate(); } });
      el.addEventListener("change", e => { if (e.target.closest("#aSetForm")) { setDirty = true; validate(); } });
      el.addEventListener("submit", e => { if (e.target.id === "aSetForm") { e.preventDefault(); save(); } });
      loadLeaflet().then(initMap).catch(e => { $("aMap").insertAdjacentHTML("beforeend", `<div class="empty">Map not available: ${esc(e.message)}</div>`); });
      window.addEventListener("drifter-theme", () => map && map.invalidateSize());
    },
    render() {
      $("aDown").innerHTML = m.state.err ? D.downCard(m) + '<div style="height:12px"></div>' : "";
      document.querySelectorAll("#aViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.aview === view));
      $("aWatch").hidden = view !== "watch"; $("aInfo").hidden = view !== "info"; $("aSet").hidden = view !== "settings";
      const s = m.state.data; if (!s) return;
      if (view === "watch") renderWatch(s); else if (view === "info") renderInfo(s); else renderSettings(s);
    },
  };

  // ------------------------------------------------------------------ map
  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "api/anchor/vendor/leaflet/leaflet.css"; document.head.appendChild(css);
    return new Promise((res, rej) => { const s = document.createElement("script"); s.src = "api/anchor/vendor/leaflet/leaflet.js";
      s.onload = () => res(window.L); s.onerror = () => rej(new Error("Leaflet could not be loaded from the anchor watch")); document.head.appendChild(s); });
  }
  function initMap(lib) {
    L = lib;
    map = L.map("aMap", {zoomControl: true, attributionControl: true, tap: true}).setView([52.37, 4.9], 16);
    layers.osm = L.tileLayer("api/anchor/tiles/osm/{z}/{x}/{y}.png", {maxZoom: 21, maxNativeZoom: 19, attribution: "© OpenStreetMap"});
    layers.satellite = L.tileLayer("api/anchor/tiles/satellite/{z}/{x}/{y}.jpg", {maxZoom: 21, maxNativeZoom: 19, attribution: "Esri World Imagery"});
    layers.seamark = L.tileLayer("api/anchor/tiles/seamark/{z}/{x}/{y}.png", {maxZoom: 21, maxNativeZoom: 18, attribution: "OpenSeaMap"});
    map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>');
    layers.osm.addTo(map); layers.seamark.addTo(map);
    trackLine = L.polyline([], {color: "var(--accent)", weight: 3, opacity: .75}).addTo(map);
    aisLayer = L.layerGroup().addTo(map);
    map.on("dragstart", () => { follow = false; $("aFollow").setAttribute("aria-pressed", "false"); });
    map.on("click", onMapClick);
    if (m.state.data) renderWatch(m.state.data);
    D.poll(m, true);
  }
  const boatSvg = h => `<svg viewBox="0 0 40 40" width="40" height="40" style="transform:rotate(${h || 0}deg)"><path d="M20 3 29 33 20 27 11 33z" fill="currentColor" stroke="var(--card)" stroke-width="2.5" stroke-linejoin="round"/></svg>`;
  function drawMap(s) {
    if (!map) return;
    const b = s.boat || {}, a = s.anchor, pos = b.pos;
    if (pos) {
      const icn = L.divIcon({className: "boaticon", html: boatSvg(b.heading), iconSize: [40, 40], iconAnchor: [20, 20]});
      if (!boatMk) boatMk = L.marker([pos.lat, pos.lon], {icon: icn, keyboard: false, interactive: false}).addTo(map);
      else { boatMk.setLatLng([pos.lat, pos.lon]); boatMk.setIcon(icn); }
    }
    if (a) {
      const col = (s.alarms || []).some(x => x.id === "drag") ? getComputedStyle(document.body).getPropertyValue("--bad") : getComputedStyle(document.body).getPropertyValue("--ok");
      if (!circle) circle = L.circle([a.lat, a.lon], {radius: a.radius, weight: 2, fillOpacity: .08}).addTo(map);
      circle.setLatLng([a.lat, a.lon]); circle.setRadius(a.radius); circle.setStyle({color: col, fillColor: col});
      const ai = L.divIcon({className: "boaticon", html: `<svg viewBox="0 0 24 24" width="26" height="26" class="i" style="width:26px;height:26px;color:${col}"><use href="#i-anchor"/></svg>`, iconSize: [26, 26], iconAnchor: [13, 13]});
      if (!anchorMk) anchorMk = L.marker([a.lat, a.lon], {icon: ai, interactive: false}).addTo(map); else { anchorMk.setLatLng([a.lat, a.lon]); anchorMk.setIcon(ai); }
    } else { if (circle) { circle.remove(); circle = null; } if (anchorMk) { anchorMk.remove(); anchorMk = null; } }
    trackLine.setLatLngs(track.map(p => [p[1], p[2]]));
    trackLine.setStyle({color: getComputedStyle(document.body).getPropertyValue("--accent").trim()});
    aisLayer.clearLayers();
    for (const t of s.ais || []) {
      const ic = L.divIcon({className: "", html: `<svg viewBox="0 0 20 20" width="20" height="20" style="transform:rotate(${t.heading ?? t.cog ?? 0}deg);color:var(--load)"><path d="M10 2 15 17 10 14 5 17z" fill="currentColor" opacity=".85"/></svg>`, iconSize: [20, 20], iconAnchor: [10, 10]});
      L.marker([t.lat, t.lon], {icon: ic}).bindTooltip(`${esc(t.name || t.mmsi)} · ${num(t.dist)} m${t.sog != null ? ` · ${t.sog} kn` : ""}`).addTo(aisLayer);
    }
    if (follow && (pos || a)) {
      const c = pos ? [pos.lat, pos.lon] : [a.lat, a.lon];
      if (!m._fitted && a && pos) { map.fitBounds(L.latLng(a.lat, a.lon).toBounds(a.radius * 2.6)); m._fitted = true; }
      else if (!m._fitted) { map.setView(c, 17); m._fitted = true; }
      else map.panTo(c, {animate: true});
    }
  }
  async function onMapClick(e) {
    if (!moving) return;
    const {lat, lng} = e.latlng;
    if (await D.confirm({title: "Move the anchor here?", text: `${lat.toFixed(6)}, ${lng.toFixed(6)}`, ok: "Move anchor", cancel: "Cancel", safeDefault: false}))
      await cmd({action: "move", lat, lon: lng}, "Anchor position moved");
    moving = false; $("aMove").setAttribute("aria-pressed", "false"); $("aMove").textContent = "Move anchor";
  }

  // ------------------------------------------------------------------ watch view
  function renderWatch(s) {
    const a = s.anchor, b = s.boat || {}, alarms = s.alarms || [];
    let cls = "", t = "Not anchored", sub = s.core.connected ? "Drop the anchor to start the watch" : "Orca Core not connected";
    if (alarms.length) { cls = "bad"; t = alarms.map(x => x.text).join(" · "); sub = alarms[0].detail || `since ${hms(alarms[0].since)}`;
      if (s.silenced_until && s.silenced_until * 1000 > Date.now()) sub = `Silenced until ${hm(s.silenced_until)} · ` + sub; }
    else if (a) { const p = Object.keys(s.pending || {}); cls = p.length ? "warn" : "ok"; t = p.length ? `Checking: ${p.join(", ")}` : "Anchor watch on";
      sub = `Since ${dayTime(a.set_at)} · radius ${num(a.radius)} m${a.depth != null ? ` · dropped in ${num(a.depth, 1)} m` : ""}`; }
    $("aHero").className = "hero " + cls; $("aHeroT").textContent = t; $("aHeroS").textContent = sub;
    const pos = b.pos;
    $("aStats").innerHTML = [
      ["Distance", a && s.distance != null ? `${num(s.distance)}<small>m</small>` : "–", a ? `of ${num(a.radius)} m · max ${num(s.max_dist)} m` : ""],
      ["Bearing", a && s.bearing != null ? `${num(s.bearing)}<small>°</small>` : "–", "from the anchor"],
      ["Depth", b.depth != null ? `${num(b.depth, 1)}<small>m</small>` : "–", s.depth_plan && s.depth_plan.clearance_min != null ? `min under keel ${num(s.depth_plan.clearance_min, 1)} m` : ""],
      ["Wind", b.tws != null ? `${num(b.tws)}<small>kn</small>` : "–", b.twd != null ? `from ${num(b.twd)}°` : ""],
      ["Heading", b.heading != null ? `${num(b.heading)}<small>°</small>` : "–", b.sog != null ? `${num(b.sog, 1)} kn` : ""],
      ["GPS", s.gps_age == null ? "none" : s.gps_age < 5 ? "live" : D.dur(s.gps_age), pos ? esc(pos.name || pos.source || "") : ""],
    ].map(([l, n, x]) => `<div class="stat"><div class="l">${l}</div><div class="n">${n}</div><div class="s">${x}</div></div>`).join("");
    const silenced = s.silenced_until && s.silenced_until * 1000 > Date.now();
    $("aCtl").innerHTML = a ? `
      ${alarms.length ? `<div class="btns eq" style="margin-bottom:10px"><button class="btn danger" type="button" data-silence="5">${silenced ? "Silenced" : "Silence 5 min"}</button><button class="btn sec" type="button" data-silence="15">15 min</button></div>` : ""}
      <div class="row" style="border:0;padding-top:0"><div class="k"><b>Radius</b><small>Now ${num(a.radius)} m</small></div>
        <div style="display:flex;gap:6px;align-items:center"><div class="stepper"><button type="button" data-rad="-5" aria-label="Smaller">−</button><output class="num" id="aRad">${m._rad ?? Math.round(a.radius)} m</output><button type="button" data-rad="5" aria-label="Larger">+</button></div>
        <button class="btn sm" type="button" id="aRadSet" ${m._rad == null || m._rad === Math.round(a.radius) ? "disabled" : ""}>Set</button></div></div>
      <div class="btns eq" style="margin-top:6px"><button class="btn sec" type="button" id="aRaise">Raise anchor</button></div>`
      : `<div class="btns eq"><button class="btn" type="button" id="aDrop" ${pos ? "" : "disabled"}>${icon("anchor")} Drop anchor</button></div>${pos ? "" : `<p class="hint" style="margin:8px 2px 0">No GPS position: the anchor cannot be dropped.</p>`}`;
    $("aMove").hidden = !a;
    const dp = s.depth_plan || {}, td = s.tide || {};
    $("aTide").innerHTML = `
      <div class="row"><span class="k">Depth next 24 h</span><span class="v">${dp.available ? `${num(dp.min, 1)} – ${num(dp.max, 1)} m<small>${esc(dp.source || "")}</small>` : `<small>${esc(dp.reason || "–")}</small>`}</span></div>
      <div class="row"><span class="k">Chain advice</span><span class="v">${dp.available && dp.chain != null ? `${typeof dp.chain === "object" ? num(dp.chain.m ?? dp.chain.length ?? dp.chain.value) : num(dp.chain)} m<small>${esc(dp.formula || "")}</small>` : "–"}</span></div>
      <div class="row"><span class="k">Tide</span><span class="v">${td.available ? `${num(td.level, 2)} m ${esc(td.trend || "")}<small>${(td.next || []).map(e => `${e.type} ${hm(e.t)} (${num(e.h, 2)} m)`).join(" · ")}</small>` : `<small>${esc(td.error || "not available")}</small>`}</span></div>`;
    $("aLog").innerHTML = (s.events || []).slice().reverse().map(e => `<div class="${e.kind === "alarm" ? "bad" : e.kind === "warn" ? "warn" : ""}"><time>${dayTime(e.t)}</time><span class="msg">${esc(e.text)}</span></div>`).join("") || `<div class="empty">No events</div>`;
    drawMap(s);
  }

  // ------------------------------------------------------------------ GPS & AIS view
  function renderInfo(s) {
    const st = x => GPS_ST[x] || ["", x];
    $("aInfo").innerHTML = `<div class="grid g2">
      <div class="stack"><div class="card"><div class="hd">${icon("anchor")}<h3>GPS sources</h3></div><div class="rows">
        ${(s.gps_rows || []).map(g => `<div class="row"><div class="k"><b>${esc(g.name)}</b><small>source ${esc(g.source)}${g.sats != null ? ` · ${g.sats} sats` : ""}${g.hdop != null ? ` · HDOP ${num(g.hdop, 1)}` : ""}${g.last_seen != null ? ` · seen ${D.dur(g.last_seen)} ago` : ""}</small></div><span class="badge ${st(g.status)[0]}">${st(g.status)[1]}</span></div>`).join("") || `<div class="empty">No GPS seen</div>`}
      </div></div>
      <div class="card"><div class="hd"><h3>Connections</h3></div><div class="rows">
        <div class="row"><span class="k">Orca Core</span><span class="v">${s.core.connected ? '<span class="good">Connected</span>' : `<span class="badc">Not connected</span><small>${esc(s.core.last_error || "")}</small>`}</span></div>
        <div class="row"><span class="k">AIS (Core)</span><span class="v">${s.ais_stream.connected ? '<span class="good">Connected</span>' : '<span class="warnc">Not connected</span>'}</span></div>
        <div class="row"><span class="k">Internet AIS</span><span class="v">${!s.net_ais.configured ? "Not set up" : s.net_ais.connected ? `<span class="good">${s.net_ais.ships} ships</span>` : `<span class="warnc">Not connected</span><small>${esc(s.net_ais.last_error || "")}</small>`}</span></div>
        <div class="row"><span class="k">Push alerts</span><span class="v">${s.push.configured ? `<span class="good">Pushover ready</span><small>${s.push.last_error ? esc(s.push.last_error) : ""}</small>` : '<span class="warnc">Not set up</span>'}</span></div>
        <div class="row"><span class="k">Still-alive check</span><span class="v">${s.alive.configured ? `${s.alive.last_ok ? `<span class="good">OK ${hm(s.alive.last_ok)}</span>` : "–"}<small>${esc(s.alive.last_error || s.alive.note || "")}</small>` : "Not set up"}</span></div>
        <div class="row"><span class="k">noforeignland</span><span class="v">${s.nfl.configured ? `${s.nfl.last_ok ? `<span class="good">Sent ${dayTime(s.nfl.last_ok)}</span>` : "–"}<small>${esc(s.nfl.last_error || "")}</small>` : "Not set up"}</span></div>
        <div class="row"><span class="k">Network GPS</span><span class="v">${s.nmea.on ? `port ${s.nmea.port}` : "off"}<small>${esc(s.nmea.error || "")}</small></span></div>
        <div class="row"><span class="k">Anchor watch</span><span class="v">v${esc(s.version)}<small>${s.track_points} track points</small></span></div>
      </div></div></div>
      <div class="card"><div class="hd"><h3>AIS targets</h3><span class="muted">${(s.ais || []).length}</span></div><div class="rows">
        ${(s.ais || []).slice().sort((x, y) => x.dist - y.dist).slice(0, 40).map(t => `<div class="row"><div class="k"><b>${esc(t.name || t.mmsi)}</b><small>${esc(t.mmsi)}${t.length ? ` · ${num(t.length)} m` : ""} · ${t.src === "local" ? "own receiver" : "internet"}</small></div>
          <span class="v">${num(t.dist)} m<small>${num(t.bearing)}°${t.sog != null ? ` · ${t.sog} kn` : ""}</small></span></div>`).join("") || `<div class="empty">No AIS targets</div>`}
      </div></div></div>
      <h2 class="sec">Tests</h2><div class="card pad btns"><button class="btn sec sm" data-act="push_test" type="button">Test push</button><button class="btn sec sm" data-act="push_alarm_test" type="button">Test alarm (emergency)</button>
        <button class="btn sec sm" data-act="push_alarm_stop" type="button">Stop test alarm</button><button class="btn sec sm" data-act="alive_check" type="button">Still-alive ping</button></div>`;
  }

  // ------------------------------------------------------------------ settings view
  function renderSettings(s) {
    const box = $("aSet"); if (setBuilt && setDirty) return; setBuilt = true;
    const v = s.settings;
    box.innerHTML = `<form class="card" id="aSetForm" novalidate style="max-width:720px"><div class="rows">
      ${SET.map(([k, l, h, lo, hi, step, u]) => lo === undefined ? `<div class="row"><div class="k"><b>${l}</b><small>${h}</small></div>${D.sw("as-" + k, v[k])}</div>`
        : `<div class="row"><div class="k"><b>${l}</b>${h ? `<small>${h}</small>` : ""}</div><label class="numf"><input class="field" type="number" inputmode="decimal" id="as-${k}" min="${lo}" max="${hi}" step="${step}" value="${v[k]}" required><span class="u">${u}</span></label></div>`).join("")}
      <div class="row"><div class="k"><b>Position format</b></div><select class="field" id="as-pos_format"><option value="dmm">DD° MM.mmm′</option><option value="dms">DD° MM′ SS.s″</option><option value="dd">DD.ddddd°</option></select></div>
      <div class="row"><div class="k"><b>My MMSI</b><small>Never shown as a target; 9 digits or empty</small></div><input class="field" id="as-own_mmsi" inputmode="numeric" maxlength="9" style="width:130px" value="${esc(v.own_mmsi)}"></div>
      <div class="row"><div class="k"><b>Chain formula</b><small>D = max depth next 24 h, B = bow height, LOA</small></div><input class="field" id="as-chain_formula" style="width:150px" value="${esc(v.chain_formula)}"></div>
      <div class="row"><span class="hint" id="aSetMsg"></span><button class="btn" type="submit" id="aSetSave" disabled>Save</button></div></div></form>
      <p class="hint" style="margin:10px 4px">GPS source order, network GPS port and the other advanced settings are on the classic anchor page.</p>`;
    $("as-pos_format").value = v.pos_format; validate();
  }
  function validate() {
    let msg = "";
    for (const [k, l, , lo, hi] of SET) { if (lo === undefined) continue; const el = $("as-" + k), x = +el.value, bad = el.value === "" || !isFinite(x) || x < lo || x > hi;
      el.classList.toggle("invalid", bad); if (bad && !msg) msg = `${l}: ${lo}–${hi}`; }
    const mm = $("as-own_mmsi").value.trim(); if (!msg && mm && !/^\d{9}$/.test(mm)) msg = "My MMSI must be 9 digits (or empty)";
    $("aSetMsg").textContent = msg || (setDirty ? "Unsaved changes" : ""); $("aSetMsg").className = "hint" + (msg ? " badc" : "");
    $("aSetSave").disabled = !setDirty || !!msg; return !msg;
  }
  async function save() {
    if (!validate()) return;
    const cur = m.state.data.settings, out = {};
    for (const [k, , , lo] of SET) { const el = $("as-" + k), v = lo === undefined ? el.checked : +el.value; if (v !== cur[k]) out[k] = v; }
    for (const k of ["pos_format", "own_mmsi", "chain_formula"]) { const v = $("as-" + k).value.trim(); if (v !== cur[k]) out[k] = v; }
    try { await D.run(m, $("aSetSave"), () => D.api("anchor", "/api/command", {action: "settings", settings: out}), "Settings saved"); setDirty = false; setBuilt = false; } catch (e) {}
  }

  // ------------------------------------------------------------------ commands
  const cmd = (body, ok, el) => D.run(m, el, () => D.api("anchor", "/api/command", body), ok).catch(() => {});
  async function drop() {
    const s = m.state.data, r0 = s.settings.default_radius;
    const v = await D.sheet(`<h3 id="dlgTitle">${icon("anchor")} Drop anchor</h3><p>The watch starts at once. Radius: the boat may swing this far from the anchor.</p>
      <div class="rows" style="padding:0"><div class="row"><span class="k">Anchor position</span><select class="field" id="dMode"><option value="here">At the bow now</option><option value="ahead">Ahead of the bow</option></select></div>
      <div class="row" id="dAheadRow" hidden><span class="k">Distance ahead</span><label class="numf"><input class="field" type="number" id="dDist" min="0" max="2000" value="20" inputmode="decimal"><span class="u">m</span></label></div>
      <div class="row"><span class="k">Radius</span><label class="numf"><input class="field" type="number" id="dRad" min="5" max="2000" value="${r0}" inputmode="decimal"><span class="u">m</span></label></div></div>
      <div class="acts"><button class="btn" data-value="ok" data-default>Drop anchor</button><button class="btn sec" data-value="cancel">Cancel</button></div>`);
    if (v !== "ok") return;
  }
  document.addEventListener("change", e => { if (e.target.id === "dMode") $("dAheadRow").hidden = e.target.value !== "ahead"; });
  // read the drop sheet's fields before it closes
  document.addEventListener("click", e => {
    const b = e.target.closest('#dlgSheet [data-value="ok"]'); if (!b || !$("dRad")) return;
    const rad = +$("dRad").value, mode = $("dMode").value, dist = +$("dDist").value;
    if (!(rad >= 5 && rad <= 2000) || (mode === "ahead" && !(dist >= 0 && dist <= 2000))) { e.stopPropagation(); D.toast("Radius 5–2000 m, distance 0–2000 m", true); return; }
    cmd({action: "drop", radius: rad, mode, distance: dist}, "Anchor down — watch started");
  }, true);
  async function onClick(e) {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.aview) { view = b.dataset.aview; m.render(); if (view === "watch" && map) setTimeout(() => map.invalidateSize(), 50); return; }
    if (b.id === "aDrop") return drop();
    if (b.id === "aRaise") { if (await D.confirm({title: "Raise the anchor?", text: "The anchor watch stops.", ok: "Raise anchor", cancel: "Keep watching", danger: true})) cmd({action: "raise"}, "Anchor up — watch stopped", b); return; }
    if (b.dataset.silence) return cmd({action: "silence", minutes: +b.dataset.silence}, `Alarm silenced for ${b.dataset.silence} min`, b);
    if (b.dataset.rad) { const a = m.state.data.anchor; m._rad = Math.max(5, Math.min(2000, (m._rad ?? Math.round(a.radius)) + +b.dataset.rad)); renderWatch(m.state.data); return; }
    if (b.id === "aRadSet") { const r = m._rad; await cmd({action: "radius", radius: r}, `Radius ${r} m`, b); m._rad = null; return; }
    if (b.dataset.act) return cmd({action: b.dataset.act}, "Sent", b);
    if (b.id === "aFollow") { follow = !follow; b.setAttribute("aria-pressed", follow); if (follow && m.state.data) drawMap(m.state.data); return; }
    if (b.id === "aBase" && map) { map.removeLayer(layers[base]); base = base === "osm" ? "satellite" : "osm"; layers[base].addTo(map); layers[base].bringToBack(); b.textContent = base === "osm" ? "Satellite" : "Map"; return; }
    if (b.id === "aSea" && map) { seamarks = !seamarks; seamarks ? layers.seamark.addTo(map) : map.removeLayer(layers.seamark); b.setAttribute("aria-pressed", seamarks); return; }
    if (b.id === "aMove") { moving = !moving; b.setAttribute("aria-pressed", moving); b.textContent = moving ? "Tap the map…" : "Move anchor"; return; }
  }
  D.register(m);
})();
