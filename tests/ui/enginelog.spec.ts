// Engine log: every entry can be created, read, changed and deleted; a new fill takes the date, the engine hours (Orca
// Core) and the boat's position, all of which can be changed; deleting asks first with Keep as the default. The fuel
// entry list is folded by default; a position opens Google Maps in its own window; the engine alarms are listed.
import { test, expect, setUp, open, type Posted } from "./support";
import fs from "node:fs";
import path from "node:path";

test("Engine log: a new fuel entry is filled in automatically and saves what the form shows", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#anchor", null);                          // the anchor watch knows the boat's position
  await open(page, "#enginelog", null);
  await expect(page.locator("#lBody .lrow")).toHaveCount(3);
  await expect(page.locator("#lFuelFold")).not.toHaveAttribute("open", "");    // the fuel entries are folded by default
  await page.locator("[data-new=fuel]").click();
  await expect(page.locator("#lHours")).toHaveValue("2321.4");        // live from the engine
  await expect(page.locator("#lMarina")).toHaveCount(0); await expect(page.locator("#lCountry")).toHaveCount(0);
  await expect(page.locator("#lPos")).toContainText("N");
  await expect(page.locator("#lPosBtns [data-maps]")).toHaveCount(1);
  await page.locator("#lHours").fill("2330.5"); await page.locator("#lLitres").fill("95");
  await page.locator("#lAmount").fill("-3"); await page.locator("#lSave").click();
  await expect(page.locator("#lErr")).toContainText("Amount");
  await page.locator("#lAmount").fill("152.50"); await page.locator("#lSave").click();
  await expect.poll(() => posts.length).toBe(1);
  const b = posts[0].body as any;
  expect(posts[0].url).toBe("/api/enginelog/api/fuel");
  expect([b.engine_hours, b.litres, b.country, b.marina]).toEqual([2330.5, 95, undefined, undefined]);
  expect(b.amount).toBe(152.5); expect(b.date).toMatch(/^\d{4}-\d\d-\d\d$/); expect(b.time).toBeUndefined(); expect(typeof b.lat).toBe("number");
  await expect(page.locator("#lForm")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("Engine log: change and delete a fill (Keep is the default), and add, change and delete maintenance", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#enginelog", null);
  await page.locator("#lFuelFold summary").click();
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
  await expect(page.locator("#lBody .lrow[data-edit^=maintenance]")).toHaveCount(3);
  await page.locator("[data-new=maintenance]").click();
  await expect(page.locator("#lHours")).toHaveValue("2321.4");        // the engine hours, filled in
  await page.locator("#lSave").click();
  await expect(page.locator("#lErr")).toContainText("what was done");       // nothing ticked and no text
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
  await expect(page.locator("#lTemp")).toHaveValue("95"); await expect(page.locator("#lOil")).toHaveValue("1");
  await page.locator("#lOil").fill("0.8");
  await page.locator("#lTank").fill("380"); await page.locator("#lSetSave").click();
  await expect.poll(() => posts.at(-1)?.body).toEqual({ tank_capacity_l: 380, fuel_margin_pct: 115, temp_high_c: 95, oil_low_bar: 0.8 });
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
  await expect(page.locator("#lChart .flegend")).toContainText("Average");
  const tiles = page.locator("#lBody .minis.m4 .mini");
  await expect(tiles).toHaveCount(4);
  await expect(tiles.nth(0)).toContainText("6.0"); await expect(tiles.nth(2)).toContainText("€ 1.61"); await expect(tiles.nth(3)).toContainText("€ 550");
  expect(errors).toEqual([]);
});

test("Maintenance schedule: what is due on top, all items folded; Log opens a new entry with the item ticked", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await open(page, "#enginelog", "#lViews [data-lview=maintenance]");
  const card = page.locator("#lBody .sched");
  await expect(card.locator("h3")).toHaveText("Maintenance schedule");
  await expect(card.locator(".hd .badge.bad")).toHaveText("2 due");                                 // the mock: fuel filter and coolant
  await expect(card.locator(":scope > .srows .srow")).toHaveCount(2);
  await expect(card.locator(":scope > .srows")).toContainText("Replace the fuel filter element");
  await expect(page.locator("#lSchedFold")).not.toHaveAttribute("open", "");                        // all items: folded
  await page.locator("#lSchedFold summary").click();
  await expect(page.locator("#lSchedFold .srow")).toHaveCount(23);
  await expect(page.locator("#lSchedFold")).toContainText("Replace the marine gear oil (KM4A)");
  await expect(page.locator(".lrow").first().locator(".itags span")).toHaveCount(4);                 // an entry shows the items it did
  await card.locator(':scope > .srows [data-log="fuel_filter"]').click();
  await expect(page.locator('#lForm input[name="lItem"]:checked')).toHaveCount(1);
  await expect(page.locator('#lForm input[value="fuel_filter"]')).toBeChecked();
  await page.locator("#lSave").click();                                                             // no text needed with an item ticked
  await expect.poll(() => posts.find(p => p.url.endsWith("/api/maintenance"))?.body).toMatchObject({ text: "", items: ["fuel_filter"] });
  expect(errors).toEqual([]);
});

