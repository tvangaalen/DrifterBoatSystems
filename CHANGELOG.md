# Changelog

## Unreleased

- Energy page: the Now tab is Control; the House bank card with the meter, power and Voltage/Current/Temperature boxes;
  House battery is House bank on the Overview too
- Energy Control: providers/consumers with totals, Other batteries with meters under House bank
- Energy Control: switches on their provider/consumer line, consumers with a minus sign, small meters' needles clear of
  the pill
- Controls stand out in dark (own --ctl tokens for secondary buttons, segments, steppers); Other batteries moved to the
  Batteries tab
- Batteries tab: one-screen overview with a meter, cells, balancer and MOSFET state per pack, start and bow batteries;
  balancers folded
- Batteries tab: start and bow on top, House bank frame, per pack ON/OFF MOSFET switches, Set SOC, average cell voltage
  and a steady Read line; equal buttons
- Batteries tab: Pack details as one compact table with a House column (voltage, average cell voltage, maximum
  difference)
- Batteries tab: Bluetooth status and Bluetooth events fold to one line with a summary
- Batteries tab: flow in watts on the start/bow batteries and the House bank; Pack details folds, with an alarm row and
  the SOC on the charging/discharging curve (GET /api/bms adds it per battery, display only)
- Batteries tab: Balancers section removed (each pack tile shows its balancer)
- Anchor watch map measures its box again when it is shown or resized (a window resized on another page left it drawing
  one tile in the corner)
- History: state of charge as stacked columns on a fixed 0-100 % scale with a smooth total line; a legend tap shows one
  series in any chart
- History: state of charge as smooth stacked areas instead of columns
- Energy tile: one House bank tile on the Overview and Control, with temperature, battery type and the Float state in
  its header
- Energy: opens on Control; Generator mode; Sources chart smooth on a fixed 0-1800 W scale with amps; History Update
  button
- History: a two-handled slider zooms all charts into part of the period; tapping the chosen period reloads it
- History: fixed head with tabs, periods and zoom slider plus Reset; Sources 0-1400 W; Battery current smooth stacked
  0-100 A with watts; smooth cell spread
- History: no gaps when zoomed in, Sources and DC consumers smooth with 250 W / 25 A scales; no BMS pop-up setting;
  anchor map: info button for credits, magenta track and max swing, Holding fixed above the map
- History: Energy in this period as a flow diagram (share with kWh) and battery charged/discharged bars; DC consumers in
  100 W / 5 A steps
- Energy flow: shore power out of the DC balance and shown on its own with the net; HOUSE BANK label in the bar;
  batteries charged left, discharged right
- Tabs open on their first view; anchor map colours per light/dark and Fit one zoom closer; Float protection Pushover
  notification with a switch; energy Save sends every setting again; all manuals removed (energy technical chapters kept
  as docs/TECHNICAL.md); no pictures in the BoatGuard and Washer tiles
- History: Alarms chart per battery with alarm types (server: /api/history/alarms); anchor Fit puts the largest circle
  just inside the map; an open colour picker is no longer rebuilt
- Shore power ON/OFF notification with its own switch; Anchor watch Events foldable

## 1.2

### 1.2.0 — 2026-11-03

- **Overview, Energy**: the meter's needle is only its tip, clear of the percentage pill; the meter sits at the right of
  the tile. The small values sit at the bottom of every tile, level across a row.
- **Overview, Anchor watch**: a swing radar on the right (limit circle, max swing, track and boat, north up), as wide as
  the Energy meter: green while holding, orange close to the limit, red with a pulsing ring in an alarm; grey and dashed
  when no anchor is set. The app also fetches the track for it while an anchor is set.
- **Overview, BoatGuard**: an outlined wall camera on the right, its square red while the camera is armed. The title is
  *Monitoring off* or *Monitoring active* (green; red *Arming at …*); Phone *Away* and Camera *Armed* in red. An armed
  camera is no longer an alarm: no red badge or navigation dot.
- **Overview, Washer**: a graphite washing machine on the right whose display shows the time left.
- **Washer page**: an ON/OFF power switch in the status header (not during a wash; with a schedule set, switching off
  asks first). The cards: *Select program* (*Set program*; *Start now* and *Schedule* stay greyed out until the washer
  confirms), *Current program* with *Start now* and *Pause*, *Schedule* with its own messages; *Diagnostics* and
  *Events* fold to one status line.
