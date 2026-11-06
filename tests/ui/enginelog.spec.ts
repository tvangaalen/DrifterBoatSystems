// Engine log: every entry can be created, read, changed and deleted; a new fill takes the time, the boat's position and
// the looked-up country and marina, all of which can be changed; deleting asks first with Keep as the default.
import { test, expect, setUp, open, type Posted } from "./support";

test("Engine log: a new fuel entry is filled in automatically and saves what the form shows", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#anchor", null);                          // the anchor watch knows the boat's position
  await open(page, "#enginelog", null);
  await expect(page.locator("#lBody .lrow")).toHaveCount(3);
  await page.locator("[data-new=fuel]").click();
  await expect(page.locator("#lMarina")).toHaveValue("Mock Marina North");
  await expect(page.locator("#lCountry")).toHaveValue("Testland");
  await expect(page.locator("#lPos")).toContainText("N");
  await page.locator("#lCountry").fill("Otherland");          // a changed value is what is saved
  await page.locator("#lHours").fill("2330.5"); await page.locator("#lLitres").fill("95");
  await page.locator("#lAmount").fill("-3"); await page.locator("#lSave").click();
  await expect(page.locator("#lErr")).toContainText("Amount");
  await page.locator("#lAmount").fill("152.50"); await page.locator("#lSave").click();
  await expect.poll(() => posts.length).toBe(1);
  const b = posts[0].body as any;
  expect(posts[0].url).toBe("/api/enginelog/api/fuel");
  expect([b.engine_hours, b.litres, b.country, b.marina]).toEqual([2330.5, 95, "Otherland", "Mock Marina North"]);
  expect(b.amount).toBe(152.5); expect(b.date).toMatch(/^\d{4}-\d\d-\d\d$/); expect(b.time).toBeUndefined(); expect(typeof b.lat).toBe("number");
  await expect(page.locator("#lForm")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("Engine log: change and delete a fill (Keep is the default), and add, change and delete maintenance", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#enginelog", null);
  await page.locator("[data-edit='fuel:a1b2c3d4e5f6']").click();
  await expect(page.locator("#lLitres")).toHaveValue("182");
  await page.locator("#lLitres").fill("185"); await page.locator("#lSave").click();
  await expect.poll(() => posts.map(p => p.url)).toEqual(["/api/enginelog/api/fuel/a1b2c3d4e5f6"]);
  expect((posts[0].body as any).litres).toBe(185);
  await page.locator("[data-edit='fuel:a1b2c3d4e5f6']").click();
  await page.locator("[data-delete]").click();
  await page.keyboard.press("Escape");                        // Escape keeps it
  expect(posts.length).toBe(1);
  await page.locator("[data-delete]").click();
  await page.locator("#dlgSheet [data-value]:not([data-default])").click();
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/enginelog/api/fuel/a1b2c3d4e5f6/delete");
  await page.locator("#lViews [data-lview=maintenance]").click();
  await expect(page.locator("#lBody .lrow")).toHaveCount(2);
  await page.locator("[data-new=maintenance]").click();
  await page.locator("#lSave").click();
  await expect(page.locator("#lErr")).toContainText("what was done");
  await page.locator("#lText").fill("Fuel filters\nprimary and secondary"); await page.locator("#lHours").fill("2320"); await page.locator("#lSave").click();
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/enginelog/api/maintenance");
  expect((posts.at(-1)!.body as any).text).toBe("Fuel filters\nprimary and secondary");
  expect((posts.at(-1)!.body as any).engine_hours).toBe(2320);
  await page.locator("[data-edit='maintenance:e5f6a1b2c3d4']").click();
  await page.locator("#lText").fill("Impeller and gasket"); await page.locator("#lSave").click();
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/enginelog/api/maintenance/e5f6a1b2c3d4");
  await page.locator("[data-edit='maintenance:e5f6a1b2c3d4']").click();
  await page.locator("[data-delete]").click(); await page.locator("#dlgSheet [data-value]:not([data-default])").click();
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/enginelog/api/maintenance/e5f6a1b2c3d4/delete");
  expect(errors).toEqual([]);
});

test("Engine log: dates as dd/mm/yyyy (or as chosen on System), typed or picked; Settings saves the fuel tank capacity", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#enginelog", "#lViews [data-lview=maintenance]");
  await expect(page.locator("#lBody .lrow").first()).toContainText(/\d\d\/\d\d\/\d{4}/);
  await page.locator("[data-new=maintenance]").click();
  await expect(page.locator("#lDate")).toHaveValue(/^\d\d\/\d\d\/\d{4}$/);
  await page.locator("#lDatePick").fill("2026-10-03");                 // the device's calendar
  await expect(page.locator("#lDate")).toHaveValue("03/10/2026");
  await page.locator("#lDate").fill("31/02/2026"); await page.locator("#lText").fill("x"); await page.locator("#lSave").click();
  await expect(page.locator("#lErr")).toContainText("dd/mm/yyyy");
  await page.locator("#lDate").fill("1/9/2026"); await page.locator("#lSave").click();
  await expect.poll(() => (posts.at(-1)?.body as any)?.date).toBe("2026-09-01");
  await page.locator("#lViews [data-lview=settings]").click();
  await expect(page.locator("#lTank")).toHaveValue("400");
  await page.locator("#lTank").fill("380"); await page.locator("#lSetSave").click();
  await expect.poll(() => posts.at(-1)?.body).toEqual({ tank_capacity_l: 380 });
  await open(page, "#system", null);
  await page.locator("[data-datefmt='yyyy-mm-dd']").click();
  await page.waitForLoadState();
  await open(page, "#enginelog", "#lViews [data-lview=maintenance]");
  await expect(page.locator("#lBody .lrow").first()).toContainText(/\d{4}-\d\d-\d\d/);
  expect(errors).toEqual([]);
});

test("Engine log: the fills over time, litres per fill and the use per engine hour", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#enginelog", null);
  const svg = page.locator("#lChart svg.fsvg");
  await expect(svg.locator("rect.fbar")).toHaveCount(3);
  await expect(svg.locator("circle.usedot")).toHaveCount(2);
  await expect(svg.locator("line.avg")).toHaveCount(1);
  await expect(page.locator("#lChart .flegend")).toContainText("Average 6.0 L/h");
  expect(errors).toEqual([]);
});
