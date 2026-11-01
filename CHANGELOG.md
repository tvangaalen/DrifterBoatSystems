# Changelog

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
