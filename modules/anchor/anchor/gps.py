"""GPS: the position sources with their frozen/hold rules (read_boat) and network GPS over NMEA 0183 (NetGPS)."""
import asyncio, ipaddress, threading, time
from datetime import datetime, timezone
from orca_reader import KN, RAD

from anchor.geo import num
from anchor.settings import FRESH_S, NET_MAX_AGE_S, NET_SRC_BASE, log


# ---------------------------------------------------------------- reading the Core values


def position_sources(sensors, now, kind="position"):
    """Every source with a fixed, fresh-or-not position: src -> {lat, lon, age, sats, hdop}.
    kind "position" = navigation.position (the normal one), "gnss" = navigation.gnss (the receiver's own fix)."""
    def val(k):
        v = sensors.get(k); return (v[0], now - v[1]) if v and num(v[0]) else (None, None)
    out = {}
    for k in sensors:
        if k.startswith(f"navigation.{kind}.") and k.endswith(".latitude"):
            src = k.split(".")[2]
            lat, a1 = val(k); lon, a2 = val(f"navigation.{kind}.{src}.longitude")
            fix, _ = val(f"navigation.gnss.{src}.method")
            if lat is None or lon is None or fix == 0 or (lat == 0 and lon == 0): continue
            out[src] = {"lat": lat, "lon": lon, "age": max(a1, a2), "source": src, "raw": kind == "gnss",
                        "sats": val(f"navigation.gnss.{src}.satellites")[0], "hdop": val(f"navigation.gnss.{src}.HDOP")[0]}
    return out


def read_boat(sensors, now, sources_pref, frozen=frozenset(), transducer_depth=0.0, raw=frozenset(), hold=frozenset()):
    """Pick the position and the other values the watch needs from the Store's sensor map (key -> (value, t)).
    Sources in `frozen` (position unchanged for FROZEN_S) are skipped; for sources in `raw` (navigation.position
    held, own fix still changing) the receiver's own fix is used. Sources in `hold` (254 on static hold, within
    HOLD_M) are used only when no live source is left."""
    def val(k):
        v = sensors.get(k); return (v[0], now - v[1]) if v and num(v[0]) else (None, None)

    cands = position_sources(sensors, now)
    if raw: cands.update({s: c for s, c in position_sources(sensors, now, "gnss").items() if s in raw})
    cands = {s: c for s, c in cands.items() if s not in frozen}
    order = list(sources_pref) + sorted((s for s in cands if s not in sources_pref), key=lambda s: cands[s]["age"])
    order = [s for s in order if s not in hold] + [s for s in order if s in hold]
    pos = next((dict(cands[s]) for s in order if s in cands and cands[s]["age"] <= FRESH_S), None)

    def first(keys):
        for k in keys:
            v, a = val(k)
            if v is not None and a <= FRESH_S: return v, k
        return None, None

    hdg, hk = first(["navigation.heading.254.heading", "navigation.heading.128.heading", "navigation.heading.9.heading"])
    if hdg is not None:
        src = hk.split(".")[2]; ref, _ = val(f"navigation.heading.{src}.reference")
        if ref == 1:                                   # magnetic -> true
            var, _ = first([f"navigation.heading.{src}.variation", "navigation.heading.254.variation", "navigation.magvar.254.variation"])
            hdg += var or 0
        hdg = hdg * RAD % 360
    depth, dk = first([k for k in sensors if k.startswith("environment.depth.") and k.endswith(".belowTransducer")])
    raw, water, off_src = depth, None, None
    if depth is not None:
        # water depth = reading + transducer depth below the waterline: the sounder's own offset when it reports a
        # positive one (N2K: positive = transducer to waterline, negative = to the keel), else the setting
        off, _ = val(dk.rsplit(".", 1)[0] + ".offset")
        if off is not None and off > 0: water, off_src = depth + off, "sounder"
        else: water, off, off_src = depth + transducer_depth, transducer_depth, "setting"
    tws, _ = first(["environment.wind.254.0.speed", "environment.wind.254.3.speed", "environment.wind.2.0.speed", "environment.wind.2.3.speed"])
    twd, _ = first(["environment.wind.254.0.angle", "environment.wind.2.0.angle"])
    sog, _ = first(["navigation.cogsog.254.speed"] + ([f"navigation.cogsog.{pos['source']}.speed"] if pos else []))
    return {"pos": pos, "heading": hdg, "depth": round(water, 2) if water is not None else None, "depth_transducer": raw,
            "depth_offset": off if raw is not None else None, "depth_offset_src": off_src, "tws": tws * KN if tws is not None else None,
            "twd": twd * RAD % 360 if twd is not None else None, "sog": sog * KN if sog is not None else None}


