// Browser tests of the Drifter app (tests/ui), always against their own mock gateway (tools/mock_upstreams.py --gateway
// --offset 1000: port 9101), never against the live servers: a click there could arm the camera, switch the inverter or start the
// washer. The app's API answers come from recorded fixtures (tests/ui/fixtures), with the page's clock fixed, so every
// run renders exactly the same page. Record them again with RECORD=1 after a change to the mock.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/ui",
  timeout: 60_000,
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  reporter: process.env.CI ? [["list"]] : [["list"]],
  // DOM snapshots are text and the same on every platform; screenshots (SCREENS=1, local only) depend on fonts.
  snapshotPathTemplate: "{testDir}/__snapshots__/{arg}{ext}",
  expect: { toHaveScreenshot: { pathTemplate: "{testDir}/screens/{projectName}/{arg}{ext}", maxDiffPixels: 0 } },
  use: { baseURL: "http://127.0.0.1:9101/", timezoneId: "Europe/Amsterdam", locale: "en-GB", serviceWorkers: "block" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "iphone", use: { ...devices["iPhone 13"] }, grep: /@iphone/ },   // WebKit, as Safari on the iPhone
  ],
  webServer: {
    command: process.platform === "win32" ? ".venv\\Scripts\\python.exe tools/mock_upstreams.py --gateway --offset 1000" : ".venv/bin/python tools/mock_upstreams.py --gateway --offset 1000",
    url: "http://127.0.0.1:9101/",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
