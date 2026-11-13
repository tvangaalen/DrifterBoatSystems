// The confirmations that guard the boat: the safe answer is the default button, and Escape, tapping outside and the
// safe button send nothing. Commands are captured by the fixtures, never sent.
import { test, expect, setUp, open, type Posted } from "./support";
import fs from "node:fs";
import path from "node:path";

const dialog = (page: import("@playwright/test").Page) => page.locator("#dlgSheet");
/** A recorded answer's body, to answer with a changed copy. */
const fixture = (name: string) => JSON.parse(JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8")).body);

test("Engine ECU off: default is Keep ECU ON, and declining sends nothing @iphone", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#power", "#eViews [data-view=now]");      // the controls are on Control
  const ecu = page.locator("#ec-engine_ecu");
  test.skip(!(await ecu.count()), "the mock has no Engine ECU switch");
  test.skip(!(await ecu.isChecked()), "the mock's Engine ECU is off");
  for (const decline of ["button", "Escape", "outside"]) {
    await expect(ecu).toBeChecked({ timeout: 10_000 });     // the next read from the server shows it on again
    await ecu.click({ force: true });
    await expect(dialog(page)).toContainText("Switch off Engine ECU?");
    await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Keep ECU ON");
    await expect(page.locator("#dlgSheet [data-default]")).toBeFocused();
    if (decline === "button") await page.locator("#dlgSheet [data-default]").click();
    else if (decline === "Escape") await page.keyboard.press("Escape");
    else await page.locator("#dialog").click({ position: { x: 5, y: 5 } });
    await expect(page.locator("#dialog")).not.toHaveClass(/open/);
  }
  expect(posts).toEqual([]);
});

test("Battery discharge MOSFET off: default is Keep ON, and declining sends nothing", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#power", "#eViews [data-view=batt]");
  await expect(page.locator("#eBatt .pack #bms-d-1, #eBatt .pack [data-soc]")).toHaveCount(0);     // not in the pack tiles:
  await page.locator("#ePackFold summary").click();                                               // at the bottom of Pack details
  await expect(page.locator("#ePackFold tbody tr").last()).toContainText("Set SOC");
  const fet = page.locator("#ePackFold #bms-d-1");
  await expect(fet).toBeChecked();
  await fet.scrollIntoViewIfNeeded();
  for (const decline of ["button", "Escape"]) {
    await fet.click({ force: true });
    await expect(dialog(page)).toContainText("Switch off discharge on Battery 1?");
    await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Keep ON");
    if (decline === "button") await page.locator("#dlgSheet [data-default]").click();
    else await page.keyboard.press("Escape");
    await expect(page.locator("#dialog")).not.toHaveClass(/open/);
    await expect(fet).toBeChecked();
  }
  expect(posts).toEqual([]);
});

test("Overview: the Inverter button at the bottom of the tile; off asks first (Keep Inverter ON the default), on is sent at once", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#overview", null);
  const inv = page.locator("#ov-inverter");
  await expect(inv).toHaveText("Switch Inverter ON");                      // the mock's inverter is off
  await expect(inv).toHaveAttribute("aria-pressed", "false");
  await inv.click();
  await expect.poll(() => posts.map(p => [p.url, p.body])).toEqual([["/api/power/api/control/inverter", { enabled: true }]]);
  await page.route(/\/api\/power\/api\/energy$/, async r => {                // now it reads back on
    const b = fixture("power_api_energy.json"); b.combimaster.inverter_enabled = 1;
    await r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
  });
  await expect(inv).toHaveText("Switch Inverter OFF", { timeout: 10_000 });
  await expect(inv).toHaveAttribute("aria-pressed", "true");
  posts.length = 0;
  await inv.click();
  await expect(dialog(page)).toContainText("Switch off the Inverter?");
  await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Keep Inverter ON");
  await expect(page.locator("#dlgSheet [data-default]")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#dialog")).not.toHaveClass(/open/);
  expect(posts).toEqual([]);
});

