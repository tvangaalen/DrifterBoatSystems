// Engine log module: diesel fuel fills, engine maintenance and the engine alarms. The log lives on the engine log server
// (data/log.json on the boat PC); this page shows it and sends new, changed and deleted entries. A new fill takes today's
// date, the engine hours (live from the Orca Core, or its last reading) and the boat's position from the anchor watch; a
// new maintenance entry the date and the engine hours: every automatic value can be changed before saving. The engine
// alarms are logged by the server (enginelog/engine.py). Deleting always asks first (Keep is the default).
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, num, icon, pad} = D;
let view = "fuel", edit = null, fuelOpen = false, alarmsOpen = false, schedOpen = false;   // edit: {kind, id (null = new), touched: Set of fields the user changed} while a form is open; fuelOpen: the fuel entry list unfolded

const dmy = (/** @type {string} */ iso) => D.dateText(iso) || "–";
/** A date in the chosen format (System page), typed or picked: the calendar button lies under an invisible native date input,
 * so a tap opens the device's own calendar on every browser. @param {string} id @param {string} iso YYYY-MM-DD */
const dateField = (id, iso) => `<div class="datef"><input class="field lf-date" id="${id}" value="${esc(D.dateText(iso))}" placeholder="${esc(D.dateFmt())}" inputmode="numeric" maxlength="10" autocomplete="off" aria-label="Date (${esc(D.dateFmt())})">
  <span class="pickbtn">${icon("calendar")}<input type="date" id="${id}Pick" value="${iso}" tabindex="-1" aria-label="Pick a date"></span></div>`;
/** Today as YYYY-MM-DD (this device's date). */
const today = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
/** YYYY-MM-DD to local midnight, in ms. @param {string} iso */
const dayMs = iso => new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)).getTime();
const euro = (/** @type {number | null | undefined} */ v) => v == null ? "" : `€ ${num(v, 2)}`;
const boatPos = () => { const a = D.byId.anchor && D.byId.anchor.state.data, p = a && a.boat && a.boat.pos; return p && p.lat != null ? {lat: p.lat, lon: p.lon} : null; };
/** @param {number} v @param {string} pos @param {string} neg */
const dm = (v, pos, neg) => { const a = Math.abs(v), d = Math.floor(a); return `${d}° ${((a - d) * 60).toFixed(3)}′ ${v >= 0 ? pos : neg}`; };
const posText = (/** @type {any} */ p) => p && p.lat != null ? `${dm(p.lat, "N", "S")}  ${dm(p.lon, "E", "W")}` : "No position";
/** Time since a moment, short: minutes, hours, then days. @param {number} t ms */
const since = t => { const d = Math.round((dayMs(today()) - t) / 864e5); return d <= 0 ? "today" : d === 1 ? "1 day" : `${d} days`; };
const auto = (/** @type {string} */ t) => `<span class="autochip">${t}</span>`;
/** Google Maps at a position, in its own browser window. @param {{lat: number, lon: number}} p */
const openMaps = p => window.open(`https://www.google.com/maps/search/?api=1&query=${p.lat.toFixed(6)},${p.lon.toFixed(6)}`, "drifter-maps", "popup,noopener,noreferrer");
const mapsBtn = (/** @type {any} */ p, cls = "") => p && p.lat != null ? `<button class="btn sec sm${cls}" type="button" data-maps="${p.lat},${p.lon}" aria-label="Open in Google Maps">Maps ${icon("ext")}</button>` : "";
/** The engine hours for a new entry: live from the Orca Core, else its last reading. @param {any} d */
function engineHours(d) {
  const e = d.engine || {};
  if (e.fresh && e.hours != null) return {h: Math.round(e.hours * 10) / 10, note: "live from the engine"};
  if (e.last_hours != null) return {h: Math.round(e.last_hours * 10) / 10, note: `engine's last reading${e.last_hours_at ? ", " + D.dayTime(Date.parse(e.last_hours_at)) : ""}`};
  return null;
}
/** The fuel left, estimated: the tank was full at the last fill (always assumed), since then the average use per engine
 * hour over the engine hours run (live, else the last reading). Null without a tank capacity or an average use.
 * @param {any} d @returns {{l: number, h: number, ran: number, cap: number} | null} */
function estimate(d) {
  const s = d.stats || {}, cap = (d.settings || {}).tank_capacity_l, e = d.engine || {}, avg = s.avg_l_per_h;
  if (!cap || !avg || s.last_hours == null) return null;
  const now = e.fresh && e.hours != null ? e.hours : e.last_hours != null ? e.last_hours : s.last_hours;
  const ran = Math.max(0, now - s.last_hours), l = Math.max(0, Math.min(cap, cap - ran * avg));
  return {l, h: l / avg, ran, cap};
}
const estText = (/** @type {any} */ x) => `${num(x.l, 0)} L · ${num(x.h, 0)} h`;
/** The estimate as a line in the Overview tile. @param {any} d */
const estWhy = (/** @type {any} */ d) => !(d.settings || {}).tank_capacity_l ? "set the tank capacity in Settings" : "after two fills";
const estLine = (/** @type {any} */ d) => { const x = estimate(d);
  return `<div class="line">Estimated remaining ${x ? `<b class="est num">${estText(x)}</b>` : `– (${estWhy(d)})`}</div>`; };

