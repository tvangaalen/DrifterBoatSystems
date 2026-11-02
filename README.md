# Drifter Boat Systems

Version 0.14.1 · one web app for the boat's systems, for iPhone and iPad (also works on a computer), and the code of
every system behind it in one repository:

| Module | System | Server it talks to | Code |
|---|---|---|---|
| **Energy** | Mastervolt (MasterBus), DALY BMS and balancers | MasterVolt YMS, `127.0.0.1:8000` | `modules/energy` |
| **Anchor watch** | Orca Core 2 anchor alarm, GPS, AIS, tide | Anchor watch, `127.0.0.1:8766` (network GPS stays on the LAN) | `modules/anchor` |
| **BoatGuard** | EZVIZ camera armed when the iPhone leaves the boat | BoatGuard, `127.0.0.1:8095` (no page of its own) | `modules/guard` |
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
- **Desktop icon "Drifter Boat Systems"** (made by `tools\create_shortcut.ps1`, run from `C:\Drifter`; run it again if the icon does nothing) runs `start_all.ps1`: starts the scheduled tasks (Drifter, BoatGuard) if they are not running and leaves MasterVolt, the anchor watch and the washer controller to Drifter's supervisor, which starts them at once in its own session (a module started from the desktop would end at log-off). It never restarts a server that runs, waits up to 3 min, shows the status and opens the app. With the supervisor off it starts every module itself, as before.
- **Starting without anybody logged on:** run `powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1` once from an *elevated* PowerShell in `C:\Drifter`. It asks for your Windows password (Task Scheduler needs it for a task that runs while nobody is logged on), first checks in that session that the MasterBus USB Link, Bluetooth and starting processes work (read-only; nothing is changed if not), then makes the task **DrifterBoatSystems** start `pyw tools\run_module.py gateway` 2 min after boot, whether anybody is logged on or not, restarted within a minute if it stops. The supervisor then starts the other modules in that session; BoatGuard has its own boot task. `-Status` shows what runs in which session, `-Remove` goes back to starting at log-on, `-Now` moves the gateway at once. That session has no desktop: no console windows and no sound on the PC (the anchor watch's PC beep is silent; the alarm on the iPhone/iPad and the push alerts are unchanged). Until it is installed, the task starts the gateway at log-on.

## Supervisor

With `"supervise": true` in `config.json` (the live setting) the gateway keeps the four servers running:

- A server that runs is left alone. One that is not running when the supervisor starts is started at once; one that stops later after 30 s (the same way as the desktop icon does, outside the gateway's process tree, so restarting the gateway never takes a server down), then given 2.5 min to come up; failed starts are retried after 1, 2, 5, 10 and then every 15 min.
- It never stops a server by itself. **System → Restart** stops and starts one on request, after a confirmation that says what pauses; MasterVolt is refused while a BMS control runs or Float is latched, the anchor watch while an alarm is active.
- A server that stops is started again after 30 s (use *Switch all systems off* to stop everything). To keep a module stopped, create the file `C:\DrifterData\hold\<module>` (energy, anchor, guard, washer); `switch_module.ps1` does that itself while moving a module.
- The System page shows each server's state, uptime and the supervisor's events.
- **Logs instead of console windows:** every module runs without a window through `tools\run_module.py`, its output in `C:\DrifterData\<module>\logs\<module>.console.log` (the gateway: `C:\Drifter\logs\gateway.console.log`; the previous 5 MB move to `.log.1` at a start). System → **Show log** opens a module's log in its own window or tab (refreshes every 3 s while *Follow* is on). Started by Drifter, the MasterVolt and anchor watch start scripts skip their final `pause`.
- **System → Switch all systems off** asks first (default *Leave on*; the list says what stops, e.g. that the anchor alarm stops when the anchor is set), is refused while a BMS control runs or the anchor watch has an alarm (a latched Float is no reason), then stops the washer, BoatGuard, anchor watch and MasterVolt and finally the gateway itself (exit code 0, so its task does not start it again). The page then says *All systems have been shut down* and closes on OK (a home-screen app or a tab the browser will not close shows a "switched off" page instead). Switches, chargers and the camera stay as they are. Start everything again with the desktop icon.

## Moving the servers to `C:\Drifter` (one module at a time)

Since 2026-11-01 every server runs from `C:\Drifter`, with its runtime files in `C:\DrifterData`. How the move works (and how to undo it per module):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\prepare_live.ps1          # clone C:\Drifter, Python environments, C:\DrifterData (nothing is stopped)
cd C:\Drifter
powershell -NoProfile -ExecutionPolicy Bypass -File tools\switch_module.ps1 washer  # then guard, anchor, energy, gateway
powershell -NoProfile -ExecutionPolicy Bypass -File tools\switch_module.ps1 washer -Back   # undo
```

`switch_module.ps1` checks first (energy: no BMS control busy, Float not latched; anchor: no alarm), copies the module's runtime files (settings, keys, state, history, logs; listed in `modules.json`) to `C:\DrifterData\<module>` and its certificates into `C:\Drifter`, asks for confirmation, stops the old server, copies once more, and starts the module from `C:\Drifter`. Nothing is deleted from the old folder. Each switch restarts that server for about a minute. On 2026-11-02 the old folders were moved to `C:\DrifterArchive\legacy-2026-11-02` (`modules.json` points there), so `-Back` is best effort now: the old anchor watch and BoatGuard certificate scripts look for the CA in `C:\Temp\mastervoltproject\certs`. Which module runs where is kept in `C:\DrifterData\locations.json`; `start_all.ps1` (the desktop icon) follows it.

## Development

**Python environments.** Everything runs on the python.org Python 3.12, never on the Microsoft Store Python (that one hung at boot in session 0 and cannot be started through Win32_Process Create). `pyproject.toml` lists each module's packages as a dependency group (`energy`, `anchor`, `guard`, `washer`; the gateway is stdlib only) and `uv.lock` fixes every version. `py -3.12 tools\sync_envs.py` builds `.venv` (gateway) and `modules\<name>\.venv` from the lock, nothing else; on the boat PC: `--into .venv-next`, then `--swap <module>` (or Restart on the System page): the supervisor puts `.venv-next` in place between stopping and starting the module (only it can stop the servers in their session). To change a package: edit `pyproject.toml`, `py -3.12 -m uv lock`, run the tests, rebuild. Needs `py -3.12 -m pip install --user uv`.

**Checks.** `tests\run_all.py` (every suite, each in its module's environment), `ruff` (`pyproject.toml`; MasterVolt keeps its own, stricter configuration), `node --check` on `web\*.js`. GitHub runs all of them on every push (`.github/workflows/ci.yml`, Windows, environments from the lock), plus the privacy scan.

**Privacy scan.** The repository is public. `tools\privacy_scan.py` refuses added lines that look like positions (5+ decimals), keys/tokens, MAC addresses, private keys or e-mail addresses, or contain an entry of the local deny list `C:\DrifterData\privacy_denylist.txt` (MMSI, serials, the owner's e-mail, anchorages; not in git). It runs before every commit (`.githooks\pre-commit`, active after `git config core.hooksPath .githooks`) and in CI (patterns only). Made-up test data may carry `privacy: ok`.

`py tools/mock_upstreams.py --gateway` starts four fake servers with made-up data plus a gateway on http://127.0.0.1:8101/ (`tools/config.mock.json`). Use it for every UI test: it never contacts the boat. `py tools/mock_upstreams.py` alone starts only the fakes.

Shared code lives in `common/` (stdlib only): `net.py` (LAN-only bind check, DNS-rebinding and same-origin checks), `web.py` (HTTPS context, quiet threading server), `logs.py` (one log format with the 24-hour clock, rotating log file), `timefmt.py`, `pushover.py` (posting to Pushover; each module keeps its own key file, queue and retries) and `issue_cert.ps1` (a server certificate from the existing Mastervolt Local CA, by default from `modules\energy\certs`; it refuses to run without that CA and never creates one). The gateway, the anchor watch, BoatGuard and the washer controller use it; MasterVolt keeps its own code (it owns the CA and its launcher). A module finds `common` by putting the repository root on `sys.path`.

Files: `drifter.py` (gateway), `web/index.html` (shell), `web/app.css` (design system and themes), `web/app.js` (routing, polling, dialogs, overview, System page), `web/energy.js`, `anchor.js`, `guard.js`, `washer.js` (modules), `web/sw.js` (app-shell cache; live data is never cached).