test("Overview: Anchor up asks first, Cancel the default; confirming raises it", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await page.route(/\/api\/anchor\/api\/state/, async r => {               // the anchor down (made-up position near the boat)
    const s = fixture("anchor_api_state.json"), p = (s.boat || {}).pos || { lat: 10.5, lon: -20.25 };
    s.anchor = { lat: p.lat - 0.0001, lon: p.lon, radius: 40, set_at: Date.now() / 1000 - 600, depth: 6.4 };
    await r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(s) });
  });
  await open(page, "#overview", null);
  const raise = page.locator("#ovRaise");
  await expect(raise).toBeVisible();
  for (const decline of ["button", "Escape"]) {
    await raise.click();
    await expect(dialog(page)).toContainText("Anchor up?");
    await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Cancel");
    await expect(page.locator("#dlgSheet [data-default]")).toBeFocused();
    if (decline === "button") await page.locator("#dlgSheet [data-default]").click(); else await page.keyboard.press("Escape");
    await expect(page.locator("#dialog")).not.toHaveClass(/open/);
  }
  expect(posts).toEqual([]);
  await expect(page).toHaveURL(/#overview$/);                               // the button does not open the page under it
  await raise.click();
  await page.locator("#dlgSheet button:not([data-default])").filter({ hasText: "Anchor up – stop watch" }).click();
  await expect.poll(() => posts.map(p => [p.url, p.body])).toEqual([["/api/anchor/api/command", { action: "raise" }]]);
});

test("Overview: Drop anchor & start watch, as Already lying to it with the advised chain; Cancel the default", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#overview", null);
  const drop = page.locator("#ovDrop");                                  // the mock's anchor is up; its chain advice 43 m
  await expect(drop).toContainText("43 m · radius 55 m");                // 43 + 10, rounded up to a multiple of 5
  await drop.click();
  await expect(dialog(page)).toContainText("Anchor 43 m ahead of the bow");
  await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Cancel");
  await page.keyboard.press("Escape");
  await expect(page.locator("#dialog")).not.toHaveClass(/open/);
  expect(posts).toEqual([]);
  await drop.click();
  await page.locator("#dlgSheet button:not([data-default])").filter({ hasText: "Drop anchor" }).click();
  await expect.poll(() => posts.map(p => [p.url, p.body])).toEqual([["/api/anchor/api/command", { action: "drop", mode: "ahead", distance: 43, radius: 55 }]]);
});

test("Switch all systems off: default is Leave on, and declining sends nothing", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#system", null);
  await page.locator("#sysOff").click();
  await expect(dialog(page)).toContainText("Switch all systems off?");
  await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Leave on");
  await expect(page.locator("#dlgSheet [data-default]")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#dialog")).not.toHaveClass(/open/);
  expect(posts).toEqual([]);
});

test("Restart a module: Cancel is the default", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#system", null);
  await page.locator('[data-restart="energy"]').click();
  await expect(page.locator("#dlgSheet [data-default]")).toHaveText("Cancel");
  await page.keyboard.press("Escape");
  expect(posts).toEqual([]);
});

test("Backup keys and tokens sends one request and says what it copied", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#system", null);
  await page.locator("#sysBackup").click();
  await expect(page.locator("#toast")).toContainText("files copied");
  expect(posts.map(p => p.url)).toEqual(["/api/backup-keys"]);
});

test("Alerts: Send test sends one request", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#system", null);
  await page.locator("#sysAlertTest").click();
  await expect(page.locator("#toast")).toContainText("Test alert sent");
  expect(posts.map(p => p.url)).toEqual(["/api/alerts/test"]);
});

