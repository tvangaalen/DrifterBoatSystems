"""BoatGuard: arm the EZVIZ camera when the owner's iPhone leaves the boat Wi-Fi, disarm it on return.

Presence comes from the UDR Max 5G's live Wi-Fi station tables (read-only SSH, `wlanconfig <ap> list sta`).
Arming goes through the EZVIZ cloud (pyezviz), using a saved session token: the password is never stored.

    py boatguard.py login     # one-time: sign in to EZVIZ (asks password and, if needed, the SMS/e-mail code)
    py boatguard.py pushover  # one-time: Pushover keys for iPhone notifications (sends a test)
    py boatguard.py status    # show which Wi-Fi clients the router sees and whether the phone is aboard
    py boatguard.py arm|disarm  # manual test of the camera
    py boatguard.py run       # the service loop, plus the API for the Drifter app (boatguard_web.py)
"""
from __future__ import annotations

import json, logging, os, re, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # the repository root: common/ (shared with the Drifter gateway)
from common import logs, pushover, timefmt  # noqa: E402
# Runtime files (settings, state, tokens, logs): next to the code, or in DRIFTER_DATA\guard when Drifter Boat Systems sets it.
DATA = Path(os.environ["DRIFTER_DATA"].strip()) / "guard" if os.environ.get("DRIFTER_DATA", "").strip() else HERE
CONFIG, STATE, TOKEN = DATA / "config.json", DATA / "state.json", DATA / "ezviz_token.json"
PUSHOVER = DATA / "pushover.json"  # {"token": app token, "user": user key}; written by `boatguard.py pushover`, never logged
# Notification events and Pushover's built-in sounds ("" = the default set in the Pushover app).
EVENTS = {"armed": "Camera armed", "disarmed": "Camera disarmed", "unguarded": "Left the boat, monitoring OFF"}
# Pushover priorities. 2 (emergency) repeats every EMERGENCY_RETRY_S until acknowledged in the app, for at most EMERGENCY_EXPIRE_S.
PRIORITIES = {-2: "Lowest", -1: "Quiet", 0: "Normal", 1: "High", 2: "Emergency"}
DEFAULT_PRIORITY = {"armed": 0, "disarmed": 0, "unguarded": 1}
EMERGENCY_RETRY_S, EMERGENCY_EXPIRE_S = 60, 3600
SOUNDS = ["", "pushover", "bike", "bugle", "cashregister", "classical", "cosmic", "falling", "gamelan", "incoming",
          "intermission", "magic", "mechanical", "pianobar", "siren", "spacealarm", "tugboat", "alien", "climb",
          "persistent", "echo", "updown", "vibrate", "none"]
MAC_RE = re.compile(r"^([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.M)
# Lists every associated station on every SSID of every radio; the UDR uses Qualcomm `wlanconfig`.
STATION_CMD = 'for i in $(ls /sys/class/net | grep -E "^wifi[0-9]+ap[0-9]+$"); do wlanconfig $i list sta 2>/dev/null; done; echo BOATGUARD_OK'

log = logging.getLogger("boatguard")


def load_json(p: Path, default):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError: return default


def save_json(p: Path, data) -> None:
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=2), encoding="utf-8"); tmp.replace(p)


