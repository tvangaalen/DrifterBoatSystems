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
export const day = t => { const d = toDate(t); return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`; };
export const dayTime = t => { if (t == null) return "–"; const d = toDate(t), now = new Date();
  return d.toDateString() === now.toDateString() ? hm(d) : `${pad(d.getDate())}-${pad(d.getMonth() + 1)} ${hm(d)}`; };
export const dur = s => { if (s == null || !isFinite(s)) return "–"; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h} h ${pad(m)} min` : m ? `${m} min${r && m < 10 ? ` ${r} s` : ""}` : `${r} s`; };
export const ago = t => t == null ? "–" : dur(Date.now() / 1000 - (t > 1e12 ? t / 1000 : t)) + " ago";
export const num = (v, d = 0) => v == null || v === "" || !isFinite(+v) ? "–" : (+v).toFixed(d);
export const W = v => { if (v == null || !isFinite(+v)) return "–"; v = +v; return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(2)} kW` : `${Math.round(v)} W`; };
export const icon = (id, cls = "i") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
