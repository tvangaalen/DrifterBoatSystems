# Changelog

All notable changes to MasterVolt YMS (the Mastervolt Energy web app). Newest first.

This file consolidates the former per-release `CHANGELOG_v*.md` and `README_*.md` notes; the originals are kept
in [`docs/archive/`](docs/archive/). Versions before 1.0.0 were documented only in the per-fix READMEs, so their
entries are summaries. There are no release notes for 1.3.12.

Unless an entry says otherwise, every release also bumps the application version, footer and service-worker cache.

---

## 2.1 — Shore power history

### 2.1.2
- The autostart installer is started with `powershell -NoProfile -ExecutionPolicy Bypass -File ...`: Windows refuses to run the unsigned script directly ("not digitally signed"). The system execution policy is not changed.

### 2.1.1
- **Start at boot:** `tools/install_autostart.ps1` registers a scheduled task that starts the server 30 s after every boot, before anybody has logged on (installed once from an elevated PowerShell; it asks for and validates the Windows password of the account that runs the server, which Task Scheduler needs for a task that runs while nobody is logged on; `-Status`, `-Remove`). A boot-time task has no desktop: no console window, and Windows may refuse Bluetooth/USB to such a session - the manual says how to check and what to do then.

### 2.1.0
- **History / Sources / Source conditions:** the *Shore Power AC voltage* chart now also shows the **shore current** on a right-hand axis (0-20 A in steps of 5 A); the voltage keeps the left axis.
- **History / Sources: new section *Shore power intake*** with a line of the power (W) taken in from shore power over the selected period, and underneath **Total kWh intake over the selected period** with the average power and how much of the period was recorded. The total is the time integral of the shore power over the full-resolution history, summed on the server (`GET /api/history/contributions` has a new `shore` entry: `wh`, `avg_w`); the browser only displays it. The chart points now carry `shore_current` and `shore_power` (read from the stored dashboard samples, so the whole history shows them after a restart).
- **History / Sources / Generated power:** the right-hand axis in amps now starts at 0 and steps by 10 A.
- **BMS table, CELLS section:** all balancer values are gone; Average, Max difference and every cell show the BMS values only. (The balancer readings remain in the tile bars and the BALANCING section.)

## 2.0 — Professional restructure

### 2.0.5
- **Battery health report: headings are headings again.** The report text came back from its process with Windows line endings (CRLF), and the page's small Markdown renderer did not match `# ...` lines that ended in a carriage return, so the section titles were shown as raw `## Verdict` text. The service now normalises the line endings and the renderer accepts both. (The tables and lists were never affected: all 9 tables and 52 rows of a live 7-day report are displayed, checked against the Markdown.)
- Documented why some report cells show a dash: the cell-resistance analysis only uses current steps while the bank is at 30-90% SOC, so after two days at 99-100% SOC the "last 48 h" and recent-day rows have no qualifying data (checked on the live history: 0 of ~4,900 samples per battery in that window). The report's output and logic are otherwise identical to 1.22.2 (same data, same text).

### 2.0.4
- **The manual is no dead end on the iPhone.** In the installed app the manual opens inside the app window, which has no browser back button. The manual now has a sticky **← Back to the app** button at the top: it closes a pop-up window (desktop), otherwise goes back in the history, otherwise to the app's start page.

### 2.0.3
- **History → Reports has a *Manual* button** that opens the user manual (`/manual`) in a separate window, so the History page keeps its place (a blocked pop-up falls back to a normal tab). The Settings page keeps its *Manual* link.

### 2.0.2
- **The dashboard no longer goes blank for the first minute after a start.** At every start the MasterShunt configuration discovery (a long read-only conversation: about two metadata requests per field, each waiting up to 0.3 s three times when a field does not exist) held the bus lock so persistently that the poller was starved and the values of the first minute expired to "-". The discovered field numbers only change with the device firmware, so the result in `mastershunt_config_maps.json` is now trusted for 30 days (discovery runs when the file is missing, empty or older, and `force` exists for tools); when it does run it lets the poller in between two attempts. Behaviour of the discovery itself is unchanged.

### 2.0.1
- **Balancer scans also read the scanner's collected results.** 2.0.0 ends a scan as soon as the wanted balancers have been seen (a detection callback); at the time-out it now also consults what the scanner has collected, exactly as the former fixed-length scan did, so a device whose advertisement was collected but not reported to the callback is never missed. Covered by a test with a scanner whose callback never fires.
- Prettier accepts either line-ending style (a Windows checkout writes CRLF).

### 2.0.0

A ground-up reorganisation of the code, **with the hardware behaviour of 1.22.2 reproduced exactly** (proved by golden tests, below),
a review and hardening of the Bluetooth connection code, a front end split into readable files, and a complete manual
([`docs/MANUAL.md`](docs/MANUAL.md), also served at `/manual`). MasterBus field maps, control sequences, Float protection,
DALY read/write sequences and timings are unchanged; the HTTP API answers exactly as before (65 recorded requests) apart from
the additions listed under *API*.

**Structure**
- The flat modules became the **`mastervolt` package**: `masterbus` (usb, protocol, registry, io, discovery, shunt_config, labels,
  controls, energy, float_policy, service), `bluetooth` (daly_protocol, link, coordinator, events, bms, balancers), `history` (store,
  series, chart_cache, totals, recorder, service), `reports`, `api` (one router per area), plus `settings`, `soc`, `runtime`,
  `config`, `logs`. The 1,474-line `MasterBusService` is now six cohesive classes behind a small facade; `app.py` (416 lines of
  routes) is a 10-line entry point and nine routers; the 370-line `energy()` is a documented `EnergyModel`. `uvicorn app:app` and the
  launchers are unchanged. Paths are injectable (`Paths`), so every service can run against a temporary folder.
- **Settings are one table** (`mastervolt/settings.py`): defaults, limits, UI messages, validation, the saved file and the API request
  model all derive from it (before, each setting was spelled out in three files).
- **Front end:** the 179 KB `index.html` (117 KB of JavaScript on very long lines) is now `index.html` (markup), `css/app.css` and 14
  `js/*.js` files, formatted with prettier; the AST of every file is identical to the old inline code. Side by side in one browser the
  old and the new page have **no computed-style difference over 13 page states in both themes** and identical canvas pixels. The footer
  version comes from `GET /api/version`, so the version is defined in one place (`mastervolt/__init__.py`).
- **Python style:** formatted with black (the old `a=1;b=2` one-liners are gone) and checked with ruff (`pyproject.toml`); no star imports,
  no bare `except:`, typed public signatures, docstrings that say *why*.
- **Removed:** dead code (`_resolve_engine_ecu_power_control`, the `device_maps.json` heuristics, `masterbus_presentation`, the field-56
  ECU experiments `ecu_control_test`/`ecu_commit_test`/`ecu_dropdown_probe`/`ecu_power_probe`, and the broken v0.x tools
  `masterbus_discover`, `masterbus_monitor`, `masterbus_cache_schemas`, `masterbus_control` that no longer imported). The diagnostic
  tools are now `tools/` with a shared helper: `inspect_device` (snapshot / candidates / writable / controls), `reversible_write_test`,
  `show_fields`, `alpha_stop_charge_watch`, `capture_hid`. `masterbus_capture.py` used to start a 30 s HID listen merely by being
  imported; it now has a `main`.

**Bluetooth**
- One `Supervisor` for all workers (BMS and balancers). Before, only the balancer had crash recovery: **a BMS worker that hit an
  exception ended for good**, leaving that battery disconnected until a server restart. Now any exception or stray `CancelledError`
  restarts the worker, and a monitor thread replaces a worker whose thread died or whose loop made no progress for 5 minutes.
- **Scanning ends when the wanted balancers have been seen** (a detection-callback scan) instead of always holding the radio for the
  full 12 s: less time in which BMS reads have to wait. The signal strength of every DALY device seen is still recorded.
- BMS links use **cached GATT services** on Windows (as the balancers already did): faster reconnects.
- **BMS back-off keeps growing.** A rescan used to reset the failure counter, so an unreachable battery cycled 1×, 2×, 4× the retry
  interval for ever (never reaching the 60 s cap) with a 10 s scan every third attempt. The counter now resets only on a successful
  connect; the rescan has its own counter.
- Automatic BMS reads **wait up to 6 s for the radio** instead of 2 s: about 40% of them used to time out and be retried (visible as
  `radio_wait` failures in `/api/bluetooth-events`) although the other read was nearly done. Manual and control priorities are untouched.
- Workers wake **immediately** on a refresh request or a lost link (thread-safe `Wakeup`) instead of polling every 250 ms; the BMS
  connection pause no longer blocks the worker's event loop.
