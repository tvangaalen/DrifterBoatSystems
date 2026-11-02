# MasterVolt YMS

**Mastervolt Energy v3.0.1** — a private server (its page is the Energy module of the Drifter app) that monitors and controls a boat's
Mastervolt electrical system and its DALY battery management, from a Windows PC on the boat's LAN.

> **MasterVolt is used through the Energy module of the Drifter app** ([DrifterBoatSystems](https://github.com/tvangaalen/DrifterBoatSystems), `modules/energy`): dashboard, controls, batteries, SOC calibration, Bluetooth diagnostics, history charts, reports and settings. The Drifter service runs this server (`python -m mastervolt`, 127.0.0.1:8000 only); since 3.0 it has no page of its own.

- **MasterBus** over the Mastervolt USB Link: CombiMaster (shore power, inverter, charger), Solar ChargeMaster,
  Alpha Pro alternator regulator, Mass chargers, MasterShunts and the Yanmar engine ECU interface.
- **DALY Bluetooth** for the three house-battery BMS units (`BATTERY 1`–`3`) and the three balancers (`DL-BAL1`–`3`).
- **FastAPI** backend (the `mastervolt` package), SQLite measurement history; the page is the Drifter app's (since 3.0).

**The complete guide is the [manual](docs/MANUAL.md)** (also served by the app at `/manual`): what every screen shows, how
every number is obtained, Float protection, the Bluetooth design, files, API, operations, troubleshooting and the developer
guide. Release history: [CHANGELOG.md](CHANGELOG.md). Protocol findings and field maps: [docs/hardware-notes.md](docs/hardware-notes.md).

## Pages

| Page | What it does |
|---|---|
| **Control panel** | Sources, Storage and Loads tiles with live V/A/W and an arc-gauge SOC; ON/OFF controls; Motor / Anchor / Sail / Marina modes (the last one applied is remembered server-side and highlighted for every browser); shore-power AC limit; `INV` and `SUP`; Engine ECU power with a safety confirmation |
| **BMS** | The three batteries side by side with their balancers: SOC gauge, V/A/°C and per-cell balancer bars in each tile; a table with status, balancing, the BMS cell voltages and Charge/Discharge controls; Set SOC (curve, 100% or a manual percentage); separate Refresh BMS and Refresh BAL |
| **History** | Sources, Storage, Loads and Alarms charts from a server-side cache, with 4 h … All, Custom and Zoom ranges and a donut with exact totals per tab; a Reports tab with the battery health report |
| **Settings** | Default AC limit, Float protection thresholds, refresh/retry intervals, history retention, database status, a link to the manual |

Swipe left/right moves between pages on touch devices. A light UI (for sunlight) and a dark UI are available from the header.

## Run

On the boat the Drifter service runs it (`python -m mastervolt`, plain HTTP on 127.0.0.1:8000 under the Drifter module
contract); see the Drifter runbook. The environment comes from the repository's `uv.lock` (`tools\sync_envs.py`). Never start
a second server by hand: it needs exclusive use of the MasterBus USB Link and the Bluetooth radio (close MasterAdjust and the
diagnostic tools first). Before the first start after changing control code, check the mappings with `py -m tools.show_fields`
(`engine_ecu` must show `verified True`, address `3AE394`, field `43`).

## Safety model

- Only hardware-verified MasterBus fields are used; nothing is guessed at run time.
- Every control writes, reads back and verifies. Engine ECU OFF (and Alternator OFF) need an explicit confirmation whose default
  is *keep it ON*; no operating mode ever switches the ECU off.
- DALY writes go through one Bluetooth priority queue, with a pre-change backup in `backups/`.
- **Float protection** runs on the server every 3 s and forces the charging sources to Float once any single BMS cell reaches the
  trigger (default 3500 mV), back to Bulk once every cell is at or below the resume level (default 3420 mV). It reads cell voltage
  only from the three DALY BMSes, only trusts fresh data, never starts on missing data and holds Float rather than resuming blind.
  When it starts, every battery's SOC is set to 100% once.
- The server listens only on a private RFC1918 address (or localhost). Nothing is published to the internet.

## Project layout

```text
mastervolt/             the application
  masterbus/              USB protocol, bus I/O, controls, energy model, Float protection, polling service
  bluetooth/              DALY protocol, radio coordinator, BMS and balancer workers, event log
  history/                SQLite store, chart cache, energy totals, recorder
  reports/                battery health report
  api/                    the HTTP routes, one module per area
  settings.py, soc.py, runtime.py, app.py, config.py, logs.py
tests/                  hardware-free tests, simulated USB/Bluetooth, golden files from the verified 1.22.2 release
tools/                  diagnostic command-line tools (py -m tools.<name>)
docs/                   MANUAL.md (+ manual.html), hardware notes, verified field map, HTTPS guide, device schemas
control_maps.json, mastershunt_config_maps.json     verified device/control mappings
certs/, setup_local_https.ps1, install_*_certificate.cmd     local HTTPS
```

Runtime data (not for version control): `data/history.sqlite3`, `backups/`, `logs/`, `reports/`, `user_settings.json`,
`certs/*-key.pem`. See `.gitignore`.

## Tests

```powershell
py -m tests.run_all          # about two and a half minutes; no hardware is touched
py -m tests.run_all quick    # without the slow simulations
```

The golden tests prove that controls, the energy model, Float protection, DALY decoding, the history and the HTTP API still
behave exactly like the hardware-verified 1.22.2 release; the simulation tests run the real Bluetooth workers and the whole
application against a simulated USB Link and Bluetooth stack.

## Development

Python is formatted with black and checked with ruff (`pyproject.toml`).
These are development tools only and are not needed to run the server. The release procedure, the rules that must not be broken
and how to add a setting, field, control or page are in the manual, chapter 9.

## License and disclaimer

Released under the [MIT License](LICENSE). This is an independent project, not affiliated with or endorsed by Mastervolt
or DALY; product names belong to their owners. It sends commands to real electrical equipment (chargers, inverter,
alternator regulator, engine ECU, battery MOSFETs) using reverse-engineered protocols. Use it at your own risk and verify
every control on your own installation.
