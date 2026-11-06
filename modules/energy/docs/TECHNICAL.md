# Mastervolt Energy - technical guide

How the energy server works, for whoever runs, maintains or changes it: the safety model, how every number is obtained,
files, the API, operations and the developer guide. The user manuals were removed on 2026-11-06 (new ones per tab will
follow); this is what remains of the former manual's technical chapters.

## Safety model

The application writes to real equipment: a charger, the inverter, the alternator regulator, the engine ECU and the battery
MOSFETs. These rules are built in and are the reason the code is cautious.

* **Only verified fields are used.** A MasterBus field number or DALY command is never guessed. Every field the application
  reads or writes was confirmed on this hardware, in a device snapshot or in a MasterAdjust capture
  (`docs/VERIFIED_FIELD_MAP.txt`, `docs/hardware-notes.md`).
* **Every write is read back.** After a switch is operated, the application reads the device until it confirms the new state
  (twice in a row), and reports a failure with the values it saw if it does not. A setting that is already in effect is not
  written again.
* **The Engine ECU is protected.** Switching the ECU OFF always asks for confirmation, and the default answer is *Keep ECU ON*.
  No operating mode ever switches it off (Motor and Sail switch it on; Anchor and Marina leave it alone).
* **Switching the alternator OFF asks for confirmation** too (*Keep Alternator ON* is the default).
* **Battery MOSFETs are verified.** Charge/Discharge commands are checked by reading the BMS back; the *other* MOSFET is
  checked and restored if the unit changed it as a side effect. A backup of the battery's last status is written to `backups/`
  before every battery control.
* **Float protection only trusts fresh data.** It acts on cell voltages from the three BMS units only (never the balancers),
  ignores a reading older than max(2 minutes, 4 refresh intervals), never starts Float on missing data, and never returns to
  Bulk on missing data (section 5.3).
* **Private network only.** The server listens only on a private (RFC1918) address or localhost, over HTTPS with a private
  certificate authority. Nothing is published to the internet and no cloud service is used.
* **One program owns the hardware.** The USB Link and the Bluetooth radio can only be used by one program at a time: close
  MasterAdjust and the diagnostic tools before starting the server, and stop the server before running a tool.

> The application is an independent project, not made or endorsed by Mastervolt or DALY. It uses reverse-engineered
> protocols. Use it at your own risk and verify every control on your own installation.

---

## How it works

### 5.1 Architecture

One Python process (Uvicorn serving a FastAPI application) runs these long-lived parts, each on its own thread(s):

| Part | Thread(s) | Job |
|---|---|---|
| MasterBus poller | `masterbus-cache` | reads ~60 fields from the USB Link in a loop (about every 0.35 s per cycle) into a value cache |
| Float protection | `high-soc-float-policy` | every 3 s applies the cell-voltage policy to the charging sources |
| BMS workers | `daly-battery-1`..`3` (+ monitors) | each keeps its battery's Bluetooth link open and reads it periodically |
| Balancer worker | `daly-balancers` (+ monitor) | reads the three balancers one at a time |
| History recorder | `measurement-history` | stores samples, prunes, keeps the chart cache current |
| Shunt discovery | `mastershunt-config` | finds the battery type/capacity fields by name; skipped at start while the saved result (`mastershunt_config_maps.json`) is under 30 days old |
| Web requests | Uvicorn's worker threads | answer the browser from the caches; carry out commands |

The code lives in the `mastervolt` package: `masterbus` (USB protocol, I/O, controls, energy model, Float protection),
`bluetooth` (DALY protocol, coordinator, BMS and balancer workers), `history`, `reports`, `api` (the routes), plus `settings`,
`soc`, `runtime` (creates and wires the services) and `app` (the FastAPI factory). Section 9 describes it for developers.

### 5.2 MasterBus

**The USB Link.** The Link is a HID device carrying CAN frames in 64-byte reports. One `BusIO` object owns it; every exchange
(clear pending frames, send a request, wait for the answer) happens under one lock, so the poller, a control action and Float
protection never interleave their frames.

**Polling and the cache.** The poller reads each field in turn. Values go into a cache with a timestamp; the dashboard is built
*only* from the cache, so a browser request never waits for the bus. A value older than 20 s counts as unknown and shows as "-".
The polled fields are fixed: they were verified on the hardware and are listed in `mastervolt/masterbus/service.py`
(`POLLED_FIELDS`) and `docs/VERIFIED_FIELD_MAP.txt`. Fields of the mapped on/off controls are polled too, so a button always shows
the real state.

