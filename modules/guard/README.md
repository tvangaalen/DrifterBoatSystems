# BoatGuard

Arms an EZVIZ camera when your iPhone leaves the boat's Wi-Fi, and disarms it when the iPhone comes back. It runs on a Windows PC on board and can send Pushover notifications. Its page is the **BoatGuard** module of the Drifter app ([DrifterBoatSystems](https://github.com/tvangaalen/DrifterBoatSystems), `modules/guard`); since 2026-11-01 BoatGuard has no page of its own, only the API the app uses.

- **Presence:** every 30 s, BoatGuard asks the UniFi router (read-only SSH, `wlanconfig <ap> list sta`) which devices are connected to Wi-Fi. If the phone's address (`phone_macs` in `config.json`) is missing for `away_after_s`, the camera is armed.
- **Camera:** arming goes through the EZVIZ cloud (`pyezviz`), the same as the arm button in the EZVIZ app. Only a session token is stored (`ezviz_token.json`); your password is never saved.
- **Safety:** if the router can't be read, BoatGuard changes nothing. It only disarms when BoatGuard armed the camera itself, so a camera you armed by hand stays armed. A failed arm is retried on the next check.

Tested with a UniFi UDR Max 5G (Qualcomm Wi-Fi, `wlanconfig`) and an EZVIZ C3A battery camera.

## Setup

Requirements: Windows, Python 3.12+, OpenSSH client, and SSH key access to the router as root.

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.json config.json           # then fill in phone MAC, router key path and camera serial
.venv\Scripts\python.exe boatguard.py login    # once: EZVIZ e-mail, password, and the verification code if asked
.venv\Scripts\python.exe boatguard.py pushover # optional: Pushover keys (sends a test notification)
.venv\Scripts\python.exe boatguard.py status   # is the phone on board?
.venv\Scripts\python.exe boatguard.py arm      # test the camera (then: disarm)
.venv\Scripts\python.exe boatguard_self_test.py
start_boatguard.cmd                            # run the service in a console
```

To find the phone's address, run `wlanconfig <ap> list sta` on the router while only the phone is connected, or look it up in the router's client list.

Logs are in `logs\boatguard.log` (24-hour timestamps). `state.json` remembers whether BoatGuard armed the camera, so a restart doesn't trigger it again.

## The page (in Drifter) and the API

While BoatGuard runs, it serves its API on **https://127.0.0.1:8095/** (localhost only: the Drifter gateway on the same PC uses it; `"web": {"host": "<private LAN address>"}` adds one LAN address on purpose). The BoatGuard page in Drifter shows:

- the current status: whether the phone is on board, the countdown to arming, what EZVIZ reports for the camera (armed, battery), and the router check;
- a **Monitoring** switch. *Off* means BoatGuard never arms the camera; it also disarms a camera BoatGuard armed. The setting is kept in `state.json` and survives a restart;
- a **Test** button: arms the camera, reads the state back, disarms it and reads it back again (about 15 s). It's refused while BoatGuard has armed the camera for real;
- **Settings:** arming delay (30–3600 s), router check interval (10–300 s, never longer than the delay), and per notification a sound and a priority. They're checked on the page and on the server, written to `config.json`, and apply at once;
- the log, newest first.

After BoatGuard arms or disarms the camera, the page shows the new state at once, marked "waiting for EZVIZ to confirm" until the EZVIZ cloud reports it too (the cloud can lag a few seconds).

API: `GET /api/status`, `/api/log?n=`; `POST` (JSON only) `/api/enabled`, `/api/settings`, `/api/notify-test`, `/api/test`. There is no password; it never listens on a public address. The port is set in `config.json` under `"web": {"port": 8095}`.

**HTTPS:** `setup_https.ps1 [-CaDir <folder>]` creates `certs\boatguard-cert.pem`/`-key.pem`, signed by a local CA (`ca-cert.pem` + `ca-key.pem` in that folder). The certificate covers localhost, the PC's name, 127.0.0.1 and its private IPv4 addresses, and is valid for 825 days (the most iOS accepts). The iPhone must trust that CA (install it as a profile, then Settings → General → About → Certificate Trust Settings). Run the script again if the PC's LAN address changes, then restart BoatGuard. Without a certificate the page falls back to plain HTTP, and the log says so.

**Firewall:** not needed any more (localhost only); the iPhone reaches BoatGuard through Drifter. `add_firewall_rule.cmd` is only for a configured `web.host`.

## Notifications (Pushover)

`boatguard.py pushover` asks for the Pushover User Key and API Token (hidden input), stores them in `pushover.json` and sends a test notification. The keys are read again for every notification, so no restart is needed. Notifications:

- **Camera armed** / **Camera disarmed**, whenever BoatGuard itself arms or disarms the camera (with the reason);
- **Left the boat, monitoring OFF**: the phone has been away for the arming delay while monitoring was off. Sent once per departure, also across restarts (`unguarded_sent` in `state.json`), and not when you switched monitoring off yourself while already away.

**Sounds:** each notification has its own Pushover sound (`"sounds"` in `config.json`; *App default* = the sound chosen in the Pushover app). The ▶ button on the page sends a sample with the selected sound and priority before you save.

**Priority:** each notification also has a Pushover priority (`"priorities"` in `config.json`; defaults: armed and disarmed *Normal*, left with monitoring off *High*):

| Priority | Effect |
|---|---|
| Lowest (-2) | No alert, only listed in the Pushover app |
| Quiet (-1) | No sound or vibration |
| Normal (0) | Sound per the iPhone's settings |
| High (1) | Also sounds during Pushover quiet hours |
| Emergency (2) | Repeats every 60 s until acknowledged in Pushover, for at most 1 hour. A ▶ test with Emergency stops after 2 minutes. |

Pushover has no volume setting per message: the iPhone's ringer volume decides. Notifications go to every device on the Pushover account.

Sending happens in the background, up to 5 tries. A failed notification never blocks arming or disarming. Results are in the log.

## Autostart

Register a scheduled task that starts BoatGuard without a window when you sign in, and restarts it if it crashes (run in PowerShell from the BoatGuard folder):

```powershell
$dir = (Get-Location).Path
$a = New-ScheduledTaskAction -Execute "$dir\.venv\Scripts\pythonw.exe" -Argument 'boatguard.py run' -WorkingDirectory $dir
$t = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName BoatGuard -Action $a -Trigger $t -Settings $s
```

Restart it after a code or `config.json` change with `Stop-ScheduledTask BoatGuard; Start-ScheduledTask BoatGuard`. To run it straight from boot, without anyone signing in: in Task Scheduler, open BoatGuard → *Run whether user is logged on or not*, and enter the Windows password when asked.

## Notes

- On iOS, Settings → Wi-Fi → (boat network) → **Private Wi-Fi Address** must stay *Off* or *Fixed*. *Rotating* changes the address, and BoatGuard would think the phone left.
- If a UniFi firmware update wipes the router's SSH key, `status` reports "router not readable" and BoatGuard changes nothing until the key is added back.
- If the EZVIZ session expires, the log shows arm errors. Run `login` again.
- `config.json`, `state.json`, `ezviz_token.json`, `pushover.json`, `certs/` and `logs/` hold personal data and keys, and are kept out of git.
