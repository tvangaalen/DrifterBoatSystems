# Drifter Boat Systems

Version 0.17.0 · one web app for the boat's systems, for iPhone and iPad (also works on a computer), and the code of
every system behind it in one repository:

| Module | System | Server it talks to | Code |
|---|---|---|---|
| **Energy** | Mastervolt (MasterBus), DALY BMS and balancers | MasterVolt YMS, `127.0.0.1:8000` | `modules/energy` |
| **Anchor watch** | Orca Core 2 anchor alarm, GPS, AIS, tide | Anchor watch, `127.0.0.1:8766` (network GPS stays on the LAN) | `modules/anchor` |
| **BoatGuard** | EZVIZ camera armed when the iPhone leaves the boat | BoatGuard, `127.0.0.1:8095` (FastAPI, module contract) | `modules/guard` |
| **Washer** | VIOMI W1 washing machine and its schedule | VIOMI controller, `127.0.0.1:8080` (no page of its own) | `modules/washer` |

The modules were separate repositories until 2026-11-01 (MasterVolt-YMS, OrcaCore2-AnchorWatch, BoatGuard,
viomi-w1-controller, now archived on GitHub); their full history and release tags are kept here (`energy/v2.1.2` etc.).

```
drifter.py        gateway: serves web/ and passes the app's requests on to the module servers
web/              the app (HTML/CSS/JS, no build step)
modules/<name>/   each system's server, with its own README, CLAUDE.md, tests and changelog
common/           code shared by the gateway and the modules (network checks, HTTPS, logging, Pushover, certificates)
tests/run_all.py  every hardware-free test of the gateway and all modules
tools/            mock servers for testing the app without the boat
```

The four existing servers keep running unchanged and keep all their own logic: Float protection, the anchor alarm and
its push alerts, arming the camera and the washer schedule all keep working when Drifter is closed or stopped.
`drifter.py` is a small gateway: it serves the app and passes the app's requests on to those servers. It makes no
decisions and talks to no hardware itself.

## What the app does

- **Overview**: one tile per system with the key values; a red badge on a system that needs attention.
- **Anchor alarm on every page**: while the anchor watch reports an alarm, a red bar with *Silence 5 min* is shown at the top of every page.
- **Energy**: house battery (SOC, power, battery type and capacity, Float/Bulk state by cell voltage), sources, consumers, start and bow battery; modes (Motor, Anchor, Marina, Sail; the active one marked); inverter, charger, AC support, AC input limit, alternator, solar, charge-start/bow and Engine ECU; per battery the cells, temperatures, MOSFETs and SOC calibration (charge/discharge curve, 100 %, manual value); balancers (balancing, delta, cells); Bluetooth diagnostics; history charts (state of charge, sources, DC consumers, battery current, cell spread; 6 h to 31 days, crosshair) with the energy per period from the server's full-resolution totals; battery health report, manual and history database status; settings.
- **Anchor watch**: everything the old anchor page did. Map (street, satellite or plain, seamarks) with boat, anchor circle, max swing, rode, a fading track and AIS targets; drop (dropping now or already lying to it, with a scope calculator), move (tap or nudge 1 m), radius ±5 m, raise, silence; the alarm sounds and vibrates on the phone or tablet while sound is on (and when the watch cannot be reached with the anchor set), keeping the screen awake; tiles for distance, max swing, depth, wind, AIS, SOG, heading, sun, position (dmm/dms/dd); tide chart with chain advice and keel clearance; GPS order and removal; connections (Pushover, still-alive, internet AIS, noforeignland, network GPS) with their tests; all settings; Windy; new track.
- **BoatGuard**: status, monitoring on/off, phone/camera/router, camera test, arming delay, check interval, sound and priority per notification with a test, log.
- **Washer**: status and time left, start/pause/resume, power, program/temperature/rinses (confirmed by the washer before it says "applied"), schedule by start or finish time, events; diagnostics (startup checks, controller version and uptime, washer and PC address, model, firmware; recheck and JSON export).
- **Themes**: Auto (follows the device), Light, Dark and Night (dim red on black, keeps your night vision). Chosen with the sun/moon button or on the System page, remembered per device. In dark mode map tiles are dimmed, never colour-inverted; Night tints them red.
- **iPhone and iPad**: tab bar at the bottom on iPhone, a sidebar on iPad (an icon rail in portrait). Safe areas, large touch targets, no zooming on inputs. Add it to the home screen for a full-screen app.
- 24-hour times everywhere.

