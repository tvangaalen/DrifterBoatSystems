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