const m = {
  id: "enginelog", title: "Engine and fuel", short: "Engine", icon: "enginefuel", background: 120000,
  get every() { return view === "data" ? 2000 : 30000; },      // Current data: live; the lists: slowly
  async load() { m.state.data = await D.api("enginelog", "/api/log"); },
  enter() { view = "fuel"; },      // from the Overview or the navigation: always Diesel fuel
  tile() {
    const d = m.state.data; if (!d) return `<div class="line">${esc(m.state.err.message)}</div>`;
    const f = d.fuel[0], mt = d.maintenance[0], s = d.stats;
    return `<div class="u-fs-22 big">${f ? `${num(f.litres, 0)} L` : "No fills yet"}</div>
      ${estLine(d)}
      <div class="line">${f ? esc(dmy(f.date)) : "Log the next fill on the Engine and fuel page"}${d.engine && d.engine.running ? ` · engine running, ${num(d.engine.rpm, 0)} rpm` : ""}</div>
      <div class="minis"><div class="mini"><div class="l">Engine hours</div><div class="n">${f ? num(f.engine_hours, 0) + " h" : "–"}</div></div>
      <div class="mini"><div class="l">Avg use</div><div class="n">${s.avg_l_per_h != null ? num(s.avg_l_per_h, 1) + " L/h" : "–"}</div></div>
      <div class="mini"><div class="l">Maintenance</div><div class="n">${mt ? esc(dmy(mt.date)) : "–"}</div></div></div>`;
  },
  mount(el) {
    el.innerHTML = `<div id="lDown"></div>
      <div class="u-m-4-0-14 u-maxw-460 seg" id="lViews"><button type="button" data-lview="fuel">Diesel fuel</button><button type="button" data-lview="maintenance">Maintenance</button><button type="button" data-lview="data">Current data</button><button type="button" data-lview="settings">Settings</button></div>
      <div id="lBody"></div>`;
    el.addEventListener("click", onClick);
    el.addEventListener("input", e => { if (edit && e.target.id) edit.touched.add(e.target.id); });
    el.addEventListener("change", e => { const t = e.target; if (t.id && t.id.endsWith("Pick") && t.value) { const f = $(t.id.slice(0, -4)); f.value = D.dateText(t.value); edit && edit.touched.add(f.id); } });
    el.addEventListener("submit", e => { e.preventDefault(); if (e.target.id === "lForm") save(); else if (e.target.id === "lSetForm") saveSettings(); });
    el.addEventListener("toggle", e => { const t = /** @type {HTMLDetailsElement} */ (e.target);
      if (t.id === "lFuelFold") fuelOpen = t.open; else if (t.id === "lAlarmFold") alarmsOpen = t.open; else if (t.id === "lSchedFold") schedOpen = t.open; }, true);
  },
  render() {
    $("lDown").innerHTML = m.state.err ? D.downCard(m) + '<div class="u-h-12"></div>' : "";
    document.querySelectorAll("#lViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.lview === view));
    if (edit) return;                                    // never rebuild an open form under the user's hands
    const d = m.state.data; if (!d) { $("lBody").innerHTML = m.state.err ? "" : `<div class="empty">Loading…</div>`; return; }
    if (view === "settings") { if (!$("lSetForm")) $("lBody").innerHTML = setView(d); return; }    // a form: built once, kept while open
    $("lBody").innerHTML = view === "fuel" ? fuelView(d) : view === "data" ? dataView(d) : maintView(d);
    if (view === "fuel" && $("lChart")) $("lChart").innerHTML = fuelChart(d.fuel, d.stats.avg_l_per_h);     // again at the box's real width
  },
};

// ------------------------------------------------------------------ lists
function fuelView(d) {
  const s = d.stats, x = estimate(d);
  return `<div class="u-maxw-720 card pad">
    <div class="estim"><div class="k"><b>Estimated remaining</b><small>${x ? `Tank full (${num(x.cap, 0)} L) at the last fill, ${num(x.ran, 1)} engine hours since, at ${num(s.avg_l_per_h, 1)} L/h` : esc(estWhy(d)[0].toUpperCase() + estWhy(d).slice(1))}</small></div>
      ${x ? `<div class="v num"><b>${num(x.l, 0)}<small> L</small></b><b>${num(x.h, 0)}<small> h</small></b></div>` : ""}</div>
    <div class="minis u-mt-12"><div class="mini"><div class="l">Last fill</div><div class="n">${s.last_litres != null ? num(s.last_litres, 0) + " L" : "–"}</div></div>
      <div class="mini"><div class="l">Since</div><div class="n">${s.last_date ? since(dayMs(s.last_date)) : "–"}</div></div>
      <div class="mini"><div class="l">Fills</div><div class="n">${s.fills}</div></div></div>
    <div class="minis m4 u-mt-12"><div class="mini"><div class="l">Avg L/h</div><div class="n">${s.avg_l_per_h != null ? num(s.avg_l_per_h, 1) : "–"}</div></div>
      <div class="mini"><div class="l">Litres</div><div class="n">${num(s.litres_total, 0)}</div></div>
      <div class="mini"><div class="l">Avg price</div><div class="n">${s.avg_price != null ? `€ ${num(s.avg_price, 2)}` : "–"}</div></div>
      <div class="mini"><div class="l">Total cost</div><div class="n">${s.amount_total ? `€ ${num(s.amount_total, 0)}` : "–"}</div></div></div>
    <div class="fuelchart" id="lChart">${fuelChart(d.fuel, s.avg_l_per_h)}</div>
    <button class="u-mt-12 btn wide" type="button" data-new="fuel">${icon("fuel")} New fuel entry</button>
    <details class="lfold" id="lFuelFold" ${fuelOpen ? "open" : ""}><summary><b>Fuel entries</b><span class="muted">${d.fuel.length}</span>${icon("chev", "i chev")}</summary>
    <div class="lrows">${d.fuel.map(f => `<div class="lrowx"><button class="lrow" type="button" data-edit="fuel:${esc(f.id)}"><span class="t"><b>${num(f.litres, 0)} L</b> <span class="muted">· ${num(f.engine_hours, 0)} h${f.amount != null ? ` · ${euro(f.amount)} (${euro(f.amount / f.litres)}/L)` : ""}</span>
        <small>${esc(dmy(f.date))}${f.lat != null ? ` · ${esc(posText(f))}` : ""}</small></span>${icon("chev", "i chev")}</button>${mapsBtn(f, " maps")}</div>`).join("")
      || `<div class="empty">No fills logged yet</div>`}</div></details>
    ${s.fills ? `<p class="u-m-8-0-0 hint">${s.fills} fill${s.fills === 1 ? "" : "s"} · ${num(s.litres_total, 0)} L in total. Average use: the litres of every fill after the first over the engine hours since the first.${s.amount_total ? ` Paid: ${euro(s.amount_total)}${s.avg_price != null ? `, on average ${euro(s.avg_price)} per litre` : ""}.` : ""}</p>` : ""}</div>`;
}
// ---- the fills over time: litres per fill as columns (left), the use since the fill before in L per engine hour as a
// smooth line with the average dashed (right). Drawn at the box's own width, so the text never scales.
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** @param {any[]} fuel @param {number | null} avg */
function fuelChart(fuel, avg) {
  const F = fuel.slice().sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : a.engine_hours - b.engine_hours).map(f => ({...f, t: dayMs(f.date)}));
  if (F.length < 2) return `<p class="u-m-8-0-0 hint">The chart appears after two fills.</p>`;
  const box = $("lChart"), W = Math.max(280, Math.round(box ? box.clientWidth : 340)), H = 170, L = 40, R = W - 40, T = 10, B = H - 22;
  const span = F[F.length - 1].t - F[0].t, t0 = F[0].t - span * .04, t1 = F[F.length - 1].t + span * .04, X = (/** @type {number} */ t) => L + (t - t0) / (t1 - t0) * (R - L);
  const maxL = Math.max(...F.map(f => f.litres)), stL = maxL > 400 ? 200 : maxL > 200 ? 100 : 50, topL = Math.ceil(maxL / stL) * stL, YL = (/** @type {number} */ v) => B - v / topL * (B - T);
  const use = F.slice(1).map((f, i) => ({t: f.t, u: f.engine_hours > F[i].engine_hours ? f.litres / (f.engine_hours - F[i].engine_hours) : null})).filter(u => u.u != null);
  const topU = Math.max(2, Math.ceil(Math.max(avg || 0, ...use.map(u => u.u)) / 2) * 2), YU = (/** @type {number} */ v) => B - v / topU * (B - T);
  let g = "";
  for (let v = 0; v <= topL; v += stL) g += `<line class="gl" x1="${L}" x2="${R}" y1="${YL(v)}" y2="${YL(v)}"/><text class="ax" x="${L - 5}" y="${YL(v) + 3.5}" text-anchor="end">${v}${v === topL ? " L" : ""}</text>`;
  for (let v = 0; v <= topU; v += topU / 4) g += `<text class="ax use" x="${R + 5}" y="${YU(v) + 3.5}">${num(v, v % 1 ? 1 : 0)}${v === topU ? " L/h" : ""}</text>`;
  for (let d = new Date(new Date(t0).getFullYear(), new Date(t0).getMonth() + 1, 1); +d <= t1; d.setMonth(d.getMonth() + 1))
    g += `<text class="ax" x="${X(+d)}" y="${H - 6}" text-anchor="middle">${MON[d.getMonth()]}</text>`;
  const bw = Math.max(4, Math.min(14, (R - L) / F.length * .5));
  g += F.map(f => `<rect class="fbar" x="${(X(f.t) - bw / 2).toFixed(1)}" y="${YL(f.litres).toFixed(1)}" width="${bw.toFixed(1)}" height="${(B - YL(f.litres)).toFixed(1)}" rx="2"><title>${esc(`${D.day(f.t)} · ${num(f.litres, 0)} L · ${num(f.engine_hours, 0)} h`)}</title></rect>`).join("");
  if (avg != null) g += `<line class="avg" x1="${L}" x2="${R}" y1="${YU(avg)}" y2="${YU(avg)}"/>`;
  if (use.length) {
    const P = use.map(u => [X(u.t), YU(u.u)]);
    let path = `M${P[0][0].toFixed(1)} ${P[0][1].toFixed(1)}`;
    for (let i = 1; i < P.length; i++) { const m = (P[i - 1][0] + P[i][0]) / 2; path += ` C${m.toFixed(1)} ${P[i - 1][1].toFixed(1)} ${m.toFixed(1)} ${P[i][1].toFixed(1)} ${P[i][0].toFixed(1)} ${P[i][1].toFixed(1)}`; }
    g += `<path class="useline" d="${path}"/>` + use.map(u => `<circle class="usedot" cx="${X(u.t).toFixed(1)}" cy="${YU(u.u).toFixed(1)}" r="3"><title>${esc(`${D.day(u.t)} · ${num(u.u, 1)} L/h since the fill before`)}</title></circle>`).join("");
  }
  return `<svg class="fsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Diesel fills over time and the fuel use per engine hour">${g}</svg>
    <div class="flegend"><span><i class="fbar"></i>Litres per fill</span><span><i class="useline"></i>L per engine hour since the fill before</span>${avg != null ? `<span><i class="avg"></i>Average</span>` : ""}</div>`;
}
window.addEventListener("resize", () => { if (D.visibleIs("enginelog") && view === "fuel" && !edit && m.state.data && $("lChart")) $("lChart").innerHTML = fuelChart(m.state.data.fuel, m.state.data.stats.avg_l_per_h); });
function maintView(d) {
  const names = /** @type {Record<string, string>} */ (Object.fromEntries((d.schedule || []).map((/** @type {any} */ x) => [x.id, x.name])));
  return `${schedView(d)}<div class="u-maxw-720 u-mt-12 card pad"><button class="btn wide" type="button" data-new="maintenance">${icon("wrench")} New maintenance entry</button>
    <div class="lrows">${d.maintenance.map(x => `<button class="lrow" type="button" data-edit="maintenance:${esc(x.id)}"><span class="t"><b>${esc(dmy(x.date))}</b>${x.engine_hours != null ? ` <span class="muted">· ${num(x.engine_hours, 0)} h</span>` : ""}
        ${(x.items || []).length ? `<small class="itags">${x.items.map((/** @type {string} */ i) => `<span>${esc(names[i] || i)}</span>`).join("")}</small>` : ""}${x.text ? `<small class="pre">${esc(x.text)}</small>` : ""}</span>${icon("chev", "i chev")}</button>`).join("") || `<div class="empty">No maintenance logged yet</div>`}</div></div>
    ${alarmView(d)}`;
}
// ---- the maintenance schedule (the Yanmar 4JH80 and its KM4A marine gear; the server's schedule.py works out what is due)
const STATE = /** @type {Record<string, [string, string]>} */ ({due: ["bad", "Due"], soon: ["warn", "Soon"], ok: ["ok", "OK"], never: ["", "Not logged"]});
/** "every 250 h or year" @param {any} x */
const every = x => "every " + [x.hours ? `${num(x.hours, 0)} h` : "", x.months ? x.months % 12 ? `${x.months} month${x.months === 1 ? "" : "s"}` : x.months === 12 ? "year" : `${x.months / 12} years` : ""].filter(Boolean).join(" or ");
/** How far off, in hours and/or time. @param {any} x */
function left(x) {
  if (x.state === "never") return "not logged";
  const t = [];
  if (x.left_hours != null) t.push(x.left_hours <= 0 ? `${num(-x.left_hours, 0)} h over` : `in ${num(x.left_hours, 0)} h`);
  if (x.left_days != null) { const d = x.left_days, a = Math.abs(d), w = a < 62 ? `${a} day${a === 1 ? "" : "s"}` : `${Math.round(a / 30.4)} months`;
    t.push(d <= 0 ? `${w} over` : `in ${w}`); }
  return t.map(esc).join("<br>");      // hours and time each on a line: the item's name keeps the room
}
/** One schedule item: its name, interval and last time; how far off; a button that logs it. @param {any} x */
const schedRow = x => { const [c, label] = STATE[x.state] || ["", x.state];
  return `<div class="srow"><div class="k"><b>${esc(x.name)}${x.dealer ? ` <span class="badge plain dealer">dealer</span>` : ""}</b>
    <small>${esc(every(x))}${x.note ? ` · ${esc(x.note)}` : ""}<br>${x.last_date ? `last ${esc(dmy(x.last_date))}${x.last_hours != null ? ` at ${num(x.last_hours, 0)} h` : ""}` : "never logged"}</small></div>
    <div class="v"><span class="badge ${c}">${label}</span><small>${left(x)}</small></div>
    <button class="btn sec sm" type="button" data-log="${esc(x.id)}" aria-label="Log ${esc(x.name)}">Log</button></div>`; };