- **BoatGuard page**: the Monitoring switch in the same ON/OFF style (switching off still asks first).
- **Releasing**: `tools/ship.py` runs only the tests for what changed, commits, pushes, deploys (restarting only what
  needs it) and verifies, in about a minute; small changes collect here until a release. The gateway puts a fingerprint
  of `web/` into the service worker's cache name, so a web-only deploy reaches the home-screen apps without a version
  bump or a restart. CI was red on a lint error from 0.22.0 until 2026-11-03 (fixed).

## 1.1

### 1.1.0 — 2026-11-03

- **Overview, Energy tile**: the house battery charge is a half-circle meter (red → orange → green, with a needle and the
  percentage below it) instead of the small ring, on the right of the tile. On the left *House battery*, the battery power
  and the voltage and current (without "House"); the first flow is called *Charger*. Colours from the theme tokens (in
  Night red only, without the sheen); no needle while the charge is unknown.

## 1.0

### 1.0.0 — 2026-11-02

The base for new functionality: the migration (0.1–0.13) and the refactoring (0.14–0.22) are complete. No functional change
since 0.22.0.
- One public repository with the full history; the Windows service *Drifter* (drifterd 1.2.0) runs the gateway and the four
  module servers, each under the module contract (plain HTTP on 127.0.0.1, token, `/health`); only the app serves HTTPS.
- Modules: MasterVolt 3.0.1, anchor watch 2.0.1, BoatGuard 2.0.0, washer controller 4.0.1.
- The app: ES modules, a type check, browser tests on recorded mock data; the user manual in the app.
- Operations: `verify_live.py`, push alerts when a system is down, *Backup keys and tokens*, the runbook and the developer guide.

## 0.22

### 0.22.0 — 2026-11-02

Improvements from the review of 2026-11-02.
- **Alerts**: the gateway's watchdog sends a push message (Pushover) when a system has not been running, or not answering, for
  5 minutes, and one when it is back (Energy and the anchor watch with high priority). It only reads drifterd's status; quiet
  after *Switch all systems off* and for a module on hold. Keys in `C:\DrifterData\gateway\pushover.json`; System → Alerts shows
  its state and has *Send test*. *Backup keys and tokens* copies that file too.
- `verify_live.py` checks the app's certificate and the Mastervolt Local CA (fails 60 days before they end).
- **MasterVolt 3.0.1** (no access log: ~3 MB a day less; the old stand-alone launchers removed) and **anchor watch 2.0.1**
  (GPS diagnostics kept 30 days). `start_drifter.cmd` and `tools/run_module.py` are removed as well.
- The app's templates have no fixed inline styles any more: 89 became utility classes in `app.css` (the 81 screenshots are
  identical pixel for pixel). The System page's install text no longer mentions the modules' old certificates.
