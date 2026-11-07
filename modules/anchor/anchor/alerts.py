"""Push alerts through Pushover (worker thread) and the still-alive ping (dead man's switch)."""
import json, queue, re, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from common import pushover 
from anchor.settings import VERSION, log


# ---------------------------------------------------------------- push alerts (Pushover)


class Pushover:
    """Sends alarms to the phone through Pushover (https://pushover.net/api).

    Keys: the shared <DRIFTER_DATA>\\pushover.json (the System page, `shared`), else the module's own older file; both
    {"app_token": "...", "user_key": "..."}, local and never committed. Priority and sound come with each alarm (settings);
    anchor drag is always an emergency.
    Messages go out from one worker thread, in order, with retries, so a slow or absent internet link never delays the
    alarm checks. An emergency message (priority 2) repeats on the phone until it is acknowledged; its receipt is kept
    so it can be cancelled when the alarm clears, is silenced in the app, or the anchor is raised.
    """
    PRIORITY = {"drag": 2, "gps": 1, "core": 1, "depth": 1, "wind": 1, "ais": 1}   # 2 = emergency, 1 = high
    # Emergency: repeat every 30 s (Pushover's minimum) for up to 3 h (its maximum) until acknowledged in the app.
    # iOS caps one notification's sound at 30 s, so this is as close to "rings until I stop it" as a push can get.
    RETRY_S, EXPIRE_S = 30, 10800
    TEST_EXPIRE_S = 600                                                 # a forgotten test alarm stops after 10 min
    KEY_RE = pushover.KEY_RE
    BACKOFF_S = (5, 15, 45)

    def __init__(self, cfg_file, page_url=None, on_event=None, start=True, shared=None):
        self.cfg_file, self.page_url = Path(cfg_file), page_url
        self.shared = Path(shared) if shared else None
        self.on_event = on_event or (lambda text, kind: None)
        self.cfg, self.receipts, self.q = None, {}, queue.Queue()
        self.last_error = None; self.last_sent = None
        self.reload()
        if start: threading.Thread(target=self._worker, daemon=True).start()

    def reload(self):
        """(Re)reads the key file (the shared one first); returns an error text, or None when it is usable."""
        k = pushover.read_keys(self.shared)
        if k: self.cfg = {"app_token": k["token"], "user_key": k["user"]}; return None
        try: d = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        except FileNotFoundError: self.cfg = None; return f"{self.cfg_file.name} not found"
        except Exception as e: self.cfg = None; return f"{self.cfg_file.name}: {type(e).__name__}: {e}"
        tok, usr = str(d.get("app_token", "")).strip(), str(d.get("user_key", "")).strip()
        if any(self.KEY_RE.match(str(k)) for k in d):          # a key pasted over a field name instead of after it
            self.cfg = None
            return (f"{self.cfg_file.name}: a key was pasted in place of a field name; keep the names \"app_token\" and "
                    f"\"user_key\" and put each key after the colon, between quotes")
        if not (self.KEY_RE.match(tok) and self.KEY_RE.match(usr)):
            self.cfg = None; return f"{self.cfg_file.name}: app_token and user_key must each be the 30-character Pushover keys"
        self.cfg = {**d, "app_token": tok, "user_key": usr}; return None

    @property
    def configured(self): return self.cfg is not None

    def alarm(self, key, title, message, when, priority=None, sound=None):
        p = 2 if key == "drag" else min(1, self.PRIORITY.get(key, 1) if priority is None else int(priority))   # only drag is an emergency
        self.q.put(("send", key, {"title": title, "message": message, "priority": p, "timestamp": int(when), **({"sound": sound} if sound else {})}))

    def cleared(self, key, title, message, when, priority=0, sound=None):
        self.q.put(("cancel", key, None))
        self.q.put(("send", None, {"title": title, "message": message, "priority": min(1, int(priority)), "timestamp": int(when), **({"sound": sound} if sound else {})}))

    def cancel(self, key=None):
        """Stops the repeating emergency for one alarm, or (no key) for all of them."""
        self.q.put(("cancel", key or "*", None))

    def test_alarm(self):
        """A real emergency message (repeats, Critical Alert), so the phone set-up can be checked without a drag."""
        self.q.put(("send", "test", {"title": "\u2693 TEST anchor alarm", "priority": 2, "timestamp": int(time.time()),
                                     "expire": self.TEST_EXPIRE_S,
                                     "message": "Test of the anchor-drag alarm. It repeats every 30 s until you tap Acknowledge "
                                                "in Pushover (or press Stop test alarm), at most 10 minutes."}))

    def test(self):
        self.q.put(("send", None, {"title": "Anchor Watch test", "priority": 0, "timestamp": int(time.time()),
                                   "message": "Push alerts work. Anchor drag alarms arrive as emergency alerts that repeat until acknowledged."}))

    def _post(self, path, fields): return pushover.post(path, fields, f"OrcaCore2-AnchorWatch/{VERSION}")

    def _do(self, op, key, msg):
        if op == "cancel":
            for k in (list(self.receipts) if key == "*" else [key]):
                receipt = self.receipts.get(k)
                if receipt: self._post(f"receipts/{receipt}/cancel.json", {"token": self.cfg["app_token"]})
                self.receipts.pop(k, None)
            return
        fields = {"token": self.cfg["app_token"], "user": self.cfg["user_key"], **msg}
        if self.cfg.get("device"): fields["device"] = self.cfg["device"]
        if self.page_url: fields.update(url=self.page_url, url_title="Open Anchor Watch")
        if msg["priority"] == 2:
            fields.setdefault("retry", self.RETRY_S); fields.setdefault("expire", self.EXPIRE_S)
            fields.setdefault("sound", self.cfg.get("emergency_sound", "persistent"))
        elif self.cfg.get("sound"): fields.setdefault("sound", self.cfg["sound"])
        r = self._post("messages.json", fields)
        if key and r.get("receipt"): self.receipts[key] = r["receipt"]
        self.last_sent = time.time()

    def process(self, item):
        """Runs one queued item with retries (called by the worker thread; tests call it directly)."""
        op, key, msg = item
        if not self.configured: return
        for attempt in range(len(self.BACKOFF_S) + 1):
            try: self._do(op, key, msg); self.last_error = None; return
            except pushover.PushoverError as e:
                self.last_error = str(e)
                if e.code < 500: break                         # bad key or request: retrying will not help
            except Exception as e: self.last_error = f"{type(e).__name__}: {e}"
            if attempt < len(self.BACKOFF_S): time.sleep(self.BACKOFF_S[attempt])
        if op == "send": self.on_event(f"Push alert not delivered: {self.last_error}", "warn")

    def _worker(self):
        while True: self.process(self.q.get())


