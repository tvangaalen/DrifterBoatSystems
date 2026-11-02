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

## Live (since 2026-11-01)

- All five (energy, anchor, guard, washer, gateway) run from the clone `C:\Drifter`, runtime files in `C:\DrifterData\<module>` (gateway: `config.json`, `certs`, `logs` in `C:\Drifter`). `C:\DrifterData\locations.json` says `drifter` for each.
- **Deploying** = commit and push here, then `git pull --ff-only` in `C:\Drifter`, then restart only the module that changed (stop it, then `C:\Drifter\start_all.ps1 -Only <module> -NoWait`; guard and gateway: `Stop-ScheduledTask`/`Start-ScheduledTask`). Never edit files in `C:\Drifter` directly. A web-only gateway change needs no restart (files are read per request).
- `tools/run_module.py` puts itself in a kill-on-close job object and starts the server suspended, assigns it to the job explicitly, then resumes it (an inherited job is not enough: the real python behind the venv launcher escaped it), so stopping a scheduled task (or killing the runner) also stops the server under it. Without it BoatGuard's server outlived Stop-ScheduledTask and, in session 0, could not be stopped without admin rights (2026-11-01). Keep it.
- Started outside any tool session: energy and anchor as minimised consoles under WmiPrvSE (`start_all.ps1`), washer hidden through `tools\run_module.py`, guard and gateway by their scheduled tasks (`BoatGuard` runs whether logged on or not, `DrifterBoatSystems` at logon), both running `tools\run_module.py`.
- The old folders (`C:\Temp\mastervoltproject`, `..\OrcaCore2`, `..\BoatGuard`, `..\viomi-w1-controller`) are no longer used but kept for `tools\switch_module.ps1 <module> -Back`. Do not delete them without the user's go-ahead.
- The Mastervolt Local CA now also lives in `C:\Drifter\modules\energy\certs` (identical copy). Since 0.11.0 the gateway's, BoatGuard's and the anchor watch's certificate scripts read it there by default (`common/issue_cert.ps1`); MasterVolt's own `setup_local_https.ps1` uses it in place.

## Hard rules (app and gateway)

- **The module servers stay the authority.** Never move logic into the gateway or the page: Float protection, the anchor alarm (`AnchorWatch.tick`), arming and the washer schedule run on their own servers. The gateway only passes requests on; it never sends a command by itself, retries a command or polls hardware.
- **Engine ECU OFF** always needs the confirmation whose default is *Keep ECU ON* (`web/energy.js`); Escape/tap outside = keep on. Never weaken this or add a path that switches the ECU off without it.
- Confirm-first for every action that cuts power, stops charging, stops a watch or deletes data; the safe answer is the default button.
- **Route allowlist**: a new upstream route goes into `ROUTES` in `drifter.py` with the narrowest pattern, plus a test in `tests/test_gateway.py`. Do not add catch-all patterns. SOC calibration (`set-soc-*`) is exposed with its choice dialog (Cancel default); history export and the CA download are not exposed.
- Keep the gateway checks: `check_bind` (localhost/private only), `host_allowed` (DNS rebinding), and for POST: JSON, `X-Drifter-Request: 1`, same Origin. The washer's `X-Viomi-Request` header is added by the gateway only after those checks.
- **Never run UI tests against the live servers.** Use `py tools/mock_upstreams.py --gateway` (launch config `drifter-mock`, port 8101). A test click on the live servers can arm the camera, switch the inverter or start the washer. GETs to live servers for reading payload shapes are fine.
- The supervisor must never stop a running server on its own initiative, and never start one as a child of the gateway. Keep `"supervise"` off in every config except the live one; UI tests use the fake supervisor in `tools/mock_upstreams.py`.
- Do not start, stop or restart the live module servers unless the user asks in that turn (MasterVolt owns the USB link and Bluetooth; restarts pause Float protection and the anchor watch). `start_all.ps1` never restarts a running server; keep it that way.
- LAN only: never bind a public address, port-forward or tunnel. Remote access is UniFi Teleport (clients 192.168.2.x).
- HTTPS certificates come from the existing Mastervolt Local CA through `common/issue_cert.ps1` (only reads the CA folder, refuses without it). Never create a new CA or write into the CA folder.
- **Shared code goes in `common/`** (stdlib only): network checks, HTTPS, logging, clock texts, Pushover posting, the certificate script. Change it with every user in mind (gateway, anchor, guard, washer) and run the whole `run_all.py`. Keep module behaviour in the module: alarm decisions, Pushover queues/priorities and retries stay where they are. MasterVolt does not import `common` (own package, golden tests, owner of the CA). A module imports it after `sys.path.insert(0, <repository root>)`; the live servers run from `C:\Drifter`, so `common/` is deployed with `git pull` like everything else, and a change there means restarting every module that uses it.
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
2. **Done (1b), all modules moved on 2026-11-01:** every module keeps its runtime files in `DRIFTER_DATA\<module>` when `DRIFTER_DATA` is set (unset = next to the code, as before; the anchor watch gets them as command-line options). `modules.json` describes each module (port, old folder, new folder, command, runtime files); `C:\DrifterData\locations.json` (not in git) records per module whether it runs from its old folder (`legacy`, the default) or from Drifter. `tools/prepare_live.ps1` clones `C:\Drifter` and builds the venvs; `tools/switch_module.ps1 <module> [-Back]` (run from `C:\Drifter`) moves one module: pre-checks, copies the runtime files (never deletes them in the old folder), stops the old server, starts the new one. **A switch restarts that module: only with the user's go-ahead, one module at a time.** `start_all.ps1` and `tools/run_module.py` start each module from its recorded location, through Win32_Process Create (outside any tool session's process tree; MasterVolt and the anchor watch in a minimised console). Never set `DRIFTER_DATA` machine- or user-wide: a legacy server restarted with it would look for its files in `C:\DrifterData`.
   Until a module is switched, it runs from its old folder (`C:\Temp\mastervoltproject`, `..\OrcaCore2`, `..\BoatGuard`, `..\viomi-w1-controller`) and a change made here reaches live only by deploying it there (each module CLAUDE.md describes how). After the switch, deploying = `git pull` in `C:\Drifter` plus restarting that module.
   **MasterVolt's certificate script creates a new CA when `certs\ca-*.pem` are missing**, which would force every iPhone/iPad to trust a new CA: the switch copies `certs` and refuses to start energy without the CA.
