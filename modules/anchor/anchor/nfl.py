"""noforeignland.com boat tracking: uploads only points of the watch's own track, from its own thread."""
import json, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from anchor.geo import dist_bearing_m
from anchor.settings import VERSION, log


# ---------------------------------------------------------------- noforeignland.com boat tracking


class NoForeignLand:
    """Sends the boat's track to noforeignland.com (Boat tracking), so the boat's position there follows the boat.

    Same API as NFL's own Signal K plugin (github.com/noforeignland/nfl-signalk): a form POST with timestamp, track
    ([[ms, lat, lon], ...]) and boatApiKey, plus an integration key in the X-NFL-API-Key header. That plugin's
    built-in key must not be reused: NFL hands out a key per integration (ask support@noforeignland.com; privacy: ok, NFL's public address).
    Config, a local file that is never committed:
    {"boat_api_key": "<Account > Settings > Boat tracking > API Key>", "api_key": "<integration key from NFL>"}.

    Points come from the watch's own track, so a frozen GPS never gets in. They are thinned like the plugin does: a point
    goes in only when the boat moved MIN_MOVE_M from the previous one and at least MIN_GAP_S later. New points go up as
    one track every UPLOAD_EVERY_S; while the internet is down they wait (as long as the track keeps them, track_hours)
    and go up together later. At anchor nothing moves, so once per KEEPALIVE_S the current position is sent anyway to
    keep the boat active on the website. What was sent last is kept in the state file, so a restart sends nothing twice.
    When the anchor drops (setting nfl_on_anchor) the waiting track goes up straight away, ending at the boat's current
    position even when it is closer than MIN_MOVE_M to the last point, so the anchorage shows on the website. This also
    works with the continuous upload (nfl_tracking) switched off.
    """
    URL = "https://www.noforeignland.com/home/api/v1/boat/tracking/track"
    MIN_MOVE_M = 80
    MIN_GAP_S = 60
    UPLOAD_EVERY_S = 600
    KEEPALIVE_S = 86400
    RETRY_S = 300
    FRESH_S = 60        # the keepalive only sends a position younger than this

    def __init__(self, cfg_file, points, enabled, sent=None, on_event=None, start=True):
        self.cfg_file, self.points, self.enabled = Path(cfg_file), points, enabled   # callables: track [[t, lat, lon], ...], on/off
        self.on_event = on_event or (lambda text, kind: None)
        self.cfg = None; self.sent = sent          # {"t", "lat", "lon"}: last point NFL accepted
        self.last_ok = self.last_error = None; self.last_count = 0
        self.next_try = 0.0; self.failing = False
        self.anchor_drop = False           # anchor just dropped: send now, up to the current position (until it got through)
        self.wake = threading.Event()
        self.reload()
        if start: threading.Thread(target=self._worker, daemon=True).start()

    def reload(self):
        """(Re)reads the config file; returns an error text, or None when it is usable."""
        try: d = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        except FileNotFoundError: self.cfg = None; return f"{self.cfg_file.name} not found"
        except Exception as e: self.cfg = None; return f"{self.cfg_file.name}: {type(e).__name__}: {e}"
        boat, key = str(d.get("boat_api_key") or "").strip(), str(d.get("api_key") or "").strip()
        if not boat: self.cfg = None; return f"{self.cfg_file.name}: boat_api_key is missing (noforeignland.com: Account > Settings > Boat tracking)"
        if not key: self.cfg = None; return f"{self.cfg_file.name}: api_key is missing (ask support@noforeignland.com for an integration key)"   # privacy: ok (NFL's public support address)
        self.cfg = {"boat_api_key": boat, "api_key": key}
        return None

    @property
    def configured(self): return self.cfg is not None

    def poke(self):
        """Send what is waiting straight away."""
        self.next_try = 0.0; self.wake.set()

    def dropped(self):
        """The anchor is down: send the track up to here straight away."""
        self.anchor_drop = True; self.poke()

    def pending(self, now):
        """The points not sent yet, thinned to MIN_MOVE_M / MIN_GAP_S; the keepalive point when nothing moved for a day."""
        pts = self.points(); ref = self.sent; out = []
        for t, lat, lon in pts:
            if ref is not None and (t - ref["t"] < self.MIN_GAP_S or dist_bearing_m(ref["lat"], ref["lon"], lat, lon)[0] < self.MIN_MOVE_M):
                continue
            ref = {"t": t, "lat": lat, "lon": lon}; out.append([t, lat, lon])
        fresh = pts and now - pts[-1][0] <= self.FRESH_S
        if self.anchor_drop and fresh and (not out or out[-1][0] != pts[-1][0]) and (self.sent is None or pts[-1][0] > self.sent["t"]):
            out.append(list(pts[-1]))       # the anchorage itself, however close to the last point
        elif not out and fresh and (self.sent is None or now - self.sent["t"] >= self.KEEPALIVE_S):
            out.append(list(pts[-1]))
        return out

    def _post(self, track):
        body = urllib.parse.urlencode({"timestamp": str(int(track[-1][0] * 1000)),
                                       "track": json.dumps([[int(t * 1000), lat, lon] for t, lat, lon in track]),
                                       "boatApiKey": self.cfg["boat_api_key"]}).encode()
        req = urllib.request.Request(self.URL, data=body, method="POST",
                                     headers={"User-Agent": f"OrcaCore2-AnchorWatch/{VERSION}", "X-NFL-API-Key": self.cfg["api_key"],
                                              "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: raw = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read(300).decode('utf-8', 'replace').strip() or e.reason}") from None
        # any 2xx means NFL stored the track: an unreadable reply must not make us send it again (duplicate track)
        try: reply = json.loads(raw)
        except ValueError: return
        if isinstance(reply, dict) and reply.get("status") not in (None, "ok"):
            raise RuntimeError(str(reply.get("message") or reply.get("status")))

    def step(self, now=None):
        """One round of the worker: upload the waiting points when due. Tests call it directly."""
        now = now or time.time()
        if not self.configured or now < self.next_try or not (self.enabled() or self.anchor_drop): return
        track = self.pending(now)
        if not track: self.anchor_drop = False; return
        self.next_try = now + self.UPLOAD_EVERY_S
        try: self._post(track)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e)
            self.next_try = now + self.RETRY_S
            if not self.failing: self.failing = True; self.on_event(f"noforeignland.com upload failed (will retry): {self.last_error}", "warn")
            return
        t, lat, lon = track[-1]; self.sent = {"t": t, "lat": lat, "lon": lon}
        self.last_ok, self.last_error, self.last_count = now, None, len(track)
        if self.anchor_drop:
            self.anchor_drop = False
            self.on_event(f"Track sent to noforeignland.com ({len(track)} point{'s' if len(track) != 1 else ''})", "info")
        if self.failing: self.failing = False; self.on_event("noforeignland.com uploads get through again", "ok")

    def _worker(self):
        while True:
            try: self.step()
            except Exception: log.exception("noforeignland step failed")
            self.wake.wait(timeout=30); self.wake.clear()
