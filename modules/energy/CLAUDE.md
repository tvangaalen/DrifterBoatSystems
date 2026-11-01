# MasterVolt YMS

Windows-hosted FastAPI app (iPhone PWA frontend) that monitors and controls a real boat's Mastervolt electrical
system over the MasterBus USB Link, plus DALY BMS/balancers over Bluetooth. **It writes to live hardware** (inverter,
chargers, alternator regulator, Engine ECU, battery MOSFETs). Treat every control path as safety-critical.

Everything about operation, architecture and the code is in **`docs/MANUAL.md`** (chapter 9 is the developer guide). Protocol
findings, field maps and the Float rationale: `docs/hardware-notes.md`, `docs/VERIFIED_FIELD_MAP.txt`. Release history:
`CHANGELOG.md`. Read the hardware notes before touching any MasterBus or DALY code.

## Hard rules

- **Never guess a MasterBus field number, CAN opcode or DALY command.** Only use fields verified on hardware, in a device snapshot (`py -m tools.inspect_device snapshot`) or in a MasterAdjust capture. If a mapping is unknown, say so and propose a read-only inspection instead of writing code that "tries" a field.
- **Never run anything that writes to hardware** (`tools/reversible_write_test.py`, the app's `/api/control/*` and `/api/bms/*` POST routes) unless the user explicitly asks in that turn. Prefer read-only tools. Do not start the server: it takes exclusive ownership of the USB Link and the Bluetooth radio.
- **Importing must never touch hardware.** Tests and tools are imported by the test runner; keep module level free of device access (`tools/masterbus_capture.py` once started a 30 s HID listen merely by being imported, next to the live server). Hardware access belongs in `main()`.
- **Engine ECU safety is fixed:** OFF always needs the in-app confirmation whose default is *Keep ECU ON*, and no operating mode may switch the ECU off. Do not weaken this.
- Preserve write-then-read-back verification on controls. Do not turn a verified write into fire-and-forget.
- Keep hardware-verified mappings, control sequences and safety logic unchanged unless the task is specifically about them, and say so when it is. `tests/test_masterbus_golden.py` (and the other golden tests) compare the code with the hardware-verified 1.22.2 release: a failing golden test means behaviour changed. **Never regenerate a golden file to make a test pass**; regenerate only for an intended behaviour change, and say so in the changelog.
- Keep everything on a private LAN: the server binds only to an RFC1918 address or localhost. Never bind a public interface or add cloud/tunnel dependencies.
- Never commit or print `certs/*-key.pem`, `user_settings.json`, `backups/`, `data/*.sqlite3`, `captures/*.pcap` or generated `reports/` (all in `.gitignore`).
- `mastervolt/reports/battery_health.py` only reads the history database (opened `mode=ro`) and the BMS backups; keep it that way. Never point analysis tools at the live database with anything but a read-only connection.
- The Reports tab runs `battery_health` through `reports/service.py` in a **separate low-priority process**. Do not import it into the server process or run analyses in a server thread: the GIL would slow the MasterBus/Bluetooth threads and Float protection.

## Verifying changes

```powershell
py -m tests.run_all          # every hardware-free test (about 2.5 minutes); exit code = number of failed modules
py -m tests.run_all quick    # without the slow simulations
```

No test touches hardware: the USB Link is `tests/masterbus_fakes.py:FakeBus` (with a fake clock), Bluetooth is the fake `bleak` of
`tests/ble_fakes.py`, the database is a temporary file. New Bluetooth logic is tested against the simulated `bleak`, never with real
hardware. Run the whole suite before finishing; run `py -m tests.test_release` after any version or front-end file change.

Frontend: the scripts in `static/js/` are classic scripts sharing one global scope, loaded in the order of the `<script>` tags at the end of `index.html` (`tests/test_release.py` checks the list against the service worker and syntax-checks each file with `node --check`). For UI changes compare against the previous build side by side (computed styles and canvas pixels of every page, both themes) - see the 2.0.0 changelog entry for how that was done.

Delete `__pycache__` folders after running Python here; the project lives in Google Drive.

## Conventions

- **Style.** Python 3.12+, formatted with **black** (140 columns) and checked with **ruff** (`pyproject.toml`); the front end with **prettier** (`.prettierrc.json`). One statement per line, no star imports, no bare `except:`. Comments and docstrings say *why*. These tools are development-only and live outside the project (for example `C:\Temp\mv_devtools`, see manual 9.5).
- **Never edit source files with PowerShell `Get-Content`/`Set-Content`** (Windows PowerShell 5.1 reads UTF-8 as the ANSI code page and writes a BOM: every "–", "·", "—" became "â€“" etc. in a version bump once). Use the Edit tool, or a Python script that reads and writes bytes as UTF-8, and check `git diff --stat` shows only the intended lines afterwards. Working-tree files may be CRLF while Git stores LF.
- `py` launcher, not `python`. Paths must not be hardcoded: use `mastervolt.config.Paths` (injectable, so tests run on a temporary folder).
- **Layering.** `api` → `runtime` → services → protocol/IO. Nothing below `api` imports FastAPI. Nothing in `masterbus` imports `bluetooth`: the two meet only in `runtime.py` (Float protection is given the BMS cell data and the "all batteries to 100%" callback there).
- New MasterBus/DALY behaviour goes through the existing classes (`BusIO`, `DeviceControls`, `FloatProtection`, `BatteryWorker`, `DalyBalancerService`) and the shared `io_lock` / Bluetooth coordinator. Never open a second HID or BLE connection from a new code path.
- Bluetooth work goes through `bluetooth/coordinator.py` using the existing priority order (user controls > manual refresh > auto reconnect > auto reads > balancers). Per-battery workers are failure-isolated; keep them so. **Every Windows BLE call needs a hard deadline** (`asyncio.wait_for` around `connect`, `start_notify`, GATT writes, `disconnect`); a client that connected but failed later must be disconnected; `acquire()` returns a token that `release()` must be given. **`except Exception` does not catch `asyncio.CancelledError`**: worker loops run under a `link.Supervisor` (restart on crash, monitor for dead/hung workers) - a new worker must too. Log failures with `ble_events.ble_log` (`/api/bluetooth-events`).
- **Float protection only trusts fresh data** (`soc.py`). Do not read `cells_mv` from the BMS snapshot directly for control decisions: use `Services.house_soc_details` (`runtime.py`), which reads only the three DALY BMSes - never the balancers' own cell readings, which exist for display only. Float is triggered purely by the highest single cell voltage (`soc.float_decision`); the pack-average House SOC is shown for information but never starts, holds or resumes Float. A fresh Float start also sets every battery's SOC to 100% once (`FloatProtection.started_callback`, fire-and-forget in its own thread). No MasterShunt fallback without the user's approval.
- **The server-side chart cache** (`history/chart_cache.py`) is append-only in id order and only grows (heading for ~230k/~270k points at the 31-day default retention): any code that filters it by time or id must bisect (`bisect_left(cache, cutoff, key=...)`), never scan or rebuild the list. The same applies to anything touching `history.sqlite3` directly.
- History totals (the donut charts) come from `history/totals.py`, integrated over the full-resolution caches. The chart data sent to the browser is a *sample* (2,500 dashboard points, 1,200 per battery) for drawing only: never add up totals from it in the browser.
- Stacked History charts are drawn as areas by `drawStackedHistoryChart`, not as bars: no per-bar gaps or alpha, so no stripes. Keep bands opaque on the offscreen layer and composite once.
- **iPhone touch rules.** Pages switch on a horizontal swipe (`static/js/main.js`). Any control that is dragged or scrolled sideways (sliders, scrollable tables, carousels) must be an `input`/`select`/`textarea` or sit inside an element with class `no-swipe`, otherwise dragging it changes page. Touch targets should be at least ~40 px.
- **CSS edits:** when removing or rewriting rules with a script, remove the *whole* rule including its selector prefix, then compare the set of rules before and after and confirm only the intended rules changed (a dangling prefix once silently turned `.voltage-cell{position:relative}` into a light-theme-only rule, changelog 1.11.0).
- Settings are one table in `mastervolt/settings.py` (defaults, limits, messages, validation, API model). Add a setting there and to the Settings page (`static/index.html`, `static/js/settings.js`) with the same limits; give it a default that keeps existing `user_settings.json` files working.

## Releasing

The version is defined once, in `mastervolt/__init__.py`. Every user-visible change bumps it and updates, in the same commit:
`CACHE` in `static/service-worker.js` (a new cache name is what makes the iPhone PWA refresh), the version in the first paragraph of
`README.md`, the version line of `docs/MANUAL.md` (then `py -m tools.build_manual`), and a `### x.y.z` entry at the top of
`CHANGELOG.md`. `py -m tests.test_release` fails until they all agree. Do not recreate per-release `README_*.md` /
`CHANGELOG_v*.md` files; those live in `docs/archive/` for history only.

## Version control

- Git 2.55 (installed via winget; it may not be on the PATH of an already-open shell — use `C:\Program Files\Git\cmd\git.exe`). Branch `main`, repo-local identity set.
- The repository data lives **outside Google Drive** at `C:\Users\TvanG\.gitrepos\MasterVolt-YMS.git`; the project folder only holds a `.git` pointer file. Never move or delete that folder, and never run `git init` again in the project.
- History: `v1.8.8` = the original zip as delivered; then the docs consolidation; then `v1.8.10` and on. Tag each release (`git tag -a vX.Y.Z`) on the commit that bumps the version.
- Commit code and docs changes separately where practical. Commit messages: imperative summary line, then what and why; write the message to a file and use `git commit -F` (a PowerShell here-string once mis-tagged a release). Do not commit runtime data, certificates/keys, backups, captures or `user_settings.json` (see `.gitignore`); check `git status` before `git add -A`.
- Remote: `origin` = https://github.com/tvangaalen/MasterVolt-YMS (**public**, `main` plus the `v*` tags). Push after every finished change (see the standing deploy-and-push instruction below); never force-push or rewrite pushed history. Everything committed is public, so re-check `git status` and the staged diff for keys, certificates, settings, hardware serials and personal data before every push.
- GitHub CLI (`gh`, per-user winget install; path `C:\Users\TvanG\AppData\Local\Microsoft\WinGet\Packages\GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\gh.exe`) is signed in as `tvangaalen`. This repo's local `credential.helper` points at it, so plain `git push` works from the project folder. Auth changes and account settings are the user's to make.
- License: MIT (`LICENSE`, copyright holder "TvanG"). Do not change the license or copyright holder without asking.
- **Keep the user's real email out of git.** Commits use the GitHub no-reply address (set as this repo's local `user.email`); never put the user's personal or company email address, or other personal data, in commits, files or tags.
- The live folder `C:\Temp\mastervoltproject` is **not** a git repository. Commit in the source folder first, then deploy the changed files.