**Classic pages:** none on the network any more. Every module server listens on 127.0.0.1 (the anchor watch's network GPS stays on the LAN); MasterVolt's own page is still reachable on the boat PC itself (https://127.0.0.1:8000/) as a fallback. The gateway does not pass on routes the app does not use.

## Safety

- Engine ECU OFF always asks first, with *Keep ECU ON* as the default (Escape and tapping outside also keep it on). No mode switches the ECU off (that rule lives on the MasterVolt server).
- Alternator OFF, discharge/charge MOSFET OFF, monitoring OFF, raising the anchor and shortening the history ask first, the safe choice being the default.
- A switch keeps showing the real state until the server has read the new state back.
- The gateway only passes on the routes listed in `ROUTES` in `drifter.py`; everything else is refused. It binds only to localhost or a private LAN address, accepts only requests addressed to an IP, localhost or this PC's name (DNS rebinding), and a command must carry the app's own header from the app's own origin, so a web page opened on the boat Wi-Fi cannot send commands through it.
- No login: anyone on the boat network (or on UniFi Teleport) can use it, like the existing pages. Never port-forward it or put it behind a public tunnel.

## Setup (boat PC)

Requirements: Windows, Python 3.12+ (stdlib only, no packages), OpenSSL for the certificate.

```powershell
copy config.example.json config.json        # check the addresses: bind = this PC's LAN address
powershell -NoProfile -ExecutionPolicy Bypass -File setup_https.ps1   # certificate from the existing Mastervolt Local CA
py tests/run_all.py quick                   # all tests (fake servers and hardware; nothing on the boat is touched)
start_drifter.cmd                           # or: py drifter.py
```

Then open **https://192.168.1.166:8100/** on the iPhone or iPad → Share → *Add to Home Screen*. The devices already trust the Mastervolt Local CA (used by Energy, Anchor watch and BoatGuard), so no new profile is needed.

- Firewall: right-click `add_firewall_rule.cmd` → *Run as administrator* (TCP 8100, Private profile, local subnet and Teleport clients 192.168.2.x).
- `config.json`: `bind`, `port`, `allowed_hosts` (extra host names, e.g. `"drifter.lan"`), the certificate files, `ca_file` (to check the module servers' certificates) and per module the server `url` and the `classic` page link.
- **The Drifter service.** `drifterd.py` runs as the Windows service **Drifter** ("Drifter Boat Systems"): it starts at boot (delayed), whether anybody is logged on or not, runs the gateway and the four modules as its own processes (each in a kill-on-close job object), writes their output to `C:\DrifterData\<module>\logs\<module>.console.log` (the gateway: `C:\Drifter\logs\gateway.console.log`; its own: `C:\DrifterData\logs\drifterd.log`), and Windows restarts it after a crash. Install once from an *elevated* PowerShell in `C:\Drifter`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_service.ps1`. It asks for your Windows password (the service runs as your account), checks USB, Bluetooth and process starts in a session without desktop, asks Drifter whether a restart is safe now, gives your account "Log on as a service", creates the service and lets your account start and stop it, then switches over (Float and the anchor watch pause about a minute) and goes back to the old scheduled task by itself if the app does not come up. `-Status` shows what runs, `-Remove` goes back to the scheduled task. There is no desktop in that session: no console windows (System → Show log) and no sound on the PC (the anchor watch's PC beep is silent; the alarm on the iPhone/iPad and the push alerts are unchanged).
- **Desktop icon "Drifter Boat Systems"** (made by `tools\create_shortcut.ps1`, run from `C:\Drifter`; run it again if the icon does nothing) runs `start_all.ps1`: starts the service if it is stopped (after *Switch all systems off*), waits until every server answers (up to 4 min), shows the status and opens the app. It never restarts a running server.

## Supervisor

drifterd keeps the four modules running (`supervisor.py`; the gateway it keeps running itself):

- A server that runs is left alone. One that is not running when drifterd starts is started at once; one that stops later is started again after 30 s, given 5 min to come up; failed starts are retried after 1, 2, 5, 10 and then every 15 min.
- It never stops a server by itself. **System → Restart** stops and starts one on request, after a confirmation that says what pauses; MasterVolt is refused while a BMS control runs or Float is latched, the anchor watch while an alarm is active. A restart puts a freshly built Python environment in place (`tools\sync_envs.py --into .venv-next`).
- **Health:** every 30 s drifterd asks each module a cheap question (`modules.json` `health`); a server that listens but does not answer is shown as *not answering* on the System page. That is display only: nothing is stopped or restarted because of it.
- To keep a module stopped, create the file `C:\DrifterData\hold\<module>` (energy, anchor, guard, washer).
- The System page shows each server's state, uptime, health and the supervisor's events; **Show log** opens a module's log (and the service's own log) in its own window or tab (refreshes every 3 s while *Follow* is on).
- **System → Switch all systems off** asks first (default *Leave on*; the list says what stops, e.g. that the anchor alarm stops when the anchor is set), is refused while a BMS control runs or the anchor watch has an alarm (a latched Float is no reason), then stops the washer, BoatGuard, anchor watch and MasterVolt; 15 s later the gateway and the service end (the service stays stopped until the desktop icon or a boot starts it). The page then says *All systems have been shut down* and closes on OK (a home-screen app or a tab the browser will not close shows a "switched off" page instead). Switches, chargers and the camera stay as they are.
- The gateway reaches drifterd on 127.0.0.1:8099 with the token in `C:\DrifterData\drifterd.token` (`config.json`: `supervise`, `drifterd`, `drifterd_token`).

## Development

**Python environments.** Everything runs on the python.org Python 3.12, never on the Microsoft Store Python (that one hung at boot in session 0 and cannot be started through Win32_Process Create). `pyproject.toml` lists each module's packages as a dependency group (`energy`, `anchor`, `guard`, `washer`; the gateway is stdlib only) and `uv.lock` fixes every version. `py -3.12 tools\sync_envs.py` builds `.venv` (gateway) and `modules\<name>\.venv` from the lock, nothing else; on the boat PC: `--into .venv-next`, then `--swap <module>` (or Restart on the System page): the supervisor puts `.venv-next` in place between stopping and starting the module (only it can stop the servers in their session). To change a package: edit `pyproject.toml`, `py -3.12 -m uv lock`, run the tests, rebuild. Needs `py -3.12 -m pip install --user uv`.

**Checks.** `tests\run_all.py` (every suite, each in its module's environment), `ruff` (`pyproject.toml`; MasterVolt keeps its own, stricter configuration), `node --check` on `web\*.js`. GitHub runs all of them on every push (`.github/workflows/ci.yml`, Windows, environments from the lock), plus the privacy scan.

**Privacy scan.** The repository is public. `tools\privacy_scan.py` refuses added lines that look like positions (5+ decimals), keys/tokens, MAC addresses, private keys or e-mail addresses, or contain an entry of the local deny list `C:\DrifterData\privacy_denylist.txt` (MMSI, serials, the owner's e-mail, anchorages; not in git). It runs before every commit (`.githooks\pre-commit`, active after `git config core.hooksPath .githooks`) and in CI (patterns only). Made-up test data may carry `privacy: ok`.

`py tools/mock_upstreams.py --gateway` starts four fake servers with made-up data plus a gateway on http://127.0.0.1:8101/ (`tools/config.mock.json`). Use it for every UI test: it never contacts the boat. `py tools/mock_upstreams.py` alone starts only the fakes.

Shared code lives in `common/` (stdlib only): `net.py` (LAN-only bind check, DNS-rebinding and same-origin checks), `web.py` (HTTPS context, quiet threading server), `logs.py` (one log format with the 24-hour clock, rotating log file), `timefmt.py`, `pushover.py` (posting to Pushover; each module keeps its own key file, queue and retries) and `issue_cert.ps1` (a server certificate from the existing Mastervolt Local CA, by default from `modules\energy\certs`; it refuses to run without that CA and never creates one). The gateway, the anchor watch, BoatGuard and the washer controller use it; MasterVolt keeps its own code (it owns the CA and its launcher). A module finds `common` by putting the repository root on `sys.path`.

Files: `drifter.py` (gateway), `web/index.html` (shell), `web/app.css` (design system and themes), `web/app.js` (routing, polling, dialogs, overview, System page), `web/energy.js`, `anchor.js`, `guard.js`, `washer.js` (modules), `web/sw.js` (app-shell cache; live data is never cached).
