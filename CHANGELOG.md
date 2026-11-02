# Changelog

## 0.11

### 0.11.0 — 2026-11-02

Shared code into `common/` (migration step 5).

- `common/net.py`: one LAN-only bind check, DNS-rebinding check and same-origin check, used by the gateway, the anchor watch (1.17.1), BoatGuard and the washer controller (3.8-v60) instead of four copies.
- `common/web.py`: HTTPS context and the quiet threading server (gateway, anchor watch, BoatGuard). `common/logs.py` + `common/timefmt.py`: one log format with date and 24-hour time; the gateway's log file under the scheduled task now rotates (1 MB × 5) instead of growing without limit.
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

- `switch_module.ps1`: checks (and where allowed sets) the scheduled task before stopping anything; scheduled tasks run `toolsun_module.py`, which follows `locations.json`, so a switch never edits a task; stops the launchers above a server too (no console window left at "pause"); a launcher that already exited no longer aborts the switch; safety net: any failure after stopping the old server starts it again from the old folder.
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
