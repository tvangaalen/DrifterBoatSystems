"""The tide forecast (offline copy) and the depth window over the next hours."""
import asyncio, json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from anchor.geo import dist_bearing_m, num
from anchor.settings import VERSION


# ---------------------------------------------------------------- tide (Open-Meteo marine sea level)


def tide_summary(series, now):
    """Level now, rising/falling, the next high and low waters and a curve, from an hourly sea-level series.

    series: [[unix time, metres], ...] (hourly). The model gives centimetres, so the series is smoothed over three
    hours before looking for turning points, and each turning point is refined with a parabola through its
    neighbours. Returns None outside the series.
    """
    if len(series) < 6 or not (series[0][0] <= now <= series[-1][0]): return None
    ts = [t for t, _ in series]; hs = [h for _, h in series]
    sm = [hs[0]] + [(hs[i - 1] + hs[i] + hs[i + 1]) / 3 for i in range(1, len(hs) - 1)] + [hs[-1]]
    ext = []
    for i in range(1, len(sm) - 1):
        a, b, c = sm[i - 1], sm[i], sm[i + 1]
        if not ((b > a and b >= c) or (b < a and b <= c)): continue
        den = a - 2 * b + c; off = max(-1.0, min(1.0, 0.5 * (a - c) / den)) if den else 0.0
        t = ts[i] + off * (ts[i + 1] - ts[i]); h = b - 0.25 * (a - c) * off
        kind = "high" if b > a else "low"
        if ext and ext[-1]["type"] == kind:                     # same kind twice (plateau): keep the more extreme
            if (kind == "high") == (h > ext[-1]["h"]): ext[-1] = {"type": kind, "t": t, "h": h}
            continue
        ext.append({"type": kind, "t": t, "h": h})
    i = next(k for k in range(len(ts) - 1) if ts[k] <= now <= ts[k + 1])
    f = (now - ts[i]) / (ts[i + 1] - ts[i]); level = hs[i] + f * (hs[i + 1] - hs[i])
    nxt = [e for e in ext if e["t"] > now][:2]
    prev = [e for e in ext if e["t"] <= now][-1:]
    trend = ("rising" if nxt[0]["type"] == "high" else "falling") if nxt else None
    span = [e["h"] for e in prev + nxt[:1]]
    return {"level": round(level, 3), "trend": trend,
            "next": [{"type": e["type"], "t": round(e["t"]), "h": round(e["h"], 3)} for e in nxt],
            "range": round(abs(span[0] - span[1]), 3) if len(span) == 2 else None,
            "curve": [[t, h] for t, h in series if now - 6 * 3600 <= t <= now + 18 * 3600]}


def tide_at(series, t):
    """Sea level at time t, linear between the hourly points; None outside the series."""
    if not series or not (series[0][0] <= t <= series[-1][0]): return None
    for (t0, h0), (t1, h1) in zip(series, series[1:]):
        if t0 <= t <= t1: return h0 + (h1 - h0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    return series[-1][1]


def depth_window(series, now, depth, depth_t, hours=24, back=6):
    """Depth now and its lowest and highest value over the next `hours`, from one depth reading and the tide.

    depth: a reading at time depth_t (now for a live sounder, earlier for the last reading). The depth at any time t
    is depth + tide(t) - tide(depth_t). Returns None when the tide series does not cover depth_t and the window.
    "curve" is that depth from `back` hours ago (as far as the series goes) to the end of the window, for the chart.
    """
    base = tide_at(series, depth_t); end = now + hours * 3600
    if base is None or tide_at(series, now) is None or series[-1][0] < end: return None
    pts = [(now, tide_at(series, now))] + [(t, h) for t, h in series if now < t < end] + [(end, tide_at(series, end))]
    lo = min(pts, key=lambda p: p[1]); hi = max(pts, key=lambda p: p[1])
    d = lambda h: round(depth + h - base, 2)
    start = max(series[0][0], now - back * 3600)
    curve = [[t, d(h)] for t, h in series if start <= t < now] + [[round(t), d(h)] for t, h in pts]
    return {"now": d(pts[0][1]), "min": d(lo[1]), "min_t": round(lo[0]), "max": d(hi[1]), "max_t": round(hi[0]), "curve": curve}


class TideFeed:
    """Hourly sea level (tide plus weather effects) for the boat's area from the Open-Meteo marine API, free for
    non-commercial use (attribution: Open-Meteo.com). Refreshed every REFRESH_S or after the boat moved MOVE_M, and
    kept in a local cache file so the tide still shows without internet. Only a position rounded to 0.01 degree
    (about 1 km) is sent. A model value on a grid of several km, not a tide-gauge reading; not for navigation.
    """
    URL = ("https://marine-api.open-meteo.com/v1/marine?latitude={lat:.2f}&longitude={lon:.2f}"
           "&hourly=sea_level_height_msl&timezone=UTC&past_days=1&forecast_days=7&cell_selection=sea")
    REFRESH_S, MOVE_M, RETRY_S = 3 * 3600, 5000, 600

    def __init__(self, cache_file, center, on_event=None):
        self.cache_file, self.center = Path(cache_file), center
        self.on_event = on_event or (lambda text, kind: None)
        self.data = None; self.last_error = None; self.next_try = 0.0
        try: self.data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception: pass

    def due(self, now, c):
        d = self.data
        return (not d or now - d.get("fetched", 0) > self.REFRESH_S or not d.get("series") or now > d["series"][-1][0] - 86400
                or dist_bearing_m(d["lat"], d["lon"], *c)[0] > self.MOVE_M)

    def fetch(self, c, now=None):
        now = now or time.time()
        req = urllib.request.Request(self.URL.format(lat=c[0], lon=c[1]), headers={"User-Agent": f"OrcaCore2-AnchorWatch/{VERSION}"})
        with urllib.request.urlopen(req, timeout=20) as r: d = json.loads(r.read())
        h = d.get("hourly") or {}
        series = [[int(datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp()), v]
                  for t, v in zip(h.get("time", []), h.get("sea_level_height_msl", [])) if num(v)]
        if len(series) < 24: raise ValueError("no sea-level data for this position")
        self.data = {"fetched": now, "lat": c[0], "lon": c[1], "grid": [d.get("latitude"), d.get("longitude")], "series": series}
        tmp = self.cache_file.with_suffix(".tmp"); tmp.write_text(json.dumps(self.data), encoding="utf-8"); os.replace(tmp, self.cache_file)

    def summary(self, now=None):
        now = now or time.time()
        if not self.data: return {"available": False, "error": self.last_error}
        s = tide_summary(self.data["series"], now)
        if not s: return {"available": False, "error": self.last_error or "tide data out of date"}
        return {"available": True, **s, "fetched": self.data["fetched"], "grid": self.data.get("grid"), "error": self.last_error}

    async def run(self):
        while True:
            now = time.time(); c = self.center()
            if c and now >= self.next_try and self.due(now, c):
                try:
                    await asyncio.to_thread(self.fetch, c)
                    if self.last_error: self.on_event("Tide data available again", "ok")
                    self.last_error = None
                except Exception as e:
                    if not self.last_error: self.on_event(f"Tide data not updated: {type(e).__name__}: {e}", "warn")
                    self.last_error = f"{type(e).__name__}: {e}"; self.next_try = now + self.RETRY_S
            await asyncio.sleep(60 if self.data else 5)      # at start-up the boat's position comes a moment later
