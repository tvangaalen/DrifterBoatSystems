// Dialogs (bottom sheets) and the toast. confirm(): the safe answer is the default button; Escape and tapping outside
// also choose it, and a locked sheet (switching off) cannot be dismissed.
import {$, esc} from "./format.js";

export let dlgResolve = null, lastFocus = null;
export function sheet(html, focusSel) {
  return new Promise(res => {
    if (dlgResolve) dlgResolve(null);
    dlgResolve = res; lastFocus = document.activeElement;
    delete $("dlgSheet").dataset.lock; $("dlgSheet").innerHTML = html; $("dialog").classList.add("open"); $("dialog").setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => { const f = $("dlgSheet").querySelector(focusSel || "[data-default]") || $("dlgSheet").querySelector("button"); f && f.focus(); });
  });
}
export function closeSheet(v) {
  $("dialog").classList.remove("open"); $("dialog").setAttribute("aria-hidden", "true");
  const r = dlgResolve; dlgResolve = null; if (r) r(v); if (lastFocus && lastFocus.focus) lastFocus.focus();
}
$("dialog").addEventListener("click", e => {
  if (e.target === $("dialog")) return $("dlgSheet").dataset.lock ? null : closeSheet(null);   // tap outside = the safe choice (cancel)
  const b = e.target.closest("[data-close],[data-value]"); if (b) closeSheet(b.dataset.value ?? null);
});
document.addEventListener("keydown", e => { if (e.key === "Escape" && dlgResolve && !$("dlgSheet").dataset.lock) closeSheet(null); });
// confirm(): the safe answer is the default button, Escape and tapping outside also choose it.
/** @typedef {{title: string, text?: string, note?: string, items?: string[], ok?: string, cancel?: string, danger?: boolean, safeDefault?: boolean}} ConfirmOptions */
/** @param {ConfirmOptions} opts @returns {Promise<boolean>} */
export async function confirm({title, text, note, items, ok = "OK", cancel = "Cancel", danger = false, safeDefault = true}) {
  const v = await sheet(`<h3 id="dlgTitle">${danger ? '<span class="warnicon">!</span>' : ""}${esc(title)}</h3>
    ${text ? `<p style="color:var(--fg)">${esc(text)}</p>` : ""}${items ? `<ul>${items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}${note ? `<p>${esc(note)}</p>` : ""}
    <div class="acts"><button class="btn ${danger ? "danger" : ""}" data-value="ok" ${safeDefault ? "" : "data-default"}>${esc(ok)}</button>
    <button class="btn sec" data-value="cancel" ${safeDefault ? "data-default" : ""}>${esc(cancel)}</button></div>`);
  return v === "ok";
}
export let toastT = null;
export function toast(msg, bad) {
  const t = $("toast"); t.textContent = msg; t.className = "toast on" + (bad ? " bad" : "");
  clearTimeout(toastT); toastT = setTimeout(() => t.className = "toast" + (bad ? " bad" : ""), bad ? 6000 : 2600);
}
