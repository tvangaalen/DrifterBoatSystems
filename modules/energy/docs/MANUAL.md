# Mastervolt Energy - Manual

**Version 2.1.2** - the complete guide to using, operating and maintaining the application. It explains what every screen
shows, how every number is obtained, what the application does on its own (Float protection, Bluetooth recovery, history),
which files it keeps, what to do when something goes wrong, and how the code is organised for whoever changes it next.

How to read it: chapters 1-2 are for everybody, 3-4 for the person using the app on the boat, 5-8 for the person who runs and
maintains it, 9-10 for the person who changes the code.

---

## 1. What the application does

Mastervolt Energy is a private web application for a boat's electrical system. It runs on a Windows PC that stays on board
and is used from a phone or a browser on the boat's own network. It does four things:

1. **Shows** what the system is doing right now: shore power, house charger, solar, alternator, the three batteries and every
   load, in volts, amps and watts, plus the state of charge of the house bank.
2. **Controls** the equipment: inverter, house charger, shore-power AC limit, `AC IN support`, the two Mass chargers, the Solar
   controller, the alternator regulator and the Yanmar engine ECU - singly, or together as the operating modes *Motor*,
   *Anchor*, *Marina* and *Sail*.
3. **Protects** the house batteries: when any single cell of the three lithium batteries gets too high, it switches the
   charging sources to Float by itself, and back to Bulk when every cell has come down. This runs on the PC, whether or not a
   phone is connected.
4. **Remembers**: every ten seconds the picture is stored, so you can look back hours or weeks, see totals per source and per
   consumer, review alarms, and generate a battery health report.

### The equipment it talks to

| Equipment | Connection | What the application does with it |
|---|---|---|
| CombiMaster (shore power, inverter, house charger) | MasterBus, USB Link | measures; switches inverter, charger, `AC IN support`; sets the AC limit; Float/Bulk events |
| Solar ChargeMaster | MasterBus | measures; On/Off; Float/Bulk events |
| Alpha Pro alternator regulator | MasterBus | measures; *Stop charge* On/Off; Float/Bulk events |
| Two Mass chargers (start battery, bow-thruster battery) | MasterBus | measures their input; On/Standby |
| Yanmar engine ECU interface | MasterBus | measures; ECU power On/Off (always with a safety confirmation) |
| Three MasterShunts (house, start, bow battery) | MasterBus | voltage, current, battery type and capacity; SOC of the start and bow batteries |
| Three DALY BMS units (`BATTERY 1`-`3`) | Bluetooth LE | cell voltages, temperatures, alarms, SOC, charge/discharge MOSFET state and control, Set SOC |
| Three DALY balancers (`DL-BAL1`-`3`) | Bluetooth LE | read-only: cell voltages, balance current, which cell is being balanced |

The MasterBus connection is the **Mastervolt USB Link**, a USB device on the PC. The Bluetooth connections use the PC's own
Bluetooth adapter.

### The software in one picture

```text
   phone / browser  ──HTTPS──►  FastAPI web server (this PC)  ──►  the page itself (HTML, CSS, JavaScript)
                                       │
        ┌──────────────────────────────┼───────────────────────────────┐
        ▼                              ▼                               ▼
   MasterBus service              Bluetooth services               History service
   poller + cache + controls      BMS workers (persistent)         recorder → SQLite database
   energy model, Float protection balancer worker                  chart cache, energy totals
        │                              │
        ▼                              ▼
   Mastervolt USB Link            Bluetooth radio (one gate:
   (HID, one at a time)           the "coordinator")
```

Everything is one Python process. The browser never talks to the equipment: it asks the server for the latest cached picture
(`GET /api/energy`, once a second) and sends commands, which the server carries out and verifies.

---

## 2. Safety model

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

## 3. Installation and first start

### 3.1 Requirements

* Windows 10/11 with the **Mastervolt USB Link** attached and a **Bluetooth adapter**.
* **Python 3.12 or newer** (the `py` launcher).
* OpenSSL (on `PATH`, or in the FireDaemon OpenSSL folder) for the certificate set-up.
* A phone or browser on the same private network.

```powershell
py -m pip install -r requirements.txt      # fastapi, uvicorn, hidapi, bleak
```

