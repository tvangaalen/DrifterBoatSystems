// Engine log module: diesel fuel fills and engine maintenance. The log lives on the engine log server (data/log.json on
// the boat PC); this page shows it and sends new, changed and deleted entries. A new fill takes the time now, the boat's
// position from the anchor watch, and the country and nearest marina from the server's OpenStreetMap lookup: every
// automatic value can be changed before saving. Deleting always asks first (Keep is the default).
import Drifter from "./core/app.js";

const D = Drifter, {$, esc, num, icon, pad} = D;
let view = "fuel", edit = null;     // edit: {kind, id (null = new), touched: Set of fields the user changed} while a form is open

const dmy = (/** @type {string} */ iso) => D.dateText(iso) || "–";
/** A date in the chosen format (System page), typed or picked: the calendar button lies under an invisible native date input,
 * so a tap opens the device's own calendar on every browser. @param {string} id @param {string} iso YYYY-MM-DD */
const dateField = (id, iso) => `<div class="datef"><input class="field lf-date" id="${id}" value="${esc(D.dateText(iso))}" placeholder="${esc(D.dateFmt())}" inputmode="numeric" maxlength="10" autocomplete="off" aria-label="Date (${esc(D.dateFmt())})">
  <span class="pickbtn">${icon("calendar")}<input type="date" id="${id}Pick" value="${iso}" tabindex="-1" aria-label="Pick a date"></span></div>`;
/** The local date (YYYY-MM-DD) and 24-hour time (HH:MM) of an ISO time, or of now. @param {string} [iso] */
function parts(iso) {
  const d = iso ? new Date(iso) : new Date();
  return {date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}`};
}
/** ISO 8601 with this device's offset for a local date and time. @param {string} date @param {string} time */
function isoOf(date, time) {
  const [y, mo, d] = date.split("-").map(Number), [h, mi] = time.split(":").map(Number), t = new Date(y, mo - 1, d, h, mi), off = -t.getTimezoneOffset();
  return `${date}T${time}:00${off >= 0 ? "+" : "-"}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
}
const boatPos = () => { const a = D.byId.anchor && D.byId.anchor.state.data, p = a && a.boat && a.boat.pos; return p && p.lat != null ? {lat: p.lat, lon: p.lon} : null; };
/** @param {number} v @param {string} pos @param {string} neg */
const dm = (v, pos, neg) => { const a = Math.abs(v), d = Math.floor(a); return `${d}° ${((a - d) * 60).toFixed(3)}′ ${v >= 0 ? pos : neg}`; };
const posText = (/** @type {any} */ p) => p && p.lat != null ? `${dm(p.lat, "N", "S")}  ${dm(p.lon, "E", "W")}` : "No position";
/** Time since a moment, short: minutes, hours, then days. @param {number} t ms */
const since = t => { const h = (Date.now() - t) / 3600e3; return h < 1 ? `${Math.max(0, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} days`; };
const auto = (/** @type {string} */ t) => `<span class="autochip">${t}</span>`;