**USB recovery.** If the Link is missing at start, or vanishes while running (unplugged, a USB reset), the service retries
every 5 s and resumes by itself; the dashboard shows dashes meanwhile. Time-outs from a device that simply does not answer (an
unpowered regulator) are not mistaken for a lost Link.

**The energy model** (`masterbus/energy.py`) turns cached fields into the dashboard:

* Shore, Charger House and Solar power are voltage × current from their verified fields (never negative).
* The **Inverter** counts as a DC load only while the CombiMaster reports *Inverting* or *Supporting*.
* The **Engine ECU** has no input-current field: input power = (output voltage × output current) / 0.85, input current = that
  power / input voltage.
* **Alternator current** has no trustworthy field either. It is derived from the house-bus balance (sign: House MasterShunt
  current is positive *into* the battery). While the Alpha Pro is *Off* or *Stopped* the model learns the total house load,
  smoothed with a 0.25 filter; while it *charges* (Bulk/Absorption/Float) it uses that learned baseline:

  ```text
  stopped:   TotalHouseLoad = ChargerHouse + Solar - HouseBattery            (filtered into the baseline)
  charging:  Alternator     = HouseBattery + Baseline - ChargerHouse - Solar
  OtherDC    = Total (or Baseline) - ChargerStart - ChargerBow - EngineECU - Inverter - AlternatorField
  ```

  Shaft rotation is shown for diagnostics only; the Alpha Pro's own charge state decides. See `docs/hardware-notes.md`.

**Controls and read-back** (`masterbus/controls.py`). Each control follows the same pattern: read the current value; if it
is already right, report "not changed"; otherwise write (a value, and for Btm1 switches the commit token to the adjacent field),
wait 0.35 s, then read back until the target is seen twice in a row (up to 4-5 s) - or raise an error that lists the values read.
The table of verified controls:

| Control | Device | Write | Verified by |
|---|---|---|---|
| Inverter | CombiMaster | field 19 + commit 20 | field 19 read-back |
| House charger | CombiMaster | field 21 + commit 22 | field 21 |
| AC limit | CombiMaster | field 23 (3-15 A) | field 23 |
| `AC IN support` | CombiMaster, Btm3 | Btm3 field 11 (0/1) | Btm3 read-back |
| Charger Start / Bow | Mass charger | field 64 (0 Standby, 1 On) | field 64 |
| Solar | SCM | field 12 + commit 13 | OFF must read 0; ON is permissive (no PV → may revert) |
| Alternator OFF / ON | Alpha Pro | field 39 *Stop charge* = 1 / 0 + commit 40 (no Bulk request) | field 5 = 5 (Stopped) / 1-3 (charging) |
| Engine ECU | Yanmar | field 43, 0.0 / 1.0, no commit | field 43 |
| Float / Bulk events | CombiMaster 42/43 and 38/39, Solar 18/19 and 14/15, Alpha Pro 37/38 and 33/34 | event + commit | the charger-state field = Float (3) / Bulk (1) |

**Operating modes** are lists of these actions (section 4.2). **Settings** (`user_settings.json`) are kept in one table
(`mastervolt/settings.py`) that defines each setting's default, limits and message, and generates both the server validation and
the API model. A saved file is read setting by setting: one invalid or unknown entry falls back to its default and never discards
the rest (important for the history retention period, whose default is only 7 days).

### 5.3 Float protection

Lithium cells must not stay at high voltage. Three batteries in parallel do not reach "full" together, so the pack average (or
the SOC) can look harmless while one cell of one battery is already in the danger zone. Float protection therefore looks at
**the highest single cell of any battery** and nothing else.

Every 3 seconds, on the server:

1. Take the freshest cell data of the three BMS units (a battery whose last reading is older than max(120 s, 4 × refresh
   interval) is ignored). If no battery is fresh, the highest cell is **unknown**.
2. Decide (`soc.float_decision`):
   * **Start:** protection is ON and the highest cell is at or above the *trigger* (default 3500 mV) → Float is *active*.
   * **Resume:** Float is latched and every cell is at or below the *resume level* (default 3420 mV) → return to Bulk.
   * **Hold:** Float is latched and the reading is *unknown* → stay in Float; never resume on old data.
   * An unknown reading **never starts** Float; between the two thresholds nothing changes.