def dur_text(s: float) -> str:
    s = int(s); h, m = divmod(s // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min" if m else f"{s} s"


class RouterError(Exception):
    """The router's Wi-Fi clients could not be read. kind: "unreachable" (offline or restarting),
    "auth" (the router refused the SSH key: needs action) or "other"."""
    def __init__(self, kind: str, detail: str):
        super().__init__(detail); self.kind, self.detail = kind, detail


UNREACHABLE = ("connection refused", "timed out", "no route to host", "network is unreachable", "could not resolve",
               "connection reset", "connection closed", "broken pipe", "host is down")
AUTH = ("permission denied", "host key verification failed", "remote host identification has changed", "no such file")


def classify_ssh_error(stderr: str) -> RouterError:
    lines = [l for l in stderr.splitlines() if l.strip() and "post-quantum" not in l and "openssh.com/pq" not in l
             and "upgraded" not in l.lower() and "vulnerable" not in l.lower()]
    detail = lines[-1].strip() if lines else "no output"
    low = stderr.lower()
    if any(s in low for s in AUTH): return RouterError("auth", detail)
    if any(s in low for s in UNREACHABLE) or not lines: return RouterError("unreachable", detail)
    return RouterError("other", detail)


def router_stations(cfg: dict) -> set[str]:
    """MAC addresses currently associated to the router's Wi-Fi. Raises RouterError if the router can't be read."""
    r = cfg["router"]
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", f"ConnectTimeout={r.get('timeout_s', 10)}",
           "-i", str(Path(r["key"]).expanduser()), f"{r['user']}@{r['host']}", STATION_CMD]
    try: res = subprocess.run(cmd, capture_output=True, text=True, timeout=r.get("timeout_s", 10) + 20,
                              stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console pop-up under pythonw
    except subprocess.TimeoutExpired: raise RouterError("unreachable", "no answer within the time limit") from None
    except OSError as e: raise RouterError("other", f"ssh could not start: {e}") from None
    if "BOATGUARD_OK" not in res.stdout: raise classify_ssh_error(res.stderr)
    return {m.lower() for m in MAC_RE.findall(res.stdout)}


class Camera:
    def __init__(self, cfg: dict):
        self.cfg = cfg["ezviz"]
        self.lock = threading.Lock()  # one EZVIZ session refresh at a time (the refresh id rotates)

    def _client(self):
        from pyezviz.client import EzvizClient
        tok = load_json(TOKEN, None)
        if not tok: raise RuntimeError("no EZVIZ session: run `py boatguard.py login` first")
        c = EzvizClient(token=tok, url=self.cfg.get("region_url", "apiieu.ezvizlife.com"))
        c.login()  # refreshes the session from the saved refresh id; no password needed
        save_json(TOKEN, c._token)
        return c

    def set_armed(self, armed: bool) -> None:
        with self.lock:
            c = self._client()
            try: c.set_camera_defence(self.cfg["camera_serial"], 1 if armed else 0)
            finally: save_json(TOKEN, c._token); c.close_session()

    def status(self) -> dict:
        """What the EZVIZ cloud reports for the camera: armed (alarm_notify), battery %, online."""
        with self.lock:
            c = self._client()
            try: d = c.load_cameras()[self.cfg["camera_serial"]]
            finally: save_json(TOKEN, c._token); c.close_session()
        return {"armed": bool(d.get("alarm_notify")), "battery": d.get("battery_level"), "online": d.get("status") == 1}


class Pushover:
    """iPhone notifications via the Pushover API. Sent from a background thread with retries, so a slow or
    unreachable internet connection never holds up the poll loop or the camera."""
    def __init__(self, path: Path = PUSHOVER):
        self.path = path

    @property
    def configured(self) -> bool:
        k = load_json(self.path, None) or {}
        return bool(k.get("token") and k.get("user"))

    def send(self, title: str, message: str, priority: int = 0, url: str | None = None, wait: bool = False,
             sound: str | None = None, expire: int | None = None) -> bool | None:
        k = load_json(self.path, None) or {}
        if not (k.get("token") and k.get("user")): return None
        data = {"token": k["token"], "user": k["user"], "title": title, "message": message, "priority": priority,
                "timestamp": int(time.time())}  # shows when it happened, even if delivery was delayed
        if url: data.update(url=url, url_title="Open BoatGuard")
        if sound: data["sound"] = sound  # empty: the sound chosen in the Pushover app
        if priority == 2: data.update(retry=EMERGENCY_RETRY_S, expire=expire or EMERGENCY_EXPIRE_S)  # required by Pushover
        def post() -> bool:
            for attempt in range(5):
                try: pushover.post("messages.json", data, "BoatGuard"); log.info("notification sent: %s", title); return True
                except pushover.PushoverError as e:
                    if e.code < 500:  # wrong key/token: retrying won't help
                        log.error("notification rejected by Pushover (%d): %s", e.code, e.detail); return False
                    err = e
                except Exception as e: err = e
                time.sleep(min(60, 5 * 2 ** attempt))
            log.error("notification not sent after 5 tries: %s (%s)", title, err); return False

        if wait: return post()
        threading.Thread(target=post, daemon=True, name="pushover").start(); return None


class Guard:
    """Presence state machine. `armed_by_us` makes sure we only disarm what BoatGuard armed itself."""

    def __init__(self, cfg: dict, camera, stations=router_stations, clock=time.time, state_path: Path = STATE, notifier=None):
        self.cfg, self.camera, self.stations, self.clock, self.state_path = cfg, camera, stations, clock, state_path
        self.notifier = notifier
        self.phones = {m.lower() for m in cfg["phone_macs"]}
        st = load_json(state_path, {})
        self.armed_by_us = st.get("armed_by_us", False)
        self.enabled = st.get("enabled", True)
        self.last_seen = st.get("last_seen") or clock()  # unknown history: give a full grace period
        self.unguarded_sent = st.get("unguarded_sent", False)  # "left the boat with monitoring off" sent for this departure
        self.present: bool | None = None
        self.router_ok: bool | None = None
        self.router_down: tuple[float, str, float] | None = None  # (since, kind, last logged) during an outage
        self.router_error: str | None = None
        self.last_poll: float | None = None
        self.test_running = False
        self.cam_status: dict | None = None
        self.cam_expect: tuple[bool, float] | None = None  # (armed, until): what BoatGuard just set, awaiting EZVIZ
        self.cam_gen = 0  # bumped on every change by BoatGuard, so an older status read is discarded
        self.lock = threading.RLock()  # the poll loop and the app's actions take turns
        self.wake = threading.Event()

    def save(self) -> None:
        save_json(self.state_path, {"armed_by_us": self.armed_by_us, "last_seen": self.last_seen, "enabled": self.enabled,
                                    "unguarded_sent": self.unguarded_sent})

    def notify(self, event: str, message: str, priority: int | None = None, title: str | None = None,
               sound: str | None = None, **extra) -> None:
        if self.notifier is None: return
        if sound is None: sound = self.cfg.get("sounds", {}).get(event, "")
        if priority is None: priority = self.cfg.get("priorities", {}).get(event, DEFAULT_PRIORITY[event])
        try: self.notifier.send(title or EVENTS[event], message, priority=priority, sound=sound or None, **extra)
        except Exception: log.exception("notification failed")  # a notification problem must never stop the guard

    def hm(self, t: float) -> str:
        return timefmt.hm(t)

    def _apply(self, armed: bool, reason: str = "") -> bool:
        try: self.camera.set_armed(armed)
        except Exception as e:
            log.error("could not %s camera: %s (retrying next poll)", "arm" if armed else "disarm", e); return False
        self.armed_by_us = armed; self.save(); self.expect_camera(armed)
        log.info("camera %s", "ARMED" if armed else "disarmed")
        self.notify("armed" if armed else "disarmed", reason); return True

    CONFIRM_S = 90  # the EZVIZ cloud can report the old state for a while after a change

    def expect_camera(self, armed: bool) -> None:
        """Show what BoatGuard just set at once, as 'pending' until EZVIZ reports the same (or CONFIRM_S passes)."""
        now = self.clock()
        self.cam_gen += 1; self.cam_expect = (armed, now + self.CONFIRM_S)
        self.cam_status = dict(self.cam_status or {"battery": None, "online": None}, armed=armed, checked=now, error=None, pending=True)

    def tick(self) -> None:
        try:
            seen, err = self.stations(self.cfg), None
            if seen is None: err = RouterError("other", "no data")
        except RouterError as e: seen, err = None, e
        with self.lock:
            now = self.clock(); self.last_poll, self.router_ok = now, seen is not None
            self._router_log(err, now)
            if seen is None: return  # router unreadable: never arm or disarm on missing data
            if seen & self.phones:
                if self.present is not True: log.info("phone on board")
                self.present, self.last_seen, self.unguarded_sent = True, now, False; self.save()
                if self.armed_by_us and self.cfg.get("disarm_on_return", True): self._apply(False, "Phone back on board.")
                return
            gone = now - self.last_seen
            if self.present is not False: log.info("phone not on Wi-Fi; arming after %d s away", self.cfg["away_after_s"])
            self.present = False
            if gone < self.cfg["away_after_s"] or self.armed_by_us: return
            if self.enabled:
                log.info("phone gone for %d s", gone); self._apply(True, f"Phone off the boat Wi-Fi since {self.hm(self.last_seen)}.")
            elif not self.unguarded_sent:
                log.warning("phone gone for %d s with monitoring OFF: camera not armed", gone)
                self.unguarded_sent = True; self.save()
                self.notify("unguarded", f"Phone off the boat Wi-Fi since {self.hm(self.last_seen)}. "
                            "The camera was NOT armed. Arm it in the EZVIZ app if you want it on.")

    ROUTER_REMIND_S = 1800  # during a long outage, say it's still going on this often instead of on every poll

    def _router_log(self, err: RouterError | None, now: float) -> None:
        """One log line when the router becomes unreadable (or the reason changes), a reminder every
        ROUTER_REMIND_S, and one line when it can be read again."""
        down = self.router_down
        if err is None:
            if down: log.info("router readable again after %s", dur_text(now - down[0]))
            self.router_down = self.router_error = None; return
        self.router_error = {"auth": "router refused the SSH key", "unreachable": "router not reachable"}.get(err.kind, "router read failed")
        if down and down[1] == err.kind:
            if now - down[2] >= self.ROUTER_REMIND_S:
                log.warning("router still not readable after %s (%s); nothing changed meanwhile", dur_text(now - down[0]), err.detail)
                self.router_down = (down[0], err.kind, now)
            return
        msg = {"unreachable": "router not reachable (offline or restarting): %s. Nothing is changed until it's back",
               "auth": "router refused the SSH key: %s. The key may have been removed by a firmware update; "
                       "add it again on the router. Nothing is changed until then",
               "other": "router read failed: %s. Nothing is changed until it works again"}[err.kind]
        (log.error if err.kind == "auth" else log.warning)(msg, err.detail)
        self.router_down = (down[0] if down else now, err.kind, now)

    def set_enabled(self, on: bool) -> None:
        """Monitoring off also disarms a camera BoatGuard armed (never one armed by hand)."""
        with self.lock:
            if on == self.enabled: return
            self.enabled = on
            if not on and self.present is False: self.unguarded_sent = True  # switched off while away: no warning needed
            self.save()
            log.info("monitoring %s (app)", "ON" if on else "OFF")
            if not on and self.armed_by_us: self._apply(False, "Monitoring turned off on the BoatGuard page.")

    def test(self) -> dict:
        """Arm, read back, disarm, read back. Refused while BoatGuard has the camera armed for real."""
        with self.lock:
            if self.armed_by_us: return {"ok": False, "error": "camera is armed by BoatGuard (phone away); test not possible now"}
            self.test_running = True; log.info("test started (app)")
            res = {"ok": False}
            try:
                self.camera.set_armed(True); time.sleep(self.cfg.get("test_settle_s", 5))
                res["armed_read"] = self.camera.status()["armed"]
                self.camera.set_armed(False); time.sleep(self.cfg.get("test_settle_s", 5))
                res["disarmed_read"] = self.camera.status()["armed"]
                res["ok"] = res["armed_read"] is True and res["disarmed_read"] is False
            except Exception as e:
                res["error"] = str(e)
                try: self.camera.set_armed(False)  # never leave a test arm behind
                except Exception: log.exception("could not disarm after failed test")
            finally:
                self.test_running = False
                if res["ok"]: self.expect_camera(False)  # the test ends disarmed
                else: self.cam_gen += 1; self.cam_expect = self.cam_status = None  # unknown: read EZVIZ afresh
            if res["ok"]: log.info("test OK: armed and disarmed, both confirmed by the camera")
            else: log.error("test FAILED: %s", res.get("error") or res)
            return res

    SETTINGS = {"away_after_s": (30, 3600), "poll_s": (10, 300)}  # editable from the app: (min, max) seconds

    def update_settings(self, new: dict, config_path: Path = CONFIG) -> dict:
        """Validate and apply settings from the app, then write them to config.json (other keys untouched)."""
        vals, sounds, prios = {}, None, None
        for k, v in new.items():
            if k == "sounds":
                if not isinstance(v, dict) or not set(v) <= set(EVENTS) or any(s not in SOUNDS for s in v.values()):
                    raise ValueError("sounds must map armed/disarmed/unguarded to a Pushover sound")
                sounds = dict(self.cfg.get("sounds", {}), **v); continue
            if k == "priorities":
                if (not isinstance(v, dict) or not set(v) <= set(EVENTS)
                        or any(isinstance(p, bool) or p not in PRIORITIES for p in v.values())):
                    raise ValueError("priorities must map armed/disarmed/unguarded to -2, -1, 0, 1 or 2")
                prios = dict(self.cfg.get("priorities", {}), **{e: int(p) for e, p in v.items()}); continue
            if k not in self.SETTINGS: raise ValueError(f"unknown setting {k}")
            lo, hi = self.SETTINGS[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not lo <= v <= hi:
                raise ValueError(f"{k} must be a whole number of seconds between {lo} and {hi}")
            vals[k] = int(v)
        merged = {k: vals.get(k, self.cfg[k] if k in self.cfg else 30) for k in self.SETTINGS}
        if merged["poll_s"] > merged["away_after_s"]: raise ValueError("router check interval must not exceed the arming delay")
        with self.lock:
            changed = {k: v for k, v in vals.items() if self.cfg.get(k) != v}
            old_sounds = self.cfg.get("sounds", {})
            if sounds is not None and sounds != old_sounds: changed["sounds"] = sounds
            merged["sounds"] = changed.get("sounds", old_sounds)
            old_prios = self.cfg.get("priorities", {})
            eff = lambda d: {e: d.get(e, DEFAULT_PRIORITY[e]) for e in EVENTS}  # missing = default
            if prios is not None and eff(prios) != eff(old_prios): changed["priorities"] = prios
            merged["priorities"] = eff(changed.get("priorities", old_prios))
            if not changed: return merged
            disk = load_json(config_path, {}); disk.update(changed); save_json(config_path, disk)
            self.cfg.update(changed)
            desc = [f"{k} = {v} s" for k, v in changed.items() if k != "sounds"]
            desc += [f"sound {e} = {s or 'app default'}" for e, s in changed.get("sounds", {}).items() if old_sounds.get(e, "") != s]
            if "priorities" in changed:
                desc += [f"priority {e} = {PRIORITIES[p]}" for e, p in eff(changed["priorities"]).items() if eff(old_prios)[e] != p]
            log.info("settings changed (app): %s", ", ".join(desc))
            self.wake.set()
        return merged

    def notify_test(self, event: str, sound: str, priority: int | None = None) -> bool:
        """Send a sample of one notification with the given sound and priority, so it can be checked before saving.
        An emergency test stops after 2 minutes instead of an hour, so a test can't keep alarming."""
        if event not in EVENTS or sound not in SOUNDS: raise ValueError("unknown event or sound")
        if priority is not None and (isinstance(priority, bool) or priority not in PRIORITIES): raise ValueError("unknown priority")
        if not (self.notifier and self.notifier.configured): raise ValueError("Pushover is not set up")
        p = DEFAULT_PRIORITY[event] if priority is None else priority
        self.notify(event, f"Test: sound {sound or 'app default'}, priority {PRIORITIES[p]}. "
                    f"This is how the '{EVENTS[event]}' notification will arrive.",
                    title=f"Test: {EVENTS[event]}", sound=sound, priority=p, **({"expire": 120} if p == 2 else {}))
        return True

    def camera_status(self, max_age_s: float = 60, pending_age_s: float = 10) -> dict:
        cs, exp, now = self.cam_status, self.cam_expect, self.clock()
        pending = exp is not None and now < exp[1]
        if cs is None or now - cs["checked"] > (pending_age_s if pending else max_age_s):
            gen = self.cam_gen
            try: cs = dict(self.camera.status(), checked=self.clock(), error=None, pending=False)
            except Exception as e: cs = {"armed": None, "battery": None, "online": None, "checked": self.clock(), "error": str(e), "pending": False}
            if gen != self.cam_gen: return self.cam_status  # BoatGuard changed the camera while this read was under way
            if pending and cs["armed"] is not None and cs["armed"] != exp[0]: cs = dict(cs, armed=exp[0], pending=True)  # cloud lags
            elif exp is not None and (cs["armed"] == exp[0] or not pending): self.cam_expect = None  # confirmed, or gave up waiting
            self.cam_status = cs
        return cs

    def status(self) -> dict:
        aa = self.cfg["away_after_s"]
        arm_at = self.last_seen + aa if self.enabled and self.present is False and not self.armed_by_us else None
        return {"enabled": self.enabled, "present": self.present, "router_ok": self.router_ok, "router_error": self.router_error,
                "router_down_since": self.router_down[0] if self.router_down else None, "last_poll": self.last_poll,
                "last_seen": self.last_seen, "away_after_s": aa, "poll_s": self.cfg.get("poll_s", 30), "now": self.clock(),
                "armed_by_us": self.armed_by_us, "arm_at": arm_at, "test_running": self.test_running,
                "limits": {k: list(v) for k, v in self.SETTINGS.items()},
                "notifications": bool(self.notifier and self.notifier.configured),
                "sounds": {e: self.cfg.get("sounds", {}).get(e, "") for e in EVENTS}, "sound_options": SOUNDS, "events": EVENTS,
                "priorities": {e: self.cfg.get("priorities", {}).get(e, DEFAULT_PRIORITY[e]) for e in EVENTS},
                "priority_options": PRIORITIES, "emergency": {"retry_s": EMERGENCY_RETRY_S, "expire_s": EMERGENCY_EXPIRE_S}}

    def run(self) -> None:
        log.info("BoatGuard running: phones %s, camera %s, arm after %d s",
                 sorted(self.phones), self.cfg["ezviz"]["camera_serial"], self.cfg["away_after_s"])
        while True:
            try: self.tick()
            except Exception: log.exception("poll failed")
            self.wake.wait(self.cfg.get("poll_s", 30)); self.wake.clear()  # new settings take effect at once


def setup_logging() -> None:
    logs.setup(log, DATA / "logs" / "boatguard.log")  # pythonw (scheduled task) has no console: file only


def login(cfg: dict) -> None:
    import getpass
    from pyezviz.client import EzvizClient
    from pyezviz.exceptions import EzvizAuthVerificationCode
    acct = input("EZVIZ account (e-mail or phone): ").strip()
    c = EzvizClient(acct, getpass.getpass("EZVIZ password (not saved): "), cfg["ezviz"].get("region_url", "apiieu.ezvizlife.com"))
    try: c.login()
    except EzvizAuthVerificationCode:
        c.login(sms_code=int(input("EZVIZ sent you a verification code. Code: ").strip()))
    save_json(TOKEN, c._token)
    serial = cfg["ezviz"]["camera_serial"]
    devs = c.get_device_infos()
    print(f"Signed in. Session saved to {TOKEN.name}.")
    print(f"Camera {serial} {'found' if serial in devs else 'NOT found'} on this account ({len(devs)} device(s): {', '.join(devs)})")
    c.close_session()


def setup_pushover() -> int:
    """Ask for the Pushover keys (hidden input), save them and send a test notification."""
    import getpass
    print("Pushover: your User Key is on https://pushover.net after logging in;")
    print("the API Token comes from 'Create an Application/API Token' on that page (name it BoatGuard).")
    user = getpass.getpass("User Key (hidden): ").strip()
    token = getpass.getpass("API Token (hidden): ").strip()
    if not (user and token): print("Nothing saved."); return 1
    save_json(PUSHOVER, {"token": token, "user": user})
    ok = Pushover().send("BoatGuard test", "Notifications from BoatGuard are working.", wait=True)
    print("Test notification sent: check your iPhone." if ok else "Pushover rejected the keys or was unreachable: see logs\\boatguard.log.")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    cfg = load_json(CONFIG, None)
    if cfg is None: print("config.json missing: copy config.example.json and fill it in"); return 2
    setup_logging()
    if cmd == "login": login(cfg)
    elif cmd == "pushover": return setup_pushover()
    elif cmd == "status":
        try: seen = router_stations(cfg)
        except RouterError as e: print(f"router not readable ({e.kind}): {e.detail}"); return 1
        phones = {m.lower() for m in cfg["phone_macs"]}
        print(f"{len(seen)} Wi-Fi clients; phone {'ON BOARD' if seen & phones else 'NOT on Wi-Fi'}")
    elif cmd in ("arm", "disarm"): Camera(cfg).set_armed(cmd == "arm"); log.info("manual %s done", cmd)
    elif cmd == "run":
        g = Guard(cfg, Camera(cfg), notifier=Pushover())
        from boatguard_web import serve
        serve(g, cfg)
        g.run()
    else: print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
