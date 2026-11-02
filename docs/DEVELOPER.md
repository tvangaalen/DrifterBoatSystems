# Drifter Boat Systems — developer guide

How the code is organised and how to change it safely. Running the live system: [RUNBOOK.md](RUNBOOK.md). Using the
app: [MANUAL.md](MANUAL.md). The rules for Claude Code (and for anyone): [../CLAUDE.md](../CLAUDE.md).

## 1. Architecture

```
            iPhone / iPad (Safari, home-screen app)
                         │ HTTPS 192.168.1.166:8100 (certificate from the Mastervolt Local CA)
                         ▼
   ┌───────────── drifterd (Windows service "Drifter") ─────────────┐
   │  gateway drifter.py ── serves web/, passes allowed routes on   │
   │     │ HTTP 127.0.0.1 + X-Drifter-Token                         │
   │     ├── energy  (MasterVolt, FastAPI)  :8000  USB MasterBus, Bluetooth DALY
   │     ├── anchor  (FastAPI)              :8766  Orca Core 2 (read-only), NMEA :10110 on the LAN
   │     ├── guard   (BoatGuard, FastAPI)   :8095  UniFi router, EZVIZ camera, Pushover
   │     └── washer  (FastAPI)              :8080  VIOMI W1 (miio)
   │  supervisor.py (start, restart on request, health), nightly back-up of the keys
   └────────────────────────────────────────────────────────────────┘
```

- **The module servers are the authority.** Float protection (MasterVolt), the anchor alarm (`AnchorWatch.tick`), arming
  the camera and the washer schedule run on their own servers and keep working when the app is closed. The gateway only
  passes requests on: it never decides, retries a command or polls hardware. The page only displays and sends commands.
- **drifterd** (`drifterd.py`, stdlib, the plain python.org Python) is the Windows service. It runs the gateway and the
  four modules as child processes, each in its own kill-on-close job object (`common/proc.py`), writes their output to
  `<data>\logs\<module>.console.log`, and answers the gateway on 127.0.0.1:8099 (token file `C:\DrifterData\drifterd.token`):
  `GET /status`, `GET /log`, `POST /restart`, `POST /shutdown`. It reads `modules.json` at every start and health check.
- **supervisor.py** (inside drifterd) starts a module that is down, never stops one on its own, restarts on request (after
  the gateway's pre-checks), swaps in `.venv-next` during a restart, and shows each module's state and events. Health
  checks (`modules.json` `health`, every 30 s) are display only.
- **The gateway** (`drifter.py`, stdlib) serves `web/`, passes only the routes in `ROUTES` to the modules, and checks every
  request: bind only to localhost/private addresses, Host header (DNS rebinding), and for POST: JSON, `X-Drifter-Request: 1`
  and the same Origin. It adds the module token to every upstream request.

### The module contract

Every module server (`common/service.py` for anchor, guard and washer; MasterVolt keeps its own copy in
`mastervolt/api/contract.py`):

- plain HTTP on 127.0.0.1 only; only the gateway talks to it, and the gateway serves HTTPS;
- every request but `GET /health` must carry `X-Drifter-Token` = `DRIFTER_TOKEN`, which drifterd makes new at every start
  and gives to the gateway and every module in their environment; without it everything else is refused (fail closed);
- `GET /health` → `{"ok", "module", "version", "uptime_s"}`;
- JSON answers are never cached.

## 2. Repository

```
drifter.py, drifterd.py, supervisor.py   gateway, service, supervisor
modules.json                             per server: folder, command, port, health, pre-check; the back-up schedule
web/                                     the app: index.html, app.css, main.js, core/*.js, energy/anchor/guard/washer.js
modules/energy   MasterVolt YMS (package mastervolt/, its own tests and manual docs/MANUAL.md)
modules/anchor   anchor watch (package anchor/, orca_reader.py)
modules/guard    BoatGuard (package guard/)
modules/washer   VIOMI controller (package washer/)
common/          shared by gateway, drifterd and modules (stdlib, except service.py): net, web, logs, timefmt, pushover, proc, service
tools/           sync_envs, verify_live, backup, mock_upstreams, privacy_scan, install_service.ps1, session0_check, ...
tests/           gateway/supervisor/drifterd/common tests, run_all.py, ui/ (browser tests)
docs/            RUNBOOK.md, DEVELOPER.md, MANUAL.md (the user manual, also served by the app)
```

Each module has its own README and CHANGELOG; MasterVolt also `docs/MANUAL.md` (the energy system in depth) and
`docs/hardware-notes.md`.

## 3. Environments

Everything runs on the python.org **Python 3.12** (never the Microsoft Store Python: it hung at boot in the service's
session and cannot be started from it). `pyproject.toml` lists each module's packages as a dependency group (`energy`,
`anchor`, `guard`, `washer`, `dev`); `uv.lock` fixes every version.

