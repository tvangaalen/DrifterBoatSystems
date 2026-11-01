# Drifter Boat Systems

One repository for the boat's systems: the Drifter app (iPhone/iPad PWA, `web/`), its stdlib gateway `drifter.py`, and
the four module servers in `modules/` — `energy` (MasterVolt YMS), `anchor` (Orca Core 2 anchor watch), `guard`
(BoatGuard) and `washer` (VIOMI W1). Overview: `README.md`. Migration plan and status: "Migration" below.

## Module rules

**Before touching a module, read its own `modules/<name>/CLAUDE.md`. Its hard rules (hardware safety, read-only on the
Orca Core, never guessing MasterBus fields, ECU safety, privacy) apply in full.** Only its sections about version
control, GitHub remotes, the Google Drive copy and the `.gitrepos` folder are historical: version control is this
repository (below). Deploy instructions in a module CLAUDE.md stay valid until that module has moved to `C:\Drifter`.

## Hard rules (app and gateway)

- **The module servers stay the authority.** Never move logic into the gateway or the page: Float protection, the anchor alarm (`AnchorWatch.tick`), arming and the washer schedule run on their own servers. The gateway only passes requests on; it never sends a command by itself, retries a command or polls hardware.
- **Engine ECU OFF** always needs the confirmation whose default is *Keep ECU ON* (`web/energy.js`); Escape/tap outside = keep on. Never weaken this or add a path that switches the ECU off without it.
- Confirm-first for every action that cuts power, stops charging, stops a watch or deletes data; the safe answer is the default button.
- **Route allowlist**: a new upstream route goes into `ROUTES` in `drifter.py` with the narrowest pattern, plus a test in `tests/test_gateway.py`. Do not add catch-all patterns. SOC calibration (`set-soc-*`), history export and the CA download are not exposed yet (add them only with the matching UI and confirmation).
- Keep the gateway checks: `check_bind` (localhost/private only), `host_allowed` (DNS rebinding), and for POST: JSON, `X-Drifter-Request: 1`, same Origin. The washer's `X-Viomi-Request` header is added by the gateway only after those checks.
- **Never run UI tests against the live servers.** Use `py tools/mock_upstreams.py --gateway` (launch config `drifter-mock`, port 8101). A test click on the live servers can arm the camera, switch the inverter or start the washer. GETs to live servers for reading payload shapes are fine.
- Do not start, stop or restart the live module servers unless the user asks in that turn (MasterVolt owns the USB link and Bluetooth; restarts pause Float protection and the anchor watch). `start_all.ps1` never restarts a running server; keep it that way.
- LAN only: never bind a public address, port-forward or tunnel. Remote access is UniFi Teleport (clients 192.168.2.x).
- HTTPS certificates come from the existing Mastervolt Local CA (`setup_https.ps1` only reads the CA folder). Never create a new CA or write into the CA folder.
- Times are always 24-hour (`hm`/`hms`/`dayTime` in `web/app.js`); never locale time defaults.
- Live data is never cached by the service worker (`/api/` is skipped). Bump `CACHE` in `web/sw.js` with every release so home-screen apps update.

## Conventions

- Python 3.12+, Windows, `py` launcher. Gateway: stdlib only, dense style like the modules.
- Frontend: plain JS, no build step. `web/app.css` holds all colours as tokens per theme (light, dark, night, auto = device); modules never hard-code colours. New UI uses the existing components (`card`, `row`, `stats`, `hero`, `badge`, `btn`, `switch`, `seg`, `field`, `sheet`).
- A page module registers with `Drifter.register({id, title, short, icon, every, background, load, render, mount, tile, badge})`; commands go through `Drifter.api(module, path, body)` and `Drifter.run(...)`, confirmations through `Drifter.confirm(...)`.
- Check new layouts at 390 px (iPhone), 820 px portrait and 1180 px landscape (iPad), in light, dark and night.

## Verifying

```powershell
py tests/run_all.py          # gateway + every module's suite (MasterVolt ~2.5 min); `quick` skips MasterVolt's slow simulations
node --check web\app.js      # and the other web\*.js files
```

Then the UI against the mocks (`drifter-mock`). `run_all.py` removes `__pycache__` folders afterwards.

## Version control

- Git repository in this folder, branch `main`, remote `origin` = https://github.com/tvangaalen/DrifterBoatSystems (**public**). Git: `C:\Program Files\Git\cmd\git.exe` if `git` is not on the PATH.
- Repo-local identity `TvanG` with the GitHub no-reply address. Never put the user's real e-mail or other personal data in commits, files or tags.
- **Everything committed is public.** Before every commit and push, scan the staged diff for positions (anchorages, tracks), MMSIs, keys/tokens, hardware serials and personal data, and read the result. Never commit `config.json`, `certs/`, `logs/`, module runtime files (each module's `.gitignore` lists them), captures, recordings, databases or backups.
- Commit code and docs separately; imperative summary line, then what and why. Push only when the user asks or approved a release; never force-push.
- Tags: the gateway/app as `vX.Y.Z`; a module release as `<module>/vX.Y.Z` (e.g. `energy/v2.1.3`), on the commit that bumps that module's version.
- The old repositories (MasterVolt-YMS, OrcaCore2-AnchorWatch, BoatGuard, viomi-w1-controller) are archived: never push to them. Their local folders next to this one are where the live servers still run from (see Migration).

## Releasing

App/gateway: bump `VERSION` in `drifter.py`, `CACHE` in `web/sw.js`, the version line in `README.md`, add a `CHANGELOG.md` entry.
A module: follow that module's own release steps (version places, its CHANGELOG), tag `<module>/vX.Y.Z`.

## Migration (plan agreed 2026-11-01)

1. **Done:** one repository with full history and tags (phase 0–1a). Live servers unchanged.
2. **Next (1b):** module data paths configurable (`C:\DrifterData\<module>`), live code from a clone in `C:\Drifter`; each switch-over restarts that module, so only with the user's go-ahead. Until then the live servers run from `C:\Temp\mastervoltproject` (energy) and the old folders `..\OrcaCore2`, `..\BoatGuard`, `..\viomi-w1-controller`: a change made here reaches live only by deploying it there (each module CLAUDE.md describes how).
3. Supervisor in `drifter.py` replaces the scheduled tasks and `start_all.ps1`.
4. Per module (washer → guard → anchor → energy): the Drifter UI gets everything of the classic page, then the classic page is removed and the module binds to 127.0.0.1 only.
5. Shared code into `common/` (bind check, host/CSRF checks, certificates, Pushover, logging, time formats).
