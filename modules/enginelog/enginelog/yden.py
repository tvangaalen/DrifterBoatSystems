"""The engine's own NMEA 2000 data from the Yacht Devices YDEN-02 (the alarm log's source since 2026-11-07), listen only.

The YDEN-02 sends every NMEA 2000 frame as YD RAW text over UDP (port 1456, a broadcast on the boat LAN), one frame per
line: `hh:mm:ss.mmm R 09F20103 A0 1A 00 28 00 FF FF 47`. Its server is two-way (what it receives on that port goes
onto the bus), so this module only ever listens: it binds this PC's LAN address, takes datagrams from the YDEN's own
address only and never sends a byte (no socket is ever connected or written to).

Decoded, for the first engine seen (instance 0 of one source: the Yanmar J1939 gateway, source 3 on 2026-11-07):
  PGN 127488 Engine Parameters, Rapid: rpm, boost;
  PGN 127489 Engine Parameters, Dynamic (fast packet): oil pressure and temperature, coolant temperature, alternator
  voltage, fuel rate, engine hours, coolant and fuel pressure, load, torque and the two discrete status words: the
  engine's own warning lights, which the Orca Core does not pass on.
"""
from __future__ import annotations

import ipaddress, logging, socket, threading, time

log = logging.getLogger("enginelog")
PORT = 1456

# NMEA 2000 Engine Discrete Status 1 and 2 (PGN 127489): bit -> name
STATUS1 = {0: "Check engine", 1: "Over temperature", 2: "Low oil pressure", 3: "Low oil level", 4: "Low fuel pressure",
           5: "Low system voltage", 6: "Low coolant level", 7: "Water flow", 8: "Water in fuel", 9: "Charge indicator",
           10: "Preheat indicator", 11: "High boost pressure", 12: "Rev limit exceeded", 13: "EGR system",
           14: "Throttle position sensor", 15: "Emergency stop"}
STATUS2 = {0: "Warning level 1", 1: "Warning level 2", 2: "Power reduction", 3: "Maintenance needed",
           4: "Engine communication error", 5: "Sub or secondary throttle", 6: "Neutral start protect", 7: "Engine shutting down"}
FAST = {127489}                                       # the fast-packet PGNs we assemble


def _u(b: bytes, signed=False):
    """A little-endian field, None when 'not available' (all ones, or 0x7F.. for signed; the top two codes are reserved)."""
    n = len(b); v = int.from_bytes(b, "little", signed=signed)
    if signed: return None if v >= (1 << (8 * n - 1)) - 2 else v
    return None if v >= (1 << (8 * n)) - 3 else v


def _scale(v, f, off=0.0):
    return None if v is None else v * f + off


def parse_line(line: str):
    """(pgn, source, data bytes) of a received YD RAW line, else None. A frame the YDEN sent itself ('T') is skipped."""
    p = line.split()
    if len(p) < 4 or p[1] != "R": return None
    try: cid = int(p[2], 16); data = bytes(int(x, 16) for x in p[3:])
    except ValueError: return None
    if cid > 0x1FFFFFFF or len(data) > 8: return None
    pf = (cid >> 16) & 0xFF
    pgn = (cid >> 8) & (0x3FF00 if pf < 240 else 0x3FFFF)
    return pgn, cid & 0xFF, data


class FastPackets:
    """Assembles NMEA 2000 fast packets: frame 0 = sequence|0, length, 6 bytes; then sequence|n, 7 bytes each."""
    def __init__(self): self.parts: dict[tuple[int, int], dict] = {}

    def add(self, pgn: int, src: int, data: bytes) -> bytes | None:
        if not data: return None
        seq, frame, key = data[0] >> 5, data[0] & 0x1F, (pgn, src)
        if frame == 0:
            if len(data) < 2: return None
            self.parts[key] = {"seq": seq, "len": data[1], "next": 1, "buf": bytearray(data[2:8])}
        else:
            p = self.parts.get(key)
            if not p or p["seq"] != seq or p["next"] != frame: self.parts.pop(key, None); return None
            p["buf"] += data[1:8]; p["next"] += 1
        p = self.parts[key]
        if len(p["buf"]) >= p["len"]:
            del self.parts[key]; return bytes(p["buf"][:p["len"]])
        return None