test("Engine and fuel: Dashboard shows the engine as a cockpit, with the warning lights", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  await open(page, "#enginelog", "#lViews [data-lview=data]");
  const views = page.locator("#lViews button");
  await expect(views.nth(0)).toHaveText("Diesel"); await expect(views.nth(2)).toHaveText("Dashboard"); await expect(views.nth(3)).toHaveText("Settings");   // left of Settings
  await expect(page.locator("#lBody .cockpit > .meter.big")).toHaveAttribute("aria-label", "Engine speed 1800 rpm");
  const arcs = page.locator("#lBody .ga .meter");
  await expect(arcs).toHaveCount(6);
  await expect(arcs.nth(0)).toHaveAttribute("aria-label", "Coolant 80 °C");
  await expect(arcs.nth(1)).toHaveAttribute("aria-label", "Oil pressure 3.5 bar");
  await expect(page.locator("#lLive")).toContainText("Running");
  await expect(page.locator("#lLamps .wlamp")).toHaveCount(7);
  await expect(page.locator("#lLamps .wlamp.bad, #lLamps .wlamp.warn")).toHaveCount(0);           // the mock's engine sets no lights
  await page.route(/\/api\/enginelog\/api\/log/, async r => {                                      // now the engine sets two lights and one more
    const f = JSON.parse(JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "enginelog_api_log.json"), "utf8")).body);
    f.engine.alarm_source.status = ["Over temperature", "Preheat indicator", "Rev limit exceeded"];
    await r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(f) });
  });
  await expect(page.locator("#lLamps .wlamp.bad")).toHaveCount(2, { timeout: 10_000 });
  await expect(page.locator("#lLamps .wlamp.bad").first()).toContainText("Over temperature");
  await expect(page.locator("#lLamps .wlamp.warn")).toHaveText(/Preheat\s*on/);                     // a notice, not an alarm
  await expect(page.locator("#lLamps .wlamp")).toHaveCount(8);                                     // a light outside the usual set is added
  expect(errors).toEqual([]);
});

test("Engine and fuel: the fuel left, estimated from a full tank at the last fill, on the page and the Overview", async ({ page }) => {
  const errors = await setUp(page, { theme: "dark" });
  // the mock: a 400 L tank, 6.05 L/h on average + the 15 % safety margin = 6.96 L/h, 6.37 engine hours since the last fill -> 356 L, 51 h
  await open(page, "#enginelog", null);
  await expect(page.locator("#lBody .estim")).toContainText("Estimated remaining");
  await expect(page.locator("#lBody .estim .v")).toHaveText(/356\s*L\s*51\s*h/);
  await open(page, "#overview", null);
  const tile = page.locator("#ovTiles .tile").filter({ has: page.locator("a[href='#enginelog']") });
  await expect(tile.locator("h3")).toHaveText("Engine and fuel");
  await expect(tile.locator(".big")).toHaveText("Estimated remaining 356 L – 51 h");              // big, under the title
  await expect(tile.locator(".line").first()).toContainText("Last refuel");
  await expect(tile.locator(".mini").nth(2)).toHaveText(/Maintenance\s*2/);                        // the mock: 2 schedule items due
  await expect(tile.locator(".mini").nth(2).locator(".n")).toHaveClass(/badc/);
  await expect(page.locator("#ovTiles .tile").filter({ has: page.locator("a[href='#power']") }).locator(".mini").nth(1).locator(".n")).toHaveText("0 W31°");   // the alternator's temperature, small after its power
  expect(errors).toEqual([]);
});

test("Engine log: a position opens Google Maps in its own window; the engine alarms are listed and can be deleted (Keep first)", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { theme: "dark", posts });
  await page.addInitScript(() => { (window as any).__opened = []; window.open = ((...a: any[]) => { (window as any).__opened.push(a); return null; }) as any; });
  await open(page, "#enginelog", null);
  await page.locator("#lFuelFold summary").click();
  await expect(page.locator("#lFuelFold .maps[data-maps]")).toHaveCount(2);         // the fill without a position has none
  await page.locator("#lFuelFold .maps[data-maps]").first().click();
  const opened = await page.evaluate(() => (window as any).__opened);
  expect(opened[0][0]).toBe("https://www.google.com/maps/search/?api=1&query=10.500000,-20.250000");   // privacy: ok - made-up position of the mock
  expect(opened[0][2]).toContain("popup");
  await page.locator("#lViews [data-lview=maintenance]").click();
  await expect(page.locator("#lEngine")).toContainText("1800 rpm");
  await expect(page.locator("#lAlarmSrc")).toContainText("YDEN-02");          // the alarms come from the YDEN-02
  await expect(page.locator("#lAlarmFold")).not.toHaveAttribute("open", "");   // the alarm log is folded by default
  await page.locator("#lAlarmFold summary").click();
  await expect(page.locator("[data-delalarm]")).toHaveCount(1);
  await expect(page.locator("#lBody")).toContainText("High coolant temperature");
  await page.locator("[data-delalarm]").click(); await page.keyboard.press("Escape");
  expect(posts.length).toBe(0);
  await page.locator("[data-delalarm]").click(); await page.locator("#dlgSheet [data-value]:not([data-default])").click();
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/enginelog/api/alarms/f6a1b2c3d4e5/delete");
  expect(errors).toEqual([]);
});