test("Pushover: the keys are typed hidden and sent once, the page only shows their last 4; alerts keep priority and sound", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#system", null);
  await expect(page.locator("#sysPushTok")).toHaveAttribute("type", "password");
  await expect(page.locator("#sysPushTok")).toHaveAttribute("placeholder", "…ab12");
  await page.locator("#sysPushTok").fill("short"); await page.locator("#sysPushSave").click();
  await expect(page.locator("#toast")).toContainText("30 letters"); expect(posts).toEqual([]);
  await page.locator("#sysPushTok").fill("a".repeat(30)); await page.locator("#sysPushSave").click();  // privacy: ok
  await expect.poll(() => posts.map(p => p.url)).toEqual(["/api/alerts/keys"]);
  expect(posts[0].body).toEqual({ app_token: "a".repeat(30), user_key: "" });
  await expect(page.locator("#toast")).toContainText("Pushover keys saved");
  await page.locator("#sasnd-back").selectOption("bike"); await page.locator("#sapri-back").selectOption("-1");
  await page.locator("#sysAlertSave").click();
  await expect.poll(() => posts.length).toBe(2);
  expect((posts[1].body as any).prefs.back).toEqual({ on: true, priority: -1, sound: "bike" });
  await expect(page.locator("#saon-down")).toBeChecked();                           // every alert has its own switch
  await expect(page.locator("#sapri-back option[value='2']")).toHaveCount(0);     // no emergency for the gateway's alerts
  await page.locator("#sysAlertRows [data-ntest=down]").click();                   // each alert has its own Test
  await expect.poll(() => posts.at(-1)?.url).toBe("/api/alerts/test");
  expect(posts.at(-1)!.body).toEqual({ event: "down", sound: "", priority: 0 });
});

test("BoatGuard: Monitoring and Settings; the camera test and the log are on Settings, with a Test per notification", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { posts });
  await open(page, "#guard", null);
  await expect(page.locator("#gViews [data-gview=mon]")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#gHero")).toBeVisible();
  await expect(page.locator("#gTest")).toBeHidden(); await expect(page.locator("#gLogFold")).toBeHidden();
  await page.locator("#gViews [data-gview=set]").click();
  await expect(page.locator("#gTest")).toBeVisible(); await expect(page.locator("#gSet")).toBeVisible();
  await expect(page.locator("#gLogFold")).toBeVisible(); await expect(page.locator("#gLogFold")).not.toHaveAttribute("open", "");
  await expect(page.locator("#gHero")).toBeHidden();
  await expect(page.locator("#gSounds button", { hasText: "Test" })).toHaveCount(3);
  expect(errors).toEqual([]);
});

test("Anchor watch: a Test per push alert; anchor drag's is the emergency test alarm and asks first (Cancel)", async ({ page }) => {
  const posts: Posted[] = [];
  const errors = await setUp(page, { posts });
  await open(page, "#anchor", "#aViews [data-aview=settings]");
  await page.locator("[data-ntest=depth]").click();
  await expect.poll(() => posts.at(-1)?.body).toMatchObject({ action: "push_test", key: "depth" });
  const n = posts.length;
  await page.locator("[data-ntest=drag]").click();
  await expect(dialog(page)).toContainText("Send a real test alarm?"); await page.keyboard.press("Escape");
  await page.waitForTimeout(300); expect(posts.length).toBe(n);                      // declined: nothing sent
  expect(errors).toEqual([]);
});

test("Washer: Set program greys out Start now and Schedule until the washer confirms", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await page.route(/\/api\/washer\/api\/status/, async r => { await new Promise(res => setTimeout(res, 1500)); await r.fallback(); });   // a slow washer
  await open(page, "#washer", null);
  await expect(page.locator("#wStart")).toBeEnabled();
  await page.locator("#wSet").click();
  await expect(page.locator("#wStart")).toBeDisabled();
  await expect(page.locator("#wSched")).toBeDisabled();
  await expect(page.locator("#wSetMsg")).toContainText("applied", { timeout: 15_000 });
  await expect(page.locator("#wStart")).toBeEnabled();
  expect(posts.map(p => p.url)[0]).toMatch(/^\/api\/washer\/api\/program\//);
});
