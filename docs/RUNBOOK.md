# Drifter Boat Systems — runbook

How to run, check, update and recover the boat PC's systems. For what the app shows, see the user manual (System →
*Manual* in the app, or [MANUAL.md](MANUAL.md)); for how the code is built, [DEVELOPER.md](DEVELOPER.md).

All times are 24-hour. Paths are the boat PC's.

## 1. What runs where

| Part | Where | Address |
|---|---|---|
| **Drifter service** (`drifterd.py`, Windows service *Drifter*, "Drifter Boat Systems") | `C:\Drifter` | control API 127.0.0.1:8099 |
| Gateway and app (`drifter.py`, `web/`) | `C:\Drifter` | **https://192.168.1.166:8100/** (the only address on the LAN) |
| Energy (MasterVolt) | `C:\Drifter\modules\energy` | 127.0.0.1:8000 |
| Anchor watch | `C:\Drifter\modules\anchor` | 127.0.0.1:8766; network GPS (NMEA) on 192.168.1.166:10110 |
| BoatGuard | `C:\Drifter\modules\guard` | 127.0.0.1:8095 |
| Washer controller | `C:\Drifter\modules\washer` | 127.0.0.1:8080 |

- `C:\Drifter` is a git clone of the public repository; never edit files there by hand (section 5).
- Runtime files live in `C:\DrifterData\<module>`: settings, keys, the anchor and its track, the MasterVolt history
  (`energy\data\history.sqlite3`, about 1.7 GB), logs. The gateway keeps `config.json`, `certs\` and `logs\` in `C:\Drifter`.
- The **Mastervolt Local CA** is `C:\Drifter\modules\energy\certs`. Every phone and tablet trusts it; the app's certificate
  comes from it. Never delete or recreate it: every device would have to be set up again.
- The service starts at boot (delayed), whether anybody is logged on or not, runs every server as its own child process,
  restarts a server that stops (after 30 s) and is restarted by Windows if it crashes itself. It has no desktop: no windows,
  no sound on the PC. Output goes to `<data>\logs\<module>.console.log`; its own log is `C:\DrifterData\logs\drifterd.log`.
- Remote access is UniFi Teleport (VPN into the boat LAN). Never port-forward or tunnel anything: the app has no login.

## 2. Every day

- **The app:** System page — every system *running*, health ok.
- **One command** on the PC checks everything in about a second (read-only):

  ```powershell
  py -3.12 C:\Drifter\tools\verify_live.py            # or: ... verify_live.py energy anchor
  ```

  It checks per module: `/health` and version, a 403 without the token, the supervisor's and the gateway's view, and the
  essentials (energy: 3 BMS units, no BMS control busy, Float not latched; anchor: Orca Core, NMEA, Pushover, still-alive,
  no alarm; guard: router and camera; washer: status). It waits up to `--wait` seconds (default 240) for what can still
  come right after a restart. Exit code = number of failed checks.

## 3. Starting, stopping, restarting

| To | Do |
|---|---|
| Start everything (after *Switch all systems off*, or if the service stopped) | desktop icon **Drifter Boat Systems** (`start_all.ps1`), or `sc.exe start Drifter` |
| Restart one module | app → System → *Restart* (asks first; refused while a BMS control runs, Float is latched, or the anchor watch has an alarm) |
| Restart the gateway | System → *Restart* is not offered for it; from the PC: `POST /api/supervisor/restart {"module": "gateway"}` (below) |
| Stop everything | app → System → *Switch all systems off* (default *Leave on*). Switches, chargers and the camera stay as they are. |
| Restart the service (needed after a change to `drifterd.py`, `supervisor.py` or `common/proc.py`) | `Restart-Service Drifter` — restarts **every** module: check first that the anchor is not set or has no alarm, and that no BMS control runs |
| Keep a module stopped | create the empty file `C:\DrifterData\hold\<module>` (energy, anchor, guard, washer); delete it to release |

Restart through the gateway from a shell on the PC (the same pre-checks as the app):

```powershell
curl.exe -sk -X POST -H "Content-Type: application/json" -H "X-Drifter-Request: 1" -d '{\"module\":\"energy\"}' https://192.168.1.166:8100/api/supervisor/restart
```

After a restart: MasterVolt answers within about 30 s and has its three BMS units back after about 2 minutes; Float
protection is paused until then. The anchor watch is back within about 30 s.

## 4. Logs

- App → System → *Show log* per module, *Service log* for drifterd.
- Files: `C:\DrifterData\<module>\logs\<module>.console.log`, `C:\DrifterData\logs\drifterd.log`,
  `C:\Drifter\logs\gateway.console.log`; MasterVolt also `C:\DrifterData\energy\logs\`.

## 5. Updating (deploy)

Changes are made and tested in the development checkout, committed and pushed to GitHub (CI runs there). `tools\ship.py`
does all of it in one go (`change "Summary"`, or `deploy` for what is already pushed): the steps below, restarting only what
needs it, and it prints the service restart or environment rebuild it never does itself. By hand, on the boat PC:

1. `cd C:\Drifter; git pull --ff-only`. If git refuses because of a local change, look at it first (`git diff`); a file
   that only differs in line endings can be restored with `git checkout -- <file>`.
2. New Python packages (a change to `pyproject.toml`/`uv.lock`): `py -3.12 tools\sync_envs.py --into .venv-next <module>`;
   the next restart of that module puts the new environment in place.
3. Restart only what changed (section 3). A change to `web/` only needs no restart (the files are read per request);
   home-screen apps load it when they are closed and opened again.
4. `py -3.12 tools\verify_live.py` and look at the app.

A changed address of a module (`config.json` → `modules.<name>.url`) needs a gateway restart.

## 6. Back-up of the keys and tokens

Only on request: System → **Backup keys and tokens** copies the keys that cannot be made again without the services
themselves — `anchor\pushover.json`, `anchor\nfl.json`, `guard\pushover.json`, `guard\ezviz_token.json`,
`washer\viomi_config.json` (the list is `backup.files` in `modules.json`) — to **`C:\DrifterBackups`**, in the
same folders as in `C:\DrifterData`, replacing the previous copy. Nothing runs on a schedule, and positions, the track
and the MasterVolt history are not copied (the user's choice). Press it after a key changed (a new EZVIZ login, new
Pushover or noforeignland.com keys). The System page says when it last copied them. By hand on the PC:
`py -3.12 C:\Drifter\tools\backup.py`.

- Copy to Google Drive: add `C:\DrifterBackups` once in **Google Drive for desktop** → Settings → *My Computer* →
  *Add folder*; it is then copied whenever you are logged on.
- **Restore** a key file: copy it from `C:\DrifterBackups\<module>\` to `C:\DrifterData\<module>\`, then *Restart* that
  module: it reads its keys at start. If the key itself expired (EZVIZ session, Pushover keys), make a new one instead:
  in `C:\Drifter\modules\guard`, `.venv\Scripts\python.exe -m guard login` or `-m guard pushover`; for the others the
  module's `*.example.json` shows the format.

## 6a. Alerts

The gateway pushes a message (Pushover) when a system has been down for 5 minutes, and when it is back. It needs the keys in
`C:\DrifterData\gateway\pushover.json`: `{"token": "<app token>", "user": "<user key>"}` (an application token from
pushover.net — a new application *Drifter*, or the one BoatGuard uses — and your user key), then restart the gateway.
System → Alerts shows whether it is ready and has *Send test*. It never restarts or commands anything.

## 7. Phones and tablets

- Install the app: Safari → https://192.168.1.166:8100/ → Share → *Add to Home Screen*.
- A new device must trust the Mastervolt Local CA once: on the PC run
  `C:\Drifter\modules\energy\install_iphone_certificate.cmd`, open the address it shows in Safari on the device, install
  the profile (Settings → General → VPN & Device Management) and enable full trust (Settings → General → About →
  Certificate Trust Settings). It serves only the public CA certificate and stops with Ctrl+C.

## 8. When something is wrong

| Symptom | Look at | Usually |
|---|---|---|
| App does not open | is the service running (`sc.exe query Drifter`)? `C:\Drifter\logs\gateway.console.log` | desktop icon; if the PC's address changed, `config.json` `bind` and a new certificate (`setup_https.ps1`) |
| A system shows *Not reachable* | System page state; its log | it restarts by itself within a minute; otherwise *Restart* |
| *not answering* on the System page | the module's log | display only; *Restart* if it stays |
| BMS units missing after a restart | wait 2–3 minutes | Bluetooth reconnects by itself; Batteries → Bluetooth diagnostics |
| Service in *Start pending* for minutes | `C:\DrifterData\logs\drifterd.log` | `sc.exe stop Drifter`, then start; `tools\install_service.ps1 -Status` |
| A push "Drifter: <system> down" | System page; that system's log | it is started again automatically; *Restart* if it stays down |
| Everything gone after a Windows update | `sc.exe query Drifter`, the service's log | the service starts delayed at boot: give it 4 minutes |

## 9. Rebuilding the PC (or a new one)

1. Install Git and the python.org **Python 3.12** (never the Microsoft Store Python), then `py -3.12 -m pip install --user uv`.
2. `git clone https://github.com/tvangaalen/DrifterBoatSystems C:\Drifter`, then `py -3.12 tools\sync_envs.py`.
3. Put back `C:\DrifterData` (from the old disk if possible: settings, the anchor, the history) and the key files from
   `C:\DrifterBackups` (section 6). Put back `C:\Drifter\modules\energy\certs` (the Mastervolt Local CA) from the old disk;
   without it every phone needs the new CA (section 7) and `setup_local_https.ps1` makes a new one.
4. `config.json` from `config.example.json` (bind = this PC's LAN address, `supervise: true`), then `setup_https.ps1`
   (the app's certificate from the CA).
5. In an **elevated** PowerShell in `C:\Drifter`: `powershell -NoProfile -ExecutionPolicy Bypass -File
   tools\install_service.ps1` (asks for your Windows password: the service runs as your account), then
   `tools\create_shortcut.ps1` for the desktop icon and `add_firewall_rule.cmd` (the app, TCP 8100, Private profile; network GPS
   on 10110 needs Python allowed on the Private profile, which Windows asks the first time).
6. `py -3.12 tools\verify_live.py`.