3. While Float is active, for each of **Charger House, Solar, Alternator**: if it is charging (Bulk or Absorption) it is forced
   to Float and verified (charger state 3); an already-Float source is left alone; a source that is off, stopped or unavailable
   (night, engine stopped) is **never switched on** - it is forced to Float the moment it starts charging. A source whose
   attempt fails is retried after 20 s.
4. When Float *freshly* latches, every battery's SOC is set to 100% once, in a separate thread so a slow Bluetooth write cannot
   delay the loop.
5. On resume, sources in Float are put back to Bulk, verified (state 1).

The state is in `GET /api/energy` as `high_soc_float_policy` (`active`, `float_latched`, `trigger` = `cell_voltage` or `held`,
`max_cell_mv`, `sources`, event counters that drive the on-screen notices). Float protection is independent of the native
charge stage of the MasterBus chargers. It pauses while the server is stopped.

### 5.4 DALY Bluetooth

**One radio, one gate.** A Windows PC cannot hold six reliable Bluetooth LE connections at once, so every operation that needs
the radio first takes a *lease* from the **coordinator** (`bluetooth/coordinator.py`). Only one lease exists at a time; waiters
are served by priority, and equal priorities in order of arrival:

> user control > manual refresh / connect > automatic connect > automatic BMS read > balancers

A lease that is held longer than its limit (150 s for balancers, 90 s for BMS work, 180 s for controls) is taken back, so one
hung Windows call can never block the radio for good, and a late `release` with the old token is ignored.

**BMS workers** (`bluetooth/bms.py`). Each battery has a worker with its own thread and event loop, so one stuck Windows call
cannot freeze the others. The link stays **open**; the status is read every *BMS refresh interval*. A read sends nine DALY
status requests (0x90-0x98, 0.25 s apart), waits for the answers, asks again for any that are missing, and **publishes only a
complete status** (an incomplete one never reaches the history). Three incomplete reads in a row rebuild the link. A lost single
request is retried before the link is torn down. A battery that cannot be reached is retried after *retry × 2ⁿ* seconds (cap
60 s) and is searched for again after three failed attempts, without slowing the others. Workers are *supervised*: an exception
or a stray `CancelledError` restarts the worker, and a monitor thread replaces a worker whose thread died or whose loop has not
moved for 5 minutes.

**Balancers** (`bluetooth/balancers.py`). Balancers are read **one at a time**: connect, read the nine commands, disconnect,
pause 4 s (Windows releases a link asynchronously), next. They only run when all three BMS links are up and have been read -
or, in *degraded mode*, when one BMS has been away for two minutes. A scan for missing balancers ends as soon as all wanted
devices have been seen. Each balancer has its own schedule: *refresh interval* when healthy, exponential back-off when failing,
and a deferred read (2 s) when the radio is busy. A stall watchdog first forces a fresh scan (after 5 minutes without a
successful read), then rebuilds the worker (10 minutes) and flags it **wedged** until a read succeeds. The Refresh BAL button
queues a full cycle; tapping one balancer queues just that one, ahead of the rest.

**Every Windows call has a hard deadline** (`asyncio.wait_for`); a client that connected but failed later is always
disconnected; a disconnect that hangs is logged as a possible leaked handle.

**Diagnostics.** `logs\bluetooth.log` (rotating) and `GET /api/bluetooth-events` record every failure and every slow connect,
with per-device counters and timings (connect, notify, read, disconnect, radio wait/hold, scan: count, average, median, p95,
maxima) and the signal strength (RSSI, dBm) of every DALY device seen in a scan. Use these figures, not guesses, to choose
timeouts. Roughly: -50 to -70 dBm is a good link, below about -85 dBm is marginal. `GET /api/bluetooth-coordinator` shows who
holds the radio right now.

### 5.5 History

**Recording.** Every 10 s the dashboard picture is stored (`dashboard`); each *new* BMS or balancer measurement is stored once
(`bms`, `balancer`), keyed by its capture time. Once a minute rows older than the retention period are deleted and the chart
cache is brought up to date. The store is one SQLite table in WAL mode (`data\history.sqlite3`), with indexes on time and on
(source, id); everything the Settings page shows is answered from those indexes, never by scanning payloads.

