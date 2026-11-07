"""The engine: its live values and engine hours from the Orca Core 2, its alarms from the YDEN-02.

Live values and engine hours: the Core's sensor stream filtered to `propulsion` (the Yanmar YD42 J1939 gateway, NMEA 2000
source 3 on 2026-11-07), read-only, the same WebSocket the anchor watch reads; nothing is ever sent to the Core. The Core
is always on, so the engine hours for a new entry come from it (the last ones are kept in the log for when the engine is off).

The alarm log (the user's choice of 2026-11-07): from the Yacht Devices YDEN-02 (`yden.py`, listen only), because only
the raw NMEA 2000 data carries the engine's own warning lights (PGN 127489 discrete status), which the Core drops. Logged:
  - every status bit the engine sets ("Check engine", "Over temperature", "Water in fuel", ...). "Low oil pressure",
    "Low system voltage" and "Charge indicator" only while the engine runs (with the ignition on and the engine still
    they are the normal lamp test); "Preheat indicator" is no alarm;
  - High coolant temperature: at or above the limit (Settings, 95 °C by default);
  - Low oil pressure: below the limit (Settings, 1.0 bar) while the engine runs.
"Runs" = rpm >= RUN_RPM for RUN_SETTLE_S, from the YDEN's own data. A condition must last HOLD_S to start an alarm and
be gone HOLD_S to end it; when the YDEN's engine data stops for LOST_S (the YDEN is often off) an open alarm ends. Each
alarm goes into the log (Maintenance page) with its start, end, engine hours and worst value.
"""
from __future__ import annotations

import asyncio, logging, math, threading, time

from common.orca import SENSORS_URL, parse_message
from enginelog.yden import YdenListener, status_names

log = logging.getLogger("enginelog")
FRESH_S, LOST_S = 10, 60
RUN_RPM, RUN_SETTLE_S, HOLD_S = 300, 30, 10
RUNNING_ONLY = {"Low oil pressure", "Low system voltage", "Charge indicator"}   # the lamp test with the engine still
NOT_ALARMS = {"Preheat indicator"}
# Core field -> (our name, conversion)
FIELDS = {"speed": ("rpm", lambda v: v), "temperature": ("temp_c", lambda v: v - 273.15), "oilPressure": ("oil_bar", lambda v: v / 1e5),
          "altenatorVoltage": ("alt_v", lambda v: v), "alternatorVoltage": ("alt_v", lambda v: v), "fuelRate": ("fuel_lph", lambda v: v),
          "totalHours": ("hours", lambda v: v / 3600), "load": ("load", lambda v: v), "boost": ("boost_bar", lambda v: v / 1e5)}


def _now_iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


