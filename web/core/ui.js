// Shared fragments of the pages: the "not reachable" card and the switch control.
import {esc, hms, icon} from "./format.js";

export function downCard(m) {
  const e = m.state.err; if (!e) return "";
  return `<div class="down">${icon("alert")}<div><b>${esc(m.title)} not reachable</b><span>${esc(e.message)}${m.state.data ? ` · showing data from ${hms(m.state.t)}` : ""}</span></div></div>`;
}
export const sw = (id, on, attrs = "") => `<label class="switch"><input type="checkbox" role="switch" id="${id}" ${on ? "checked" : ""} ${attrs}><i></i></label>`;
