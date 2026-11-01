# Changelog

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