**The chart cache.** The server keeps the normalised points in memory, append-only in time order, so a History page never waits
for SQLite. Selecting a period finds its start by *bisecting* the cache (a linear scan once cost 0.4-0.75 s per call), then
samples at most 2500 dashboard points and 1200 points per battery for drawing - **always keeping every alarm neighbourhood and
every MOSFET transition**. The browser only draws; it never sums.

**Totals.** The donuts come from `EnergyTotals`: the time integral of power between consecutive samples over the *full-resolution*
cache. Pairs further apart than 120 s (dashboard) or 180 s (BMS) are not integrated and show up as missing coverage. Finished
whole hours are remembered, so only the two edges of a period are computed.

**Export.** `GET /api/history/export` streams the entire history as JSON lines in batches, using a connection of its own, so a
large export neither exhausts memory nor blocks recording.

### 5.6 Battery health report

`mastervolt/reports/battery_health.py` reads the history database **read-only** (and the BMS backups) and prints a Markdown report;
the web app runs it as a separate, low-priority process (so its analysis can never slow the MasterBus/Bluetooth threads or Float
protection). It can also be run by hand:

```powershell
py -m mastervolt.reports.battery_health --project C:\Temp\mastervoltproject --days 7 --save
py -m mastervolt.reports.battery_health --project C:\Temp\mastervoltproject --split "2026-09-20 12:40"   # before/after a change
```

Thresholds are practical heuristics, not manufacturer limits (see the top of the module).

### 5.7 Logging

The console window and `logs\server.log` (rotating) carry the application's own messages; `logs\bluetooth.log` the Bluetooth
events; Uvicorn's request log goes to the console. Background loops never die from one failed pass, and they do not fail
silently: the first occurrence of each problem is logged with its traceback, repeats at most every five minutes.

---

## Files and folders

| Path | What it is | In Git? |
|---|---|---|
| `mastervolt/` | the application package | yes |
| `control_maps.json` | the verified on/off control mappings | yes |
| `mastershunt_config_maps.json` | battery type/capacity fields found by name (written at start-up) | yes |
| `user_settings.json` | your settings | **no** |
| `data\history.sqlite3` | the measurement history (+ `-wal`/`-shm` files) | **no** |
| `data\bms_mos_encoding.json` | learned per-battery Charge/Discharge payload meaning | **no** |
| `backups\` | a copy of a battery's status before every battery control | **no** |
| `logs\` | `server.log`, `bluetooth.log` | **no** |
| `reports\` | battery health reports saved with `--save` | **no** |
| `certs\` | the private CA, its key and the server certificate | **no** |
| `tests\` | the hardware-free test suite and the golden files | yes |
| `tools\` | diagnostic command-line tools | yes |
| `docs\` | this manual, hardware notes, the verified field map, device schemas, archive | yes |
| `setup_local_https.ps1`, `install_iphone_certificate.cmd`, `install_pc_certificate.cmd` | the Mastervolt Local CA and setting up a phone or the PC's browser to trust it | yes |

Never commit or print `certs\*-key.pem`, `user_settings.json`, `backups\`, `data\*.sqlite3` or generated reports: the repository
is public.

---

## API reference

Interactive documentation is at `/docs` while the server runs. All bodies are JSON. Errors have `{"detail": "..."}`; the
browser shows `detail` to the user.

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /api/energy` | the dashboard picture | polled once a second; `503` on failure |
| `GET`/`POST /api/settings` | read / save settings | `400` for a rejected value, `422` for a malformed body |
| `GET /api/version` | the application version | |
| `POST /api/control/inverter`, `/charger`, `/ac-support`, `/alternator` | `{"enabled": bool}` | `500` (inverter, charger) or `409` (others) with the verify details on failure |
| `POST /api/control/ac-limit` | `{"amps": 3-15}` | `400` for a bad value |
| `POST /api/control/mode` | `{"mode": "motor"|"anchor"|"marina"|"sail"}` | `400` unknown mode; `409` partly applied |
| `POST /api/control/device/{name}` | `{"enabled": bool}`; name = `charger_start`, `charger_bow`, `engine_ecu`, `solar` | |
| `GET /api/bms` | status of the three batteries, refresh and control progress | |
| `POST /api/bms/refresh`, `/api/bms/{1-3}/refresh` | read now | |
| `POST /api/bms/{1-3}/charge`, `/discharge` | `{"enabled": bool}` | `404` unknown battery; `503` with the reason on failure |
| `POST /api/bms/{1-3}/set-soc-{100\|charge\|discharge\|value}` | Set SOC (`value` takes `{"percent": 0-100}`) | |
| `POST /api/bms/set-all/{charge-on\|charge-off\|discharge-on\|discharge-off}` | all batteries | |
| `POST /api/bms/set-all-soc/{100\|charge\|discharge\|value}` | all batteries | |
| `GET /api/balancers` | the three balancers | |
| `POST /api/balancers/refresh`, `/api/balancers/{1-3}/refresh` | read now | |
| `GET /api/bluetooth-coordinator`, `/api/bluetooth-events?limit=` | Bluetooth diagnostics | |
| `GET /api/history`, `/status`, `/bms-series`, `/dashboard-series`, `/chart-data?hours=`, `/contributions?start=&end=`, `/export` | the history | `POST /api/history/chart-data/update` refreshes the cache first |
| `GET`/`POST /api/reports/battery-health` | status / start a report (`{"days": 1-365}`) | `409` while one is running |
| `GET /manual` | this manual (HTML) | the page itself is the Drifter app's Energy page |