### 3.2 Folders

Keep two copies if you develop on the boat PC (the arrangement used on this boat):

* the **source** folder (here: in Google Drive) holds the code and Git history;
* the **live** folder (`C:\Temp\mastervoltproject`) is what the server runs from. It holds the real `user_settings.json`, the
  history database `data\history.sqlite3`, `backups\`, `certs\` and `logs\`.

Never run the server from a cloud-synchronised folder: the database is hundreds of megabytes and changes constantly. Section 8.4
describes how code gets from the source to the live folder.

### 3.3 HTTPS and the phone

An iPhone only installs a home-screen app from an HTTPS address, so the server uses a private certificate authority
(`Mastervolt Local CA`) that exists only on this PC. `start_mastervolt_server.cmd` creates it, issues a server certificate for
the PC's current addresses, and trusts it for the current Windows user. One-time phone set-up (profile install and trust) is in
`docs/local-https.md`. If the PC's IP address changes, restart the server: it issues a new certificate containing the new
address; the phone does not need to be set up again.

### 3.4 Starting and stopping

Double-click **`start_mastervolt_server.cmd`** (or run it from PowerShell). A console window opens, prepares the certificates,
and starts the server on `https://<private address>:8000`, printing the address. Leave the window open: it is the server.
Everything the application logs appears there. Stop it with **Ctrl+C**.

* After a stop or crash, simply start it again; nothing needs repairing. Float protection is not active while the server is
  stopped.
* A server that "does not respond" while its process is alive: run `netstat -ano | findstr :8000`. No `LISTENING` line means it
  is stuck shutting down (an open browser connection can hold it); end the process and start it again. The launcher already limits
  that wait (`--timeout-graceful-shutdown 5`).
* `run.ps1` starts a plain-HTTP development server on all interfaces. Use it only on a trusted network.

