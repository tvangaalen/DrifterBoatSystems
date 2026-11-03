// Shared set-up of the browser tests: every request to api/... is answered from a recorded fixture (RECORD=1 records
// them from the mock instead), commands are captured and never sent, and the page's clock is fixed at the recording time.
import { test as base, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const DIR = path.join(__dirname, "fixtures");
const META = path.join(DIR, "_meta.json");
export const RECORD = !!process.env.RECORD;
// Query values that carry the current time: the fixture is the same whatever they are.
const VOLATILE = new Set(["since", "gen", "start", "end", "t", "_"]);

type Fixture = { note?: string; status: number; type: string; body: string; base64?: boolean };
// Fixtures hold the mock's made-up positions; the note (one line, like the file) tells the privacy scan so.
const NOTE = "privacy: ok - made-up data from tools/mock_upstreams.py";

function key(url: URL): string {
  const q = [...url.searchParams.entries()].map(([k, v]) => (VOLATILE.has(k) ? k : `${k}=${v}`)).sort().join("&");
  const p = url.pathname.replace(/^\/api\//, "") + (q ? "__" + q : "");
  return p.replace(/[^a-zA-Z0-9._=-]+/g, "_").slice(0, 180) + ".json";
}

export function recordedNow(): number {
  if (RECORD) {
    if (!fs.existsSync(META)) { fs.mkdirSync(DIR, { recursive: true }); fs.writeFileSync(META, JSON.stringify({ now: Date.now() }, null, 1)); }
  }
  return JSON.parse(fs.readFileSync(META, "utf8")).now;
}

export type Posted = { url: string; body: unknown };

export async function setUp(page: Page, opts: { theme?: string; posts?: Posted[] } = {}) {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(String(e)));
  // a failed request is reported by the response handler below (with its URL); the console line says only "404"
  page.on("console", m => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text()); });
  // map tiles: Leaflet aborts the ones it no longer needs once the map has fitted the boat, and the mock has none anyway
  page.on("requestfailed", r => { if (!/\/api\/anchor\/tiles\//.test(r.url())) errors.push(`request failed: ${new URL(r.url()).pathname} (${r.failure()?.errorText})`); });
  page.on("response", r => { if (r.status() >= 400 && !/\/api\/anchor\/tiles\//.test(r.url())) errors.push(`HTTP ${r.status()} ${new URL(r.url()).pathname}`); });
  await page.clock.setFixedTime(recordedNow());
  if (opts.theme) await page.addInitScript(t => { try { localStorage.setItem("drifter-theme", t); } catch (e) {} }, opts.theme);
  await page.route(/\/api\//, async route => {
    const req = route.request(), url = new URL(req.url());
    if (req.method() !== "GET") {                     // commands are captured, never sent
      opts.posts?.push({ url: url.pathname, body: req.postDataJSON() });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
    const file = path.join(DIR, key(url));
    if (RECORD && !fs.existsSync(file)) {
      const r = await route.fetch(), type = r.headers()["content-type"] || "", buf = await r.body();
      const text = /json|text|javascript/.test(type);
      const f: Fixture = { note: NOTE, status: r.status(), type, body: text ? buf.toString("utf8") : buf.toString("base64"), base64: !text || undefined };
      fs.writeFileSync(file, JSON.stringify(f));
    }
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: `no fixture for ${url.pathname}` }) });
    const f: Fixture = JSON.parse(fs.readFileSync(file, "utf8"));
    return route.fulfill({ status: f.status, contentType: f.type, body: f.base64 ? Buffer.from(f.body, "base64") : f.body });
  });
  return errors;
}

// The pages and views the app has: [name, hash, view button inside the page or null].
export const SCREENS: [string, string, string | null][] = [
  ["overview", "#overview", null],
  ["energy-now", "#power", null],
  ["energy-batteries", "#power", "#eViews [data-view=batt]"],
  ["energy-history", "#power", "#eViews [data-view=history]"],
  ["energy-settings", "#power", "#eViews [data-view=settings]"],
  ["anchor", "#anchor", null],
  ["guard", "#guard", null],
  ["washer", "#washer", null],
  ["system", "#system", null],
];

export async function open(page: Page, hash: string, view: string | null) {
  await page.goto("/" + hash);
  if (view) await page.locator(view).click();
  await settled(page);
}

// Waits until the page has loaded its data and stopped changing.
export async function settled(page: Page) {
  await expect(page.locator("#pages section:not([hidden])")).toBeVisible();
  await expect(page.locator("#pages section:not([hidden])")).not.toContainText("Loading…", { timeout: 15_000 });
  let last = "";
  await expect.poll(async () => { const now = await snapshot(page); const same = now === last; last = now; return same; },
    { intervals: [400, 400, 600, 800, 1000], timeout: 20_000 }).toBe(true);
}

// The visible page as normalised HTML: what the app built, independent of how its code is organised.
export async function snapshot(page: Page): Promise<string> {
  return page.evaluate(() => {
    // Leaflet's map panes are third-party markup whose tile order depends on load timing: only the map's own element counts.
    const parts = ["#title", "#sideNav", "#tabbar", "#alarmbar", "#pages section:not([hidden])"].map(s => {
      const el = document.querySelector(s)?.cloneNode(true) as HTMLElement | undefined;
      el?.querySelectorAll(".leaflet-container").forEach(m => { m.innerHTML = ""; m.removeAttribute("style"); });
      return el?.outerHTML ?? "";
    });
    return parts.join("\n").replace(/>\s+</g, ">\n<").replace(/[ \t]+/g, " ");
  });
}

export const test = base;
export { expect };