3. **Done (2026-11-01): supervisor** (`supervisor.py`, on with `"supervise": true` in the live `config.json`, off by default so the mock and test gateways never start real servers). It adopts running servers, starts a stopped one after GRACE_S through `start_all.ps1 -Only` (never as its own child: the gateway's task would take children down with it), backs off, respects `<data>\hold\<module>`, and stops a server only for a restart the user asks for in the app (System page), after `make_precheck`. `start_all.ps1` writes `<data>\starting\<module>` and skips a module that is already starting (two MasterVolts would fight over the USB link). `tools/stop_module.ps1` stops one module (task, listener and its launchers). The BoatGuard and DrifterBoatSystems scheduled tasks stay (BoatGuard needs session 0; the gateway needs something to start it).
4. Per module (washer → guard → anchor → energy): the Drifter UI gets everything of the classic page, then the classic page is removed and the module binds to 127.0.0.1 only. **Washer done (0.5.0):** controller 3.8-v59 has only its API (`/api/diagnostics` replaces the diagnostics page) and listens on 127.0.0.1 (`VIOMI_BIND` for another private address). **BoatGuard done (0.6.0):** no page, API on 127.0.0.1 only (`web.host` adds one private address on purpose); the gateway uses https://127.0.0.1:8095. **Energy done (0.10.0):** everything of MasterVolt's page is in Drifter (0.8.0–0.9.x); started by Drifter, `start_mastervolt_server.cmd` binds 127.0.0.1 (`DRIFTER_DATA` set). MasterVolt's own frontend files stay (its `test_release` checks them; the page is a fallback on the boat PC only). **Anchor watch done (0.7.0):** 1.17.0 has no page; API and tiles on `--web-bind` 127.0.0.1, network GPS (NMEA) stays on `--bind` (the LAN address, phones send there), push alerts link to `--app-url` (Drifter); Leaflet lives in `web/vendor/leaflet`. The page sounds the alarm on the device (WebAudio, vibration, wake lock) while the server says it sounds or the watch is unreachable with the anchor set: that is display, the alarm decision stays in `AnchorWatch.tick`.
5. **Done (0.11.0, 2026-11-02): shared code in `common/`** (`net`, `web`, `logs`, `timefmt`, `pushover`, `issue_cert.ps1`), used by the gateway, anchor watch 1.17.1, BoatGuard and washer 3.8-v60; MasterVolt keeps its own.
