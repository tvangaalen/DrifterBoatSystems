// The confirmations that guard the boat: the safe answer is the default button, and Escape, tapping outside and the
// safe button send nothing. Commands are captured by the fixtures, never sent.
import { test, expect, setUp, open, type Posted } from "./support";

const dialog = (page: import("@playwright/test").Page) => page.locator("#dlgSheet");

test("Engine ECU off: default is Keep ECU ON, and declining sends nothing @iphone", async ({ page }) => {
  const posts: Posted[] = [];
  await setUp(page, { posts });
  await open(page, "#power", null);
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