const m = {
  id: "enginelog", title: "Engine log", short: "Engine", icon: "fuel", every: 30000, background: 120000,
  async load() { m.state.data = await D.api("enginelog", "/api/log"); },
  enter() { view = "fuel"; },      // from the Overview or the navigation: always Diesel fuel
  tile() {
    const d = m.state.data; if (!d) return `<div class="line">${esc(m.state.err.message)}</div>`;
    const f = d.fuel[0], mt = d.maintenance[0], s = d.stats;
    return `<div class="u-fs-22 big">${f ? `${num(f.litres, 0)} L` : "No fills yet"}</div>
      <div class="line">${f ? `${esc(D.dayTime(Date.parse(f.time)))}${f.marina || f.country ? ` · ${esc(f.marina || f.country)}` : ""}` : "Log the next fill on the Engine log page"}</div>
      <div class="minis"><div class="mini"><div class="l">Engine hours</div><div class="n">${f ? num(f.engine_hours, 0) + " h" : "–"}</div></div>
      <div class="mini"><div class="l">Avg use</div><div class="n">${s.avg_l_per_h != null ? num(s.avg_l_per_h, 1) + " L/h" : "–"}</div></div>
      <div class="mini"><div class="l">Maintenance</div><div class="n">${mt ? esc(dmy(mt.date)) : "–"}</div></div></div>`;
  },
  mount(el) {
    el.innerHTML = `<div id="lDown"></div>
      <div class="u-m-4-0-14 u-maxw-460 seg" id="lViews"><button type="button" data-lview="fuel">Diesel fuel</button><button type="button" data-lview="maintenance">Maintenance</button><button type="button" data-lview="settings">Settings</button></div>
      <div id="lBody"></div>`;
    el.addEventListener("click", onClick);
    el.addEventListener("input", e => { if (edit && e.target.id) edit.touched.add(e.target.id); });
    el.addEventListener("change", e => { const t = e.target; if (t.id && t.id.endsWith("Pick") && t.value) { const f = $(t.id.slice(0, -4)); f.value = D.dateText(t.value); edit && edit.touched.add(f.id); } });
    el.addEventListener("submit", e => { e.preventDefault(); if (e.target.id === "lForm") save(); else if (e.target.id === "lSetForm") saveSettings(); });
  },
  render() {
    $("lDown").innerHTML = m.state.err ? D.downCard(m) + '<div class="u-h-12"></div>' : "";
    document.querySelectorAll("#lViews button").forEach(b => b.setAttribute("aria-pressed", b.dataset.lview === view));
    if (edit) return;                                    // never rebuild an open form under the user's hands
    const d = m.state.data; if (!d) { $("lBody").innerHTML = m.state.err ? "" : `<div class="empty">Loading…</div>`; return; }
    if (view === "settings") { if (!$("lSetForm")) $("lBody").innerHTML = setView(d); return; }    // a form: built once, kept while open
    $("lBody").innerHTML = view === "fuel" ? fuelView(d) : maintView(d);
  },
};

// ------------------------------------------------------------------ lists
function fuelView(d) {
  const s = d.stats;
  return `<div class="u-maxw-720 card pad">
    <div class="minis u-mt-0"><div class="mini"><div class="l">Last fill</div><div class="n">${s.last_litres != null ? num(s.last_litres, 0) + " L" : "–"}</div></div>
      <div class="mini"><div class="l">Since</div><div class="n">${s.last_time ? since(Date.parse(s.last_time)) : "–"}</div></div>
      <div class="mini"><div class="l">Avg use</div><div class="n">${s.avg_l_per_h != null ? num(s.avg_l_per_h, 1) + " L/h" : "–"}</div></div></div>
    <button class="u-mt-12 btn wide" type="button" data-new="fuel">${icon("fuel")} New fuel entry</button>
    <div class="lrows">${d.fuel.map(f => `<button class="lrow" type="button" data-edit="fuel:${esc(f.id)}"><span class="t"><b>${num(f.litres, 0)} L</b> <span class="muted">· ${num(f.engine_hours, 0)} h</span>
        <small>${esc(D.dayTime(Date.parse(f.time)))}${f.marina ? ` · ${esc(f.marina)}` : ""}${f.country ? `, ${esc(f.country)}` : ""}</small></span>${icon("chev", "i chev")}</button>`).join("")
      || `<div class="empty">No fills logged yet</div>`}</div>
    ${s.fills ? `<p class="u-m-8-0-0 hint">${s.fills} fill${s.fills === 1 ? "" : "s"} · ${num(s.litres_total, 0)} L in total. Average use: the litres of every fill after the first over the engine hours since the first.</p>` : ""}</div>`;
}
function maintView(d) {
  return `<div class="u-maxw-720 card pad"><button class="btn wide" type="button" data-new="maintenance">${icon("wrench")} New maintenance entry</button>
    <div class="lrows">${d.maintenance.map(x => `<button class="lrow" type="button" data-edit="maintenance:${esc(x.id)}"><span class="t"><b>${esc(dmy(x.date))}</b>${x.engine_hours != null ? ` <span class="muted">· ${num(x.engine_hours, 0)} h</span>` : ""}
        <small class="pre">${esc(x.text)}</small></span>${icon("chev", "i chev")}</button>`).join("") || `<div class="empty">No maintenance logged yet</div>`}</div></div>`;
}

