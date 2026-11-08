// Shared fragments of the pages: the "not reachable" card and the switch control.
import {esc, hms, icon} from "./format.js";

export function downCard(m) {
  const e = m.state.err; if (!e) return "";
  return `<div class="down">${icon("alert")}<div><b>${esc(m.title)} not reachable</b><span>${esc(e.message)}${m.state.data ? ` · showing data from ${hms(m.state.t)}` : ""}</span></div></div>`;
}
/** A switch; cls "onoff" gives the big green ON / red OFF style (washer power, BoatGuard monitoring). */
export const sw = (id, on, attrs = "", cls = "") => `<label class="switch${cls ? " " + cls : ""}"><input type="checkbox" role="switch" id="${id}" ${on ? "checked" : ""} ${attrs}><i></i></label>`;

// Priority and sound per push notification (Pushover), on each system's settings page. The server keeps the choices
// and checks them (common/pushover.py SOUNDS and PRIORITIES; MasterVolt keeps its own copy).
export const SOUNDS = ["", "pushover", "bike", "bugle", "cashregister", "classical", "cosmic", "falling", "gamelan", "incoming",
  "intermission", "magic", "mechanical", "pianobar", "siren", "spacealarm", "tugboat", "alien", "climb",
  "persistent", "echo", "updown", "vibrate", "none"];
export const PRIORITY_LABEL = {"-2": "Lowest", "-1": "Quiet", "0": "Normal", "1": "High", "2": "Emergency"};
export const soundLabel = s => s === "" ? "App default" : s === "none" ? "Silent" : s[0].toUpperCase() + s.slice(1);
/**
 * Rows with an on/off switch (when the notification has "on"), a sound and a priority select per notification. `events`: {key: title or [title, hint]}; `prefs`: {key: {priority, sound}};
 * `fixed`: {key: priority} for a notification whose priority cannot be changed (shown as text); priorities offered: -2..`max`;
 * `test`: a Test button per notification (`data-ntest` = its key), which the page sends with the sound and priority shown.
 */
/** @param {string} prefix @param {Record<string, string|string[]>} events @param {Record<string, {on?: boolean, priority: number, sound: string}>} prefs @param {{max?: number, fixed?: Record<string, number>, test?: boolean}} [opts] */
export function notifyRows(prefix, events, prefs, opts = {}) {
  const max = opts.max ?? 1, fixed = opts.fixed || {};
  return Object.entries(events).map(([e, t]) => {
    const [title, hint] = Array.isArray(t) ? t : [t, ""], p = prefs[e] || {priority: 0, sound: ""};
    const prio = e in fixed ? `<span class="u-flex-1 hint">${esc(PRIORITY_LABEL[fixed[e]])} (fixed)</span>`
      : `<select class="u-flex-1 field" id="${prefix}pri-${e}" aria-label="Priority for ${esc(title)}">${Object.entries(PRIORITY_LABEL).filter(([v]) => +v <= max)
        .map(([v, l]) => `<option value="${v}" ${+v === p.priority ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    return `<div class="row col"><div class="u-d-flex u-jc-between u-gap-10 u-ai-center"><div class="k"><b>${esc(title)}</b>${hint ? `<small>${esc(hint)}</small>` : ""}</div>
      ${"on" in p ? sw(`${prefix}on-${e}`, p.on !== false, `aria-label="${esc(title)} on or off"`) : ""}</div>
      <div class="u-d-flex u-gap-6"><select class="u-flex-1 field" id="${prefix}snd-${e}" aria-label="Sound for ${esc(title)}">${SOUNDS.map(o =>
        `<option value="${esc(o)}" ${o === p.sound ? "selected" : ""}>${esc(soundLabel(o))}</option>`).join("")}</select>${prio}${opts.test
        ? `<button class="btn sec" type="button" data-ntest="${esc(e)}" aria-label="Send a test of ${esc(title)}">Test</button>` : ""}</div></div>`;
  }).join("");
}
/** The sound and priority shown for one notification (for its Test button). @param {string} prefix @param {string} e */
export function notifyChoice(prefix, e) {
  const {sound, priority} = readNotify(prefix, {[e]: ""})[e] || {sound: ""};
  return priority === undefined ? {sound} : {sound, priority};
}
/** The choices of notifyRows as {key: {priority, sound}} (a fixed priority is left out: the server keeps it). */
export function readNotify(prefix, events) {
  /** @type {Record<string, {on?: boolean, priority?: number, sound: string}>} */
  const out = {};
  for (const e of Object.keys(events)) {
    const s = /** @type {HTMLSelectElement|null} */ (document.getElementById(`${prefix}snd-${e}`)), p = /** @type {HTMLSelectElement|null} */ (document.getElementById(`${prefix}pri-${e}`));
    if (!s) continue;
    const on = /** @type {HTMLInputElement|null} */ (document.getElementById(`${prefix}on-${e}`));
    out[e] = {...(on ? {on: on.checked} : {}), ...(p ? {priority: +p.value} : {}), sound: s.value};
  }
  return out;
}