- **One DALY protocol module** (`daly_protocol`): frame building, a shared `FrameAssembler` (the balancer used to drop 13 bytes after a
  bad frame, the BMS 1 byte; both now skip one byte), decoding, alarms and the voltage-derived SOC. The BMS MOS/SOC control flow is
  split into readable steps with identical behaviour (the firmware-encoding tests pass unchanged).
- The Bluetooth coordinator is created once by `Services` and handed to both services; `GET /api/bluetooth-coordinator` reads it from there.

**MasterBus and the server**
- **The USB Link is reopened automatically**: missing at start-up, or lost while running (5 consecutive bus errors, as opposed to a
  device that merely does not answer), it is retried every 5 s; previously this needed a server restart, and a Link missing at start-up
  disabled polling *and* Float protection's USB access for the whole run.
- **Settings load per setting.** One invalid value or an unknown key from another version used to make the whole `user_settings.json`
  be ignored - including `history_retention_days`, whose default (7 days) is far shorter than a configured 31 and would prune the
  history. Now only the offending setting falls back to its default (and a warning is logged).
- **Logging:** background loops no longer swallow errors silently. The first occurrence of each problem is logged with its traceback,
  repeats at most every five minutes (`logs/server.log`, rotating, plus the console). History pruning runs once a minute instead of
  every 10 s.
- The history **export streams** in batches on its own connection (it used to load every row, about a gigabyte, into memory).
- `GET /api/energy` no longer blocks the event loop while it computes (it runs in a worker thread).

**API** (everything else is byte-identical to 1.22.2)
- New: `GET /api/version`, `GET /manual`.
- An unknown battery number is a plain **404** (it was a 503 reading "404: Unknown battery"); `POST /api/bms/{n}/refresh` without a
  worker is a **503** with a reason (it was an unhandled 500); `POST /api/bms/{n}/set-soc-100` is now one of `set-soc-{mode}`
  (same URL, same answer).
- The Settings page accepts a BMS connection retry from 1 s, as the server always did (the page insisted on 5).

**Tests** (the safety net that makes the above credible; `py -m tests.run_all`, 20 modules, no hardware)
- **Golden tests against 1.22.2:** 56 control scenarios (every frame sent, every result and error text, including verify failures),
  the energy model over 70 cache states (the alternator/total-load filter included), the real Float loop over 12 steps, 31 settings
  cases, 108 DALY frames, House SOC, history charts/totals/series/export and 65 HTTP requests. Two deliberate mutations (a changed
  filter constant, a wrong commit field) are caught.
- A simulated USB Link (with a fake clock) and the simulated Bluetooth stack drive the real code, including crashes, `CancelledError`,
  hung loops, unplugged USB devices and a **whole-application test through the lifespan**.
- New release checks: the version, the service-worker cache name and file list, README, CHANGELOG and manual must agree; every
  front-end script must parse.

**Docs:** [`docs/MANUAL.md`](docs/MANUAL.md) (+ `manual.html`, built by `py -m tools.build_manual`), README and CLAUDE.md rewritten for
the new layout; the device schemas and the verified field map moved into `docs/`.

## 1.22 — Balance page removed

### 1.22.2
- **History - Source conditions:** the vertical axes of the Shore Power AC voltage, Solar panel voltage and Alternator temperature charts now start at **0** (0 V, 0 V, 0 °C) with round tick steps, instead of at a padded negative minimum (the dips to zero when a source drops out used to draw the axis down to -28 V / -17 V / -3 °C).
- **History opens on 4 h:** every History page now starts with the **4 h** range selected (it used to open on the full history). The other presets, Zoom and Custom work as before.

### 1.22.1
- **Balancer worker could die silently; Refresh BAL then stayed greyed out for ever.** Live on 2 Oct 2026 the balancer thread stopped at 14:46 (no log line, no error state) and the three balancers went stale ("N min old") while the BMS carried on. The Bluetooth libraries can end `connect()` with an `asyncio.CancelledError`, which is not an `Exception`: it slipped past the per-balancer and supervisor handlers, ended the thread, and with it the in-loop watchdog. A pending *Refresh BAL* generation could then never complete, and the button (disabled while a refresh is pending) stayed grey although nobody had clicked it just now. Fixed in three layers: a `CancelledError` during connect/read/scan is now an ordinary failed attempt (retried with the usual back-off); the supervisor also restarts the worker after one; and a new **monitor thread** replaces a worker thread that has died or whose event loop made no progress for 5 minutes (`worker_dead` / `worker_hung` in `bluetooth.log`, `worker_restarts` and `worker_alive` in `GET /api/balancers`). The balancer self-test now simulates all three failures (it fails on 1.22.0). Hardware-verified read sequences, timings and the Bluetooth priority order are unchanged.

