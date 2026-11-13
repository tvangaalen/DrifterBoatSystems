// The anchor watch map must measure its box again when it is shown: a window resized while another page was open used to
// leave Leaflet at 0 x 0, so it drew the boat in the top-left corner at the wrong scale.
import { test, expect, setUp, open } from "./support";

test("Anchor watch map: resized while hidden, the boat is still in the middle", async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 900 });
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#anchor", null);
  await expect(page.locator("#aMap .leaflet-marker-icon.boaticon").last()).toBeVisible({ timeout: 10_000 });
  await page.evaluate(() => { location.hash = "#overview"; });
  await expect(page.locator("#aMap")).toBeHidden();
  await page.setViewportSize({ width: 600, height: 900 });
  await page.evaluate(() => { location.hash = "#anchor"; });
  await expect(page.locator("#aMap")).toBeVisible();
  await page.waitForTimeout(2500);     // a refresh (every 1.5 s) redraws and refits the map: then the old size shows
  await expect.poll(async () => {
    const map = await page.locator("#aMap").boundingBox(), boat = await page.locator("#aMap .leaflet-marker-icon.boaticon").last().boundingBox();
    if (!map || !boat) return Infinity;
    return Math.max(Math.abs(boat.x + boat.width / 2 - (map.x + map.width / 2)) / map.width, Math.abs(boat.y + boat.height / 2 - (map.y + map.height / 2)) / map.height);
  }, { timeout: 5_000 }).toBeLessThan(0.25);
  expect(errors).toEqual([]);
});

test("Anchor map: no credits on the map, its info button opens them on GPS & links; Holding stays at the top", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#anchor", null);
  await expect(page.locator("#aMap .leaflet-control-zoom")).toBeVisible();
  await expect(page.locator("#aMap .leaflet-control-attribution")).toHaveCount(0);
  await expect(page.locator("#aHead #aHero")).toBeVisible();
  await page.locator("#aCreditsBtn").click();
  await expect(page.locator("#aViews [data-aview=gps]")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#aCredits")).toBeInViewport();
  await expect(page.locator("#aHero")).toBeHidden();
  expect(errors).toEqual([]);
});

test("Anchor settings: an open colour picker is not rebuilt by the next poll", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#anchor", "#aViews [data-aview=settings]");
  const pick = page.locator("#as-col_track_dark");
  await pick.dispatchEvent("pointerdown"); await pick.focus();
  await pick.evaluate(e => e.setAttribute("data-mark", "1"));
  await page.waitForTimeout(6000);     // more than one poll
  await expect(page.locator("#as-col_track_dark[data-mark='1']")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("Anchor watch: Events is folded with a one-line summary and opens on a tap (and stays open)", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#anchor", null);
  await expect(page.locator("#aLogSum")).toContainText("last");
  await expect(page.locator("#aLog")).toBeHidden();
  await page.locator("#aLogFold summary").click();
  await expect(page.locator("#aLog")).toBeVisible();
  await page.waitForTimeout(3500);     // the next polls keep it open
  await expect(page.locator("#aLog")).toBeVisible();
  expect(errors).toEqual([]);
});

test("Anchor map: Seamarks, Fit and Windy side by side at the top left, equally wide, Map/Sat/Plain on the same row; zoom at the bottom left", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#anchor", null);
  const btns = page.locator("#aMap .maprow .btn");
  await expect(btns).toHaveText([/Seamarks/, /Fit/, /Windy/]);
  const box = await Promise.all([0, 1, 2].map(i => btns.nth(i).boundingBox()));
  const map = (await page.locator("#aMap").boundingBox())!;
  expect(new Set(box.map(b => Math.round(b!.y))).size).toBe(1);                         // one row
  expect(Math.max(...box.map(b => b!.width)) - Math.min(...box.map(b => b!.width))).toBeLessThan(1);   // equally wide
  const seg = (await page.locator("#aBase").boundingBox())!;                              // Map/Sat/Plain on the same row, at the right
  expect(Math.abs(seg.y + seg.height / 2 - (box[0]!.y + box[0]!.height / 2))).toBeLessThan(4);
  expect(seg.x).toBeGreaterThanOrEqual(box[2]!.x + box[2]!.width);
  expect(seg.x + seg.width).toBeLessThanOrEqual(map.x + map.width);                      // all inside the map on a phone
  const zoom = (await page.locator("#aMap .leaflet-control-zoom").boundingBox())!;
  expect(zoom.y).toBeGreaterThan(map.y + map.height / 2);                                // the zoom buttons moved down
  expect(errors).toEqual([]);
});

test("GPS sources: each device once with its address; Deleted GPS sources folded, Restore puts one back", async ({ page }) => {
  const posts: { url: string; body: any }[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#anchor", "#aViews [data-aview=gps]");
  const rows = page.locator("#aGps .gpsrow");
  await expect(rows.first()).toContainText("Orca Core 2"); await expect(rows.first()).toContainText("address 254");
  await expect(page.locator("#aGpsDel")).not.toHaveAttribute("open", "");
  await expect(page.locator("#aGpsDel summary")).toContainText("1");
  await page.locator("#aGpsDel summary").click();
  await page.locator("[data-grestore]").click();
  await expect.poll(() => posts.at(-1)?.body).toEqual({ action: "gps_restore", source: "n1000000000000000002" });
  await page.locator('[data-forget="300"]').click();                                       // removing asks first, Keep the default
  await expect(page.locator("#dlgSheet")).toContainText("Deleted GPS sources");
  await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Keep");
  await page.keyboard.press("Escape");
  expect(posts.filter(p => p.body.action === "gps_forget")).toEqual([]);
  expect(errors).toEqual([]);
});