- The tags `v0.16.0` and `washer/v4.0.0`, put on the wrong commit on 2026-11-02, are deleted (the user's OK).

## 0.21

### 0.21.1 — 2026-11-02

- **Backup keys and tokens** on the System page replaces the nightly back-up of 0.21.0 (never deployed; the user's choice):
  it copies the Pushover, noforeignland.com, EZVIZ and washer keys to `C:\DrifterBackups` (the same folders as in
  `C:\DrifterData`, replacing the previous copy) only when pressed, through the gateway (`POST /api/backup-keys`, only on the
  live gateway), and shows when it last did. drifterd stays 1.2.0: no schedule and no service restart for a back-up.

### 0.21.0 — 2026-11-02

Refactoring phase 5: documentation and operations.
- **User manual in the app** (English, the user's choice): System → *Manual* opens `web/manual.html`, built from `docs/MANUAL.md` by `tools/build_manual.py` (MasterVolt's renderer, the app's stylesheet and theme, a "‹ Drifter" button back). It describes every page, the alarms, the safety questions and the System page.
- **Runbook** (`docs/RUNBOOK.md`) and **developer guide** (`docs/DEVELOPER.md`); the README is a short overview linking to them.
- **One CLAUDE.md**: the rules of MasterVolt and the anchor watch moved into the root CLAUDE.md; their own CLAUDE.md files are gone.
- **Nightly back-up of the keys** (drifterd 1.3.0, `tools/backup.py`): at 03:30, only the Pushover, noforeignland.com, EZVIZ and washer keys (the user's choice: no positions, track or history), to `C:\DrifterBackups`, 7 daily and 4 weekly kept. The System page shows the newest back-up and a failed one, with its log.
- `tools/verify_live.py` waits for the start-up states after a restart (no answer yet, "starting", not yet polled) instead of failing at once.
- MasterVolt's leftover product photos are removed from `C:\Drifter`.

## 0.20

### 0.20.0 — 2026-11-02

Refactoring phase 4: the frontend.
- **Browser tests** (Playwright, `tests/ui`): every page and view at 390, 820 and 1180 px on recorded mock data with the clock fixed, compared with DOM snapshots; no console errors; only 24-hour times; the safe defaults of the confirmations (Keep ECU ON, Leave on, Cancel) and that declining sends nothing; every page in WebKit (Safari on the iPhone). They never touch the live servers: their own mock (`--offset 1000`) and captured commands.
- **The app as ES modules**: `web/app.js` split into `web/core` (format, api, dialogs, ui, app) and imported by the pages, `web/main.js` as the entry. The DOM of every page is unchanged and 81 screenshots (3 widths, 3 themes) are identical pixel for pixel.
- **Type check**: `npm run typecheck` (`tsc --checkJs` over `web/`, JSDoc types) at 0 errors. Node is a development tool only (`package.json`); there is no build step.
- **MasterVolt 3.0.0**: its classic page (`modules/energy/static`) is removed; the Energy page of this app is the only one. The API and everything behind it are unchanged.
- The gateway accepts up to 64 waiting connections (it was 5: a page load with many files at once got connections refused, found by the browser tests).
- CI runs the type check and the browser tests.

## 0.19

### 0.19.1 — 2026-11-02

- `tools/verify_live.py`: one read-only check of the live system after a deploy or restart (health and version, 403 without the token, supervisor and gateway state, and per module: energy - 3 BMS units connected, no BMS control busy, Float not latched; anchor - Orca Core, network GPS, Pushover, still-alive, no alarm; guard - router and camera; washer - status). Takes about a second; waits only for what can still come right. Not a gateway change: the app stays 0.19.0.

### 0.19.0 — 2026-11-02

Refactoring phase 3: energy, the last module.
- **MasterVolt 2.2.0**: `python -m mastervolt` under the module contract (plain HTTP on 127.0.0.1:8000, token, `/health`), with its own copy of the contract (MasterVolt does not import `common`). MasterBus, DALY, Float protection and every route are unchanged: the golden tests pass as before. drifterd starts it as `python -m mastervolt` instead of `start_mastervolt_server.cmd`, so no server certificate is issued for it any more; the Mastervolt Local CA stays in `modules/energy/certs` (the gateway's certificate comes from it).
- Every module now follows the contract: only the gateway serves HTTPS. The gateway's default address for energy is http://127.0.0.1:8000; the mock checks the token for energy too.

## 0.18

### 0.18.0 — 2026-11-02

Refactoring phase 3: the anchor watch.
- **Anchor watch 2.0.0**: the package `modules/anchor/anchor` on FastAPI with the module contract (plain HTTP on 127.0.0.1:8766, token, `/health`). `anchor_watch.py` was split block by block without changing the code (`AnchorWatch.tick`, the GPS rules, alerts, AIS, NFL, tide): its 114 tests run unchanged against the package, and `test_api_contract.py` (state, track, commands with every error path, tiles) passed against the stdlib server of 1.17 and against 2.0. drifterd starts it as `python -m anchor`; network GPS (NMEA) stays on the LAN address (`--bind auto`). Its certificate script and start scripts are gone.
- `common/service.py`: `start()` serves a module's API in a thread, for the anchor watch, whose main thread runs its asyncio data loops.
- The gateway's default address for the anchor watch is http://127.0.0.1:8766; the mock checks the token for the anchor watch too.

## 0.17

### 0.17.0 — 2026-11-02

Refactoring phase 3: BoatGuard.
- **BoatGuard 2.0.0**: the package `modules/guard/guard` on FastAPI with the module contract (plain HTTP on 127.0.0.1:8095, token, `/health`): `config.py` (schema of config.json: a mistake stops it with the field and the reason), `router.py`, `camera.py`, `notify.py`, `core.py` (the presence logic of 1.x, unchanged: generated from boatguard.py) and `api.py`. `test_api_contract.py` (8 tests: status, log, monitoring, every settings refusal, notification tests, the camera test, refused requests) passed against the stdlib server of 1.x and against 2.0; `test_core.py` is the self-test of 1.x on the package. `python -m guard run | login | pushover | status | arm | disarm`. Its HTTPS certificate, firewall script, start script and own requirements file are gone; `requests` leaves its environment (Pushover goes through `common/pushover.py`). boatguard.py and boatguard_web.py stay one release for the comparison.
- drifterd 1.2.0 reads modules.json at every start and health check: a module's new command or health check applies at its next restart, without restarting the service.
- The gateway's default address for BoatGuard is http://127.0.0.1:8095.

## 0.16

### 0.16.1 — 2026-11-02

- Washer controller 4.0.1: the Flask controller 3.8, its contract adapter, its old tests and its requirements files are removed (4.0.0 has run live since 14:43 and passed the same contract); Flask leaves the lock.
- The tags `v0.16.0` and `washer/v4.0.0` point at the commit before 0.16.0 (a blocked commit, the script tagged anyway); 0.16.0 is the commit "Module contract and the washer on FastAPI". Tags from here on: `v0.16.1`, `washer/v4.0.1`.

### 0.16.0 — 2026-11-02

Refactoring phase 3, the module contract; the washer first.
- **The module contract** (`common/service.py`, for the FastAPI modules): plain HTTP on 127.0.0.1, a token on every request but `GET /health` (`X-Drifter-Token`; drifterd 1.1.0 makes a new one at every start and gives it to the gateway and every module as `DRIFTER_TOKEN`; without it a module refuses everything but `/health`), `/health` for drifterd's health check, no caching of JSON. The gateway sends the token with every upstream request (modules not yet on the contract ignore it) instead of the washer's own `X-Viomi-Request`.
- **Washer controller 4.0.0**: the Flask controller (one 973-line file with module-level state) is now the package `modules/washer/washer` on FastAPI: config with a schema, device, events, schedule, diagnostics, API. `test_api_contract.py` pins down the API at HTTP level (15 tests: every route, status code and message, the schedule's life cycle, diagnostics, export) and passed against the Flask controller 3.8 and against 4.0; plus tests for the module contract and the config schema. drifterd starts it as `python -m washer` and checks `/health`. The Flask file stays one release for that comparison.

## 0.15

### 0.15.1 — 2026-11-02

The first install of the service hung, and every server stayed stopped until it was fixed:
- drifterd 1.0.1: the Windows service calls have full ctypes signatures. Without them the 64-bit status handle was passed as a 32-bit number, "running" never reached Windows and the service hung in Start Pending; the exception was lost inside the callback. Every failure in the service code is now logged.
- `install_service.ps1`: TLS 1.2 for the pre-checks (Windows PowerShell 5.1 did not offer it, so they failed and the script went on: now it stops when Drifter runs but cannot be asked); `sc.exe start` instead of `Start-Service`, which waited without end, so the automatic way back never came; a hanging service is ended before it is replaced; the way back runs drifterd from a boot task (the old gateway task no longer starts the modules).

### 0.15.0 — 2026-11-02

Refactoring phase 2: the runtime.
- **drifterd, the Windows service "Drifter"** (`drifterd.py`, stdlib only, on the plain python.org Python): runs the gateway and the four modules as its own child processes, each in its own kill-on-close job object (`common/proc.py`), writes their output to the console logs, keeps them running (the supervisor now lives here, not in the gateway) and answers the gateway on a control API (127.0.0.1:8099, token file). Windows starts it at boot (delayed), whether anybody is logged on or not, and restarts it after a crash. The service control code is ctypes, not pywin32: a virtual environment's python.exe is only a launcher, which a Windows service cannot be.
- `tools/install_service.ps1` replaces `install_autostart.ps1`: session check, pre-checks, "Log on as a service", the service with restart-after-crash and start/stop rights for the user, and a switch-over that goes back to the scheduled task by itself when the app does not come up. `start_all.ps1` (the desktop icon) starts the service.
- The gateway talks to drifterd (`DrifterdClient`): states, logs (now also the service's own), restart (also of the gateway) and switch-off, after its own pre-checks. Switch-off ends the modules, then the gateway and the service.
- **Health checks** per module (display only): *not answering* on the System page when a server listens but does not answer.
- Removed: the migration tools (`switch_module.ps1`, `prepare_live.ps1`, `locations.json`, legacy folders in `modules.json`), `stop_module.ps1` and the PowerShell/WMI start path (`start_all.ps1 -Only`). `tools/run_module.py` stays only for the fallback scheduled task.
- Planned for phase 3 instead (it needs each module's server, rewritten on FastAPI there): a shared token between gateway and modules with plain HTTP on 127.0.0.1.

## 0.14

### 0.14.2 — 2026-11-02

- **One scheduled task.** BoatGuard no longer has its own task: Drifter's supervisor starts it like the other three modules (the gateway runs in session 0 too now, so the reason for a separate task is gone). `install_autostart.ps1` stops and removes the BoatGuard task and restarts the gateway; `modules.json` marks it `old_task`, and while that task still exists BoatGuard stays a task module, so there can never be two BoatGuards (both would steer the camera).

### 0.14.1 — 2026-11-02

- A restart from the app puts a module's new Python environment in place when `tools/sync_envs.py --into .venv-next` built one: the supervisor swaps it between stopping and starting. Only it can do that: the servers run in session 0, and a process of another logon session may not stop them (the first live switch failed that way, nothing changed). `sync_envs.py --swap <module>` now just asks the gateway for that restart (same pre-checks as the System page).

### 0.14.0 — 2026-11-02

Refactoring phase 1: the foundation. No behaviour changes (every suite, including MasterVolt's golden tests, passes unchanged).
- **One Python, one lockfile.** All servers run on the python.org Python 3.12 instead of the Microsoft Store Python 3.13 (which hung at boot in session 0). `pyproject.toml` has a dependency group per module and `uv.lock` fixes all 80 packages; `tools/sync_envs.py` builds the gateway's `.venv` and each module's `.venv` from it, and swaps a module's environment live (`--into .venv-next`, `--swap`). MasterVolt gets its own environment for the first time (it used the user's shared Store Python packages); `start_mastervolt_server.cmd` uses it when present. Pinned as they ran: starlette 1.6.0, websockets 13.1 for the anchor watch (14+ changed the client API); netifaces is left out for the washer as before.
- The gateway, `start_all.ps1`, `stop_module.ps1` and `install_autostart.ps1` (both tasks, Drifter and BoatGuard) use these environments instead of the py launcher. Run `install_autostart.ps1` once more to move the scheduled tasks over.
- **Lint:** `ruff` for the gateway, `common/`, `tools/`, `tests/` and the anchor, guard and washer modules (pyflakes and bugbear; the dense style stays); MasterVolt keeps its own black + ruff configuration. Four small findings fixed (unused imports, an f-string without placeholders).
- **Privacy scan** automated: `tools/privacy_scan.py`, as pre-commit hook and in CI, with a local deny list outside git.
- **CI** on GitHub (Windows): privacy scan, lint, JavaScript syntax and all hardware-free tests on every push.

## 0.13

### 0.13.2 — 2026-11-02

- Desktop icon: a scheduled task whose server stops while the icon waits is started again. Clicked right after "Switch all systems off", the gateway still listened for its last 15 s, so it counted as "already running", then ended, and nothing started the other modules.
- Log window: a **‹ Drifter** button goes back to the app (closes the log window, or opens the System page). In the home-screen app the log opens in place, since there are no tabs or back button there.
- `tools/create_shortcut.ps1` (re)creates the desktop icon with the full path of powershell.exe; the icon on the OneDrive desktop had lost its target.

### 0.13.1 — 2026-11-02

First boot without anybody logged on: BoatGuard, MasterVolt (USB Link and all three BMS over Bluetooth), the anchor watch and the washer all ran in session 0, but getting there was slow and fragile. Fixed:
- The supervisor starts modules in their own threads: it used to wait for each `start_all.ps1`, which took up to 90 s in session 0 after the boot, so the anchor watch's first start timed out and the others waited. A start is timed from when it really began.
- `start_all.ps1` reads the module list once (each Python start is slow in session 0 right after a boot); the supervisor gives the script 4 min, a module 5 min before it counts as failed, and the "already starting" marker blocks a second start for 5 min (MasterVolt listened 177 s after its start; two MasterVolts would fight over the USB Link).
- `install_autostart.ps1` sets the boot delay to 2 min: with 30 s the py launcher hung before starting Python (the task then stays "running" and is never restarted); BoatGuard's task, at 1 min, was fine. Run it once more to apply this.

### 0.13.0 — 2026-11-02

- **Every module runs without a window, with a log file**, so all of Drifter can run while nobody is logged on. MasterVolt and the anchor watch now start through `tools/run_module.py` like the others; output goes to `<data>\logs\<module>.console.log` (previous 5 MB kept as `.log.1`). The console-window switches of 0.12.0 are replaced by **System → Show log**: the module's log in its own window or tab (`web/log.html`, `GET /api/supervisor/log`), following the newest lines.
- **Start at boot without logging on:** `tools/install_autostart.ps1` (run once, elevated; asks for the Windows password) checks in the boot session that the MasterBus USB Link, Bluetooth and process starts work (`tools/session0_check.py`, read-only), then makes the DrifterBoatSystems task start at boot whether anybody is logged on or not. The supervisor starts a module that is down at its own start at once (no 30 s grace); the desktop icon only starts the scheduled tasks when the supervisor is on and waits up to 3 min.
- **Switch all systems off** no longer refuses while Float is latched (BMS control busy and an anchor alarm still refuse).
- Overview, Energy tile: **Charger house / Alternator / Solar / DC load (−)**; Shore removed. Labels may wrap so the values stay aligned.
- Anchor watch, GPS & links: the GPS in use also shows when it is **on hold** (the server marks the Core's GPS on static hold in the position; the row status "in use" hid it).
- 24-hour clock everywhere: the washer schedule uses hour and minute lists instead of `<input type="time">` (which iOS shows with AM/PM in a 12-hour region); MasterVolt 2.1.3 shows the BMS card's time with `hourCycle: 'h23'`.

## 0.12

### 0.12.0 — 2026-11-02

- **System → Switch all systems off.** Confirmation with *Leave on* as the default, listing what stops (Float protection; the anchor alarm when the anchor is set; BoatGuard's automatic arming; a scheduled wash). Refused like a restart (BMS control busy, Float latched, anchor alarm). The supervisor stops its loop, stops washer, BoatGuard, anchor watch and MasterVolt, and the gateway ends itself 15 s later with exit code 0 (its scheduled task does not restart it). The page shows the progress, then "All systems have been shut down. Press OK to close the application" and closes the tab on OK, or shows a "switched off" page where the browser does not allow that. Nothing is switched on the boat: inverter, chargers, alternator, Engine ECU and camera stay as they are.
- **Console windows per system**, hidden by default: System → *Console window on the boat PC* for MasterVolt and the anchor watch. Kept in `C:\DrifterData\consoles.json`; `start_all.ps1` starts the consoles hidden or shown accordingly, the supervisor applies a change at once and keeps it. The window is found through the process listening on the module's port, not by title. Started by Drifter, both start scripts skip their final `pause` (anchor watch 1.17.2), so a stopped server leaves no hidden window behind.
- Overview, Energy tile: **Alternator** power next to Solar and Shore; **DC load** shown as a negative value.

## 0.11

### 0.11.0 — 2026-11-02

Shared code into `common/` (migration step 5).

- `common/net.py`: one LAN-only bind check, DNS-rebinding check and same-origin check, used by the gateway, the anchor watch (1.17.1), BoatGuard and the washer controller (3.8-v60) instead of four copies.
- `common/web.py`: HTTPS context and the quiet threading server (gateway, anchor watch, BoatGuard). `common/logs.py` + `common/timefmt.py`: one log format with date and 24-hour time. Started without a console (`pyw drifter.py`), the gateway's `logs\drifter.log` now rotates (1 MB × 5); under the scheduled task `tools/run_module.py` keeps appending its output to `logs\gateway.console.log`, as before.
- `common/pushover.py`: posting to Pushover for the anchor watch and BoatGuard. Each keeps its own key file, queue, priorities and retries; BoatGuard no longer needs `requests` for it.
- `common/issue_cert.ps1`: one certificate script from the Mastervolt Local CA (random serial, nothing written to the CA folder, refuses without the CA). The gateway's `setup_https.ps1`, BoatGuard's `setup_https.ps1` and the anchor watch's `setup_local_https.ps1` call it; their default CA folder is now `modules\energy\certs` of the same checkout instead of the old `C:\Temp\mastervoltproject\certs`.
- MasterVolt (energy) unchanged. New `tests/test_common.py` (suite `common` in `run_all.py`).

## 0.10

### 0.10.0 — 2026-11-02

Energy, part 3: MasterVolt leaves the network.

- `start_mastervolt_server.cmd` binds 127.0.0.1 when started by Drifter (`DRIFTER_DATA` set); the gateway reaches MasterVolt on https://127.0.0.1:8000. MasterVolt's own page stays reachable on the boat PC itself as a fallback; its frontend files are kept (MasterVolt's release test checks them). MasterBus/DALY code, mappings and safety logic unchanged.
- With this every module is in Drifter and no module server is reachable from the boat network any more (except the anchor watch's network GPS port).
- The gateway and BoatGuard read a POST body before answering, also when they refuse it (403/415/400): closing with unread data reset the connection, so the page saw a network error instead of the reason (the BoatGuard API test failed now and then because of it).

## 0.9

### 0.9.1 — 2026-11-02

- Gateway: passes gzip through when the browser accepts it, so the History charts load about 2.5 MB less JSON from MasterVolt each time.

### 0.9.0 — 2026-11-01

Energy, part 2: history charts.

- History tab: charts of the state of charge (total and per battery, from the remaining Ah), sources and DC consumers (stacked, opaque bands), battery current and cell spread, for 6 h, 24 h, 3 d, 7 d or 31 d, with a crosshair that shows the values (touch or mouse). The chart data is the server's drawing sample, refreshed once a minute.
- Energy in this period: kWh and average W per source (incl. shore), per DC consumer, and charged/discharged per battery, from `/api/history/contributions` (the server's full-resolution totals; never added up in the browser).

## 0.8

### 0.8.0 — 2026-11-01

Energy, part 1 of moving MasterVolt's classic page into Drifter.

- Fixed for MasterVolt 2.x: the Settings form follows its settings table (Float purely by the highest cell voltage; the old SOC thresholds and warning pop-up are gone, so saving failed), the Float line shows the cell trigger and the highest cell now, and the balancer cards read the balancer's `status` (they were empty).
- New: active mode marked, battery type and capacity, SOC calibration per battery and for all (Charge % / Discharge % from the cell voltages, 100 %, or a manual value; Cancel is the default), Bluetooth diagnostics (radio, waiting queue, per device counters and timings, recent events), a History tab with the battery health report (runs in the server's separate low-priority process, shown as formatted Markdown), the manual and the history database status.
- Gateway: passes SOC calibration (`set-soc-100|charge|discharge|value`, `set-all-soc/…`), starting a report, `/api/history/status`, `/api/version` and `/manual`.

## 0.7

### 0.7.0 — 2026-11-01

Anchor watch: everything is in Drifter now; the anchor watch has no page of its own.

- App: the Anchor watch page gets everything of the old page: alarm sound, vibration and wake lock on the phone or tablet (Sound on/off, also in the alarm bar; on automatically when dropping), an alarm when the watch cannot be reached with the anchor set (on every page), the classic status lines (holding, close to the limit, outside the circle with countdown), map layers, max swing, rode, fading track, named AIS targets (internet hollow), scale, fit, Windy, move with 1 m nudges and arrow keys, radius ±5 m, scope calculator, new track, the classic tiles incl. sun and position, tide chart with chain advice and keel clearance, GPS order/removal/default, connection statuses with tests (test alarm asks first), all settings incl. transducer depth, NMEA port and NFL at anchor, My MMSI suggestion, credits.
- Anchor watch 1.17.0: page, manifest and icons removed; `--web-bind` (API on 127.0.0.1) separate from `--bind` (network GPS on the LAN); `--app-url` for the link in push alerts. Alarm logic unchanged. New `test_api.py`.
- Leaflet is served by Drifter (`web/vendor/leaflet`); the gateway no longer passes `/vendor/` on.

## 0.6

### 0.6.2 — 2026-11-01

- `run_module.py`: the job object of 0.6.1 was not enough. The modules start through the venv launcher (`.venv\Scripts\pythonw.exe`), which starts the real python itself, and that python escaped the inherited job and outlived the runner. The server is now started suspended, assigned to the job explicitly, then resumed; everything it starts stays in the job. Tests for the venv launcher and for a silent-breakaway outer job.

### 0.6.1 — 2026-11-01

- `tools/run_module.py` runs the server inside a kill-on-close job object: stopping the scheduled task (BoatGuard, gateway) now stops the server too. Before, BoatGuard's server outlived `Stop-ScheduledTask` and, running in session 0, could not be stopped from the app (restart failed with "port 8095 still in use"). Test added (`tests/test_run_module.py`).

### 0.6.0 — 2026-11-01

BoatGuard: everything is in Drifter now; BoatGuard has no page of its own.

- App: an Emergency (priority 2) test notification asks first (it repeats every minute until acknowledged); the arming countdown updates every second.
- BoatGuard: the page (`static/index.html`) is removed; the API listens on 127.0.0.1 only (`web.host` adds one private LAN address on purpose, never a public one). Arming, presence, notifications and settings unchanged. New `test_web.py`.
- Gateway: BoatGuard is reached on https://127.0.0.1:8095; no classic-page link.

## 0.5

### 0.5.1 — 2026-11-01

- Supervisor: a tick during a restart from the app no longer marks the module "on hold" and starts a new 30 s grace period; a slow server (MasterVolt) could otherwise get a second start while the first was still coming up. Test added.

### 0.5.0 — 2026-11-01

Washer: everything is in Drifter now; the controller has no page of its own.

- App: Diagnostics card on the Washer page (summary, failed checks first and the passed ones folded, controller version and uptime, washer and PC address, model, firmware; Recheck and JSON export) and a refresh button.
- VIOMI controller 3.8-v59: the controller and startup-diagnostics pages and the app icons are removed; new `GET /api/diagnostics` (`?recheck=1` re-runs the checks); it listens on 127.0.0.1 only (`VIOMI_BIND` may choose another private address). Commands, validation and scheduler unchanged.
- Gateway: `GET /api/washer/api/diagnostics` replaces the HTML route `/`; the washer has no classic-page link any more.

## 0.4

### 0.4.0 — 2026-11-01

Supervisor: the gateway keeps the module servers running.

- `supervisor.py`: adopts running servers, starts one that has not listened for 30 s (through `start_all.ps1 -Only`, outside the gateway's process tree), waits 2.5 min for it, backs off 1/2/5/10/15 min; never stops a server by itself; respects `C:\DrifterData\hold\<module>`. On with `"supervise": true` (live config only).
- System page: per server its state, uptime and last event, a Restart button (with confirmation; refused while a BMS control runs, Float is latched or an anchor alarm is active; allowed when the server does not answer), and the supervisor's events. `POST /api/supervisor/restart`.
- `start_all.ps1` marks a module as starting and never starts it twice within 2 min; skips modules on hold. New `tools/stop_module.ps1`, used by `switch_module.ps1` (which now sets a hold while moving).
- Tests: `tests/test_supervisor.py` (adopt, grace, back-off, hold, restart, pre-checks, API); the mock gateway runs a fake supervisor that only logs.

## 0.3

### 0.3.1 — 2026-11-01

All five servers moved to `C:\Drifter` / `C:\DrifterData` (washer, BoatGuard, anchor watch, MasterVolt, gateway).

- `switch_module.ps1`: checks (and where allowed sets) the scheduled task before stopping anything; scheduled tasks run `tools
un_module.py`, which follows `locations.json`, so a switch never edits a task; stops the launchers above a server too (no console window left at "pause"); a launcher that already exited no longer aborts the switch; safety net: any failure after stopping the old server starts it again from the old folder.
- `modules.json`: MasterVolt's product photos are copied on switch-over; `prepare_live.ps1` installs without the pip cache.

### 0.3.0 — 2026-11-01

Moving the servers to `C:\Drifter` is prepared (nothing has moved yet).

- Modules keep their runtime files in `DRIFTER_DATA\<module>` when `DRIFTER_DATA` is set; unset, everything stays where it was. energy: `mastervolt.config.Paths.runtime` (settings, history, backups, logs, MasterShunt cache; code and certificates stay), new `tests/test_paths.py`; guard and washer: their config/state/token files and logs; anchor: its existing command-line options.
- `modules.json` + `tools/modules.py`: per module port, old and new folder, command and runtime files; the active location per module in `C:\DrifterData\locations.json`.
- `tools/prepare_live.ps1` (clone `C:\Drifter`, venvs), `tools/switch_module.ps1` (move one module, or back with `-Back`), `tools/run_module.py` (run a module without a window, for scheduled tasks).
- `start_all.ps1` follows the recorded locations and starts servers through Win32_Process Create, outside the starting process's tree; MasterVolt and the anchor watch get their usual console window again (minimised).

## 0.2

### 0.2.0 — 2026-11-01

One repository for everything.

- The four module repositories are now `modules/energy`, `modules/anchor`, `modules/guard` and `modules/washer`, with their full history; their release tags are kept as `<module>/vX.Y.Z`.
- Layout: app in `web/`, gateway tests in `tests/`, mock servers in `tools/`; `tests/run_all.py` runs the gateway tests and every module's suite.
- `start_all.ps1` and a desktop icon start whatever is not running (never restarting a running server) and open the app; scheduled task `DrifterBoatSystems` starts the gateway at logon.
- Behaviour of the app and of all module servers is unchanged; the live servers still run from their old folders.

## 0.1

### 0.1.0 — 2026-11-01

First version: one app for Energy (MasterVolt YMS), Anchor watch (Orca Core 2), BoatGuard and the VIOMI washer.

- Gateway `drifter.py` (stdlib): serves the app and passes an allowlist of routes on to the four existing servers; LAN-only bind, host check, JSON + own-header + same-origin check on commands; `/api/systems` reports each server's reachability.
- App: overview, the four module pages and a System page; anchor alarm bar on every page; nav badges.
- One design system with Auto, Light, Dark and Night themes; iPhone tab bar, iPad sidebar/icon rail; home-screen app (manifest, icons, app-shell service worker).
- Safety confirmations: Engine ECU OFF (default *Keep ECU ON*), alternator OFF, MOSFETs OFF, monitoring OFF, raise anchor, shorter history.
- `mock_upstreams.py` + `config.mock.json` for testing without the boat; `test_drifter.py` (13 tests).
- The module servers are unchanged.
