// Formatting helpers shared by every page: escaping, numbers, watts, icons and the clock. Times are always 24-hour
// (never locale time defaults: AM/PM must not appear).

/** An element by id. Typed loosely on purpose: the pages use it for inputs, buttons and plain elements alike.
 * @param {string} id @returns {any} */
export const $ = id => document.getElementById(id);
export const pad = n => String(n).padStart(2, "0");
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
export const toDate = t => t instanceof Date ? t : new Date(typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : t);
export const hm = t => { if (t == null) return "–"; const d = toDate(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
export const hms = t => { if (t == null) return "–"; const d = toDate(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
// Dates follow the format chosen on the System page (remembered on this device): dd/mm/yyyy (default), dd-mm-yyyy or yyyy-mm-dd.
export const DATE_FORMATS = ["dd/mm/yyyy", "dd-mm-yyyy", "yyyy-mm-dd"];
export const dateFmt = () => { try { const f = localStorage.getItem("drifter-datefmt"); return DATE_FORMATS.includes(f) ? f : DATE_FORMATS[0]; } catch (e) { return DATE_FORMATS[0]; } };
/** A date as text in the chosen format; `short` leaves out the year. */
export const day = (t, short = false) => { const d = toDate(t), f = dateFmt(), D2 = pad(d.getDate()), M2 = pad(d.getMonth() + 1), Y = d.getFullYear();
  return f === "yyyy-mm-dd" ? (short ? `${M2}-${D2}` : `${Y}-${M2}-${D2}`) : `${D2}${f[2]}${M2}${short ? "" : f[2] + Y}`; };
export const dm = t => day(t, true);
/** YYYY-MM-DD (a stored date) as text in the chosen format. @param {string} iso */
export const dateText = iso => /^\d{4}-\d{2}-\d{2}$/.test(iso || "") ? day(new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10))) : "";
/** Text typed in the chosen format (also with / - or . between) to YYYY-MM-DD, or null. @param {string} text */
export const parseDate = text => {
  const p = String(text || "").trim().split(/[/.\-\s]+/); if (p.length !== 3 || p.some(x => !/^\d+$/.test(x))) return null;
  const [y, mo, d] = dateFmt() === "yyyy-mm-dd" ? p.map(Number) : [+p[2], +p[1], +p[0]], t = new Date(y, mo - 1, d);
  return y > 1900 && t.getFullYear() === y && t.getMonth() === mo - 1 && t.getDate() === d ? `${y}-${pad(mo)}-${pad(d)}` : null;
};
export const dayTime = t => { if (t == null) return "–"; const d = toDate(t), now = new Date();
  return d.toDateString() === now.toDateString() ? hm(d) : `${dm(d)} ${hm(d)}`; };
export const dur = s => { if (s == null || !isFinite(s)) return "–"; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h} h ${pad(m)} min` : m ? `${m} min${r && m < 10 ? ` ${r} s` : ""}` : `${r} s`; };
export const ago = t => t == null ? "–" : dur(Date.now() / 1000 - (t > 1e12 ? t / 1000 : t)) + " ago";
export const num = (v, d = 0) => v == null || v === "" || !isFinite(+v) ? "–" : (+v).toFixed(d);
export const W = v => { if (v == null || !isFinite(+v)) return "–"; v = +v; return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(2)} kW` : `${Math.round(v)} W`; };
export const icon = (id, cls = "i") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