---

## Operating and maintaining

### 8.1 Day to day

Nothing to do: leave the server window open. Open the app on the phone. If the status dot is red, the server is unreachable
(PC off, server stopped, different Wi-Fi). If *System OK* turns into *Alarm n*, the CombiMaster reports an alarm code.

### 8.2 What to check when something looks wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| Red dot, "Offline" | server not running, PC asleep, wrong network, new IP address | start the server; if the IP changed, restart it so the certificate follows |
| Many values show "-" | MasterBus not answering: Link unplugged, MasterAdjust open, bus power off | check the USB Link and close other MasterBus programs; the app reconnects by itself (server log: "USB Link lost; reopening it") |
| House SOC shows "-" | no BMS reading in the last 2 minutes (Bluetooth down) | BMS page: is the battery *connected*? `GET /api/bluetooth-events`; close the DALY phone app (a BMS accepts one connection) |
| A balancer says "N min old" | its connection keeps failing (weak signal, out of range) | look at the signal in `bluetooth.log`/`/api/bluetooth-events` (below -85 dBm is marginal); tap its status line to retry; see section 8.5 |
| Refresh BAL stays grey | a balancer refresh is pending | it ends when every balancer has been tried; if it never does, the worker restart (monitor) will clear it - check `worker_restarts` in `GET /api/balancers` |
| Charge/Discharge command refused | battery not connected/refreshed, or the Bluetooth queue was busy | wait for *connected*, try again; the message names the step that failed |
| Float message appeared | a cell reached the trigger | expected: it names the battery and cell; the sources return to Bulk by themselves |
| `charger_house Bulk verify failed` in the Float status | the charger did not confirm Bulk (it may be off, or in another stage) | check the CombiMaster; the protection retries on the next resume |
| History page shows old data | the server was stopped; or the page is cached | press **Update**; the server refreshes its cache every minute |
| Page does not update after an upgrade | the phone still has the old version of the Drifter app | close and reopen the app |
| Energy shows *Not reachable* | the server stopped or crashed | the Drifter service starts it again within a minute; look at `C:\DrifterData\energy\logs\` |

### 8.3 Bluetooth tuning

Everything is measured, so tune from the numbers. In `GET /api/bluetooth-events` look at `counters.<device>.timings`:
`connect` (balancers often need 8-14 s; a *failed* connect near 15 s is a timeout), `radio_wait`, `read`, and `signal`. Settings
that help: a longer *Balancer refresh interval* (fewer connects), keeping the PC close to the batteries, and not running the
DALY phone app while the PC is connected. Do not shorten the hard deadlines in `bluetooth/bms.py` and `bluetooth/balancers.py`
without measuring: they are the safety net against a hung Windows call.

### 8.4 Updating the live server

The server runs from the Drifter Boat Systems checkout `C:\Drifter`; deploying is `git pull` there and a restart from the
app's System page, which first checks that no battery control runs and Float is not latched (a restart pauses Float
protection for the minute it takes). The procedure, verification and rollback are in the Drifter runbook
(`docs/RUNBOOK.md` of the repository, section 5).

### 8.5 Data care

* The history database grows about 50 MB per day at the default intervals (about 1.6 GB for 31 days). The Settings page shows
  the current and the expected size. Lowering *Save history period* deletes the older rows within a minute; the file does not
  shrink by itself (the freed space is reused).
* Copy `data\history.sqlite3` only while the server is stopped, or use `GET /api/history/export`.
* `backups\` collects one small JSON per battery control. Delete old ones whenever you like.
* `user_settings.json` and `control_maps.json` are small and worth including in any backup of the live folder.

---

## Developer guide

### 9.1 Layout

```text
mastervolt/
  __init__.py          __version__ (the one place the version is defined)
  config.py            Paths: every file location, injectable for tests
  settings.py          the settings table, validation, SettingsStore
  soc.py               House SOC, cell-voltage statistics, float_decision (pure functions)
  logs.py              logging set-up, warn_once
  runtime.py           Services: creates and wires everything; start/stop
  app.py               create_app() - the FastAPI factory
  masterbus/           usb, protocol, registry, io (BusIO), discovery, shunt_config, labels,
                       controls, energy, float_policy, service (the assembly + poller)
  bluetooth/           daly_protocol, link (Wakeup, Supervisor, client helpers, scanner), coordinator,
                       events (log + counters), bms, balancers
  history/             store (SQLite), series, chart_cache, totals, recorder, service (facade)
  reports/             battery_health (analysis + CLI), service (runs it as a process)
  api/                 one router per area: system, energy, settings, controls, bms, balancers,
                       bluetooth, history, reports; deps (Services dependency, error mapping)
