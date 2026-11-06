// History charts: tapping a legend item shows only that series in that chart; tapping it again shows them all.
import { test, expect, setUp, open } from "./support";

test("History: a legend tap shows one series on its own, a second tap all of them", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#power", "#eViews [data-view=history]");
  const leg = page.locator("#eChSocLeg");
  await expect(leg.locator("button")).toHaveCount(4);
  await leg.locator('[data-label="Battery 2"]').click();
  await expect(leg.locator('[data-label="Battery 2"]')).toHaveAttribute("aria-pressed", "true");
  await expect(leg.locator("button.off")).toHaveCount(3);
  await expect(page.locator("#eChSrcLeg button.off")).toHaveCount(0);     // the other charts keep all their series
  await leg.locator('[data-label="Battery 2"]').click();
  await expect(leg.locator("button.off")).toHaveCount(0);
  await expect(leg.locator('[aria-pressed="true"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("Energy opens on Control from the Overview, and History's Update reads the charts again", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#power", "#eViews [data-view=history]");
  await expect(page.locator("#eChSrc")).toBeVisible();
  const reads = [];
  page.on("request", r => { if (r.url().includes("/api/history/chart-data")) reads.push(r.url()); });
  await page.locator("#eHistUpd").click();
  await expect.poll(() => reads.length).toBeGreaterThan(0);
  await expect(page.locator("#eHistUpd")).toBeEnabled();
  await page.goto("/#overview");
  await page.locator("#ovTiles a[href='#power']").click();
  await expect(page.locator("#eViews [data-view=now]")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#eNow")).toBeVisible();
  expect(errors).toEqual([]);
});

test("History: the zoom slider shows part of the period in every chart; a period choice shows it whole again", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#power", "#eViews [data-view=history]");
  await expect(page.locator("#eChSrc")).toBeVisible();
  const span = () => page.evaluate(() => ["eChSoc", "eChSrc", "eChSpread"].map(id => { const o = (document.getElementById(id) as any)._map.opt; return o.t1 - o.t0; }));
  const whole = await span();
  const from = await page.locator("#eZFrom").textContent();
  await page.locator("#eZA").fill("500");
  await expect(page.locator("#eZFrom")).not.toHaveText(from || "");
  await expect.poll(async () => (await span()).map((s, i) => Math.round(s / whole[i] * 10) / 10)).toEqual([0.5, 0.5, 0.5]);
  await expect(page.locator("#eZReset")).toBeEnabled();
  await page.locator("#eZReset").click();
  await expect(page.locator("#eZA")).toHaveValue("0");
  await expect(page.locator("#eZReset")).toBeDisabled();
  await page.locator("#eZA").fill("500");
  await page.locator("#eRange [data-hours='24']").click();
  await expect(page.locator("#eZA")).toHaveValue("0");
  await page.mouse.wheel(0, 1500);     // the tabs, periods and slider stay at the top
  await expect.poll(() => page.locator("#eHistHead").evaluate(e => Math.round(e.getBoundingClientRect().top))).toBeLessThan(120);
  await expect(page.locator("#eHistHead #eViews")).toBeVisible();
  expect(errors).toEqual([]);
});