```powershell
py -3.12 -m pip install --user uv
py -3.12 tools\sync_envs.py                 # .venv (gateway, stdlib only) and modules\<name>\.venv from the lock
py -3.12 tools\sync_envs.py --into .venv-next anchor   # on the boat PC: next to the running one; a restart swaps it in
```

To change a package: edit its group in `pyproject.toml`, `py -3.12 -m uv lock`, test, rebuild. Never `pip install` into an
environment by hand. Node (`package.json`: Playwright, TypeScript) is a development tool only: `npm ci`.

## 4. The app (web/)

- ES modules loaded as they are, no build step: `index.html` → `main.js` → `core/app.js` (modules, polling, routing,
  themes, overview, System page), `core/api.js`, `core/dialogs.js` (sheets; `confirm()` whose default is the safe answer),
  `core/format.js` (escaping, numbers, the 24-hour clock), `core/ui.js` (shared fragments); one page module per system.
- A page registers with `Drifter.register({id, title, short, icon, every, background, load, render, mount, tile, badge})`;
  commands go through `Drifter.api(module, path, body)` and `Drifter.run(...)`, confirmations through `Drifter.confirm(...)`.
- All colours are tokens in `app.css` per theme (light, dark, night, auto). Times are always 24-hour.
- `sw.js` caches only the shell; `api/` is never cached. Bump `CACHE` with every release.
- `npm run typecheck` (`tsc --checkJs`, JSDoc types, `web/types.d.ts` for browser facts) must stay at 0 errors.

## 5. Tests

```powershell
.venv\Scripts\python.exe tests\run_all.py        # every suite, each in its module's environment (`quick` skips slow ones)
py -3.12 -m ruff check .; py -3.12 -m ruff check modules\energy
npm run typecheck
npx playwright test                              # the app in Chromium and WebKit
```

- No test touches the boat. MasterVolt runs on a fake USB link and a fake `bleak`; its golden tests compare with the
  hardware-verified release 1.22.2 (never regenerate a golden file to make a test pass). The anchor watch's alarm logic is
  covered by `test_anchor_watch.py` (simulated Core data). Every FastAPI module has an `ApiContract` test of its HTTP API.
- **Browser tests** (`tests/ui`): their own mock (`tools/mock_upstreams.py --gateway --offset 1000`, port 9101). Every
  `api/` request is answered from fixtures recorded from the mock (`tests/ui/fixtures`, made-up data), commands are
  captured, the clock is fixed. `pages.spec.ts` compares the DOM of every page and view at 390, 820 and 1180 px with
  `tests/ui/__snapshots__` and checks for console errors and AM/PM times; `safety.spec.ts` checks the safe defaults.
  - An intended UI change: `npx playwright test --update-snapshots`, then read the snapshot diff.
  - A change to the mock: delete `tests/ui/fixtures`, `RECORD=1 npx playwright test --workers 1`, then update the snapshots.
  - A refactor that must not change the look: `SCREENS=1 npx playwright test --project chromium -g width
    --update-snapshots=missing` before, the same without `--update-snapshots` after (81 screenshots, kept locally).
- **Never test the UI against the live servers**: a click could arm the camera, switch the inverter or start the washer.
  `py tools/mock_upstreams.py --gateway` gives a mock app on http://127.0.0.1:8101/ for trying things by hand.

## 6. Privacy (the repository is public)

`tools/privacy_scan.py` refuses added lines that look like positions (5+ decimals), keys, tokens, MAC addresses, private keys
or e-mail addresses, or that contain an entry of the local deny list `C:\DrifterData\privacy_denylist.txt` (MMSI, serials,
anchorages; not in git). It runs before every commit (`git config core.hooksPath .githooks`) and in CI. Made-up data may
carry `privacy: ok`. Never bypass it; read the staged diff yourself too. Never commit `config.json`, `certs/`, logs or any
module's runtime files.

## 7. CI and releases

- GitHub Actions (`.github/workflows/ci.yml`, Windows) on every push: privacy scan, `uv lock --check`, environments, ruff,
  JavaScript syntax, type check, browser tests, `run_all.py quick`. A failure arrives by e-mail.
- The app/gateway: bump `VERSION` in `drifter.py`, `CACHE` in `web/sw.js`, the version line of `README.md`, add a
  `CHANGELOG.md` entry; tag `vX.Y.Z`. A module: its own version places and CHANGELOG; tag `<module>/vX.Y.Z`.
- Deploying to the boat PC: [RUNBOOK.md](RUNBOOK.md) section 5.
