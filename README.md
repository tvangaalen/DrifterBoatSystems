# Drifter Boat Systems

Version 1.2.0 · one web app for the boat's systems, for iPhone and iPad (also works on a computer), and the code of
every system behind it in one repository:

| Module | System | Server it talks to | Code |
|---|---|---|---|
| **Energy** | Mastervolt (MasterBus), DALY BMS and balancers | MasterVolt YMS, `127.0.0.1:8000` | `modules/energy` |
| **Anchor watch** | Orca Core 2 anchor alarm, GPS, AIS, tide | Anchor watch, `127.0.0.1:8766` (network GPS stays on the LAN) | `modules/anchor` |
| **BoatGuard** | EZVIZ camera armed when the iPhone leaves the boat | BoatGuard, `127.0.0.1:8095` | `modules/guard` |
| **Washer** | VIOMI W1 washing machine and its schedule | VIOMI controller, `127.0.0.1:8080` | `modules/washer` |

The Drifter service (`drifterd.py`, a Windows service) runs the app's gateway and the four module servers on the boat PC,
whether anybody is logged on or not. Each module server keeps its own logic: Float protection, the anchor alarm and its
push alerts, arming the camera and the washer schedule keep working when the app is closed. The gateway (`drifter.py`)
serves the app over HTTPS and passes the app's requests on; it makes no decisions and talks to no hardware itself.

The modules were separate repositories until 2026-11-01 (MasterVolt-YMS, OrcaCore2-AnchorWatch, BoatGuard,
viomi-w1-controller, now archived on GitHub); their history and release tags are kept here (`energy/v2.1.2` etc.).

## Documentation

- **[User manual](docs/MANUAL.md)** — what every page shows and does (also in the app: System → *Manual*).
- **[Runbook](docs/RUNBOOK.md)** — running the boat PC: start, restart, update, check, back-up, recovery.
- **[Developer guide](docs/DEVELOPER.md)** — architecture, the module contract, environments, tests, releases.
- [CHANGELOG.md](CHANGELOG.md), and each module's own README and CHANGELOG under `modules/`; the energy system in depth:
  [modules/energy/docs/MANUAL.md](modules/energy/docs/MANUAL.md).

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

Only the app (port 8100) and the anchor watch's network GPS (port 10110) listen on the boat LAN; every module
server listens on 127.0.0.1 and has no page of its own.

## Safety

- Engine ECU OFF always asks first, with *Keep ECU ON* as the default (Escape and tapping outside also keep it on). No mode switches the ECU off (that rule lives on the MasterVolt server).
- Alternator OFF, discharge/charge MOSFET OFF, monitoring OFF, raising the anchor and shortening the history ask first, the safe choice being the default.
- A switch keeps showing the real state until the server has read the new state back.
- The gateway only passes on the routes listed in `ROUTES` in `drifter.py`; everything else is refused. It binds only to localhost or a private LAN address, accepts only requests addressed to an IP, localhost or this PC's name (DNS rebinding), and a command must carry the app's own header from the app's own origin, so a web page opened on the boat Wi-Fi cannot send commands through it.
- No login: anyone on the boat network (or on UniFi Teleport) can use it, like the existing pages. Never port-forward it or put it behind a public tunnel.