class Engine:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.lock = threading.Lock()
        self.values: dict[str, tuple[object, float]] = {}   # Core field -> (raw value, unix time the Core last updated it)
        self.source: str | None = None                      # "3.0": NMEA 2000 source and engine instance
        self.connected, self.error, self.last_message = False, None, None
        self.run_since: float | None = None
        self.pending: dict[str, float] = {}                 # condition on, since
        self.clearing: dict[str, float] = {}                # open alarm whose condition is off, since
        self.open: dict[str, dict] = {}                     # key -> {"id", "worst"}
        self.yd: dict[str, tuple[object, float]] = {}       # the YDEN's engine fields -> (value, unix time received)
        self.yden: YdenListener | None = None
        self.saved_hours = (store.engine() or {}).get("hours")
        store.close_open_alarms(_now_iso(clock()), "ended when the engine log restarted")

    # ---- the stream ------------------------------------------------------------------------------------------
    def apply(self, msg: dict, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        vals, ages = msg.get("values") or {}, msg.get("values_age") or {}
        with self.lock:
            if msg.get("event_type") == "full": self.values.clear()
            for k, v in vals.items():
                parts = k.split(".")
                if len(parts) < 4 or parts[0] != "propulsion": continue
                src = f"{parts[1]}.{parts[2]}"
                if self.source is None: self.source = src
                if src != self.source: continue                # one engine: the first one seen
                self.values[".".join(parts[3:])] = (v, now - (ages.get(k) or 0) / 1000)
            for k, a in ages.items():                           # a value that did not change: only its age
                parts = k.split(".")
                if k not in vals and len(parts) >= 4 and f"{parts[1]}.{parts[2]}" == self.source:
                    f = ".".join(parts[3:])
                    if f in self.values: self.values[f] = (self.values[f][0], now - a / 1000)
            self.last_message = now

    def apply_yd(self, fields: dict, now: float | None = None) -> None:
        """Decoded NMEA 2000 engine fields from the YDEN-02 (None = not available)."""
        now = self.clock() if now is None else now
        with self.lock:
            for k, v in fields.items():
                if v is not None: self.yd[k] = (v, now)

    def _yd(self, now: float) -> dict:
        """The YDEN's fields -> (value, age in s)."""
        return {k: (v, now - t) for k, (v, t) in self.yd.items()}

    def _read(self, now: float) -> dict:
        """Our names -> (value, age in s), for the known fields with a number."""
        out = {}
        for f, (v, t) in self.values.items():
            if f in FIELDS and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                out[FIELDS[f][0]] = (FIELDS[f][1](v), now - t)
        return out

    def snapshot(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        with self.lock: r = self._read(now); extra = {f: v for f, (v, t) in self.values.items() if f not in FIELDS and now - t < LOST_S}
        rpm = r.get("rpm"); fresh = rpm is not None and rpm[1] < FRESH_S
        e = self.store.engine() or {}
        val = lambda k, d: round(r[k][0], d) if k in r and r[k][1] < LOST_S else None
        return {"connected": self.connected, "error": self.error, "fresh": fresh, "running": bool(fresh and rpm[0] >= RUN_RPM),
                "age_s": round(rpm[1], 1) if rpm else None, "source": self.source,
                "rpm": val("rpm", 0), "temp_c": val("temp_c", 1), "oil_bar": val("oil_bar", 2), "alt_v": val("alt_v", 2),
                "fuel_lph": val("fuel_lph", 1), "load": val("load", 0), "boost_bar": val("boost_bar", 2), "hours": val("hours", 2),
                "last_hours": e.get("hours"), "last_hours_at": e.get("t"), "other": extra,
                "alarms_open": sorted(self.open), "alarm_source": self.alarm_source(now)}

    def alarm_source(self, now: float) -> dict:
        """The YDEN-02 as the alarm log's source: listening, its engine data fresh, the status bits on now."""
        with self.lock: y = self._yd(now)
        rpm = y.get("rpm"); fresh = rpm is not None and rpm[1] < FRESH_S
        st = lambda k: y[k][0] if k in y and y[k][1] < FRESH_S else None
        yl = self.yden
        return {"device": "YDEN-02", "host": yl.host if yl else None, "listening": bool(yl and yl.listening), "error": yl.error if yl else None,
                "fresh": fresh, "age_s": round(min(a for _, a in y.values()), 1) if y else None, "source": yl.source() if yl else None,
                "status": status_names(st("status1"), st("status2"))}

    # ---- alarms and the hours (every second, from the ticker) ------------------------------------------------
    def conditions(self, now: float) -> dict:
        """key -> (name, worst-value text, value used for "worst", lower is worse or None) for the conditions that are on,
        from the YDEN-02's engine data."""
        with self.lock: y = self._yd(now)
        fresh = lambda k: y[k][0] if k in y and y[k][1] < FRESH_S else None
        s = self.store.settings(); on = {}
        rpm = fresh("rpm")
        if rpm is not None and rpm >= RUN_RPM: self.run_since = self.run_since or now
        else: self.run_since = None
        running = self.run_since is not None and now - self.run_since >= RUN_SETTLE_S
        t = fresh("temp_c")
        if t is not None and t >= s["temp_high_c"]:
            on["temp_high"] = ("High coolant temperature", f"{{:.0f}} °C (limit {s['temp_high_c']:g} °C)", t, False)
        o = fresh("oil_bar")
        if running and o is not None and o < s["oil_low_bar"]:
            on["oil_low"] = ("Low oil pressure", f"{{:.1f}} bar (limit {s['oil_low_bar']:g} bar)", o, True)
        for name in status_names(fresh("status1"), fresh("status2")):
            if name in NOT_ALARMS or (name in RUNNING_ONLY and not running): continue
            on[f"status:{name}"] = (f"Engine: {name}", "reported by the engine", None, None)
        return on

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        on = self.conditions(now)
        snap_hours = self._read(now).get("hours")
        if snap_hours and snap_hours[1] < FRESH_S:
            h = round(snap_hours[0], 2)
            if h != self.saved_hours: self.saved_hours = h; self.store.set_engine(h, _now_iso(now))
        with self.lock: yh = self.yd.get("hours"); lost = now - max([t for _, t in self.yd.values()] or [0]) >= LOST_S
        hours = round(yh[0], 2) if yh and now - yh[1] < FRESH_S else self.saved_hours
        for key, (name, fmt, value, low_bad) in on.items():
            self.clearing.pop(key, None)
            if key in self.open:
                w = self.open[key]
                if low_bad is not None and (value < w["worst"] if low_bad else value > w["worst"]):
                    w["worst"] = value; self.store.update_alarm(w["id"], detail=fmt.format(value))
                continue
            since = self.pending.setdefault(key, now)
            if now - since >= HOLD_S:
                a = self.store.open_alarm(name, fmt.format(value) if value is not None else fmt, hours, _now_iso(since))
                self.open[key] = {"id": a["id"], "worst": value}; self.pending.pop(key, None)
                log.warning("engine alarm: %s", name)
        for key in [k for k in self.pending if k not in on]: del self.pending[key]
        for key in [k for k in self.open if k not in on]:
            since = self.clearing.setdefault(key, now)
            if now - since >= HOLD_S or lost:
                self.store.update_alarm(self.open[key]["id"], end=_now_iso(since))
                log.info("engine alarm ended: %s", key); del self.open[key]; self.clearing.pop(key, None)

    # ---- the threads -----------------------------------------------------------------------------------------
    async def _stream(self, host: str) -> None:
        import websockets
        url, delay = SENSORS_URL.format(host=host, ms=1000, ns="%5Epropulsion"), 2
        while True:
            try:
                async with websockets.connect(url, open_timeout=10, ping_interval=20, ping_timeout=20, max_size=8 * 2**20, compression=None) as ws:
                    log.info("engine data: connected to the Orca Core %s", host); self.connected, self.error, delay = True, None, 2
                    async for raw in ws: self.apply(parse_message(raw))      # read only: nothing is ever sent
            except asyncio.CancelledError: raise
            except Exception as e:
                if self.error != f"{type(e).__name__}: {e}": log.warning("engine data: %s: %s", type(e).__name__, e)
                self.error = f"{type(e).__name__}: {e}"
            self.connected = False
            await asyncio.sleep(delay); delay = min(delay * 2, 30)

    def start(self, host: str | None, yden: str | None = None) -> None:
        """host: the Orca Core (live values, hours); yden: the YDEN-02 (the alarms). None = without that one."""
        if host: threading.Thread(target=lambda: asyncio.run(self._stream(host)), daemon=True, name="engine-stream").start()
        if yden: self.yden = YdenListener(yden, self.apply_yd); self.yden.start()

        def ticker():
            while True:
                time.sleep(1)
                try: self.tick()
                except Exception: log.exception("engine tick")
        threading.Thread(target=ticker, daemon=True, name="engine-tick").start()
