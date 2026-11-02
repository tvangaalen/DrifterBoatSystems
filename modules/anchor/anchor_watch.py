"""1.17's module name, kept so that test_anchor_watch.py runs unchanged against the package anchor/ (2.0): every name is
re-exported from there, and the modules the tests patch through this name (time, urllib, websockets, asyncio) are the
same module objects. The stdlib HTTP server of 1.17 (make_handler) stays one release for test_contract_stdlib.py;
the anchor watch runs as `python -m anchor`."""
import asyncio, json, time, urllib.error, urllib.parse, urllib.request  # noqa: F401  (patched by the tests)
from http.server import BaseHTTPRequestHandler

import websockets  # noqa: F401

import anchor  # noqa: F401  (puts the repository root and this folder on sys.path)
from common import net
from anchor.ais import InternetAIS, read_ais  # noqa: F401
from anchor.alerts import Pushover, StillAlive  # noqa: F401
from anchor.chain import ChainFormula, chain_advice  # noqa: F401
from anchor.geo import dist_bearing_m, num, offset  # noqa: F401
from anchor.gps import NetGPS, position_sources, read_boat  # noqa: F401
from anchor.nfl import NoForeignLand  # noqa: F401
from anchor.settings import AIS_ALARM_AGE_S, AIS_MAX_AGE_S, AIS_RANGE_M, BOOT_JITTER_S, CORE_INFO_S, DEFAULTS, DEFAULT_GPS, DIAG_S, EARTH, FRESH_S, FROZEN_S, HOLD_LOG_S, HOLD_M, HOLD_MERGE_S, HOLD_NEAR_M, HOLD_SOON_S, NET_AWAY_M, NET_GPS_PORT, NET_MAX_AGE_S, NET_SRC_BASE, ROUTE_KEYS, SETTING_LIMITS, SLOW_GPS, TRACK_EVERY_S, VERSION, log  # noqa: F401
from anchor.tide import TideFeed, depth_window, tide_at, tide_summary  # noqa: F401
from anchor.tiles import TILE_RE, TileCache, tile_bbox_3857  # noqa: F401
from anchor.watch import AnchorWatch, _bad, _num, core_info_loop, sound_loop, watch_loop, winsound  # noqa: F401


def make_handler(watch, tiles):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json", code=200, cache="no-store"):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            try: self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError): pass   # browser cancelled (tiles while zooming)

        def _json(self, obj, code=200): self._send(json.dumps(obj, default=lambda o: None).encode(), code=code)

        def do_GET(self):
            path, _, q = self.path.partition("?")
            args = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
            if path == "/api/state": self._json(watch.state())
            elif path == "/api/track":
                try: self._json(watch.track_since(float(args.get("since", 0)), int(args.get("gen", -1))))
                except ValueError: self._json({"error": "bad query"}, 400)
            elif (m := TILE_RE.match(path)) and m[1] in TileCache.SOURCES:
                t = tiles.get(m[1], int(m[2]), int(m[3]), int(m[4]))
                if t: self._send(t[0], t[1], cache="max-age=86400")
                else: self._send(b"", "text/plain", 404, cache="max-age=300")
            else: self._send(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path != "/api/command": return self._send(b"not found", "text/plain", 404)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 10000: raise ValueError("request too large")
                watch.command(json.loads(self.rfile.read(n) or b"{}")); self._json({"ok": True, "state": watch.state()})
            except ValueError as e: self._json({"ok": False, "error": str(e)}, 400)
            except Exception as e: log.exception("command failed"); self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

        timeout = 30                                   # a client that stalls (e.g. mid TLS handshake) only ties up its own thread

        def log_message(self, *a): pass
    return Handler


def check_bind(addr):
    """Only loopback or a private (RFC 1918) LAN address: the watch must never listen on a public interface."""
    net.check_bind(addr, "--bind")
