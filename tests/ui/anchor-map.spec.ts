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
