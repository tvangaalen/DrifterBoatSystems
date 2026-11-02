"""AIS targets near the boat: the Core's own receiver first, internet AIS (aisstream.io) second."""
import asyncio, json, re, threading, time
from datetime import datetime, timezone
from pathlib import Path

import websockets

from orca_reader import KN, RAD

from anchor.geo import dist_bearing_m, num
from anchor.settings import AIS_MAX_AGE_S, AIS_RANGE_M


def read_ais(ais, now, lat, lon, own_mmsi="", near_us=None, internet=None):
    """AIS targets within AIS_RANGE_M, from the Core's own (local) AIS and, optionally, internet AIS.

    My MMSI is dropped before anything else, so it can never be shown. The local receiver always has priority: an
    internet report is only used for a ship the local receiver has no current position for (none, or older than
    AIS_MAX_AGE_S). `internet` is a list of InternetAIS records (degrees, knots, metres, unix time "t").
    With no MMSI set, targets within 10 m of our GPS are taken to be ourselves; they are added to near_us (if given)
    so the page can offer to save one as My MMSI."""
    targets = {}
    for k, (v, t) in ais.items():
        parts = k.split(".")                           # ais.x.<mmsi>.position.<field>
        if len(parts) < 5 or (own_mmsi and parts[2] == own_mmsi): continue
        tg = targets.setdefault(parts[2], {"mmsi": parts[2], "age": 1e9}); tg[parts[-1]] = v; tg["age"] = min(tg["age"], now - t)
    recs = {}
    for tg in targets.values():
        if not (num(tg.get("latitude")) and num(tg.get("longitude"))): continue
        recs[tg["mmsi"]] = {"mmsi": tg["mmsi"], "name": str(tg.get("name") or "").strip(), "lat": tg["latitude"], "lon": tg["longitude"],
                            "length": tg.get("length") if num(tg.get("length")) else None,
                            "heading": round(tg["headingTrue"] * RAD % 360) if num(tg.get("headingTrue")) and tg["headingTrue"] < 6.3 else None,
                            "cog": round(tg["COG"] * RAD % 360) if num(tg.get("COG")) else None,
                            "sog": round(tg["SOG"] * KN, 1) if num(tg.get("SOG")) else None, "age": tg["age"], "src": "local"}
    for tg in internet or ():
        m = tg["mmsi"]
        if (own_mmsi and m == own_mmsi) or not (num(tg.get("lat")) and num(tg.get("lon"))): continue
        loc = recs.get(m)
        if loc and loc["age"] <= AIS_MAX_AGE_S: continue          # the local receiver always has priority
        recs[m] = {"mmsi": m, "name": tg.get("name") or (loc or {}).get("name", ""), "lat": tg["lat"], "lon": tg["lon"],
                   "length": tg.get("length") or (loc or {}).get("length"), "heading": tg.get("heading"), "cog": tg.get("cog"),
                   "sog": tg.get("sog"), "age": max(0.0, now - tg["t"]), "src": "internet"}
    out = []
    for r in recs.values():
        if lat is None: continue
        d, b = dist_bearing_m(lat, lon, r["lat"], r["lon"])
        if d > AIS_RANGE_M or r["age"] > AIS_MAX_AGE_S: continue
        if not own_mmsi and d < 10:
            if near_us is not None: near_us.append({"mmsi": r["mmsi"], "name": r["name"], "dist": round(d, 1)})
            continue
        out.append({**r, "dist": round(d, 1), "bearing": round(b), "age": round(r["age"])})
    return sorted(out, key=lambda x: x["dist"])


