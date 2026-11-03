// Shared fragments of the pages: the "not reachable" card and the switch control.
import {esc, hms, icon} from "./format.js";

export function downCard(m) {
  const e = m.state.err; if (!e) return "";
  return `<div class="down">${icon("alert")}<div><b>${esc(m.title)} not reachable</b><span>${esc(e.message)}${m.state.data ? ` · showing data from ${hms(m.state.t)}` : ""}</span></div></div>`;
}
/** A switch; cls "onoff" gives the big green ON / red OFF style (washer power, BoatGuard monitoring). */
export const sw = (id, on, attrs = "", cls = "") => `<label class="switch${cls ? " " + cls : ""}"><input type="checkbox" role="switch" id="${id}" ${on ? "checked" : ""} ${attrs}><i></i></label>`;