function setView(d) {
  const cap = (d.settings || {}).tank_capacity_l;
  return `<form class="u-maxw-720 card lform" id="lSetForm" novalidate><div class="hd">${icon("gear")}<h3>Settings</h3></div><div class="rows">
    <div class="row"><div class="k"><b>Fuel tank capacity</b><small>Litres; empty = not set</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lTank" min="1" max="10000" step="1" value="${cap ?? ""}"><span class="u">L</span></label></div>
    </div><div class="u-d-flex u-gap-8 u-mt-12"><button class="btn" type="submit" id="lSetSave">Save</button></div><p class="err" id="lSetErr" hidden></p></form>`;
}
async function saveSettings() {
  const v = $("lTank").value.trim(), err = $("lSetErr"); err.hidden = true;
  if (v !== "" && !(+v >= 1 && +v <= 10000)) { err.textContent = "Fuel tank capacity: 1–10000 L"; err.hidden = false; return; }
  try { await D.run(m, $("lSetSave"), () => D.api("enginelog", "/api/settings", {tank_capacity_l: v === "" ? null : +v}), "Settings saved"); } catch (e) { err.textContent = e.message; err.hidden = false; }
}

// ------------------------------------------------------------------ forms
function openForm(kind, id) {
  const d = m.state.data, e = id ? d[kind].find(x => x.id === id) : null;
  if (id && !e) { D.toast("That entry was deleted", true); return; }
  edit = {kind, id, touched: new Set(), pos: e ? (e.lat != null ? {lat: e.lat, lon: e.lon} : null) : boatPos()};
  const btns = `<div class="u-d-flex u-gap-8 u-fw-wrap u-mt-12"><button class="btn" type="submit" id="lSave">Save</button><button class="btn sec" type="button" data-cancel>Cancel</button>
    ${id ? `<span class="u-flex-1"></span><button class="btn sec danger" type="button" data-delete>Delete</button>` : ""}</div><p class="err" id="lErr" hidden></p>`;
  if (kind === "fuel") {
    const p = parts(e ? e.time : undefined);
    $("lBody").innerHTML = `<form class="u-maxw-720 card lform" id="lForm" novalidate><div class="hd">${icon("fuel")}<h3>${id ? "Fuel entry" : "New fuel entry"}</h3></div><div class="rows">
      <div class="row stackrow"><div class="k"><b>Date and time</b>${id ? "" : auto("auto")}</div><div class="u-d-flex u-gap-6 u-ai-center">${dateField("lDate", p.date)}
        <input class="field lf-time" id="lTime" value="${p.time}" inputmode="numeric" maxlength="5" placeholder="HH:MM" aria-label="Time (24-hour)"></div></div>
      <div class="row"><div class="k"><b>Engine hours</b></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lHours" min="0" max="100000" step="0.1" value="${e ? e.engine_hours : ""}"><span class="u">h</span></label></div>
      <div class="row"><div class="k"><b>Litres</b></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lLitres" min="0.1" max="5000" step="0.1" value="${e ? e.litres : ""}"><span class="u">L</span></label></div>
      <div class="row"><div class="k"><b>Position</b>${id ? "" : auto("GPS")}<small id="lPos">${esc(posText(edit.pos))}</small></div>${edit.pos ? `<button class="btn sec sm" type="button" data-nopos>Remove</button>` : ""}</div>
      <div class="row stackrow"><div class="k"><b>Country</b>${id ? "" : auto("auto")}</div><input class="field lf-text" id="lCountry" maxlength="60" value="${esc(e ? e.country : "")}" autocomplete="off"></div>
      <div class="row stackrow"><div class="k"><b>Nearest marina</b>${id ? "" : auto("auto")}<small id="lLook"></small></div><input class="field lf-text" id="lMarina" maxlength="100" value="${esc(e ? e.marina : "")}" autocomplete="off"></div>
      </div>${btns}</form>`;
    if (!id) { if (edit.pos) look(edit.pos); else $("lLook").textContent = "No position from the anchor watch: type them in"; }
  } else {
    $("lBody").innerHTML = `<form class="u-maxw-720 card lform" id="lForm" novalidate><div class="hd">${icon("wrench")}<h3>${id ? "Maintenance entry" : "New maintenance entry"}</h3></div><div class="rows">
      <div class="row"><div class="k"><b>Date</b>${id ? "" : auto("today")}</div>${dateField("lDate", e ? e.date : parts().date)}</div>
      <div class="row"><div class="k"><b>Engine hours</b><small>The meter's total; empty = not noted</small></div><label class="numf"><input class="field" type="number" inputmode="decimal" id="lHours" min="0" max="100000" step="0.1" value="${e && e.engine_hours != null ? e.engine_hours : ""}"><span class="u">h</span></label></div>
      <div class="row col"><div class="k"><b>What was done</b></div><textarea class="field" id="lText" maxlength="2000" rows="5" placeholder="Oil and oil filter changed…">${esc(e ? e.text : "")}</textarea></div>
      </div>${btns}</form>`;
  }
  m.render();
}
/** Country and nearest marina from the server; fields the user already typed in are left alone. @param {{lat: number, lon: number}} pos */
async function look(pos) {
  $("lLook").textContent = "Looking up…";
  try {
    const r = await D.api("enginelog", `/api/lookup?lat=${pos.lat.toFixed(5)}&lon=${pos.lon.toFixed(5)}`);
    if (!edit || !$("lMarina")) return;
    if (!edit.touched.has("lCountry") && r.country) $("lCountry").value = r.country;
    if (!edit.touched.has("lMarina") && r.marina) $("lMarina").value = r.marina;
    $("lLook").textContent = r.marina ? `${num(r.marina_distance_m / 1000, 1)} km away (OpenStreetMap)` : r.error ? "Not found (no internet?): type it in" : "No marina within 15 km";
  } catch (e) { if ($("lLook")) $("lLook").textContent = "Not found (no internet?): type it in"; }
}
function fail(msg) { const el = $("lErr"); el.textContent = msg; el.hidden = false; return null; }
function body() {
  $("lErr").hidden = true;
  const date = D.parseDate($("lDate").value);
  if (!date) return fail(`Date as ${D.dateFmt()}`);
  if (edit.kind === "maintenance") {
    const text = $("lText").value.trim(), hours = $("lHours").value; if (!text) return fail("Say what was done");
    if (hours !== "" && !(+hours >= 0 && +hours <= 100000)) return fail("Engine hours: 0–100000");
    return {date, engine_hours: hours === "" ? null : +hours, text};
  }
  const time = $("lTime").value.trim(), hours = $("lHours").value, litres = $("lLitres").value;
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) return fail("Time as HH:MM (24-hour)");
  if (hours === "" || !(+hours >= 0 && +hours <= 100000)) return fail("Engine hours: 0–100000");
  if (litres === "" || !(+litres >= 0.1 && +litres <= 5000)) return fail("Litres: 0.1–5000");
  return {time: isoOf(date, time), engine_hours: +hours, litres: +litres, lat: edit.pos ? edit.pos.lat : null, lon: edit.pos ? edit.pos.lon : null,
    country: $("lCountry").value.trim(), marina: $("lMarina").value.trim()};
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
  if (b.dataset.lview) { view = b.dataset.lview; edit = null; $("lBody").innerHTML = ""; m.render(); return; }
  if (b.dataset.new) return openForm(b.dataset.new, null);
  if (b.dataset.edit) { const [kind, id] = b.dataset.edit.split(":"); return openForm(kind, id); }
  if (b.hasAttribute("data-cancel")) return close();
  if (b.hasAttribute("data-delete")) return remove();
  if (b.hasAttribute("data-nopos")) { edit.pos = null; $("lPos").textContent = posText(null); b.remove(); }
}

D.register(m);
