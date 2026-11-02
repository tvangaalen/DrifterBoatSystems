# Drifter Boat Systems

One repository for the boat's systems: the Drifter app (iPhone/iPad PWA, `web/`), its stdlib gateway `drifter.py`, and
the four module servers in `modules/` — `energy` (MasterVolt YMS), `anchor` (Orca Core 2 anchor watch), `guard`
(BoatGuard) and `washer` (VIOMI W1). Overview: `README.md`. Migration plan and status: "Migration" below.

## Module rules

**Before touching a module, read its own `modules/<name>/CLAUDE.md`. Its hard rules (hardware safety, read-only on the
Orca Core, never guessing MasterBus fields, ECU safety, privacy) apply in full.** Only its sections about version
control, GitHub remotes, the Google Drive copy, the `.gitrepos` folder, the live folder `C:\Temp\mastervoltproject` and
deploying by copying files are historical: version control is this repository and every module runs from `C:\Drifter`
(see "Live" below). Their pre-restart checks (e.g. MasterVolt: `/api/bms` not busy, Float not latched) still apply.

## Live

- Everything runs from the clone `C:\Drifter`; runtime files in `C:\DrifterData\<module>` (gateway: `config.json`, `certs`, `logs` in `C:\Drifter`).
- **The Windows service `Drifter` (drifterd.py)** runs the gateway and all four modules as its own children, each in a kill-on-close job object, in session 0, as the user's account, whether anybody is logged on or not; output in `<data>\logs\<module>.console.log`, its own log in `C:\DrifterData\logs\drifterd.log`. It is installed (and removed with `-Remove`) by the user's `tools\install_service.ps1`: it needs the user's password and an elevated shell, so the user runs it, never Claude. Until it is installed, the scheduled task DrifterBoatSystems (`tools\run_module.py gateway`) is the fallback.
- **Deploying** = commit and push here, then `git pull --ff-only` in `C:\Drifter`, then restart only what changed through the gateway (System page, or `POST /api/supervisor/restart` with `X-Drifter-Request: 1`; the gateway itself: module `gateway`); a change to drifterd.py, supervisor.py or common/proc.py needs a service restart (`Restart-Service Drifter`, or Stop/Start; the user's account may do both). Claude's session cannot stop session-0 processes directly. New packages: `py -3.12 tools\sync_envs.py --into .venv-next`, then restart that module. Never edit files in `C:\Drifter` directly. A web-only change needs no restart (files are read per request).
- **After a deploy or restart**, verify with `py -3.12 toolserify_live.py [module ...]` (read-only GETs, about a second; it retries
  what can still come right, like the BMS units ~2 minutes after an energy restart, up to `--wait 240`): health, version,
  403 without the token, supervisor and gateway state, and each module's own essentials. Exit code = failed checks.
- A session without desktop has no sound and no windows; never add a feature that needs either.
- The old project folders are in `C:\DrifterArchive\legacy-2026-11-02` (the user's to delete). The Mastervolt Local CA lives in `C:\Drifter\modules\energy\certs`; `common/issue_cert.ps1` reads it there.

## Hard rules (app and gateway)

- **The module servers stay the authority.** Never move logic into the gateway or the page: Float protection, the anchor alarm (`AnchorWatch.tick`), arming and the washer schedule run on their own servers. The gateway only passes requests on; it never sends a command by itself, retries a command or polls hardware.
- **Engine ECU OFF** always needs the confirmation whose default is *Keep ECU ON* (`web/energy.js`); Escape/tap outside = keep on. Never weaken this or add a path that switches the ECU off without it.
- Confirm-first for every action that cuts power, stops charging, stops a watch or deletes data; the safe answer is the default button.
- **Route allowlist**: a new upstream route goes into `ROUTES` in `drifter.py` with the narrowest pattern, plus a test in `tests/test_gateway.py`. Do not add catch-all patterns. SOC calibration (`set-soc-*`) is exposed with its choice dialog (Cancel default); history export and the CA download are not exposed.
- Keep the gateway checks: `check_bind` (localhost/private only), `host_allowed` (DNS rebinding), and for POST: JSON, `X-Drifter-Request: 1`, same Origin. The washer's `X-Viomi-Request` header is added by the gateway only after those checks.
- **Never run UI tests against the live servers.** Use `py tools/mock_upstreams.py --gateway` (launch config `drifter-mock`, port 8101). A test click on the live servers can arm the camera, switch the inverter or start the washer. GETs to live servers for reading payload shapes are fine.
- The supervisor (inside drifterd) must never stop a running server on its own initiative; health checks are display only. It stops servers only for a restart or *Switch all systems off* the user asks for in the app, both after the gateway's `make_precheck` (for switch-off a latched Float does not count, the user's choice of 2026-11-02); *Switch all systems off* never sends a command to the boat (only processes stop) and its confirmation keeps *Leave on* as the default. Keep `"supervise"` off in every config except the live one; UI tests use the in-process mock supervisor in `tools/mock_upstreams.py`, never drifterd.
- Do not start, stop or restart the live module servers unless the user asks in that turn (MasterVolt owns the USB link and Bluetooth; restarts pause Float protection and the anchor watch). `start_all.ps1` (the desktop icon) only starts the service; it never restarts a running server; keep it that way.
- LAN only: never bind a public address, port-forward or tunnel. Remote access is UniFi Teleport (clients 192.168.2.x).
- HTTPS certificates come from the existing Mastervolt Local CA through `common/issue_cert.ps1` (only reads the CA folder, refuses without it). Never create a new CA or write into the CA folder.
- **Shared code goes in `common/`** (stdlib only, except `common/service.py`, the FastAPI module contract: token, `/health`, 127.0.0.1): network checks, HTTPS, logging, clock texts, Pushover posting, the certificate script. Change it with every user in mind (gateway, anchor, guard, washer) and run the whole `run_all.py`. Keep module behaviour in the module: alarm decisions, Pushover queues/priorities and retries stay where they are. MasterVolt does not import `common` (own package, golden tests, owner of the CA). A module imports it after `sys.path.insert(0, <repository root>)`; the live servers run from `C:\Drifter`, so `common/` is deployed with `git pull` like everything else, and a change there means restarting every module that uses it.
- Times are always 24-hour (`hm`/`hms`/`dayTime` in `web/core/format.js`); never locale time defaults.
- Live data is never cached by the service worker (`/api/` is skipped). Bump `CACHE` in `web/sw.js` with every release so home-screen apps update.

## Conventions

- Python: the python.org **Python 3.12** in the environments built from `uv.lock` (`tools/sync_envs.py`): `.venv` for the gateway and tools, `modules/<name>/.venv` per module. Never the Microsoft Store Python (hung at boot in session 0, cannot be started through Win32_Process Create), never `pip install` into an environment by hand: add the package to its group in `pyproject.toml`, `py -3.12 -m uv lock`, rebuild. Gateway: stdlib only, dense style like the modules; `ruff check .` must pass.
- Frontend: plain JS, no build step. `web/app.css` holds all colours as tokens per theme (light, dark, night, auto = device); modules never hard-code colours. New UI uses the existing components (`card`, `row`, `stats`, `hero`, `badge`, `btn`, `switch`, `seg`, `field`, `sheet`).
- The app is ES modules loaded as they are (`web/main.js` → `web/core/*.js` and the page modules); a page starts with `import Drifter from "./core/app.js"`. New shared code goes in `web/core/`, with JSDoc types where the check needs them; `npm run typecheck` must stay at 0 errors. Node (`package.json`) is a development tool only: never add a build step or a runtime npm dependency.
- **UI changes:** `npx playwright test` compares every page's DOM with `tests/ui/__snapshots__`. A change you intend updates them (`--update-snapshots`), and the diff shows what changed; re-record the fixtures (`RECORD=1`, delete `tests/ui/fixtures` first) only after changing the mock. For a refactor that must not change the look, take screenshots first (`SCREENS=1 npx playwright test --project chromium -g width --update-snapshots=missing`, kept locally) and compare after.
- A page module registers with `Drifter.register({id, title, short, icon, every, background, load, render, mount, tile, badge})`; commands go through `Drifter.api(module, path, body)` and `Drifter.run(...)`, confirmations through `Drifter.confirm(...)`.
- Check new layouts at 390 px (iPhone), 820 px portrait and 1180 px landscape (iPad), in light, dark and night.

## Verifying

```powershell
.venv\Scripts\python.exe tests\run_all.py   # every suite in its module's environment (MasterVolt ~3 min); `quick` skips its slow simulations
py -3.12 -m ruff check .; py -3.12 -m ruff check modules\energy   # lint (MasterVolt with its own configuration)
npm run typecheck                            # tsc --checkJs over web/ (JSDoc types; nothing is compiled)
npx playwright test                          # the app in Chromium and WebKit on recorded mock data (tests/ui)
```

GitHub CI (`.github/workflows/ci.yml`) runs the same on every push, plus the privacy scan. Do not wait for it after a push (about 5 minutes; the user's choice of 2026-11-02): run the full
local suite before committing, push, carry on (deploy included), and check the run's result once at the end of the turn
(`gh run list --limit 1`); a failed run also reaches the user by e-mail. Never skip CI or the privacy hook.

Then the UI against the mocks (`drifter-mock`). `run_all.py` removes `__pycache__` folders afterwards.

## Version control

- Git repository in this folder, branch `main`, remote `origin` = https://github.com/tvangaalen/DrifterBoatSystems (**public**). Git: `C:\Program Files\Git\cmd\git.exe` if `git` is not on the PATH.
- Repo-local identity `TvanG` with the GitHub no-reply address. Never put the user's real e-mail or other personal data in commits, files or tags.
- **Everything committed is public.** The pre-commit hook (`tools/privacy_scan.py`, `git config core.hooksPath .githooks`, local deny list `C:\DrifterData\privacy_denylist.txt`) and CI scan every commit; never bypass them (`--no-verify`), and still read the staged diff yourself. Before every commit and push, scan the staged diff for positions (anchorages, tracks), MMSIs, keys/tokens, hardware serials and personal data, and read the result. Never commit `config.json`, `certs/`, `logs/`, module runtime files (each module's `.gitignore` lists them), captures, recordings, databases or backups.
- Commit code and docs separately; imperative summary line, then what and why. Push only when the user asks or approved a release; never force-push.
- Tags: the gateway/app as `vX.Y.Z`; a module release as `<module>/vX.Y.Z` (e.g. `energy/v2.1.3`), on the commit that bumps that module's version.
- The old repositories (MasterVolt-YMS, OrcaCore2-AnchorWatch, BoatGuard, viomi-w1-controller) are archived: never push to them. Their old local folders are in `C:\DrifterArchive\legacy-2026-11-02`.

## Releasing

App/gateway: bump `VERSION` in `drifter.py`, `CACHE` in `web/sw.js`, the version line in `README.md`, add a `CHANGELOG.md` entry.
A module: follow that module's own release steps (version places, its CHANGELOG), tag `<module>/vX.Y.Z`.

## History and refactoring

- 2026-11-01/02, the migration (done): one repository with full history and tags; every server moved to `C:\Drifter` with its data in `C:\DrifterData`; the supervisor; every module's classic page replaced by the Drifter UI, modules on 127.0.0.1 only; shared code in `common/`. Details: CHANGELOG 0.1–0.13.
- Refactoring, plan of 2026-11-02 (user's choices: a real Windows service, FastAPI for every module, python.org Python, no frontend build step):
  1. **Done (0.14.x):** one Python 3.12 and `uv.lock`, ruff, privacy hook, CI; one scheduled task; the Store Python removed.
  2. **Done (0.15.0):** drifterd as the Windows service, the supervisor inside it, health checks, migration tools removed.
  3. **Done (washer 4.0 in 0.16.0, BoatGuard 2.0 in 0.17.0, anchor watch 2.0 in 0.18.0, MasterVolt 2.2 in 0.19.0):** module contract, per module (washer, guard, anchor, energy): a package on FastAPI, one config file with a schema, logging from `common`, `/health`, plain HTTP on 127.0.0.1 with a shared token from the gateway (then certificates only for the gateway). MasterBus/DALY code, Float and `AnchorWatch.tick` stay as they are (characterization and golden tests first).
  4. **Done (0.20.0):** ES modules (`web/core`), `tsc --checkJs` at 0 errors, Playwright tests on recorded mock data (DOM of every page and view, the safe defaults, Chromium and WebKit); MasterVolt's classic page removed (MasterVolt 3.0). Shared components so far: the core's fragments (`ui.js`); more can move there with the DOM snapshots as the check.
  5. Docs and operations: one Dutch user manual, English developer docs, one CLAUDE.md, a runbook, backups of `C:\DrifterData`.