**Starting automatically when the PC boots.** `tools\install_autostart.ps1` registers a scheduled task that starts the server 30 seconds
after every boot, before anybody has logged on. Run it once from an **elevated** PowerShell (Run as administrator) in the folder the
server runs from. Windows blocks unsigned scripts, so start it with `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1` (this one command only; the system policy stays as it is); it asks for the Windows password of the account that runs the server and checks it before changing anything.
The account matters: Python and its packages are installed for one user, so only that user can run the server. The password goes
to Task Scheduler, which stores it protected; the script saves it nowhere. `-Status` shows the task and whether the server answers,
`-Remove` removes the task. Two limits: a boot-time task has no desktop, so there is no console window (look at `logs\`), and Windows
may refuse Bluetooth or USB access to a session without a desktop - after the first reboot check that the BMS page shows the
batteries connected. If it does not, remove the task and start the server at log-on instead (a task with an *At log on* trigger, or a
shortcut in the Startup folder).

Before the first start after changing control code, check the mappings:

```powershell
py -m tools.show_fields
```

`engine_ecu` must show `verified True`, address `3AE394`, field `43`.

### 3.5 Installing on the phone

Open the HTTPS address in Safari, then *Share → Add to Home Screen*. The app opens full-screen, shows the last values when
the server cannot be reached ("Offline - showing last values") and refreshes itself when a new version is installed on the PC.

---

## 4. Using the application

### 4.1 The basics

* **Header:** ☰ (reserved), the name, a **status dot** (green = the server answered; red = it did not), the word *System OK* or
  *Alarm n* (the CombiMaster's alarm code), the **clock** (24-hour) and a **☀/☾ button** that switches between the dark and the
  light theme (the light one is for sunlight). The choice is remembered on that phone.
* **Four pages**, in the bar at the bottom: **Control panel**, **BMS**, **History**, **Settings**. On a touch screen you can also
  **swipe** left and right between them (on History, the swipe first moves between its tabs).
* A red **Offline** bar means the server cannot be reached; the page keeps showing the last values and retries every second.

### 4.2 Control panel

Three sections, each with a total in its header, and a row of operating modes at the bottom.

**Sources** (*Total DC Input*): what feeds the 12 V system.

| Tile | Shows | Button |
|---|---|---|
| **Shore Power** | connected or not, frequency, voltage/amps/watts of the AC input | the **AC limit (A)** box (3-15 A, whole numbers) sets the CombiMaster's input limit; **SUP** switches `AC IN support` (blinks while it is actually supporting) |
| **Charger House** | the CombiMaster's charge state (Off/Bulk/Absorption/Float) and its DC output | ON/OFF: the CombiMaster charger |
| **Alternator** | state (Off/Bulk/Absorption/Float/Stopped), temperature, estimated output | ON/OFF: *Stop charge* (OFF asks for confirmation) |
| **Solar** | charge state, PV voltage, charge current and power | ON/OFF: the Solar controller (it may fall straight back to OFF at night - that is the controller, not a fault) |

**Storage**: the three batteries as arc gauges. **House Battery** is the lithium bank: its SOC is the *average of the three DALY
BMS units*, shown only while their readings are fresh (otherwise the gauge shows "-"). Start and Bow use their MasterShunt SOC.
Below each name: battery type and capacity. A negative current is a discharge; the header says *Charging*, *Discharging* or
*Idle*. A discharge above 100 A is highlighted.

**Loads** (*Total DC Load*; AC loads are listed but not added): **House AC loads**, **Inverter** (its DC draw only while it is
actually *Inverting* or *Supporting*), **Charger Start** and **Charger Bow** (Mass chargers; their *input* is the load; ON/OFF
= On/Standby), **Engine ECU** (input current is *estimated* from its output at 85% efficiency; ON/OFF with the safety
confirmation), **Alternator** (the regulator's own field current) and **Other DC loads**.

The columns are always *kind* (AC/DC), volts, amps, watts.

**Operating modes** - four buttons that carry out a whole set of switch actions, each verified:

| Mode | What it does |
|---|---|
| **Motor** | inverter OFF, Engine ECU ON, Solar ON, both Mass chargers ON, Alternator ON, house charger OFF |
| **Anchor** | inverter OFF, house charger OFF, Alternator OFF, Solar ON, both Mass chargers OFF |
| **Marina** | inverter ON, `AC IN support` ON, AC limit = the *Default AC limit* from Settings, Alternator OFF, Solar ON, both Mass chargers ON, house charger ON |
| **Sail** | inverter OFF, house charger OFF, Alternator OFF, Solar ON, both Mass chargers OFF, Engine ECU ON |

Every action is attempted; if some fail, the rest still run and the failures are reported together. The mode you applied last
stays **highlighted, for every phone** - the server remembers it - until you switch any device individually (then no mode
highlight remains). The highlight is not remembered over a server restart.

**Float notices.** When Float protection switches the sources to Float (or back to Bulk) a message appears and stays until you
press OK: it names the battery and cell voltage that triggered it.

### 4.3 BMS page

The page shows the three batteries side by side, with each battery's balancer merged into the same column
(balancer *n* belongs to battery *n*).

**Top buttons.** **Refresh BMS** reads all three batteries now. **Refresh BAL** reads all three balancers now (it is greyed
out while a refresh you started is still running). Under them, two status lines say when each was last updated. Tapping a
battery's name refreshes just that battery; tapping a balancer's status line refreshes just that balancer.

**Battery tiles** (one per battery):

* the **SOC gauge** - below it volts, amps and °C;
* the **balancer bars**: one bar per cell, drawn *around the balancer's own average voltage* (the horizontal line; its value,
  with the unit, is on the left, and on the right the **maximum difference** between the cells in mV). The lowest cell is blue,
  the highest red, the others green. A cell the balancer is balancing right now has a ⚡ above or below its bar, and the balance
  current is printed under the chart. A bar that **blinks red** is a cell whose *BMS* reading is at or above the Float trigger
  voltage. Without a fresh balancer reading, the bars fall back to the BMS cell values and the figures are dimmed.

**The table below the tiles**, one column per battery:

* **STATUS** - *Ah remaining* and *kWh remaining* (Ah × 13.2 V nominal), *Alarms*, *Cycles*, *SOC - Charging* and
  *SOC - Discharging* (the SOC read from the average cell voltage on a charging or a discharging reference curve - comparison
  figures), and the **Set SOC** buttons (below).
* **BALANCING** - the balancer's *Balance status* (Active/Inactive), *Balance current*, *Balance position* (which cells are being
  balanced) and its *Temperature*. The column header shows the balancer's own state and age.
* **CELLS** - *Average*, *Max difference* and one row per cell, all from the BMS (the balancer's readings are in the tile bars and the
  BALANCING section). The lowest and highest cells carry a blue and a red dot.
* **CONTROL** - **Charge** and **Discharge** MOSFET switches for each battery (green = ON), and **All charge / All discharge** for
  all three. Switching a MOSFET OFF is only offered while it is safe: *Charge OFF* while the battery's current is zero or positive
  (it is not being discharged through that path), *Discharge OFF* while the current is zero or negative. A disabled button's
  tooltip says why.

**Set SOC.** The BMS keeps its own state of charge by counting current; it drifts until it is re-anchored. *Set SOC* writes a new
value to the BMS: **Charge %** or **Discharge %** (the value from the voltage curve), **100%**, or a **Manual %** you type. It is
offered per battery and for all batteries. When Float protection freshly starts, every battery is set to 100% automatically once
(the triggering cell is at the Float voltage, so the battery is effectively full).

**Controls are guarded.** A Charge/Discharge or Set SOC command asks for confirmation (switching a battery off while it carries
current is serious), waits for the Bluetooth queue, writes, reads back, and shows a progress message. All three batteries must
be connected before an *All* command; if one step fails, the command stops and says which batteries were changed and which were
not.

### 4.4 History

Header: **Update** (loads everything newer from the server) and five tabs: **Sources**, **Storage**, **Loads**, **Alarms**,
**Reports**.

**Choosing the period.** The buttons **4 h, 12 h, 24 h, 3 d, 7 d, All** select the period ending now (the page opens on
**4 h**). **Custom** shows *From* and *To* sliders for any period; **Zoom** narrows the selected period further, without
changing it; *Reset zoom* undoes the zoom. The charts' time axes use whole hours or days. A short period (up to 48 h) is
fetched at full resolution as soon as it is selected, so nothing is missing from the curve.

**The tabs.**

| Tab | Charts | Totals (donut) |
|---|---|---|
| **Sources** | *Generated power* (stacked: Charger House, Alternator, Solar, with a smooth Total line; the left axis in watts is stepped in 250 W, the right axis in amps from 0 in steps of 10 A), *Source conditions* (shore voltage on the left axis together with the shore current on the right axis, 0-20 A in steps of 5 A; solar panel voltage; alternator temperature; axes from zero) and *Shore power intake* (the AC power taken in from shore power, with **Total kWh intake over the selected period** underneath, summed on the server from the full-resolution history) | energy delivered by each source in the period |
| **Storage** | *Remaining* energy (kWh), *Charge/discharge* (watts on the left axis, amps on the right), per-battery *Voltage* and *Cell voltages* with a selectable battery | energy in and out of each battery |
| **Loads** | *Consumption*, stacked per consumer with a total line (watts and amps) and the AC loads | energy per consumer |
| **Alarms** | a timeline of every BMS alarm and MOSFET change, with per-battery metrics | alarm episodes and samples per battery |
| **Reports** | the **battery health report**, and a **Manual** button that opens this manual in a separate window | - |

Tapping a name in a chart legend highlights that series. The donuts show the **exact totals from the full-resolution
history**, not the sampled chart data; the line under a donut says how much of the period was actually recorded (a gap while
the server or Bluetooth was down is not counted).

**Battery health report.** *Reports → Battery health report* asks for a number of days (1-365), runs the analysis on the server
in a separate low-priority process (it cannot slow down the measurements) and shows the result: a verdict per battery, cell
connection resistance, how the parallel batteries share the current, cell-voltage exposure, alarms, Bluetooth reliability, the
balancers and the start/bow batteries. Only one report runs at a time. Some cells show a dash on purpose: the resistance analysis only uses load steps while the bank is between 30% and 90% SOC (the flat part of the LiFePO4 curve), so after days at 99-100% SOC the recent rows are empty - that is missing qualifying data, not a failure.

### 4.5 Settings

Values are checked on the phone and again on the server; **Save settings** stores them in `user_settings.json`.

| Setting | Range | What it does |
|---|---|---|
| **Default AC limit** | 3-15 A | the shore-power limit that *Marina* mode applies |
| **Float protection** | ON/OFF | the master switch of the cell-voltage protection (section 5.3); OFF clears any Float latch |
| **Switch to Float when any cell reaches** | 3300-3650 mV (default 3500) | the trigger; the highest single cell of any battery |
| **Switch to Bulk once every cell is at or below** | 3200-3650 mV (default 3420) | the resume level; at least 30 mV below the trigger |
| **BMS refresh interval** | 5-300 s | how often each battery's status is read (all three in parallel) |
| **BMS connection retry** | 1-300 s | the first wait after a battery connection fails (it doubles per failure, up to 60 s) |
| **Balancer refresh interval** | 5-300 s | how often each balancer is read |
| **Balancer connection retry** | 5-300 s | the first wait after a balancer fails (doubles, up to 5 minutes) |
| **BMS pop-up duration** | 1-60 s | how long information pop-ups stay |
| **Save history period** | 1-365 days | measurements older than this are deleted automatically |

Below the settings, the **database status** shows the size, the number of records per source, the oldest and newest record, the
growth per day, the expected size at the chosen period, the free space in the file and on the disk, and the size of the chart
cache in memory. A **Manual** link opens this manual.

---

## 5. How it works

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

## 6. Files and folders

| Path | What it is | In Git? |
|---|---|---|
| `app.py` | entry point for the launchers (`uvicorn app:app`) | yes |
| `mastervolt/` | the application package | yes |
| `static/` | the page: `index.html`, `css/app.css`, `js/*.js`, `service-worker.js`, `manifest.webmanifest`, `icons/` | yes |
| `static/products/` | cached product photos for the tiles (`cache_product_images.py`) | only `sources.json` |
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
| `start_mastervolt_server.cmd`, `run.ps1`, `setup_local_https.ps1`, `install_*_certificate.cmd` | launchers and certificate set-up | yes |

Never commit or print `certs\*-key.pem`, `user_settings.json`, `backups\`, `data\*.sqlite3` or generated reports: the repository
is public.

---

## 7. API reference

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
| `GET /`, `/manifest.webmanifest`, `/service-worker.js`, `/local-ca.cer`, `/manual`, `/static/*` | the page and its files | |

---

## 8. Operating and maintaining

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
| Page does not update after an upgrade | the phone still has the old version | close and reopen the app; the service-worker cache name changes with every version |
| The server window closed by itself | the process crashed, or was started from a tool that ended | start it again with `start_mastervolt_server.cmd` and look at `logs\server.log` |

### 8.3 Bluetooth tuning

Everything is measured, so tune from the numbers. In `GET /api/bluetooth-events` look at `counters.<device>.timings`:
`connect` (balancers often need 8-14 s; a *failed* connect near 15 s is a timeout), `radio_wait`, `read`, and `signal`. Settings
that help: a longer *Balancer refresh interval* (fewer connects), keeping the PC close to the batteries, and not running the
DALY phone app while the PC is connected. Do not shorten the hard deadlines in `bluetooth/bms.py` and `bluetooth/balancers.py`
without measuring: they are the safety net against a hung Windows call.

### 8.4 Updating the live server

The live folder is edited only by deployment. Procedure used on this boat:

1. In the **source** folder: change, run `py -m tests.run_all`, commit.
2. **Compare** the live code with the commit you last deployed; if the live folder differs, stop and import the differences first.
3. **Back up** what you will overwrite to a sibling folder, `C:\Temp\mastervoltproject_pre_<version>_<timestamp>`.
4. Copy the changed files: the `mastervolt` package and `static` folder for a code change; a frontend-only change needs no restart.
   Never copy runtime files (`user_settings.json`, `data\`, `backups\`, `certs\`).
5. Restart the server **only when Python changed**, and only when no battery control is running and Float is not latched
   (`GET /api/bms` → `control_status.busy` is false; `GET /api/energy` → `high_soc_float_policy.float_latched` is false): a restart
   pauses Float protection for the minute it takes.
6. Verify: the version in `GET /api/version`, the balancers recovering, no errors in the console; push the commit to GitHub.

**Rollback:** stop the server, copy the files from the backup folder back over the live folder, start it.

Starting the server from an automation tool: create the process outside the tool's own process tree (for example through
`Invoke-CimMethod Win32_Process Create` running `cmd.exe /c "C:\Temp\mastervoltproject\start_mastervolt_server.cmd"`), otherwise
it can disappear when the tool's session ends. The launcher limits the graceful-shutdown wait to 5 s so an open browser
connection cannot keep a stopping server alive.

### 8.5 Data care

* The history database grows about 50 MB per day at the default intervals (about 1.6 GB for 31 days). The Settings page shows
  the current and the expected size. Lowering *Save history period* deletes the older rows within a minute; the file does not
  shrink by itself (the freed space is reused).
* Copy `data\history.sqlite3` only while the server is stopped, or use `GET /api/history/export`.
* `backups\` collects one small JSON per battery control. Delete old ones whenever you like.
* `user_settings.json` and `control_maps.json` are small and worth including in any backup of the live folder.

---

## 9. Developer guide

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
static/                index.html, css/app.css, js/*.js (classic scripts, loaded in order), service-worker.js
tools/                 diagnostic CLIs (py -m tools.<name>)
tests/                 test_*.py, fakes, golden/*.json, run_all.py
docs/                  MANUAL.md, hardware-notes.md, VERIFIED_FIELD_MAP.txt, local-https.md, device-schemas/, archive/
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

`test_release` checks that the version, the service-worker cache name and its file list, the README, the CHANGELOG and this
manual agree.

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

**Add a setting.** One row in `mastervolt/settings.py`; the API model and validation follow. Add the control to the Settings page
(`static/index.html`, `static/js/settings.js`) with the same limits, and a line in section 4.5.

**Add a measured field.** Verify it on the hardware first (`py -m tools.inspect_device snapshot --device <address>`). Then add it
to `POLLED_FIELDS`, read it in `masterbus/energy.py`, document it in `docs/VERIFIED_FIELD_MAP.txt`, extend the golden test's
`energy_cache_states` if it changes a decision.

**Add a control.** Add the verified mapping to `control_maps.json` or a method to `masterbus/controls.py` that writes and reads
back; give it a route in `api/controls.py`; add the scenario to `tests/golden_masterbus.py`.

**Add a page or tab.** Markup in `static/index.html`, code in a new `static/js/<name>.js`, listed in the script tags of
`index.html` and in `SHELL` of `static/service-worker.js` (the release test enforces this).

### 9.5 Style and tools

Python is formatted with **black** (140 columns) and checked with **ruff**; the front end with **prettier** (single quotes, no
arrow parentheses). The configuration is in `pyproject.toml` and `.prettierrc.json`. They are development tools only; the
server needs neither. Install them outside the project, for example:

```powershell
py -m pip install --target C:\Temp\mv_devtools black ruff
npm install --prefix C:\Temp\mv_devtools prettier
$env:PYTHONPATH = "C:\Temp\mv_devtools"; py -m black mastervolt tests tools app.py; py -m ruff check mastervolt tests tools app.py
node C:\Temp\mv_devtools\node_modules\prettier\bin\prettier.cjs --write static/js static/css static/service-worker.js
```

Edit source files with an editor or a UTF-8-safe script. Do not edit them with Windows PowerShell 5.1 `Get-Content`/`Set-Content`:
it reads UTF-8 as the ANSI code page and writes a byte-order mark, turning every "–" or "·" into mojibake.

### 9.6 Releasing

1. Change the version in `mastervolt/__init__.py`; update `CACHE` in `static/service-worker.js`, the first paragraph of
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
| `py -m tools.cache_product_images [--force]` | download the tile photos into `static/products/` |
| `tools\install_autostart.ps1` | register (or `-Remove`, `-Status`) the scheduled task that starts the server at boot; needs an elevated PowerShell |
| `tools\find_masterbus_usb.ps1`, `tools\ecu_capture_session.ps1` | find the USB Link; guided USBPcap capture of MasterAdjust |

---

## 10. Glossary

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
| **PWA** | the web app installed on the phone's home screen |
| **Golden file** | recorded results of the verified release, which the current code must reproduce exactly |
| **Supervisor** | the part that restarts a Bluetooth worker that crashed, died or hung |