### 1.22.0
- **The Balance page is removed** (bottom tab, page, its polling and the raw Bluetooth diagnostics view). Everything that mattered is on the BMS page since 1.20: the balancer state per column, the BALANCING section, the balancer readings under the BMS cells, the cell bars in the tiles, and **Refresh BAL**. The balancers themselves are unchanged: still read over Bluetooth, still logged to `bluetooth.log` and available as `GET /api/balancers`, `GET /api/bluetooth-events` and the refresh routes; the Balancer refresh interval and retry stay in Settings. Swiping now runs Control panel ↔ BMS ↔ History ↔ Settings.
- **BMS Battery tiles:** *Ah remaining* is gone from the tile. The balancer chart now prints the unit on the average voltage at the left of the line (`3.347 V`) and the **Max difference** at its right (`21 mV`, the balancer's own figure while it is fresh, otherwise max - min of the BMS cells).
- **BMS table:** STATUS now starts with **Ah remaining** and, directly under it, **kWh remaining** (Ah x 13.2 V nominal bank voltage, the same figure the History *Remaining* chart uses), above Alarms and Cycles.

## 1.21 — Battery tile layout, separate BMS/BAL refresh

### 1.21.1
- **Battery tile cell bars: one instrument compared with itself.** 1.21.0 drew the BMS cell voltages around the *balancer's* average, so when the two instruments differ (live: Balancer 2 reads 12-17 mV below BMS 2 on every cell) all bars could land on one side of the line. The bars are now the **balancer's own cell voltages** around the balancer's own average, so there is always at least one bar below and one above. Lowest blue, highest red, the rest green, as before. A bar still blinks bright red when the **BMS** reading of that same cell is at or above the Float cell trigger (Float protection stays on the BMS only). Without a fresh balancer reading the tile falls back to the BMS cells and the BMS average (value dimmed). The bar tooltips say which instrument they come from. The BMS table and its dots are unchanged.

### 1.21.0
- **BMS Battery tiles:** V/A/°C and Ah remaining are back directly under the SOC gauge; the cell graphic comes below them.
- **Cell graphic redrawn as deviation bars.** A horizontal line stands for the **balancer's average voltage** and its value is printed at the line's left. Every cell is a bar growing up (above the average) or down (below it) from that line, scaled to at least +/-20 mV. The bars are the BMS cell voltages, so when the BMS and the balancer disagree by a few tens of mV all bars sit on one side of the line - that is the instrument offset made visible (without a fresh balancer reading the BMS's own average is used and its value is dimmed). Colours: lowest cell **blue**, highest **red** (as the dots in the table), the rest **green**; a cell at or above the Float cell trigger **blinks bright red**. Cells being balanced keep the pulsing yellow outline and the lightning mark above the bar; the line below now reads just *cell 3 · 1.1 A* (no lightning mark).
- **BMS table:** *Alarms* and *Cycles* moved up into STATUS, above *SOC - Charging*; the section with the Charge/Discharge buttons is now called **CONTROL** (it was SYSTEM).
- **Refresh all** on the BMS page is split into **Refresh BMS** and **Refresh BAL** (the latter is the Balance page's Refresh all). The status text under the title now has one line per source (*BMS updated hh:mm:ss · every 30s*, *BAL updated ...*).

## 1.20 — Battery and balancer integrated on the BMS page

### 1.20.0
- **BMS page: one combined table.** The separate balancer table from 1.19.0 is gone; balancer n now sits in battery n's column. The column header shows the balancer's state under the battery name (*Balancer OK*, *Balancer 7 min old*, ...; tapping it refreshes just that balancer). A new **BALANCING** section has Balance status, Balance current, Balance position and the balancer's temperature. In **CELLS**, every value (Average, Max difference, Cell 1-4) is the BMS reading with the balancer's reading small and grey underneath (`bal 3.411`); when the two differ by more than **15 mV** the balancer value turns amber (not when the balancer data is stale, which is dimmed instead). Cell values, highest/lowest dots and everything Float protection uses remain the BMS's.
- **BMS page: Battery tiles show the cells and the balancer.** Under the gauge: four mini bars, one per cell, showing each cell's deviation from the pack average (scaled to at least +/-20 mV so a few millivolts do not look dramatic): green normal, amber highest, blue lowest, red at or above the Float cell trigger. The cell(s) the balancer is currently balancing pulse with a yellow outline and a lightning mark, and a line below says *cell 3 · 1.1 A* (or *Balancer idle*, or *Balancer N min old* when its data is stale). The bars come from the BMS cells; the balancer only supplies who is balancing and the current.
- `/api/bms` and `/api/balancers` are now fetched in parallel and drawn in one pass, so the two never disagree on screen for a moment. The Balance page is unchanged apart from sharing the balancer status wording.

## 1.19 — BMS/Balance layout, History swipe, database status

### 1.19.0
- **BMS page:** the *Set SOC* buttons (and *Set all SOC*) moved from the bottom action rows into the table's STATUS section, directly under *SOC - Discharging*; Charge/Discharge (and the *All* variants) stay at the bottom.
- **BMS page:** the Balancer table from the Balance page is now also shown under the BMS table, aligned so Balancer 1 sits in Battery 1's column, and so on (clicking a balancer's header refreshes just that balancer, as on the Balance page).
- **Balance page:** removed the *Frames* row.
- **History:** swiping left/right now moves between the History tabs (Sources, Storage, Loads, Alarms, Reports); at either end it continues to the neighbouring page (Balance / Settings), as before.
- **Settings → Save history period:** now shows the database status - size (plus the write-ahead log), number of records in total and per source, oldest/newest record, stored period against the retention setting, growth per day, expected size at the full retention period, reusable space inside the file, the in-memory chart cache and the free disk space. New read-only `GET /api/history/status`: answered from the `(source, id)` index on its own connection (never under the history lock), cached for 60 s, about 0.1 s on the live ~1 GB database.

## 1.18 — Mode memory, 24-hour clock, History chart fixes, BMS/Balance cleanup

### 1.18.1
- **Fix: the History page had become sluggish, and the Storage charts' "broken bars" from 1.18.0's own fix could now take a noticeable moment to clear.** `HistoryService.chart_data()` (the per-zoom fetch added in 1.18.0 to keep short views dense) rescanned the *entire* server-side cache on every call - two full-list filters over every cached point, regardless of how few hours were requested. With about three weeks of history cached (~135k BMS + ~158k dashboard points) that cost 400-750 ms per call, on every History preset click, Custom change and Zoom-slider drag. It now finds the cutoff with a binary search (the caches are already in chronological order), which is a few hundred times faster at the same cache size (benchmarked in the self-test at ~150,000 points per cache: 400-750 ms -> ~1-5 ms) and stays fast as the cache keeps growing. `refresh_chart_cache()`'s retention trim had the same unconditional full-rebuild shape (run roughly every 60 s in the background, changelog 1.16.0); it now only rebuilds when pruning actually removed something, and does that with the same bisect instead of a full rebuild. The dense-view debounce is shortened from 300 ms to 120 ms now that the fetch itself is no longer the slow part.

### 1.18.0
- **Float protection reads cell voltage from the BMSes only** (confirmed and documented explicitly; the balancers' own cell readings, which exist for display only, were never part of the trigger). **Float now also sets every battery's SOC to 100%** the moment it starts: the triggering cell being at/above the Float voltage means the battery is effectively full, so this re-anchors the coulomb counter immediately instead of waiting for the next full discharge. Fires once per fresh Float start, never while merely held or already latched (`masterbus_service.enforce_high_soc_float`, new `float_started_callback` hook, `app.py`).
- **Control panel: the last Motor/Anchor/Marina/Sail mode is remembered server-side** and its button stays highlighted, for every browser and after a page reload - not just in the browser that clicked it. Switching any device individually clears it (also server-side) so no mode button is shown active when the system no longer matches one. New `active_mode` field on `/api/energy`; `MasterBusService.clear_active_mode()` is called from every individual control route. Not persisted across a server restart, like the other live status fields.
- **Set SOC pop-ups:** fixed the manual-entry field showing a doubled "%" and made it the same height as the Set button.
- **The clock in the header (and "Updated …" on the BMS and Balance pages) is now 24-hour**, not AM/PM.
- **Control panel:** the Shore Power tile is now the same height as the other Sources tiles. The Storage tiles' gauge shows "100%" in full again (the "%" was being dropped at 100).
- **BMS page:** the Battery tiles' V/A/°C line no longer breaks across two lines on an iPhone. The table no longer repeats Voltage, Current, Temperature and Remaining, which are already in the tiles above it.
- **Balance page:** removed the Alarms and Cycles rows (balancers don't alarm or cycle-count; these were always "None"/empty).
- **History → Sources → Generated power:** the left (W) axis now steps in multiples of 250 W.
- **History → Storage:** the Remaining chart's left axis is now in kWh instead of Ah (right axis % unchanged). The Charge/discharge chart now shows Watts on the left axis and Amps on the right (was Amps only).
- **Fix: a short History selection (e.g. 4 hours) could render as disconnected, broken-looking bars.** The chart data behind the full selection is index-sampled across the whole retention period, which can leave an uneven, sparse slice for a short preset or zoom. A short-enough view (≤ 48 hours) now also quietly fetches that exact window at full resolution in the background and re-renders with it, without touching the broader data the Custom/Zoom sliders are built from.

## 1.17 — Float protection is cell-voltage only, manual SOC entry, gauge meters

### 1.17.0
- **Float protection no longer has a SOC trigger.** It used to start on *either* the average House SOC reaching its threshold *or* any single cell reaching the cell-voltage trigger; the SOC side is removed, so Float now starts purely on the highest single cell voltage (`house_soc.float_decision`, `masterbus_service.enforce_high_soc_float`). Bulk resume also drops its SOC condition: it resumes once every cell is back at or below the resume level. The pack-average House SOC is still shown on the Control panel and reported in `/api/energy` for information, but no longer starts, holds or resumes Float. The *Switch to Float when SOC* and *Switch to Bulk when SOC* settings are removed; *Also switch to Float when a cell reaches* is renamed **Switch to Float when any cell reaches**. An older `user_settings.json` with the removed fields still loads.
- **Set SOC pop-ups (BMS page, per battery and "Set all SOC") can take a manual percentage**, next to the existing Charge-curve, Discharge-curve and 100% choices. New `POST /api/bms/{battery_id}/set-soc-value` and `POST /api/bms/set-all-soc/value` routes (body `{"percent": N}`, 0-100).
- **The Float protection warning is now a blocking pop-up**: it stays open until the user clicks OK instead of closing itself after a few seconds. The *Show warning pop-up duration* setting is removed (the BMS pop-up duration, used elsewhere, is unaffected).
- **Control panel** (renamed from "Dashboard", including the bottom-tab label): the Storage tiles' circular SOC indicators are replaced with the same arc-gauge meter (red/amber/green zones, needle, percentage) used on the BMS page, sharing one `gaugeDial()` routine with the BMS page's own gauge.
- **BMS page:** the System section's *Balancing* row is removed (balancing state is already visible on the Balance page).
- **Control panel, Sources tile:** the *AC limit (A)* label now sits below the input instead of above it.
- Mappings, control sequences and hardware-verified fields are otherwise unchanged.

## 1.16 — History cache keeps itself current

### 1.16.0
- **Fix: the History page could show data that was hours or days old.** The server-side chart cache that the History page reads was built once at startup and otherwise only advanced when a browser pressed **Update**; fresh readings kept landing in the database the whole time, but a server left running for days without anyone opening History and pressing Update (or a History tab left open) kept showing the snapshot from the last restart or click. `_history_loop` now also refreshes the chart cache roughly once a minute; the refresh was already incremental (only the rows added since the last one), so this adds no real cost. Added an index on `measurements(source, id)` so that incremental sync stays cheap as the database grows. The **Update** button still works the same way, for an on-demand refresh.

## 1.15 — History time axis and zoom

### 1.15.0
- **History → Zoom.** A **Zoom** button next to *Custom* opens two sliders (*Zoom from* / *Zoom to*, same style) that narrow the selected period: for example inside a 24 h selection, move the start forward and the end backward. All charts and donut charts follow the zoomed period, the header shows *“12 hours · zoomed in from 24”* and the Zoom button is highlighted while a zoom is active. **Reset zoom** restores the full selection; choosing another preset or a Custom range also clears it. The Zoom and Custom panels are never open at the same time. Minimum zoom is 1 minute.
- **Whole time units on every chart's horizontal axis.** Labels and tick marks now sit on whole hours (09:00, 10:00 …), never on 09:35: a longer tick on every whole hour and a shorter one on every half hour. Longer periods switch to whole days (long tick) with half days (12:00, short tick) and weeks for very long periods; far zoomed-in views use 10 and 5 minutes. Midnight is labelled with the date. Labels are thinned to fit the width (for example every 2 or 4 hours on a phone). One shared routine (`drawTimeAxis`) draws the axis of all seven chart types.
- **Power charts start at 0.** *Generated power*, *DC consumption* and *AC power* no longer show a negative range below zero (the right-hand amps axis starts at 0 A too). Charts with real negative values (charge/discharge current) still pad below zero.
- **BMS page:** tapping a battery's **column title** (Battery 1–3) in the matrix refreshes just that battery, like the tiles at the top and like the Balance page's column titles.

## 1.14 — History charts

### 1.14.0
- Merges the changes that had been made directly in the live folder (see 1.13.0 below) with the History chart work, so the repository, GitHub and the running server are the same code again.
- **History → Storage → Remaining:** the left axis is fixed at **0–1000 Ah** and a right axis shows **0–100 %**, where 100 % is the 960 Ah bank capacity (a dashed line marks 960 Ah, just below the top of the chart).
- **History → Sources:** the *Charge current (A)* chart is removed because it repeated *Generated power*. That chart is now **Generated power (W / A)**: the amps are on a right-hand axis. The two units are linked through the average bus voltage of the period (total watts ÷ total amps, shown in the subtitle, typically about 13.5 V), and the dashed average line shows both units.
- **History → Loads:** same change: *DC load current (A)* is removed and **DC consumption (W / A)** has the amps on the right axis.
- The donut charts stay directly under the remaining chart of their tab (*Source contribution*, *Total per Consumer*).

## 1.13 — Float protection dual trigger

### 1.13.0
Analysis of 10 days of stored BMS history found 44 cell-voltage/cell-imbalance alarm episodes, several ending in the
BMS itself cutting the charge MOSFET off - Float protection did not stop charging in time to prevent them. Root cause:
Float watched only the *average* House SOC across the three parallel batteries, and one battery can reach a high
individual SOC (its own coulomb counter can already read 100%) - with one of its cells already inside DALY's own
high-voltage alarm band - while the average is still far below the 95% Float threshold (as low as 58-91% in the
recorded episodes). No manufacturer alarm thresholds are read or changed; the fix works entirely from the app's own,
independently-chosen cell-voltage figure.
- **Float now has two independent triggers** (`house_soc.py`, `float_decision()`): the existing SOC average (default
  95%, unchanged), **or** the highest single cell voltage across all three batteries reaching a new threshold
  (default 3500 mV). Either is enough to force Float; a normal full-charge cell sits around 3360-3390 mV, and DALY's
  own "Cell voltage high" alarm was observed starting around 3550-3600 mV, so 3500 mV acts with real margin on both
  sides.
- **Resume to Bulk needs both signals clear**: the SOC at or below *Switch to Bulk when SOC* (default 90%, unchanged)
  **and** every cell at or below a new resume level (default 3420 mV). If either reading is unknown (stale Bluetooth
  link) while Float is latched, it holds rather than resuming blind - this generalises the 1.12.0 freshness-hold to
  the cell-voltage signal.
- **Two new settings, adjustable on the Settings page** like the existing SOC pair: *Also switch to Float when a cell
  reaches* (`float_cell_trigger_mv`, 3300-3650 mV) and *Switch to Bulk once every cell is at or below*
  (`float_cell_resume_mv`, 3200-3650 mV, must be at least 30 mV below the trigger).
- `high_soc_float_policy` (and `/api/energy`'s `storage.house`) gains `max_cell_mv`, `max_cell_battery`,
  `max_spread_mv`, `max_spread_battery`, `cell_trigger_mv`, `cell_resume_mv` and `trigger` (`"soc"`, `"cell_voltage"`,
  `"soc+cell_voltage"` or `"held"`, saying which condition forced Float). The Dashboard's Float pop-up now names the
  actual reason instead of always citing the SOC threshold.
- The per-battery **cell spread** (worst cell-to-cell difference within a battery) is now also reported for the same
  reason, but is deliberately **informational only** - it is not wired into the trigger, so a brief, harmless
  imbalance mid-charge cannot stall normal Bulk charging.
- Control write paths, the verified Float/Bulk command sequences, the 20 s per-source retry and the 3 s check
  interval are unchanged. New tests: `float_freshness_self_test.py` gained a cell-voltage part reproducing the
  reported failure mode end-to-end (a low SOC average with a hot cell still forces Float; resume is blocked until
  the cell cools; a stale cell reading holds rather than resumes blind) plus settings-validation checks.

## 1.12 — Bluetooth reliability

### 1.12.2
- **Signal strength.** Every scan now records the advertisement signal strength (RSSI, dBm) of each DALY balancer and battery it sees, also of balancers that were visible but not being looked for. `GET /api/bluetooth-events` reports it per device as `signal` (last, average, recent average, min, max), and the balancer scan line in `logs/bluetooth.log` shows it (`found DL-BAL3 (-71 dBm); also visible DL-BAL2 (-58 dBm)`). Purpose: tell a weak link (a balancer that is visible but cannot be connected) from a device that is held by another Bluetooth central or has stopped advertising. Passive: it only reads what the existing scans already return. Nothing else changed.

### 1.12.1
- **Bluetooth timings.** `GET /api/bluetooth-events` now also reports, per device, how long each step took: `connect`, `notify` (start of notifications), `read` (a complete status), `disconnect`, `radio_wait` (waiting for the radio) and `radio_hold` (how long the radio was occupied), plus the balancer `scan`. Each has the count, successful/failed, average, median, p95 and maxima (most recent 200 samples). A successful connect that takes 8 s or more is logged as `slow_connect`, and failed connects/reads now say how long they held the radio (`after 18.0 s on the radio`). This is to choose the connect time-outs from measurements. Nothing in the Bluetooth behaviour changed.
- No functional changes to the controls, Float protection or the mappings.

### 1.12.0
Based on an analysis of the stored history: the balancers were silent for 29% of the uptime (every gap ended at a server restart) and Battery 2's link was lost 4.3% of the time against 0.3% for Batteries 1 and 3. The MasterBus side and the MOSFET/SOC **control write paths are unchanged**; only the read/monitoring path and the shared radio arbitration were changed.
- **Balancers (`daly_balancer_service.py`, rewritten, same API):**
  - Every Windows BLE call now has a hard time-out (connect, notifications, GATT writes, disconnect), so a hung call can no longer freeze the single balancer loop.
  - A crash-proof supervisor rebuilds the worker if anything raises; a **stall watchdog** forces a rescan after 10 minutes without a successful read, then rebuilds the worker, and finally reports the balancers as *wedged* (visible in `/api/balancers`).
  - **Exponential back-off per balancer** (retry × 2ⁿ, at most 5 minutes): a failing balancer no longer slows the healthy ones, and a healthy balancer keeps its own refresh interval.
  - A status is **published only when all nine commands were answered**; unanswered commands are asked once more within the same connection. No more half-read balancer rows in the history.
  - Static device information is read once instead of every cycle; known balancers are not scanned for again.
  - The snapshot reports `last_success_age_seconds`, `stale`, `next_attempt_in_seconds`, `wedged`, `worker_restarts`; the Balance page shows *Data N min old* for stale data.
- **Bluetooth coordinator (`bluetooth_coordinator.py`, rewritten, same priority order):** lease tokens (a late release from a timed-out caller can no longer free someone else's turn), a maximum hold time per kind that takes the radio back from a hung holder, FIFO order within a priority, and a **degraded mode**: if one BMS stays unreachable for 2 minutes the balancers are allowed again instead of waiting forever.
- **BMS monitoring (`daly_bms_service.py`):** hard deadlines on connect/notify/disconnect, a client that connected but never finished starting notifications is now closed (no leaked handle), a lost status request is retried once before the link is rebuilt, an incomplete status is never published (three in a row rebuild the link), and an unreachable battery is retried with exponential back-off (at most 60 s). Removed the unused legacy service class.
- **Bluetooth event log:** new `ble_events.py` writes `logs/bluetooth.log` (rotating, 1 MB × 3) and keeps per-device counters; `GET /api/bluetooth-events` returns them, so the next reliability question can be answered from data.
- **Float protection freshness (`house_soc.py`):** the House SOC now only averages DALY readings younger than max(120 s, 4 refresh intervals). If none is fresh the SOC is unknown. While Float is latched an unknown SOC **holds** Float (sources that start charging are still put in Float) and **never resumes Bulk on old data**; an unknown SOC never starts Float protection by itself. Before, a battery whose link was down kept contributing its last SOC indefinitely. `high_soc_float_policy` gains `soc_held`, `soc_stale`, `soc_fresh_batteries`, `soc_age_seconds`, `last_known_soc`; `soc_source` can be `stale_hold`. The Float/Bulk thresholds, the 20 s retry and the verified Float/Bulk command sequences are unchanged. `/api/energy` reports `soc_fresh_batteries`, `soc_age_seconds` and `soc_source: daly_bms_stale` when only old readings exist (the Dashboard then shows no SOC instead of an old one).
- New hardware-free tests with a simulated `bleak` (`ble_fakes.py`): `daly_balancer_self_test.py`, `daly_bms_worker_self_test.py`, `bluetooth_coordinator_self_test.py`, `float_freshness_self_test.py`. **Not yet verified on the boat's hardware.** Suggested settings after deploying: balancer refresh interval 300 s and retry at least 60 s.

## 1.11 — History totals

### 1.11.0
- **Donut charts with totals over the selected period** on the History page, each placed under the chart it summarises, with the sum of all contributions in the centre and as a total row:
  - **Sources → Source contribution** (under *Charge current*): energy delivered by Charger House, Alternator and Solar, with each source's average power in watts.
  - **Storage → Battery contribution** (under *Charge/discharge*): energy each battery supplied (discharged), its average power, and the energy it took in while charging.
  - **Loads → Total per Consumer** (under *DC load current*): energy used per DC consumer, with average power.
  - **Alarms → Total per Battery** (under *Alarm occurrences*): number of alarms (runs of consecutive alarm samples) per battery, with the alarm sample count.
  Each card also says how much of the selected period is covered by recorded data (server or Bluetooth downtime is not counted).
- The totals are calculated **on the server from the full-resolution history** (new `GET /api/history/contributions?start=&end=`), not from the sampled chart data, so they stay accurate for short periods. Energy is the time integral of power between samples; whole finished hours are remembered, so a request costs a few milliseconds after the first one. Battery power is the sum of the cell voltages times the current.
- **Fix:** the red/blue *highest/lowest cell* dots on the BMS and Balance pages were shown at the far left of the table instead of next to the cell they belong to. This was a regression from the 1.10.0 CSS cleanup, which left `.voltage-cell` without its positioning rule in the dark theme.
- **BMS House:** the voltage in the *Battery 1–3* tiles at the top now shows 2 decimals (the table below keeps 3).

## 1.10 — History usability

### 1.10.0
- **Time range on the iPhone.** The overlapping two-handle slider (18 px targets) is replaced by touch-sized controls: preset buttons **4 h, 12 h, 24 h, 3 d, 7 d, All** (the active one is highlighted; presets longer than the available history are disabled) and a **Custom** panel with separate **From** and **To** sliders with 34 px thumbs. The *Last 4 hrs* header button is now the *4 h* preset.
- **No more accidental page swipes.** The Dashboard ↔ BMS ↔ Balance ↔ History ↔ Settings swipe now ignores gestures that start on a slider, an input, the time-range block or a scrollable report table, so dragging a control no longer switches page.
- **Stacked charts are smooth, even areas** instead of striped columns: bands are painted as solid colour on an offscreen layer (no seams) and composited once with light transparency. Positive values stack above zero and negative values below it, data gaps (for example the server being off) stay empty instead of showing a slope, and filtering on a legend item shows that component as an area with its smooth line. Applies to the Remaining, Load, Sources and Loads charts.

## 1.9 — Reports

### 1.9.1
- History charts: when a legend item is selected to filter a stacked chart, the **smooth line** is now still drawn, following the filtered data (previously it only appeared in the *Total* view). Applies to the Remaining, Load, Sources and Loads charts; the dashed average line is unchanged.

### 1.9.0
- New **Reports** tab on the History page with a **Battery health report** button. It asks how many days of data to analyse (1–365, default 7), runs the analysis on the server and shows the result on the page: verdict per battery, cell connection resistance, current sharing, alarms, balancers and usage. The status labels are colour-coded (OK / ATTENTION / CRITICAL) and wide tables scroll sideways on a phone.
- The analysis runs in a separate low-priority process (`report_service.py`), so it cannot slow down the Bluetooth/MasterBus threads or Float protection. Only one report runs at a time; the latest result is kept in memory until the server restarts and is shown again when the tab is reopened. New endpoints: `POST /api/reports/battery-health` (body `{"days": N}`) and `GET /api/reports/battery-health`.
- History time-range controls (slider, *Last 4 hrs*, *Update*) are hidden on the Reports tab.
- **`battery_health.py`** (also usable from the command line) is a read-only battery health report built on the stored measurement history: verdict per battery, per-cell connection resistance from load steps, current sharing between the parallel batteries, cell/voltage exposure, alarms and MOSFET episodes (separating your own switching from BMS protection), Bluetooth gaps, cycle counters, balancers, Start/Bow batteries and usage. `--split` compares the periods before and after a change (for example a re-tightened busbar). Includes `battery_health_self_test.py` (synthetic data, no hardware). Reports go to `reports/`, which is git-ignored.

## 1.8 — History range and polish

### 1.8.10
- Tapping a balancer column title on the Balance page (e.g. **BALANCER 1**) refreshes only that balancer. It uses the same Bluetooth coordinator as before, but the clicked balancer goes first and is the only one read in that manual cycle; it also overtakes the rest of a running full cycle. A deferred attempt is retried. New endpoint `POST /api/balancers/{1-3}/refresh`.
- The **Inverter state** History chart has a fixed axis with only three ticks — Off (0), Inverting (1), Supporting (2) — instead of five identical `1` labels, and draws as a step line. `drawHistoryChart` accepts an optional fixed-axis argument.

### 1.8.9
- Fixed **Set all SOC** staying greyed out: the enable logic still referenced the three SOC buttons removed in 1.8.8 (`bmsAll100`, `bmsAllSocCharge`, `bmsAllSocDischarge`). It now enables `bmsAllSoc` as soon as all three batteries are connected or being read. The unused hidden placeholder buttons were removed.

### 1.8.8
- One **Set SOC** button per battery and one **Set all SOC** button, opening a dialog: charge-derived SOC, discharge-derived SOC, 100%, or cancel. The queued Bluetooth write and validation flow is unchanged.
- Fixed the iPhone bottom-navigation safe-area layout on Balance and Settings; navigation glyphs replaced with consistent line icons.
- Sources history chart renamed **Charge current (A)**.

### 1.8.7
- History slider thumbs are dedicated handles rendered above the track instead of browser-painted thumbs.
- BMS and Balance voltages are centred while keeping exact decimal alignment; cell status dots sit in a fixed marker area.

### 1.8.6
- Both History slider handles stay visible in the Light UI.
- Dashboard, BMS and Balance voltages align at the decimal point; status dots no longer shift values.
- Added a **Last 4 hrs** History button.

### 1.8.5
- Left History slider handle clearly visible in the Light UI. Balance voltages use three decimals.

### 1.8.4
- All BMS voltages use three decimals.

### 1.8.3
- History axes show 24-hour `HH:mm` for periods of 48 h or less, `DD/MM` for longer periods.
- **Update** moves the selected window to the newest measurement, preserving its duration.

### 1.8.2
- Replaced *Zoom (hrs)* with a shared two-handle time-range slider below the History tabs, filtering every tab.
- `Load (A)` renamed `Charge/discharge (A)`; horizontal-axis dates use `DD/MM`.
- Selecting a single BMS cell switches the voltage axis to 2.5–4.0 V (Total stays 0–15 V).

### 1.8.1
- Alarm occurrence legend filters by All / Battery 1 / 2 / 3, applied to all alarm charts, titles and totals.

### 1.8.0
- New **Alarms** History tab: stacked alarm timeline per battery (sample and episode counts), Cell Max-difference trend with alarm markers, current trends with alarm markers, and Charge/Discharge MOS OFF consequence markers.
- Server-side BMS chart cache now includes decoded alarms and both MOS states.

## 1.7 — Server-side history cache

### 1.7.5
- Battery cell-voltage charts: fixed axes (0–15 V left, 0–400 mV right); removed the average-voltage line.

### 1.7.4
- *Total* view draws cumulative lines (Cell 1, 1+2, 1+2+3, 1+2+3+4); selecting a cell shows only that cell's raw voltage. Max difference stays visible.

### 1.7.3
- Cell-voltage charts became smooth lines with an interactive Total / Cell 1–4 legend and a red Max-difference line on a right-hand mV axis.

### 1.7.2
- 24-hour time labels; dashed average lines on power/current charts; BMS cell-voltage data and cell spread added to the server-side chart data.

### 1.7.1
- Time-axis labels follow the selected range. Charging and DC-load current charts are stacked bars. Legends are interactive (select a component to isolate it; Total restores).

### 1.7.0
- Graph cache moved from browser IndexedDB to a shared **server-side cache** rebuilt from SQLite on restart; the server sends a bounded chronological sample per zoom window.
- Added *Zoom (hrs)* (later replaced in 1.8.2). History tabs reordered to Sources, Storage, Loads; Sources is the default.
- Swipe navigation extended across Dashboard, BMS, Balance, History and Settings.
- Generated power limited to DC sources (Charger House, Alternator, Solar); Shore Power AC voltage replaces Shore frequency; Storage voltage split per battery; Loads output-frequency graph removed.

## 1.6
### 1.6.0
- All proposed Sources and Loads history charts implemented from retained Dashboard measurements (stacked generated power, per-source charge current, Solar panel voltage, Alternator temperature; stacked DC consumption, per-consumer current, AC power, Inverter state).
- Browser cache extended to Dashboard history; **Update** retrieves BMS and Dashboard data incrementally. Time axes show dates only.

## 1.5
### 1.5.1
- History tabs: Storage, Sources, Loads. Storage charts reordered to Remaining, Load, Voltage; Remaining and Load are stacked columns with a smooth total line.

### 1.5.0
- History replaced the raw record list with time-series charts for BMS voltage, current and remaining capacity (Battery 1–3 plus calculated total), covering the full retained history.
- Persistent IndexedDB chart cache in the browser; **Update** fetches only measurements since the previous update. Incremental BMS history API added.

## 1.4 — Balancers, Bluetooth coordination, history

### 1.4.30
- All discharge gets the in-button queued/waiting/progress flow (confirmation kept); its pop-up removed.
- Discharge ON always available for a connected battery; Discharge OFF only at zero or negative current.
- Clicking a battery summary card refreshes only that battery (new endpoint and worker trigger).
- All charge / All discharge write only to batteries whose MOS state differs from the target.

### 1.4.29
- Charge OFF is available from 0.0 A upward; only negative current blocks it.

### 1.4.28
- All charge shows Queued / Waiting for Bluetooth / Action in progress in the button; queue pop-up removed. Individual Charge controls are disabled during an All-charge action.
- Charge ON always available for a connected battery with Charge MOS off; Charge OFF only with charging current.

### 1.4.27
- Only the clicked individual BMS button is disabled; further actions queue (`Queued`) and run sequentially, showing `Waiting for Bluetooth` then `Action in progress`.

### 1.4.26
- Removed confirmation dialogs from individual-battery BMS controls (all-battery controls keep theirs). Failures still produce a persistent pop-up.

### 1.4.25
- All charge / All discharge became state-aware ON/OFF toggles; the wide buttons below the matrix were removed. Successful controls no longer show a completion pop-up.

### 1.4.24
- Charge/Discharge controls use a compact power icon (state kept in colour, tooltip and accessible label).
- A battery's Charge control is disabled while its current is negative; all-battery Charge needs all three connected with non-negative current.

### 1.4.23
- Fixed the adaptive MOS retry: if the learned payload does not change the requested state, the second attempt uses the opposite payload. A Charge retry never sends a Discharge command.

### 1.4.22
- Detects per battery, and separately for Charge and Discharge, whether payload `1` means ON or OFF (firmware variants differ). An encoding is accepted only after read-back and remembered in `data/bms_mos_encoding.json`.

### 1.4.21
- MOS Charge/Discharge writes are verified by read-back, retried once, and report the actual states on failure. Changing one MOS preserves the other (restoring and verifying it if the unit changes both).

### 1.4.20
- Fixed a race after a successful BMS verification that could end in a watchdog failure. Bluetooth queue waits run outside the battery worker loop; automatic reads pause briefly during a user setting.

### 1.4.19
- Fixed a false *BMS update failed* after verification completed: the 25 s per-battery watchdog was shorter than a valid write plus nine verification reads. It is now a 120 s last-resort guard.

### 1.4.18
- Deterministic Bluetooth **priority queue**: user controls, manual BMS refresh/reconnect, automatic reconnect, automatic BMS reads, balancer traffic.
- Setting writes and verification retry once. `Set all` errors name the failed, completed and untouched batteries. Failure dialogs stay until OK. BMS status exposes queue and manual-refresh progress.

### 1.4.17
- 8 s timeout on every BMS write and 4 s on each verification request; progress names `sending setting`, `waiting for BMS confirmation` and each verification read; failures name the battery, operation and timeout.

### 1.4.16
- `Set all` reserves the Bluetooth radio once for the whole three-battery batch, with server-side progress (`Updating Battery 1/3` …).

### 1.4.15
- Dashboard column widths rebalanced; lightning icon restored next to the title.
- BMS and Balancer **Refresh all** are generation-based, so every battery/balancer must complete the request. BMS cards show their real sequential *Updating* state.
- SOC - Charging / SOC - Discharging moved into STATUS. User writes register high priority immediately.
- Added persistent *Balancer refresh interval* (default 30 s). Removed the History Export button.

### 1.4.14
- Replaced *Set SOC accurate* with separate **Set SOC - charge** and **Set SOC - discharge** (plus all-battery versions), using the same curves as the measurement rows. BMS setting changes hold the radio for the whole write, delay and verification.

### 1.4.13
- Fixed stale *Waiting for BMS* states. A balancer holds one radio lease across connect, subscribe, request and read; contention shows as `Queued`.

### 1.4.12
- Coordinated scheduling for BMS connections, reads and balancer traffic; BMS reads serialised. Balancer readiness now requires all three batteries connected and read once, replacing the fixed 10 s delay.

### 1.4.11
- One process-wide **Bluetooth coordinator** for the three BMS and three balancers: BMS connections take priority and are serialised; balancers wait until the BMS links are stable and pause when one drops.
- Separate retry settings (BMS 5 s, balancers 30 s). Added a read-only coordinator diagnostics endpoint.

### 1.4.10
- Removed the fixed Balancer 1→2→3 polling order: a timed-out balancer goes first next cycle, healthy ones rotate. Post-disconnect settling raised from 2 s to 4 s.

### 1.4.9
- Default BMS refresh interval 30 s (saved settings unchanged).
- Balancers reuse the last known Windows Bluetooth identity, share one 12 s discovery scan, explicitly disconnect failed/stale GATT clients, and are polled one at a time with a settling gap. Subscriptions limited to DALY's FFF1 channel.

### 1.4.8
- Removed the derived SOC from the *Average* voltage row; every voltage-derived `Set SOC` now uses the *SOC - Discharging* curve (fixed 100% stays 100%).
- Float protection confirmed as a **server-side** policy checked every 3 s without a browser. Changing *Switch to Float when SOC* re-initialises *Switch to Bulk when SOC* five points lower.
- Added *Save history period* (default 7 days, rolling deletion). BMS refresh and control operations serialised per battery.

### 1.4.7
- Added **SOC - Charging** and **SOC - Discharging** rows: bounded linear interpolation of average cell voltage against LiFePO4 reference curves (Renogy four-cell tables). Comparison indicators only; they do not replace the DALY coulomb-counted SOC.

### 1.4.6
- Every active DALY `0x98` alarm bit decoded to text, one per line.
- Directional swipe navigation Dashboard ↔ BMS ↔ Balance.
- Durable **SQLite measurement history**: Dashboard snapshot every 10 s plus each new BMS/balancer reading; History page with recent records and JSON Lines export.
- Disconnected balancers are prioritised and retried every 5 s; stale cached identities are cleared after repeated failures.

### 1.4.5
- Balance: removed Minimum/Maximum rows, *Difference* → *Max difference*. BMS: *Cell average* → *Average*, *Cell spread* → *Max difference*.

### 1.4.4
- Balance current now uses the balancer's own current byte in response `0x93` with the observed 0.01 A scale (`0x55` = 0.85 A); the unrelated `0x90` pack current is no longer shown.

### 1.4.3
- Expanded balancer diagnostics stay open across refreshes, remembered per balancer.

### 1.4.2
- Balance page rebuilt as a compact four-column matrix matching BMS, with red/blue dots for highest/lowest cell; raw Bluetooth diagnostics in collapsed sections.

### 1.4.1
- Balancers (`DL-BAL1`–`3`) monitored directly over their own FFF1 channel (no BMS UART link assumed). Frames are reassembled and validated; semantic cards for status, current, position, statistics, temperatures, cell count, cycles and cell voltages. Device names match by prefix/substring. Read-only requests only.

### 1.4.0
- New **Balance** page for `DL-BAL1`–`3` with staggered persistent Bluetooth connections, per-characteristic GATT values, retained raw frames for protocol mapping, manual and automatic refresh.

## 1.3 — Persistent BMS Bluetooth links

### 1.3.18
- BMS page heading **BMS House**; higher-contrast dial needle and hub in the Light UI.

### 1.3.17
- Heading *BMS House Battery*. The backend *Set SOC accurate* curve now matches the displayed Cell-average curve (3.60 V charging endpoint, same interpolation and rounding).

### 1.3.16
- Dashboard House SOC is the average of all valid DALY SOC readings (one is enough). Start and Bow SOC come only from their own MasterShunts.
- Thresholds renamed **Switch to Float when SOC** / **Switch to Bulk when SOC**; the current-based Bulk delta became an absolute SOC threshold with at least 5 points of hysteresis, validated in client and server with an explanatory pop-up.

### 1.3.15
- Float protection uses the same live DALY House SOC as the Dashboard and waits while it is unavailable, preventing a conflicting MasterShunt value from triggering Float during Bluetooth start-up. The SOC source is reported in the policy status.
- Settings inputs aligned in one column; larger table and button fonts.

### 1.3.14
- Four equal-width Measurement columns, compressed rows and controls, uniform one-pixel grid-gap separators.

### 1.3.13
- Replaced the shared DALY event loop with **three failure-isolated workers** (one Windows thread and asyncio loop per battery), started in order with one-second staggering. A stall on one battery no longer blocks the others. Manual *Updating all batteries* has a 12 s server-controlled maximum.

### 1.3.11
- Aligned *All charge ON* / *All discharge ON* with their rows; OFF variants on a full-width bottom row.
- Bulk-resume delta became an absolute discharge current in amperes (later replaced in 1.3.16). Float settings indented with a guide line; all Measurement separators restored.
- Longer DALY discovery and pauses between sequential connections; Battery 3 ahead of Battery 2 so a stalled Battery 2 handshake cannot starve it.

### 1.3.10
- Dashboard Storage SOC uses the live DALY SOC. Separate *All charge ON/OFF* and *All discharge ON/OFF* controls with high-contrast Light UI styles.

### 1.3.9
- Removed the redundant SOC gauge row and connection states; larger summary values; all-battery actions in the left Controls column; guarded *All charge OFF* / *All discharge OFF* with backups and confirmation.

### 1.3.8
- "Concept A" styling: compact battery summary cards and grouped comparison sections. Immediate *Updating…* feedback, latest refresh time and interval shown.
- Hard deadlines around BLE connect and notification setup so a hung Windows connection cannot block refreshes.

### 1.3.7
- Removed the Charge/Discharge MOS rows. Added configurable Float-to-Bulk hysteresis and an informational Bulk pop-up. Bidirectional Dashboard ↔ BMS touch navigation. Better BLE reconnects by caching discovered devices and avoiding scans while GATT connections are open.

### 1.3.6
- Sequential connection of missing batteries for Windows BLE reliability. Voltage-derived SOC beside Cell average with individual and *Set all* accurate-SOC controls. Natural formatting of balancing cells; Dashboard → BMS left-swipe.

### 1.3.5
- Space between the SOC gauge and its value; remaining capacity rounded to whole Ah.

### 1.3.4
- Semicircular analog SOC dial (red/amber/green ranges, pointer). Fixed DALY balancing bit order (Bit0 = Cell 1 … Bit47 = Cell 48) and filtered against the reported cell count.
- Added *Connection retry interval* (default 5 s, 1–300 s); an unexpected disconnect wakes the reconnect loop immediately.

### 1.3.3
- Analog SOC dials, *Cell average* row, red/blue dots for highest/lowest cell, styled in-app dialogs replacing browser confirms. Added *BMS pop-up duration* (default 3 s, 1–60 s).

### 1.3.2
- BMS page rebuilt as a comparison matrix (shared label column, one column per battery) with SOC gauges, per-battery **Set SOC 100%**, Charge ON/OFF and Discharge ON/OFF. Every control confirms, saves a timestamped pre-change backup, applies the DALY command and refreshes all batteries.
- DALY write commands: SOC `0x21` (100.0% = `1000`), Charge MOS `0xDA`, Discharge MOS `0xD9`, legacy `0xA5` framing with write source byte `0x80`. Protection-threshold registers stay inaccessible.

### 1.3.1
- BMS overview as three side-by-side battery columns with per-row alignment and one row per cell voltage.

### 1.3.0
- **Persistent BLE connections** to BATTERY 1–3, refreshed concurrently with automatic reconnect. Added *BMS refresh interval* (5–300 s). Read-only.

## 1.2
### 1.2.0
- **Dashboard** rename (was Overview) and a functional **BMS** page for `BATTERY 1`–`3` using the DALY legacy `0xA5` BLE protocol: pack voltage, current, SOC, temperatures, capacity, cell voltages, spread, MOS states, balancing, alarms, cycles. Sequential reads, isolated failures, read-only. Added `bleak` to requirements.

## 1.1
### 1.1.0
- Functional **Settings** page persisted atomically in `user_settings.json`: default AC limit (3–15 A, used by Marina mode), Float protection ON/OFF, House SOC threshold (50–100%), warning pop-up duration (1–60 s). Defaults 15 A, ON, 95%, 8 s.

## 1.0 — First production release

### 1.0.22
- Removed the fixed *Type:* header from Storage tiles (subtitle is e.g. `MLI 960A`).

### 1.0.21
- House Battery Amp and Watt readings blink red at or below −100 A (not for Start or Bow); Dark and Light styles.

### 1.0.20
- Visible labels shortened: *Charger Bowthruster* → *Charger Bow*, *Bowthruster Battery* → *Bow Battery*. Internal keys unchanged.

### 1.0.19
- Frequency labels replaced by `f` (e.g. `f 50hz`).

### 1.0.18
- **Local HTTPS** on port 8000 with a private Mastervolt CA and renewable server certificate (localhost, computer name, local IPv4 addresses), automatic trust for the current Windows user, `install_pc_certificate.cmd`, a one-time iPhone CA installer on port 8001, and `/local-ca.cer`. Bound only to an RFC1918 LAN address (or localhost); no public exposure. See [docs/local-https.md](docs/local-https.md).

### 1.0.17
- High-contrast **Light UI** for sunlight, Dark stays default; toggle next to the clock; choice stored on the device and applied before first paint; theme colour follows.

### 1.0.16
- The Float information dialog auto-closes after eight seconds; OK closes it immediately.

### 1.0.15
- The *Supporting* status blinks grey/red while AC support is active; *Inverting* stays steady.

### 1.0.14
- A valid AC-limit entry clears the highlighted mode button. Float message punctuation corrected.

### 1.0.13
- High-SOC Float threshold 98% → 95%. One-time information dialog when the policy actually switches Charger House, Alternator or Solar to Float, driven by a server-side event counter.

### 1.0.12
- AC limit restricted to whole numbers 3–15 in UI and server with the message *Enter a value between 3 and 15*. AC Loads shows green-bullet Active/Inactive; output frequency styled as grey secondary text.

### 1.0.11
- SUP blinks green/translucent red while CombiMaster field 49 reports actual *Supporting*. New **Inverter** tile (battery-side V/A/W from CombiMaster fields 11/12, zero unless field 47 *Inverting* or 49 *Supporting* is active); `INV` control moved there. Inverter DC current is subtracted from Other DC Loads to avoid double counting.

### 1.0.10
- Automatic **high-SOC Float policy** (House ≥ 98%): active Charger House, Solar and Alternator are forced to Float using CombiMaster 42/43, Solar 18/19 and Alpha Pro 37/38, verified via charger-state 3 with a 20 s retry cooldown. Inactive sources are not switched on. Status exposed as `high_soc_float_policy` in `/api/energy`.

### 1.0.9
- `SUP` replaces the Shore Power `INV` control: CombiMaster Btm3 field 11 *AC IN support* (writable 0/1, write with read-back). Marina mode also enables the inverter, AC IN support and sets 15 A.

### 1.0.8
- Total DC load excludes AC Loads. Added **Sail mode** (Anchor plus Engine ECU ON). Shore Power shows connection state and input frequency (CombiMaster field 4); AC Loads shows output frequency (field 6). System OK and clock moved into the header row.

### 1.0.7
- **Alternator** load tile from Alpha Pro fields 6 (battery voltage) and 8 (field current); included in Total DC load and subtracted from Other DC Loads first. Switching the alternator off from either tile needs a confirmation dialog. Solar shows `PV ###V`.

### 1.0.6
- Fixed the AC-limit field losing focus: the one-second refresh no longer replaces the focused input, keeping the iOS keyboard open.

### 1.0.5
- iPhone-friendly numeric AC-limit input, validated in UI and server. *Already active* dialog for a pressed active mode. SOC 100 drawn without `%`.

### 1.0.4
- Compact AC-limit input; mode progress modal 6 s; active mode button turns green; operating any tile control clears the active mode.

### 1.0.3
- Fixed AC-limit input width; label moved below it. Added the mode progress modal (*Setting Motor/Anchor/Marina mode*).

### 1.0.2
- Added **Motor**, **Anchor** and **Marina** modes built from existing verified controls; Anchor and Marina never switch Engine ECU power off. Shore Power AC-limit label placement; Engine ECU state indicator.

### 1.0.1
- Storage tiles read battery type and capacity from MasterShunt metadata when safely identifiable (`Type: XXX NNNA`, LiFePO4/AGM fallback). AC limit moved into the Shore Power tile; inverter control moved right and labelled `INV`; redundant standalone controls removed.

### 1.0.0
- First production release. Storage sublabels: House `LiFePO4`, Start `AGM`, Bowthruster `AGM`. No mapping, calculation, control or safety changes from 0.18.17.

---

# Pre-1.0 development (0.x)

Hardware-verification work: reverse-engineering MasterBus fields, the Engine ECU and Alpha Pro controls, and the dashboard maths. Field-level detail is in [docs/hardware-notes.md](docs/hardware-notes.md).

## 0.18 — Product pictures, UI redesign, alternator control

### 0.18.17
- ECU shutdown warning: *Switching off the Engine ECU will STOP the engine immediately if it is running!* Slightly less opaque/blurred backdrop. Alternator tile shows Alpha Pro temperature (field 32). Tile label *Engine ECU power*.

### 0.18.16
- Removed the boxed S/S/L section initials; SOURCES, STORAGE and LOADS labels share one aligned icon column.

### 0.18.15
- Tightened AC/DC → voltage → amps → watts spacing; more separation before storage SoC. `(House)` removed from AC Loads / Other DC Loads; `AC limit A` → *Shorepower AC limit (amps)*. Version shown in the footer.

### 0.18.14
- Removed inter-column gaps between AC/DC, voltage, current and watts. Storage header shows signed House power as Charging / Discharging / Idle.

### 0.18.13
- Engine ECU OFF uses a Mastervolt-styled in-app safety dialog; **Keep ECU ON** is the focused default, and Escape or tapping outside also cancels.

### 0.18.12
- Larger iPhone typography, fixed aligned columns with tabular numerals, circular SoC rings, signed watts in Storage, horizontal inverter/AC-limit layout.
- Engine ECU OFF requires explicit confirmation (cancelling leaves it ON).

### 0.18.11
- DC-balance solver decides by Alpha Pro **field 5** (actual charge state), not shaft rotation: states 1/2/3 → calculate alternator current; 0/5 → current is zero and the house-load baseline is learned, even if the shafts still turn.

### 0.18.10
- Alternator / Other DC balance rewritten around a low-pass-filtered (α 0.25) total-house-load baseline (see hardware notes). Alternator **ON** now only clears Stop Charge (field 39 = 0 + commit 40), to test whether the Alpha Pro resumes automatically.

### 0.18.9
- Alpha Pro state `5` decoded as **Stopped**. Alternator ON first clears the latched Stop Charge, waits, then sends Bulk (field 33 + commit 34); OFF verifies state 5.

### 0.18.8
- Alternator current = signed MasterShunt House A + all DC load A, clamped at 0. Alternator gets normal ON/OFF: ON = field 33 (Bulk) + commit 34, OFF = field 39 (Stop charge) + commit 40. Removed the one-way Float/OFF action.

### 0.18.7
- Visual redesign to the approved dark charcoal / teal / green mockup: teal SVG pictograms replace emoji, larger bold device names, compact second-line status, compact green SoC bar.

### 0.18.6
- Compact iPhone dashboard: compressed header and rows (45 px), smaller icons and typography, shorter bottom navigation, desktop-width tuning.

### 0.18.5
- Solar tile shows SCM field 6 (battery/output voltage) as *Voltage*; field 4 kept as `panel_voltage`.

### 0.18.4
- Solar OFF fixed: write field 12, wait 50 ms, send the commit token to field 13, verify OFF by read-back. ON stays permissive because the SCM may legitimately fall back to OFF with insufficient PV.

### 0.18.3
- **Baseline reset** to 0.17.10 (including the Mass Charger state-0 fix). The product-picture work from 0.18.0–0.18.2 is deliberately *not* in this line at this point; numbering continues from here.

### 0.18.2
- Product images for the remaining tiles (batteries, Charger Start/Bow, Engine ECU, AC Loads, Other DC), cached once and shared.

### 0.18.1
- Worked around the Mastervolt image CDN's HTTP 403 for Python's downloader: browser-style headers with Mastervolt Referer, `curl.exe` fallback, image validation. `py cache_product_images.py --force` retries manually.

### 0.18.0
- Mastervolt product photos on the Shore Power, Charger House, Alternator and Solar tiles, downloaded once into `static/products/` (never hotlinked) and cached by the service worker.

## 0.17 — Verified fixed map and source states

### 0.17.10
- Mass Charger field 1 raw `0` displays *Off* (fixes `Unknown (0)` on Charger Bowthruster).

### 0.17.9
- Solar ON no longer returns HTTP 409 at night: dedicated `set_solar_enabled()` sends field 12 and treats an immediate OFF read-back as normal.

### 0.17.8
- Alpha Pro tile got a one-way OFF button sending Float (fields 37/38) and watching field 5 for state 3. Superseded in 0.18.8.

### 0.17.7
- Solar field 12 (`On/Off`) control enabled, with the same behaviour noted in 0.17.9.

### 0.17.6
- Charger ON/OFF moved to the Charger House tile; Solar and Alternator controls placed (disabled until verified). *Total Output* → *Total DC load*.

### 0.17.5
- Solar and Alternator show the **actual** charger-state fields (Solar field 3, Alpha Pro field 5: 0 Off, 1 Bulk, 2 Absorption, 3 Float; anything else `Unknown (n)`) instead of derived states.

### 0.17.4
- Derived Solar (Charging/Idle) and Alternator (Stopped/Charging/Running) state indicators. Superseded by 0.17.5.

### 0.17.3
- Mass Charger field 1 raw `5` displays *Constant voltage*.

### 0.17.2
- Fixed Charger House state decoding: CombiMaster uses 0 Off / 1 Bulk / 2 Absorption / 3 Float, Mass Charger uses 2 / 3 / 4.

### 0.17.1
- Display-only *State: Bulk / Absorption / Float* on Charger House, Start and Bowthruster.

### 0.17.0
- **Fixed verified measurement map** replaces heuristic field selection (which had used Solar field 4 as both voltage and power, treated Alpha Pro field 21 as alternator current, misread Mass Charger outputs as house-bus load and picked wrong Yanmar fields). Discovery code remains for diagnostics only.

## 0.16
### 0.16.1
- Charger Start/Bow house-bus load = input voltage × input current (fields 4/5; 6/7 are output). Engine ECU input current estimated from output power at 85% efficiency (fields 39/40/41).

### 0.16.0
- Alternator current derived from the house DC balance because the Alpha Pro exposes no trustworthy output-current field, using the shaft signals (fields 11/12) to break the circular dependency with *Other DC Loads*. Solar W = field 6 × field 5.

## 0.15
### 0.15.5
- `masterbus_snapshot.py` uses each device's known `max_index` instead of scanning 256 fields.

### 0.15.4
- Rebuilt `masterbus_snapshot.py` against the current `MasterBusService` + `ControlDiscovery` (it still imported a removed `MasterBusDiscovery` class).

### 0.15.3
- Added `field_audit.py`, which prints every field number the application currently uses, including persisted dynamic mappings from `device_maps.json`.

### 0.15.2
- Suppress the benign Windows `ConnectionResetError` (WinError 10054) logged when an iPhone Safari/PWA socket is closed. Only that case is filtered.

### 0.15.1
- **Engine ECU web control fixed**: a leftover v0.13 start-up routine re-discovered Yanmar field 56 and overwrote the verified field-43 mapping. The overwrite was removed; the ECU stays mapped to field 43.

### 0.15.0
- Engine ECU ON/OFF mapped to **field 43** (`Mac/Magic On`, OFF 0.0 / ON 1.0, no commit) from the MasterAdjust USB capture.

## 0.14
### 0.14.2
- Added `ecu_commit_test.py` to test whether field 56 needs a commit token on companion field 57 (the earlier failure only proved it was omitted).

### 0.14.1
- Engine ECU web write disabled again after the generic field-56 dropdown write failed; added USBPcap capture tooling (`ecu_capture_session.ps1`, `find_masterbus_usb.ps1`).

## 0.13 and earlier
### 0.13.2
- Rebuilt `masterbus_control_discovery.py` (methods had been generated at module scope); `self_check.py` now checks both classes.

### 0.13.1
- Fixed an indentation error that left `MasterBusService` without `open()`; added `self_check.py`.

### 0.11.1
- Added read-only `control_inspect.py` (Charger Start/Bow fields 60–67, Yanmar fields 54–58).