class InternetAIS:
    """AIS targets around the boat from aisstream.io (https://aisstream.io/documentation), as an addition to the
    Core's own AIS receiver, which always has priority (see read_ais).

    One WebSocket, subscribed to a box of BOX_DEG around the boat; it is re-opened with a new box when the boat has
    moved more than MOVE_M from the box centre. The API key comes from a local file that is never committed:
    {"api_key": "..."}. Only the key and the box are sent; nothing about the boat itself.
    """
    URL = "wss://stream.aisstream.io/v0/stream"
    BOX_DEG = 0.03                   # half size of the box (about 3 km north-south)
    MOVE_M = 1500
    TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"]
    POSITION = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}

    def __init__(self, cfg_file, center, enabled, on_event=None):
        self.cfg_file, self.center, self.enabled = Path(cfg_file), center, enabled      # center() -> (lat, lon) or None
        self.on_event = on_event or (lambda text, kind: None)
        self.lock = threading.Lock(); self.targets = {}                                  # mmsi -> record
        self.cfg = None; self.connected = False; self.last_message = None; self.last_error = None
        self.box_center = None; self.kick = False; self.logged_error = None
        self.reload()

    def reload(self):
        try: d = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        except FileNotFoundError: self.cfg = None; return f"{self.cfg_file.name} not found"
        except Exception as e: self.cfg = None; return f"{self.cfg_file.name}: {type(e).__name__}: {e}"
        key = str(d.get("api_key", "")).strip()
        if any(re.fullmatch(r"[A-Za-z0-9_-]{20,100}", str(k)) for k in d):
            self.cfg = None; return f"{self.cfg_file.name}: the key was pasted in place of the field name; keep \"api_key\" and put the key after the colon"
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", key):
            self.cfg = None; return f"{self.cfg_file.name}: api_key must be the API key from aisstream.io (letters and digits)"
        self.cfg = {"api_key": key}; self.kick = True; return None

    @property
    def configured(self): return self.cfg is not None

    def snapshot(self, now=None):
        now = now or time.time()
        with self.lock:
            for m in [m for m, t in self.targets.items() if now - t.get("t", 0) > AIS_MAX_AGE_S]: del self.targets[m]
            return [dict(t) for t in self.targets.values() if "lat" in t]

    @staticmethod
    def parse_time(text, now):
        try: t = datetime.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError: return now
        return min(t, now)

    def handle(self, m, now=None):
        """Folds one aisstream.io message into the targets."""
        now = now or time.time()
        if m.get("error"): self.last_error = f"aisstream.io: {m['error']}"; return
        md = m.get("MetaData") or {}; mmsi = str(md.get("MMSI") or "")
        typ = m.get("MessageType"); body = (m.get("Message") or {}).get(typ) or {}
        if not (mmsi.isdigit() and len(mmsi) == 9): return
        with self.lock:
            tg = self.targets.setdefault(mmsi, {"mmsi": mmsi})
            name = str(md.get("ShipName") or "").strip()
            if name: tg["name"] = name
            if typ in self.POSITION:
                la, lo = body.get("Latitude", md.get("latitude")), body.get("Longitude", md.get("longitude"))
                if not (num(la) and num(lo) and -90 <= la <= 90 and -180 <= lo <= 180): return
                tg.update(lat=la, lon=lo, t=self.parse_time(md.get("time_utc"), now),
                          sog=round(body["Sog"], 1) if num(body.get("Sog")) and body["Sog"] < 102.3 else None,
                          cog=round(body["Cog"]) % 360 if num(body.get("Cog")) and body["Cog"] < 360 else None,
                          heading=round(body["TrueHeading"]) if num(body.get("TrueHeading")) and body["TrueHeading"] < 360 else None)
            else:
                static = body.get("ReportB") or body if typ == "StaticDataReport" else body
                if typ == "StaticDataReport" and (body.get("ReportA") or {}).get("Name"): tg["name"] = str(body["ReportA"]["Name"]).strip()
                elif str(static.get("Name") or "").strip(): tg["name"] = str(static["Name"]).strip()
                dim = static.get("Dimension") or {}
                length = (dim.get("A") or 0) + (dim.get("B") or 0)
                if num(length) and 0 < length < 500: tg["length"] = length
        self.last_message = now

    def box(self, lat, lon):
        return [[round(lat - self.BOX_DEG, 4), round(lon - self.BOX_DEG * 1.5, 4)], [round(lat + self.BOX_DEG, 4), round(lon + self.BOX_DEG * 1.5, 4)]]

    async def run(self):
        delay = 5
        while True:
            c = self.center()
            if not (self.configured and self.enabled() and c):
                self.connected = False; await asyncio.sleep(5)
                if not self.configured: self.reload()                  # pick up a key file added later
                continue
            self.kick = False; got = False
            try:
                async with websockets.connect(self.URL, open_timeout=15, ping_interval=30, ping_timeout=30, max_size=2**20) as ws:
                    await ws.send(json.dumps({"APIKey": self.cfg["api_key"], "BoundingBoxes": [self.box(*c)], "FilterMessageTypes": self.TYPES}))
                    self.box_center = c; self.connected = True
                    while not self.kick and self.enabled():
                        try: raw = await asyncio.wait_for(ws.recv(), 30)
                        except asyncio.TimeoutError: raw = None
                        if raw is not None:
                            m = json.loads(raw)
                            if m.get("error"):                         # refused (bad key): do not hammer the service
                                self.last_error = f"aisstream.io: {m['error']}"; break
                            # only an error in THIS connection counts: a "connection closed" left over from the
                            # previous one must not break off the new connection (it did until 1.5.1)
                            self.handle(m); got = True; self.last_error = None; delay = 5
                            if self.logged_error:
                                self.on_event("Internet AIS: receiving again", "ok"); self.logged_error = None
                        now_c = self.center()
                        if now_c and dist_bearing_m(*self.box_center, *now_c)[0] > self.MOVE_M: break   # new box around the boat
            except asyncio.CancelledError: raise
            except websockets.ConnectionClosed as e:
                # aisstream.io drops the connection straight after a subscription it does not accept (bad API key)
                self.last_error = ("aisstream.io closed the connection right after subscribing: API key not accepted?"
                                   if self.connected and not got else f"connection closed: {e}")
            except Exception as e: self.last_error = f"{type(e).__name__}: {e}"
            refused = bool(self.last_error) and self.last_error.startswith("aisstream.io")
            if self.last_error and self.last_error != self.logged_error:
                self.on_event(f"Internet AIS: {self.last_error}", "warn"); self.logged_error = self.last_error
            elif not self.last_error and self.logged_error:
                self.on_event("Internet AIS: receiving again", "ok"); self.logged_error = None
            self.connected = False
            await asyncio.sleep(300 if refused else delay)
            delay = 5 if got else min(delay * 2, 120)