## Two folders: source vs live

- `G:\My Drive\Claude\MasterVolt-YMS` (Google Drive) is the **source** copy. Do not run the server from it: it holds only a stale snapshot of runtime state, and a large SQLite history should not live on Drive.
- When Google Drive (`G:`) is not available, work in the independent clone (a normal git checkout of the GitHub repository). Commit and push from there; the Drive copy and the external `.gitrepos` repository catch up later by pulling from GitHub, so never edit the same file in two copies at once.
- `C:\Temp\mastervoltproject` is the **live** folder the boat PC runs from. It holds the real `user_settings.json` (31-day retention and the configured Float thresholds), `data/history.sqlite3` (~1 GB), `backups/`, `logs/`, `certs/*-key.pem` and `data/bms_mos_encoding.json`.
- To deploy: copy only the changed code files (for a code change the `mastervolt/` package, `static/`, `docs/manual.html` and `app.py`; everything else is untouched) from source to live, after backing up the live versions to a sibling folder such as `C:\Temp\mastervoltproject_pre_<version>_<timestamp>`. Never overwrite live runtime state, and never run with a settings file that lacks `history_retention_days` against the live database (missing means the 7-day default and pruning). The 2.0.0 restructure replaced the flat modules (`masterbus_*.py`, `daly_*.py`, `bluetooth_coordinator.py`, `ble_events.py`, `house_soc.py`, `history_service.py`, `report_service.py`, `battery_health.py`) by the `mastervolt` package: they were moved out of the live folder into the backup folder so a stale copy can never be imported.
- **The live folder may also be edited directly by other tools and sessions.** Never deploy blindly. Immediately before copying, compare every file you are about to overwrite with the last deployed commit (`git show <commit>:<file>`, ignoring line endings). If a live file differs, **stop**: import the live changes first (branch from the last deployed commit, commit the live files, merge into `main`, resolve conflicts, re-apply your work), and only then deploy. Copy only the files you changed, and never touch live runtime files.
- **Always deploy and push right away (standing instruction from the user, 26 Sep 2026).** When a change is finished and its tests pass, commit it, deploy it to the live server and push it to GitHub in the same turn, without asking first. The safety steps still apply every time: (1) compare the live files with the last deployed commit and stop if they differ; (2) back up what you overwrite; (3) if the change needs a Python restart, run the read-only pre-checks below first and restart, otherwise deploy frontend files without a restart; (4) run the secrets/personal-data guard before pushing; (5) verify the live server and GitHub afterwards and report what you saw.
- Before restarting, read-only check `GET /api/bms` (`control_status.busy` false) and `GET /api/energy` (`high_soc_float_policy.float_latched` false); a restart pauses server-side Float protection.
- `start_mastervolt_server.cmd` is the normal launcher (visible console, the user's preference since 2 Oct 2026; it passes `--timeout-graceful-shutdown 5`); it regenerates the server certificate for the current LAN address. A process created with `Invoke-CimMethod Win32_Process Create` runs in the user's own session with a real window, so `cmd.exe /c "C:\Temp\mastervoltproject\start_mastervolt_server.cmd"` started that way gives the visible console outside the tool's process tree.
- **Start the server outside the tool session's process tree and with a graceful-shutdown limit.** Servers started with `Start-Process` from the PowerShell tool disappeared twice shortly after a session ended (no error in the logs, machine not rebooted), and a plain `uvicorn` waits forever for an open browser keep-alive connection when it is told to shut down: it then stops listening but never exits (seen 2 Oct 2026, Chrome held one connection). A server that "does not respond" while its process is alive: check `netstat -ano | findstr :8000` - no LISTENING line means it is stuck shutting down; kill it and start it again.

## Known quirks

- `run.ps1` binds `0.0.0.0` over plain HTTP; `start_mastervolt_server.cmd` is the HTTPS, private-address launcher.
- `docs/VERIFIED_FIELD_MAP.txt` is the v0.17 map; `docs/hardware-notes.md` lists what changed since (e.g. Solar voltage is now field 6, House SOC is the DALY average).
- Alternator ON currently only clears Stop Charge (field 39 = 0 + commit 40) and expects the Alpha Pro to resume by itself — no Bulk request is sent.
- Tools in the PowerShell tool of this environment: a command that contains the word `del`, `rm` or `rmdir` as a bare word can be refused as a "remove on a system path" even inside a script string; delete files from a Python script instead.
