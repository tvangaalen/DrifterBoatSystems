// Requests to the module servers through the Drifter gateway (api/<module>/...). Commands are POSTs with
// X-Drifter-Request, which the gateway requires; it adds the module token itself.

export class ApiError extends Error { constructor(msg, status, down) { super(msg); this.status = status; this.down = down; } }
export async function api(module, path, body, opts = {}) {
  /** @type {RequestInit} */
  const init = body === undefined ? {cache: "no-store"} :
    {method: "POST", headers: {"Content-Type": "application/json", "X-Drifter-Request": "1"}, body: JSON.stringify(body)};
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), opts.timeout || (body === undefined ? 15000 : 95000));
  init.signal = ctl.signal;
  let r;
  try { r = await fetch(`api/${module}${path}`, init); }
  catch (e) { throw new ApiError(e.name === "AbortError" ? "No answer (timed out)" : "Drifter server not reachable", 0, true); }
  finally { clearTimeout(timer); }
  let j = null; try { j = await r.json(); } catch (e) {}
  if (!r.ok || (j && j.ok === false)) {
    const d = j && (j.detail ?? j.error);
    throw new ApiError(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${r.status}`, r.status, !!(j && j.upstream_down));
  }
  return j;
}
