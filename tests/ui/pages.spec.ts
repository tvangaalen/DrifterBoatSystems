// Every page and view, as the app builds it: the DOM must stay exactly the same (characterization for the refactor
// of phase 4), no errors in the console, times on the 24-hour clock. Screenshots per width and theme with SCREENS=1.
import { test, expect, setUp, open, snapshot, SCREENS, RECORD } from "./support";

const WIDTHS: [string, number, number][] = [["phone", 390, 844], ["portrait", 820, 1180], ["landscape", 1180, 820]];
const THEMES = ["light", "dark", "night"];

for (const [name, hash, view] of SCREENS) {
  for (const [wname, w, h] of WIDTHS) {
    test(`${name} at ${wname} width`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      const errors = await setUp(page, { theme: "light" });
      await open(page, hash, view);
      expect(errors).toEqual([]);
      const html = await snapshot(page);
      expect(html).not.toMatch(/\b\d{1,2}:\d{2}(:\d{2})?\s?(AM|PM)\b/i);       // 24-hour clock only
      if (!RECORD) expect(html).toMatchSnapshot(`${name}-${wname}.html`);
      if (process.env.SCREENS) {
        for (const theme of THEMES) {
          await page.evaluate(t => { if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t; window.dispatchEvent(new CustomEvent("drifter-theme", { detail: t })); }, theme);
          await page.waitForTimeout(300);
          await expect(page).toHaveScreenshot(`${name}-${wname}-${theme}.png`, { fullPage: true, animations: "disabled" });
        }
      }
    });
  }
}

test("every page loads on the iPhone (WebKit) @iphone", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  for (const [, hash, view] of SCREENS) await open(page, hash, view);
  expect(errors).toEqual([]);
});