# ---------------------------------------------------------------- still-alive check (dead man's switch)


class StillAlive:
    """Pings an outside monitor (healthchecks.io, or any ping URL) so silence can be noticed from outside the boat.

    If the PC, this program or the boat's internet stops, the pings stop; after the still-alive interval the monitor
    alerts the phone (healthchecks.io's own Pushover integration). The PC pings every PING_EVERY_S (more often for
    short intervals), so one lost ping over a flaky link does not raise a false alarm.

    Config, a local file that is never committed: {"ping_url": "https://hc-ping.com/<uuid>", "api_key": "<optional>"}.
    With a read-write API key for a healthchecks.io ping URL, the check's period follows the setting (period =
    interval, grace = 1 min) and is paused when the interval is 0; without one, set the period on the website.
    """
    PING_EVERY_S = 300
    GRACE_S = 60
    HC_PING = re.compile(r"^https://hc-ping\.com/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$")
    HC_API = "https://healthchecks.io/api/v3/checks"

    def __init__(self, cfg_file, interval_minutes, on_event=None, start=True):
        self.cfg_file, self.interval = Path(cfg_file), interval_minutes        # interval: callable -> minutes (0 = off)
        self.on_event = on_event or (lambda text, kind: None)
        self.cfg = None; self.last_ok = self.last_error = None; self.synced = None; self.sync_note = None
        self.reported = None              # the period last set on healthchecks.io, for logging changes only
        self.next_ping = 0.0; self.next_sync_try = 0.0; self.failing = False
        self.wake = threading.Event()
        self.reload()
        if start: threading.Thread(target=self._worker, daemon=True).start()

    def reload(self):
        """(Re)reads the config file; returns an error text, or None when it is usable."""
        try: d = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        except FileNotFoundError: self.cfg = None; return f"{self.cfg_file.name} not found"
        except Exception as e: self.cfg = None; return f"{self.cfg_file.name}: {type(e).__name__}: {e}"
        url = str(d.get("ping_url", "")).strip(); u = urllib.parse.urlparse(url)
        if u.scheme != "https" or not u.netloc: self.cfg = None; return f"{self.cfg_file.name}: ping_url must be an https:// URL"
        self.cfg = {"ping_url": url, "api_key": str(d.get("api_key") or "").strip()}
        self.synced = None; self.next_sync_try = 0.0
        return None

    @property
    def configured(self): return self.cfg is not None

    def poke(self, ping_now=False):
        """Setting or config changed: re-sync the period (and optionally ping straight away)."""
        self.synced = None; self.next_sync_try = 0.0
        if ping_now: self.next_ping = 0.0
        self.wake.set()

    def ping_every(self, minutes): return max(30.0, min(self.PING_EVERY_S, minutes * 60 / 3))

    def _request(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                     headers={"User-Agent": f"OrcaCore2-AnchorWatch/{VERSION}", **(headers or {})})
        with urllib.request.urlopen(req, timeout=15) as r: return r.status, r.read()

    def _sync(self, minutes):
        m = self.HC_PING.match(self.cfg["ping_url"])
        if not (self.cfg["api_key"] and m):
            self.synced = minutes
            self.sync_note = (f"set the check's period to {minutes:g} min and grace to 1 min on the monitor's website"
                              if minutes else "pause the check on the monitor's website")
            return
        hdr = {"X-Api-Key": self.cfg["api_key"], "Content-Type": "application/json"}
        if minutes: self._request(f"{self.HC_API}/{m[1]}", json.dumps({"timeout": int(minutes * 60), "grace": self.GRACE_S}).encode(), hdr)
        else: self._request(f"{self.HC_API}/{m[1]}/pause", b"", hdr)
        self.synced = minutes; self.sync_note = None
        if self.reported is not None and minutes != self.reported:
            self.on_event("Still-alive check on healthchecks.io " + (f"set to {minutes:g} min" if minutes else "paused"), "info")
        self.reported = minutes

    def step(self, now=None):
        """One round of the worker: sync the period if needed, ping when due. Tests call it directly."""
        now = now or time.time()
        if not self.configured: return
        minutes = float(self.interval() or 0)
        if self.synced != minutes and now >= self.next_sync_try:
            try: self._sync(minutes)
            except Exception as e:
                self.sync_note = f"could not update the check: {type(e).__name__}: {e}"; self.next_sync_try = now + 300
        if minutes <= 0 or now < self.next_ping: return
        self.next_ping = now + self.ping_every(minutes)
        try:
            self._request(self.cfg["ping_url"])
            self.last_ok = now; self.last_error = None
            if self.failing: self.failing = False; self.on_event("Still-alive pings get through again", "ok")
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            if not self.failing: self.failing = True; self.on_event(f"Still-alive ping failed (will retry): {self.last_error}", "warn")

    def _worker(self):
        while True:
            try: self.step()
            except Exception: log.exception("still-alive step failed")
            self.wake.wait(timeout=5); self.wake.clear()