function schedView(d) {
  const S = /** @type {any[]} */ (d.schedule || []); if (!S.length) return "";
  const n = (/** @type {string} */ k) => S.filter(x => x.state === k).length;
  const now = S.filter(x => x.state === "due" || x.state === "soon").sort((a, b) => (a.state === "due" ? 0 : 1) - (b.state === "due" ? 0 : 1));
  const systems = [...new Set(S.map(x => x.system))];
  return `<div class="u-maxw-720 card pad sched"><div class="hd u-p-0">${icon("wrench")}<h3>Maintenance schedule</h3>${n("due") ? `<span class="badge bad">${n("due")} due</span>` : ""}${n("soon") ? `<span class="badge warn">${n("soon")} soon</span>` : ""}</div>
    <p class="u-m-6-0-0 hint">Yanmar 4JH80 with KM4A marine gear, from Yanmar's periodic maintenance schedule (whichever comes first). Tick the items in a maintenance entry, or use Log.</p>
    ${now.length ? `<div class="srows">${now.map(schedRow).join("")}</div>` : `<p class="u-m-8-0-0 hint">${n("never") === S.length ? "Nothing logged against the schedule yet." : "Nothing due or due soon."}</p>`}
    <details class="lfold" id="lSchedFold" ${schedOpen ? "open" : ""}><summary><b>All items</b><span class="muted">${S.length}${n("never") ? ` · ${n("never")} not logged` : ""}</span>${icon("chev", "i chev")}</summary>
    ${systems.map(sy => `<h4 class="ssys">${esc(sy)}</h4><div class="srows">${S.filter(x => x.system === sy).map(schedRow).join("")}</div>`).join("")}</details></div>`;
}
// ---- the engine (live from the Orca Core) and its alarms (logged by the server from the YDEN-02's NMEA 2000 data)
const clock = (/** @type {string} */ iso) => iso ? D.dayTime(Date.parse(iso)) : "–";
function alarmView(d) {
  const e = d.engine || {}, al = d.alarms || [];
  const live = e.fresh ? `${e.running ? `<span class="good">Running</span>` : `<span class="muted">Ignition on, not running</span>`} · ${num(e.rpm, 0)} rpm · ${num(e.temp_c, 0)} °C · oil ${num(e.oil_bar, 1)} bar · ${num(e.alt_v, 1)} V · ${num(e.hours, 1)} h`
    : e.connected ? `<span class="muted">Engine off</span>${e.last_hours != null ? ` · ${num(e.last_hours, 1)} h at ${esc(clock(e.last_hours_at))}` : ""}`
    : `<span class="warnc">No engine data from the Orca Core</span>${e.error ? `<small>${esc(e.error)}</small>` : ""}`;
  const y = e.alarm_source || {};
  const src = y.fresh ? `<span class="good">Alarm watch on</span> · the YDEN-02 passes the engine's data${y.status && y.status.length ? ` · lights on: ${esc(y.status.join(", "))}` : ""}`
    : y.listening ? `<span class="warnc">Alarm watch paused</span> · no engine data from the YDEN-02 (off, or the engine's gateway is)`
    : `<span class="warnc">Alarm watch off</span> · not listening for the YDEN-02${y.error ? `<small>${esc(y.error)}</small>` : ""}`;
  return `<div class="u-maxw-720 u-mt-12 card pad"><div class="hd u-p-0">${icon("alert")}<h3>Engine</h3>${al.some(a => !a.end) ? '<span class="badge bad">alarm</span>' : ""}</div>
    <p class="u-m-6-0-0 hint" id="lEngine">${live}</p>
    <p class="u-m-6-0-0 hint" id="lAlarmSrc">${src}</p>
    <details class="lfold" id="lAlarmFold" ${alarmsOpen ? "open" : ""}><summary><b>Alarm log</b><span class="muted">${al.length ? `${al.length} · last ${esc(clock(al[0].start))}` : "none"}</span>${icon("chev", "i chev")}</summary>
    <div class="lrows">${al.map(a => `<div class="lrowx"><div class="lrow"><span class="t"><b class="${a.end ? "" : "badc"}">${esc(a.name)}</b>${a.engine_hours != null ? ` <span class="muted">· ${num(a.engine_hours, 1)} h</span>` : ""}
        <small>${esc(clock(a.start))} – ${a.end ? esc(clock(a.end)) : "now"}${a.detail ? ` · ${esc(a.detail)}` : ""}</small></span></div>
        <button class="btn sec sm maps" type="button" data-delalarm="${esc(a.id)}" aria-label="Delete this alarm">Delete</button></div>`).join("")
      || `<div class="empty">No engine alarms logged</div>`}</div></details>
    <p class="u-m-8-0-0 hint">The alarms come from the YDEN-02, which passes the engine's own warning lights (the Orca Core does not). Logged: every warning light the engine sets (oil pressure, system voltage and charge only while running), and high coolant temperature and low oil pressure while running (limits in Settings). While the YDEN-02 is off, no alarms are logged.</p></div>`;
}