class NetGPS:
    """GPS positions sent as NMEA 0183 over the LAN, e.g. by GPS2IP on an iPhone or iPad (UDP or TCP push to this PC).
    Every sender (by IP address, private addresses only) becomes a position source numbered from NET_SRC_BASE, so it
    takes part in the normal source order, failover and frozen check. RMC and GGA are read (checksum required); a
    sentence whose own GPS time is more than NET_MAX_AGE_S off this PC's clock is dropped: GPS2IP re-sends up to 600
    stored messages after a reconnect, and those are old positions."""

    def __init__(self, store, sources=None, on_event=None, on_new=None):
        self.store, self.on_event, self.on_new = store, on_event, on_new
        self.lock = threading.Lock()
        self.sources = dict(sources or {})          # sender IP -> source number (kept in the state file)
        self.clock_warned = 0
        self.port, self.error = None, None          # the port listened on now, or why it could not be opened

    def ip_of(self, src):
        with self.lock: return next((ip for ip, s in self.sources.items() if s == str(src)), None)

    def is_net(self, src):
        with self.lock: return str(src) in self.sources.values()

    def forget(self, src):
        with self.lock: self.sources = {ip: s for ip, s in self.sources.items() if s != str(src)}

    def source_for(self, ip):
        with self.lock:
            src = self.sources.get(ip)
            if src: return src, False
            used = {int(s) for s in self.sources.values()}
            src = str(next(n for n in range(NET_SRC_BASE, NET_SRC_BASE + 1000) if n not in used)); self.sources[ip] = src
            return src, True

    @staticmethod
    def parse(line):
        """One NMEA sentence -> {"type", "lat", "lon", "valid", "hms", "date", "sats", "hdop"}, or None."""
        line = line.strip()
        if not line.startswith("$") or "*" not in line: return None
        body, _, ck = line[1:].partition("*")
        x = 0
        for ch in body: x ^= ord(ch)
        try:
            if int(ck[:2], 16) != x: return None
        except ValueError: return None
        f = body.split(",")
        kind = f[0][-3:]
        def coord(v, hemi, deg_digits):
            if not v or hemi not in "NSEW" or not hemi: return None
            d = float(v[:deg_digits]) + float(v[deg_digits:]) / 60
            return -d if hemi in "SW" else d
        try:
            if kind == "RMC" and len(f) >= 10:
                return {"type": kind, "hms": f[1], "valid": f[2] == "A", "lat": coord(f[3], f[4], 2), "lon": coord(f[5], f[6], 3),
                        "date": f[9], "sats": None, "hdop": None}
            if kind == "GGA" and len(f) >= 9:
                return {"type": kind, "hms": f[1], "valid": f[6] not in ("", "0"), "lat": coord(f[2], f[3], 2), "lon": coord(f[4], f[5], 3),
                        "date": None, "sats": int(f[7]) if f[7] else None, "hdop": float(f[8]) if f[8] else None}
        except ValueError: return None
        return None

    @staticmethod
    def fix_time(hms, date, now):
        """The sentence's own UTC time as a Unix time (GGA has no date: the day nearest to now is taken)."""
        if len(hms) < 6: return None
        try:
            h, m, sec = int(hms[:2]), int(hms[2:4]), float(hms[4:])
            if date and len(date) == 6:
                yy, year = int(date[4:6]), datetime.fromtimestamp(now, timezone.utc).year   # two-digit year: the century nearest to now
                d = datetime(min((year // 100 * 100 + yy + c for c in (-100, 0, 100)), key=lambda y: abs(y - year)),
                             int(date[2:4]), int(date[:2]), tzinfo=timezone.utc)
                return d.timestamp() + h * 3600 + m * 60 + sec
            day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            t = day + h * 3600 + m * 60 + sec
            return min((t - 86400, t, t + 86400), key=lambda c: abs(c - now))
        except ValueError: return None

    def feed(self, ip, data, now=None):
        """Sentences from one sender (a datagram or a line). Returns how many were used."""
        now = now or time.time()
        try:
            if not ipaddress.ip_address(ip).is_private: return 0
        except ValueError: return 0
        if isinstance(data, bytes): data = data.decode("ascii", "replace")
        used = 0
        for line in data.splitlines():
            p = self.parse(line)
            if not p: continue
            t = self.fix_time(p["hms"], p["date"], now)
            if t is None: continue
            if abs(now - t) > NET_MAX_AGE_S:
                if p["type"] == "RMC" and p["valid"] and abs(now - t) < 3600 and now - self.clock_warned > 3600 and self.on_event:
                    # an hour or less off and repeating: more likely this PC's clock than stored messages
                    self.clock_warned = now
                    self.on_event(f"Network GPS {ip}: its GPS time is {abs(now - t):.0f} s off this PC's clock; positions that old are not used", "warn")
                continue
            src, new = self.source_for(ip)
            if new and self.on_new: self.on_new(ip, src)
            vals = {f"navigation.gnss.{src}.method": 1 if p["valid"] else 0}
            if p["lat"] is not None and p["lon"] is not None:
                vals[f"navigation.position.{src}.latitude"] = p["lat"]; vals[f"navigation.position.{src}.longitude"] = p["lon"]
            if p["sats"] is not None: vals[f"navigation.gnss.{src}.satellites"] = p["sats"]
            if p["hdop"] is not None: vals[f"navigation.gnss.{src}.HDOP"] = p["hdop"]
            with self.store.lock:
                for k, v in vals.items(): self.store.values["sensors"][k] = (v, now)
            used += 1
        return used

    async def run(self, bind, port_now):
        """Listen for UDP datagrams and TCP connections on the same port (GPS2IP 'UDP Push' or 'TCP Push'). The port
        comes from port_now() (the nmea_port setting): when it changes, the listener moves; when it cannot be opened
        (in use by another program), it is retried every 30 s."""
        while True:
            port = port_now(); udp = tcp = None
            try:
                udp, tcp = await self.listen(bind, port); self.port, self.error = port, None
                log.info("Network GPS (NMEA 0183): listening on %s:%d, UDP and TCP", bind, port)
            except OSError as e:
                if udp: udp.close()
                udp = None; self.port, self.error = None, f"port {port} could not be opened: {e.strerror or e}"
                log.warning("Network GPS: %s", self.error)
                if self.on_event: self.on_event(f"Network GPS: {self.error}", "warn")
            waited = 0
            while port_now() == port and (udp or waited < 30): await asyncio.sleep(1); waited += 1
            if udp: udp.close()
            if tcp: tcp.close(); await tcp.wait_closed()
            self.port = None

    async def listen(self, bind, port):
        loop = asyncio.get_running_loop(); feed = self.feed

        class Udp(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr): feed(addr[0], data)

        async def tcp(reader, writer):
            ip = writer.get_extra_info("peername")[0]
            try:
                while line := await reader.readline():
                    if len(line) > 1000: break
                    feed(ip, line)
            except (ConnectionError, OSError, ValueError): pass        # ValueError: a line over the limit
            finally: writer.close()

        udp, _ = await loop.create_datagram_endpoint(Udp, local_addr=(bind, port))
        try: server = await asyncio.start_server(tcp, bind, port, limit=4096)
        except OSError: udp.close(); raise
        return udp, server