def decode(pgn: int, d: bytes) -> tuple[int, dict] | None:
    """(engine instance, fields) for 127488 and 127489; units: rpm, bar, °C, V, L/h, h, %."""
    if pgn == 127488 and len(d) >= 5:
        return d[0], {"rpm": _scale(_u(d[1:3]), 0.25), "boost_bar": _scale(_u(d[3:5]), 0.001)}
    if pgn == 127489 and len(d) >= 26:
        f = {"oil_bar": _scale(_u(d[1:3]), 0.001), "oil_temp_c": _scale(_u(d[3:5]), 0.1, -273.15),
             "temp_c": _scale(_u(d[5:7]), 0.01, -273.15), "alt_v": _scale(_u(d[7:9], True), 0.01),
             "fuel_lph": _scale(_u(d[9:11], True), 0.1), "hours": _scale(_u(d[11:15]), 1 / 3600),
             "coolant_bar": _scale(_u(d[15:17]), 0.001), "fuel_bar": _scale(_u(d[17:19]), 0.01),
             "status1": _u(d[20:22]), "status2": _u(d[22:24]), "load": _u(d[24:25], True), "torque": _u(d[25:26], True)}
        return d[0], f
    return None


def status_names(status1, status2) -> list[str]:
    """The names of the status bits that are on."""
    out = [n for b, n in STATUS1.items() if status1 is not None and status1 >> b & 1]
    return out + [n for b, n in STATUS2.items() if status2 is not None and status2 >> b & 1]


class YdenListener:
    """Feeds `on_fields(fields, now)` with the decoded engine data of the first engine seen. Listen only."""
    def __init__(self, host: str, on_fields, port: int = PORT, clock=time.time):
        self.host, self.port, self.on_fields, self.clock = host, port, on_fields, clock
        self.fp, self.engine = FastPackets(), None          # (source, instance) of the engine we follow
        self.listening, self.error, self.last_frame = False, None, None

    def feed_line(self, line: str, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        r = parse_line(line)
        if not r: return
        pgn, src, data = r
        if pgn not in (127488, 127489): return
        self.last_frame = now
        if pgn in FAST:
            data = self.fp.add(pgn, src, data)
            if data is None: return
        dec = decode(pgn, data)
        if not dec: return
        inst, fields = dec
        if self.engine is None: self.engine = (src, inst)
        if (src, inst) != self.engine: return
        self.on_fields(fields, now)

    def source(self) -> str | None:
        return f"{self.engine[0]}.{self.engine[1]}" if self.engine else None

    @staticmethod
    def lan_address(host: str, port: int) -> str:
        """This PC's address towards the YDEN (a UDP connect sends nothing); it must be private."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: s.connect((host, port)); ip = s.getsockname()[0]
        finally: s.close()
        if not ipaddress.ip_address(ip).is_private: raise OSError(f"{ip} is not a private address")
        return ip

    def _loop(self) -> None:
        delay = 2
        while True:
            sock = None
            try:
                ip = self.lan_address(self.host, self.port)
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((ip, self.port)); sock.settimeout(5)
                log.info("engine alarms: listening for the YDEN-02 %s on %s:%d (UDP, receive only)", self.host, ip, self.port)
                self.listening, self.error, delay = True, None, 2
                while True:
                    try: data, (addr, _) = sock.recvfrom(65536)
                    except socket.timeout: continue
                    if addr != self.host: continue                      # only the YDEN itself
                    now = self.clock()
                    for line in data.decode("ascii", "replace").splitlines(): self.feed_line(line, now)
            except Exception as e:
                if self.error != f"{type(e).__name__}: {e}": log.warning("engine alarms (YDEN-02): %s: %s", type(e).__name__, e)
                self.error = f"{type(e).__name__}: {e}"
            finally:
                if sock: sock.close()
            self.listening = False
            time.sleep(delay); delay = min(delay * 2, 30)

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="yden").start()