// ---- Current data: the engine's live values (Orca Core) as a cockpit: a big rev counter, the rest as half arcs around
// it, and the engine's warning lights (YDEN-02). Zones: coolant and oil pressure from the alarm limits in Settings.
const pt = (/** @type {number} */ cx, /** @type {number} */ cy, /** @type {number} */ r, /** @type {number} */ a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
const f1 = (/** @type {number} */ v) => v.toFixed(1);
/** @typedef {{k: string, u: string, v: number | null | undefined, min: number, max: number, z: [number, number, string][], d: number}} Gauge */
/** @param {Gauge} g @param {number} v */
const frac = (g, v) => Math.min(1, Math.max(0, (v - g.min) / (g.max - g.min)));
const has = (/** @type {Gauge} */ g) => g.v != null && isFinite(+g.v);
/** The zone a value is in ("" outside every zone). @param {Gauge} g */
const zoneOf = g => has(g) ? ((g.z.find(([lo, hi]) => +g.v >= lo && +g.v <= hi) || [])[2] || "") : "";
// The meters look like the House bank meter (energy.js meter(), its .meter styles): a band whose colour runs smoothly
// through the zones, its glow and sheen, a rim, the needle's tip and the value in a pill.
const ZC = /** @type {Record<string, string>} */ ({ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)"});
/** @param {string} a @param {string} b @param {number} t 0 = a, 1 = b */
const mix = (a, b, t) => `color-mix(in srgb, ${ZC[a]} ${Math.round((1 - t) * 100)}%, ${ZC[b]})`;
/** The band's colour at a value: its zone's, blended into the next zone near a boundary. @param {Gauge} g @param {number} v */
function colorAt(g, v) {
  const z = g.z, B = (g.max - g.min) * .07;
  let i = z.findIndex(([lo, hi]) => v >= lo && v <= hi); if (i < 0) i = v < z[0][0] ? 0 : z.length - 1;
  const [lo, hi, c] = z[i];
  if (i < z.length - 1 && hi - v < B) return mix(c, z[i + 1][2], .5 * (1 - (hi - v) / B));
  if (i > 0 && v - lo < B) return mix(c, z[i - 1][2], .5 * (1 - (v - lo) / B));
  return ZC[c];
}
/** The band as short arc pieces, each in the colour at its place. @param {Gauge} g @param {number} cx @param {number} cy @param {number} r @param {number} a0 @param {number} a1 @param {number} n */
function band(g, cx, cy, r, a0, a1, n) {
  let out = "";
  for (let i = 0; i < n; i++) {
    const s0 = a0 + (a1 - a0) * i / n, s1 = a0 + (a1 - a0) * (i + 1) / n + (i < n - 1 ? .01 : 0), [x0, y0] = pt(cx, cy, r, s0), [x1, y1] = pt(cx, cy, r, s1);
    out += `<path class="band" d="M${f1(x0)} ${f1(y0)}A${r} ${r} 0 0 1 ${f1(x1)} ${f1(y1)}" style="stroke:${colorAt(g, g.min + (g.max - g.min) * (i + .5) / n)}${i && i < n - 1 ? ";stroke-linecap:butt" : ""}"/>`;   // round only at the two ends
  }
  return out;
}
/** The needle's tip, as on the House bank meter. @param {number} cx @param {number} cy @param {number} a @param {number} from @param {number} to @param {number} w */
function tip(cx, cy, a, from, to, w) {
  const ux = Math.cos(a), uy = Math.sin(a), vx = -uy, vy = ux, P = (/** @type {number} */ d, /** @type {number} */ k) => `${f1(cx + ux * d + vx * k)},${f1(cy + uy * d + vy * k)}`;
  return `<g class="needle"><polygon points="${P(from, w)} ${P(to, 1.2)} ${P(to, -1.2)} ${P(from, -w)}"/></g>`;
}
/** The value in the pill, coloured when it is in a warn or bad zone. @param {Gauge} g */
const pill = g => `<span class="pill ${zoneOf(g) === "ok" ? "" : zoneOf(g)}">${has(g) ? num(g.v, g.d) : "–"}<small> ${esc(g.u)}</small></span>`;
/** The rev counter: the House bank meter's look on a 270° dial, with ticks per 500 rpm. @param {Gauge} g */
function tacho(g) {
  const cx = 110, cy = 108, r = 82, a0 = .75 * Math.PI, a1 = 2.25 * Math.PI, A = (/** @type {number} */ v) => a0 + (a1 - a0) * frac(g, v);
  const whole =(/** @type {number} */ rr) => { const [p, q] = pt(cx, cy, rr, a0), [u, w] = pt(cx, cy, rr, a1);
    return `M${f1(p)} ${f1(q)}A${rr} ${rr} 0 1 1 ${f1(u)} ${f1(w)}`; };
  let ticks = "";
  for (let v = g.min; v <= g.max; v += 500) {
    const big = v % 1000 === 0, [x0, y0] = pt(cx, cy, r - 15, A(v)), [x1, y1] = pt(cx, cy, r - (big ? 26 : 21), A(v));
    ticks += `<line class="tk${big ? " big" : ""}" x1="${f1(x0)}" y1="${f1(y0)}" x2="${f1(x1)}" y2="${f1(y1)}"/>`;
    if (big) { const [tx, ty] = pt(cx, cy, r - 38, A(v)); ticks += `<text class="tl" x="${f1(tx)}" y="${f1(ty + 4.5)}">${v / 1000}</text>`; }
  }
  return `<div class="meter big" role="img" aria-label="${esc(g.k)} ${has(g) ? num(g.v, 0) + " " + g.u : "unknown"}"><svg viewBox="0 0 220 196" aria-hidden="true">
    <defs><linearGradient id="lTachoSheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="g0"/><stop offset=".6" class="g1"/></linearGradient></defs>
    <path class="track" d="${whole(r)}"/><g class="glow">${band(g, cx, cy, r, a0, a1, 54)}</g>${band(g, cx, cy, r, a0, a1, 54)}
    <path class="sheen" d="${whole(r - 4)}" stroke="url(#lTachoSheen)"/><path class="rim" d="${whole(r + 12)}"/>${ticks}
    ${has(g) ? tip(cx, cy, A(+g.v), 16, r + 10, 5) : ""}<circle class="hub" cx="${cx}" cy="${cy}" r="5"/>
    <text class="tu" x="${cx}" y="${cy + 46}">× 1000 rpm</text></svg>${pill(g)}</div>`;
}
/** A small meter, exactly the House bank meter's shape, with the value in its pill and the name under it. @param {Gauge} g @param {number} i */
function halfArc(g, i) {
  const cx = 62, cy = 64, r = 48, arc = (/** @type {number} */ rr) => `M ${cx - rr} ${cy} A ${rr} ${rr} 0 0 1 ${cx + rr} ${cy}`;
  return `<div class="ga${has(g) ? "" : " off"}"><div class="meter" role="img" aria-label="${esc(g.k)} ${has(g) ? num(g.v, g.d) + " " + g.u : "unknown"}"><svg viewBox="0 0 124 76" aria-hidden="true">
    <defs><linearGradient id="lGa${i}Sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="g0"/><stop offset=".55" class="g1"/></linearGradient></defs>
    <path class="track" d="${arc(r)}"/><g class="glow">${band(g, cx, cy, r, Math.PI, 2 * Math.PI, 30)}</g>${band(g, cx, cy, r, Math.PI, 2 * Math.PI, 30)}
    <path class="sheen" d="${arc(r - 4)}" stroke="url(#lGa${i}Sheen)"/><path class="rim" d="${arc(r + 11)}"/>${has(g) ? tip(cx, cy, Math.PI * (1 + frac(g, +g.v)), 28, r + 10, 4.5) : ""}</svg>
    ${pill(g)}</div><span>${esc(g.k)}</span></div>`;
}
// the warning lights always shown (off unless the engine sets them); any other light the engine sets is added
const LIGHTS = ["Check engine", "Over temperature", "Low oil pressure", "Charge indicator", "Low system voltage", "Water in fuel", "Preheat indicator"];
/** @type {Record<string, string>} the icon per light (others: alert) */
const LIGHT_IC = {"Check engine": "engine", "Over temperature": "temp", "Low oil pressure": "drop", "Low oil level": "drop", "Charge indicator": "batt",
  "Low system voltage": "power", "Water in fuel": "fuel", "Preheat indicator": "flame", "Low coolant level": "temp", "Low fuel pressure": "fuel"};
function dataView(d) {
  const e = d.engine || {}, st = d.settings || {}, y = e.alarm_source || {}, th = st.temp_high_c ?? 95, ol = st.oil_low_bar ?? 1;
  /** @type {Gauge[]} */
  const G = [
    {k: "Coolant", u: "°C", v: e.temp_c, min: 40, max: 120, z: [[40, th, "ok"], [th, Math.min(120, th + 10), "warn"], [Math.min(120, th + 10), 120, "bad"]], d: 0},
    {k: "Oil pressure", u: "bar", v: e.oil_bar, min: 0, max: 6, z: [[0, ol, "bad"], [ol, ol + .5, "warn"], [ol + .5, 6, "ok"]], d: 1},
    {k: "Alternator", u: "V", v: e.alt_v, min: 10, max: 16, z: [[10, 12, "bad"], [12, 12.8, "warn"], [12.8, 14.8, "ok"], [14.8, 16, "warn"]], d: 1},
    {k: "Fuel rate", u: "L/h", v: e.fuel_lph, min: 0, max: 15, z: [[0, 15, "ok"]], d: 1},
    {k: "Load", u: "%", v: e.load, min: 0, max: 100, z: [[0, 85, "ok"], [85, 100, "warn"]], d: 0},
    {k: "Boost", u: "bar", v: e.boost_bar, min: 0, max: 2, z: [[0, 2, "ok"]], d: 1}];
  const rpm = {k: "Engine speed", u: "rpm", v: e.rpm, min: 0, max: 4000, z: /** @type {[number, number, string][]} */ ([[0, 3200, "ok"], [3200, 3600, "warn"], [3600, 4000, "bad"]]), d: 0};
  const on = new Set(y.fresh ? y.status || [] : []), names = [...LIGHTS, ...[...on].filter(n => !LIGHTS.includes(n))];
  // a tile per light: lit in its colour when on (Preheat is a notice, the rest alarms), grey when off
  const lights = names.map(n => { const c = on.has(n) ? n === "Preheat indicator" ? "warn" : "bad" : "";
    return `<div class="wlamp${c ? " " + c : ""}">${icon(LIGHT_IC[n] || "alert")}<span>${esc(n === "Preheat indicator" ? "Preheat" : n)}</span>${c ? `<b>on</b>` : ""}</div>`; }).join("");
  const hours = e.fresh && e.hours != null ? e.hours : e.last_hours;
  const state = e.fresh ? (e.running ? `<span class="good">Running</span>` : `<span class="muted">Ignition on, not running</span>`) + (e.age_s != null ? ` · read ${D.dur(e.age_s)} ago` : "")
    : e.connected ? `<span class="muted">Engine off: no live values</span>` : `<span class="warnc">No engine data from the Orca Core</span>${e.error ? ` · ${esc(e.error)}` : ""}`;
  const other = Object.entries(e.other || {}).filter(([, v]) => v != null && typeof v !== "object");
  return `<div class="u-maxw-720 card pad"><div class="hd u-p-0">${icon("engine")}<h3>Engine</h3><span class="muted num">${hours != null ? num(hours, 1) + " h" : "–"}</span></div>
    <p class="u-m-6-0-0 hint" id="lLive">${state}</p>
    <div class="cockpit">${tacho(rpm)}<div class="gas">${G.map((g, i) => halfArc(g, i)).join("")}</div></div>
    <div class="lamps" id="lLamps">${lights}</div>
    <p class="u-m-8-0-0 hint">${y.fresh ? "Warning lights from the YDEN-02, live." : "Warning lights: no data from the YDEN-02 (off, or the engine's gateway is), so none are shown as on."}
      Values from the Orca Core. Coolant and oil pressure zones follow the alarm limits in Settings.</p>
    ${other.length ? `<details class="lfold"><summary><b>Other values</b><span class="muted">${other.length}</span>${icon("chev", "i chev")}</summary><div class="rows">${other.map(([k, v]) =>
      `<div class="row"><span class="k">${esc(k)}</span><span class="v num">${typeof v === "number" ? num(v, Math.abs(v) < 10 ? 2 : 0) : esc(String(v))}</span></div>`).join("")}</div></details>` : ""}</div>`;
}

function setView(d) {
  const st = d.settings || {}, cap = st.tank_capacity_l;
  return `<form class="u-maxw-720 card lform" id="lSetForm" novalidate><div class="hd">${icon("gear")}<h3>Settings</h3></div><div class="rows">
    <div class="row"><div class="k"><b>Fuel tank capacity</b><small>Litres; empty = not set</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lTank" min="1" max="10000" step="1" value="${cap ?? ""}"><span class="u">L</span></label></div>
    <div class="row"><div class="k"><b>High coolant temperature</b><small>Engine alarm at or above this, 60–130 °C</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lTemp" min="60" max="130" step="1" value="${st.temp_high_c ?? 95}"><span class="u">°C</span></label></div>
    <div class="row"><div class="k"><b>Low oil pressure</b><small>Engine alarm below this while running, 0.1–5 bar</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lOil" min="0.1" max="5" step="0.1" value="${st.oil_low_bar ?? 1}"><span class="u">bar</span></label></div>
    </div><div class="u-d-flex u-gap-8 u-mt-12"><button class="btn" type="submit" id="lSetSave">Save</button></div><p class="err" id="lSetErr" hidden></p></form>`;
}
async function saveSettings() {
  const v = $("lTank").value.trim(), t = $("lTemp").value.trim(), o = $("lOil").value.trim(), err = $("lSetErr"); err.hidden = true;
  const bad = v !== "" && !(+v >= 1 && +v <= 10000) ? "Fuel tank capacity: 1–10000 L" : !(t !== "" && +t >= 60 && +t <= 130) ? "High coolant temperature: 60–130 °C"
    : !(o !== "" && +o >= 0.1 && +o <= 5) ? "Low oil pressure: 0.1–5 bar" : "";
  if (bad) { err.textContent = bad; err.hidden = false; return; }
  try { await D.run(m, $("lSetSave"), () => D.api("enginelog", "/api/settings", {tank_capacity_l: v === "" ? null : +v, temp_high_c: +t, oil_low_bar: +o}), "Settings saved"); } catch (e) { err.textContent = e.message; err.hidden = false; }
}

// ------------------------------------------------------------------ forms
/** The schedule items an entry did, as ticks per system. @param {any} d @param {string[]} on */
function itemsField(d, on) {
  const S = /** @type {any[]} */ (d.schedule || []); if (!S.length) return "";
  return `<div class="row col"><div class="k"><b>Schedule items done</b><small>Resets them in the maintenance schedule</small></div><div class="ticks">
    ${[...new Set(S.map(x => x.system))].map(sy => `<h4 class="ssys">${esc(sy)}</h4>${S.filter(x => x.system === sy).map(x =>
      `<label class="tick"><input type="checkbox" name="lItem" value="${esc(x.id)}" ${on.includes(x.id) ? "checked" : ""}><span>${esc(x.name)}</span></label>`).join("")}`).join("")}</div></div>`;
}
/** @param {string} kind @param {string | null} id @param {string[]} [pre] schedule items ticked for a new entry */
function openForm(kind, id, pre = []) {
  const d = m.state.data, e = id ? d[kind].find(x => x.id === id) : null;
  if (id && !e) { D.toast("That entry was deleted", true); return; }
  edit = {kind, id, touched: new Set(), pos: e ? (e.lat != null ? {lat: e.lat, lon: e.lon} : null) : boatPos()};
  const eh = id ? null : engineHours(d), hoursNote = eh ? `<small>${esc(eh.note)}; change it if the meter says otherwise</small>` : "";
  const btns = `<div class="u-d-flex u-gap-8 u-fw-wrap u-mt-12"><button class="btn" type="submit" id="lSave">Save</button><button class="btn sec" type="button" data-cancel>Cancel</button>
    ${id ? `<span class="u-flex-1"></span><button class="btn sec danger" type="button" data-delete>Delete</button>` : ""}</div><p class="err" id="lErr" hidden></p>`;
  if (kind === "fuel") {
    $("lBody").innerHTML = `<form class="u-maxw-720 card lform" id="lForm" novalidate><div class="hd">${icon("fuel")}<h3>${id ? "Fuel entry" : "New fuel entry"}</h3></div><div class="rows">
      <div class="row"><div class="k"><b>Date</b>${id ? "" : auto("today")}</div>${dateField("lDate", e ? e.date : today())}</div>
      <div class="row"><div class="k"><b>Engine hours</b>${eh ? auto("engine") : ""}${hoursNote}</div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lHours" min="0" max="100000" step="0.1" value="${e ? e.engine_hours : eh ? eh.h : ""}"><span class="u">h</span></label></div>
      <div class="row"><div class="k"><b>Litres</b></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lLitres" min="0.1" max="5000" step="0.1" value="${e ? e.litres : ""}"><span class="u">L</span></label></div>
      <div class="row"><div class="k"><b>Amount</b><small>Paid; empty = not noted</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lAmount" min="0" max="100000" step="0.01" value="${e && e.amount != null ? e.amount : ""}"><span class="u">€</span></label></div>
      <div class="row"><div class="k"><b>Position</b>${id || !edit.pos ? "" : auto("GPS")}<small id="lPos">${esc(posText(edit.pos))}</small></div>
        ${edit.pos ? `<span class="u-d-flex u-gap-6" id="lPosBtns">${mapsBtn(edit.pos)}<button class="btn sec sm" type="button" data-nopos>Remove</button></span>` : ""}</div>
      </div>${btns}</form>`;
  } else {
    $("lBody").innerHTML = `<form class="u-maxw-720 card lform" id="lForm" novalidate><div class="hd">${icon("wrench")}<h3>${id ? "Maintenance entry" : "New maintenance entry"}</h3></div><div class="rows">
      <div class="row"><div class="k"><b>Date</b>${id ? "" : auto("today")}</div>${dateField("lDate", e ? e.date : today())}</div>
      <div class="row"><div class="k"><b>Engine hours</b>${eh ? auto("engine") : ""}${eh ? hoursNote : "<small>The meter's total; empty = not noted</small>"}</div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lHours" min="0" max="100000" step="0.1" value="${e && e.engine_hours != null ? e.engine_hours : eh ? eh.h : ""}"><span class="u">h</span></label></div>
      ${itemsField(d, e ? e.items || [] : pre)}
      <div class="row col"><div class="k"><b>What was done</b><small>Optional when items are ticked</small></div><textarea class="field" id="lText" maxlength="2000" rows="4" placeholder="Oil and oil filter changed…">${esc(e ? e.text : "")}</textarea></div>
      </div>${btns}</form>`;
  }
  m.render();
}
function fail(msg) { const el = $("lErr"); el.textContent = msg; el.hidden = false; return null; }
function body() {
  $("lErr").hidden = true;
  const date = D.parseDate($("lDate").value);
  if (!date) return fail(`Date as ${D.dateFmt()}`);
  if (edit.kind === "maintenance") {
    const text = $("lText").value.trim(), hours = $("lHours").value;
    const items = [...document.querySelectorAll('#lForm input[name="lItem"]:checked')].map(i => /** @type {HTMLInputElement} */ (i).value);
    if (!text && !items.length) return fail("Tick a schedule item or say what was done");
    if (hours !== "" && !(+hours >= 0 && +hours <= 100000)) return fail("Engine hours: 0–100000");
    return {date, engine_hours: hours === "" ? null : +hours, text, items};
  }
  const hours = $("lHours").value, litres = $("lLitres").value, amount = $("lAmount").value;
  if (hours === "" || !(+hours >= 0 && +hours <= 100000)) return fail("Engine hours: 0–100000");
  if (litres === "" || !(+litres >= 0.1 && +litres <= 5000)) return fail("Litres: 0.1–5000");
  if (amount !== "" && !(+amount >= 0 && +amount <= 100000)) return fail("Amount: 0–100000");
  return {date, engine_hours: +hours, litres: +litres, amount: amount === "" ? null : +amount, lat: edit.pos ? edit.pos.lat : null, lon: edit.pos ? edit.pos.lon : null};
}
async function save() {
  const b = body(); if (!b) return;
  const path = `/api/${edit.kind}${edit.id ? "/" + edit.id : ""}`;
  try { await D.run(m, $("lSave"), () => D.api("enginelog", path, b), "Saved"); close(); D.poll(m, true); } catch (e) { fail(e.message); }
}
async function remove() {
  const what = edit.kind === "fuel" ? "fuel entry" : "maintenance entry";
  if (!(await D.confirm({title: `Delete this ${what}?`, text: "It is removed from the engine log. This cannot be undone.", ok: "Delete", cancel: "Keep it", danger: true}))) return;
  try { await D.run(m, null, () => D.api("enginelog", `/api/${edit.kind}/${edit.id}/delete`, {}), "Deleted"); close(); D.poll(m, true); } catch (e) {}
}
function close() { edit = null; m.render(); }

async function onClick(e) {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.lview) { view = b.dataset.lview; edit = null; $("lBody").innerHTML = ""; m.render(); D.poll(m, true); return; }   // poll: at the new view's rate
  if (b.dataset.new) return openForm(b.dataset.new, null);
  if (b.dataset.log) return openForm("maintenance", null, [b.dataset.log]);      // Log on a schedule item: a new entry with it ticked
  if (b.dataset.edit) { const [kind, id] = b.dataset.edit.split(":"); return openForm(kind, id); }
  if (b.hasAttribute("data-cancel")) return close();
  if (b.hasAttribute("data-delete")) return remove();
  if (b.hasAttribute("data-nopos")) { edit.pos = null; $("lPos").textContent = posText(null); $("lPosBtns").remove(); return; }
  if (b.dataset.maps) { const [lat, lon] = b.dataset.maps.split(",").map(Number); openMaps({lat, lon}); return; }
  if (b.dataset.delalarm) {
    if (!(await D.confirm({title: "Delete this engine alarm?", text: "It is removed from the engine log. This cannot be undone.", ok: "Delete", cancel: "Keep it", danger: true}))) return;
    try { await D.run(m, b, () => D.api("enginelog", `/api/alarms/${b.dataset.delalarm}/delete`, {}), "Deleted"); D.poll(m, true); } catch (x) {}
  }
}

D.register(m);