tools/                 diagnostic CLIs (py -m tools.<name>)
tests/                 test_*.py, fakes, golden/*.json, run_all.py
docs/                  TECHNICAL.md, hardware-notes.md, VERIFIED_FIELD_MAP.txt, local-https.md, device-schemas/, archive/
```

Dependencies point one way: `api` → `runtime` → services → protocol/IO modules. Nothing below `api` imports FastAPI; nothing in
`masterbus` imports `bluetooth` (the two meet only in `runtime.py`, where Float protection is given the BMS cell data and the
"set every battery to 100%" callback).

### 9.2 Tests

```powershell
py -m tests.run_all          # everything (about two and a half minutes)
py -m tests.run_all quick    # without the slow simulations
py -m tests.test_masterbus_golden   # any single module
```

No test touches hardware. The USB Link is `tests/masterbus_fakes.py:FakeBus` (with a fake clock, so 0.35 s settle times run
instantly); Bluetooth is the fake `bleak` of `tests/ble_fakes.py`; the database is a temporary file. Three kinds of test:

* **Golden tests** (`test_masterbus_golden`, `test_misc_golden`, `test_api_golden`) compare the current code with what the
  hardware-verified release 1.22.2 produced for the same inputs: every control scenario's frames and results (56), the energy
  model over 70 cache states, the Float loop, settings validation, DALY decoding, history charts/totals, and 65 HTTP requests.
  A difference means *behaviour changed*. Regenerating a golden file from an old checkout (`--generate <old tree>`) is for an
  intended change only - never to make a failing test pass.
* **Simulation tests** (`test_bms_workers`, `test_balancers`, `test_link`, `test_masterbus_service`, `test_app_integration`)
  run the real workers and the whole application, with timeouts, hung calls, lost requests, crashes and unplugged devices
  injected.
* **Unit tests** for pure logic (`test_soc`, `test_settings`, `test_history`, `test_ble_events`, `test_bluetooth_coordinator`,
  `test_battery_health`, `test_release`).

`test_release` checks that the version, the README, the CHANGELOG and this manual agree.

### 9.3 Rules that must not be broken

These are in `CLAUDE.md` as well; they are the lessons of earlier incidents.

* Never guess a MasterBus field or DALY command; never weaken the ECU confirmation; keep write-then-read-back.
* Everything Bluetooth goes through the coordinator, in the priority order above; every Windows call has a hard deadline; a
  half-open client is always disconnected.
* `except Exception` does **not** catch `asyncio.CancelledError`. Worker loops are run by a `Supervisor`; a new worker must be too.
* Float protection reads cell voltage only through `Services.house_soc_details` (the BMS units, fresh data only).
* The chart caches are append-only and ordered: filter them by bisecting, never by scanning.
* The browser only draws; totals are computed on the server from the full-resolution cache.
* Frontend scripts are classic scripts sharing one global scope. A control that scrolls or drags sideways must be an
  `input`/`select`/`textarea` or sit in an element with class `no-swipe`, or the page swipe will steal the gesture.
* Never commit keys, certificates, `user_settings.json`, backups, captures, the database or reports.

### 9.4 Common changes

**Add a setting.** One row in `mastervolt/settings.py`; the API model and validation follow. Add the control to the Settings view
of the Drifter app (`SETTINGS` in its `web/energy.js`) with the same limits, and a line in section 4.5.

**Add a measured field.** Verify it on the hardware first (`py -m tools.inspect_device snapshot --device <address>`). Then add it
to `POLLED_FIELDS`, read it in `masterbus/energy.py`, document it in `docs/VERIFIED_FIELD_MAP.txt`, extend the golden test's
`energy_cache_states` if it changes a decision.

**Add a control.** Add the verified mapping to `control_maps.json` or a method to `masterbus/controls.py` that writes and reads
back; give it a route in `api/controls.py`; add the scenario to `tests/golden_masterbus.py`.

**Add a page or view.** In the Drifter app (`web/energy.js` of Drifter Boat Systems), with its browser tests.

### 9.5 Style and tools

Python is formatted with **black** (140 columns) and checked with **ruff**. The configuration is in `pyproject.toml`. They are
development tools only; the server needs neither. Install them outside the project, for example:

```powershell
py -m pip install --target C:\Temp\mv_devtools black ruff
$env:PYTHONPATH = "C:\Temp\mv_devtools"; py -m black mastervolt tests tools; py -m ruff check mastervolt tests tools
```

Edit source files with an editor or a UTF-8-safe script. Do not edit them with Windows PowerShell 5.1 `Get-Content`/`Set-Content`:
it reads UTF-8 as the ANSI code page and writes a byte-order mark, turning every "–" or "·" into mojibake.

### 9.6 Releasing

1. Change the version in `mastervolt/__init__.py`; update the first paragraph of
   `README.md`, the version line of this manual and add `### x.y.z` to the top of `CHANGELOG.md`. `py -m tests.test_release` says
   what is missing.
2. `py -m tests.run_all`; format and lint.
3. Commit (message in a file: `git commit -F`), tag `vX.Y.Z`, push `main` and the tag.
4. Deploy as in section 8.4.

### 9.7 Diagnostic tools

All run from the project folder with the server **stopped**; the read-only ones say so.

| Tool | Purpose |
|---|---|
| `py -m tools.show_fields` | the fields and control mappings the application uses now (check `engine_ecu` before starting) |
| `py -m tools.inspect_device snapshot --device 3AE394` | every field of a device with type, writability and value (read-only); also `candidates`, `writable`, `controls` |
| `py -m tools.alpha_stop_charge_watch` | watch the Alpha Pro *Stop charge* fields while you change them in MasterView (read-only) |
| `py -m tools.capture_hid --seconds 30` | print the raw HID reports from the Link (read-only) |
| `py -m tools.reversible_write_test <device> --confirm-write` | **writes**: switches a charger, the ECU or Solar to the opposite state, verifies, restores |
| `tools\find_masterbus_usb.ps1`, `tools\ecu_capture_session.ps1` | find the USB Link; guided USBPcap capture of MasterAdjust |

---

## Glossary

| Term | Meaning |
|---|---|
| **MasterBus** | Mastervolt's device network; the USB Link connects it to the PC |
| **Btm1 / Btm3** | the two MasterBus message families used (most fields are Btm1; `AC IN support` is Btm3) |
| **Commit** | the fixed token written to the field next to a Btm1 switch to apply it |
| **Bulk / Absorption / Float** | the charging stages: full current, constant voltage, maintenance |
| **BMS** | battery management system - one DALY unit per battery (`BATTERY 1`-`3`) |
| **Balancer** | a DALY active balancer (`DL-BAL1`-`3`) moving charge between the cells of a battery |
| **MOSFET (MOS)** | the BMS's charge and discharge switches |
| **SOC** | state of charge; the BMS counts current and drifts, the voltage-derived SOC is a comparison figure |
| **Lease** | permission to use the Bluetooth radio, from the coordinator |
| **Degraded mode** | balancers allowed to run although one BMS has been away for two minutes |
| **Wedged** | the balancer worker was rebuilt three times without a successful read |
| **RSSI** | Bluetooth signal strength in dBm (closer to 0 is stronger) |
| **PWA** | a web app installed on the phone's home screen (the Drifter app) |
| **Golden file** | recorded results of the verified release, which the current code must reproduce exactly |
| **Supervisor** | the part that restarts a Bluetooth worker that crashed, died or hung |
