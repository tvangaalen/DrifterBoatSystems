"""Drifter Boat Systems: one web app for the boat's systems (energy, anchor watch, BoatGuard, washer).

The gateway serves the app and passes the page's requests on to the four existing servers, which keep running
unchanged and keep all their own logic (Float protection, anchor alarm, arming, washer schedule). The gateway makes
no decisions and talks to no hardware itself. With "supervise" on, supervisor.py keeps the servers running (starts a
stopped one, never stops a running one unless the user asks for a restart from the app).

Safety:
- Only routes listed in ROUTES are passed on (method + path pattern per module); everything else gets 404.
- Binds only to localhost or a private (RFC 1918) address (`check_bind`). No login: never expose it to the internet.
- Requests must address the gateway by IP, localhost, this PC's name or a configured name (blocks DNS rebinding).
- A POST must be JSON and carry `X-Drifter-Request: 1` from the gateway's own origin, so another web page in a
  browser on the boat Wi-Fi cannot send commands through it (a custom header needs a CORS preflight, never approved).
Stdlib only.
"""
from __future__ import annotations

import argparse, http.client, ipaddress, json, logging, re, socket, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "0.9.1"
HERE = Path(__file__).resolve().parent
STATIC = HERE / "web"
log = logging.getLogger("drifter")

# Per module: (method, path pattern) pairs the page may use. Paths are relative to the module's upstream root.
# Hardware writes stay on the upstream server, which validates and reads back as before.
ROUTES = {
    "power": [  # MasterVolt YMS
        ("GET", r"/api/(energy|settings|bms|balancers|bluetooth-coordinator|bluetooth-events|history)"),
        ("GET", r"/api/history/(chart-data|contributions|status)"),
        ("GET", r"/api/(reports/battery-health|version)"),
        ("GET", r"/manual"),                           # the user manual (HTML, read-only)
        ("POST", r"/api/reports/battery-health"),      # runs in a separate low-priority process on the server
        ("POST", r"/api/settings"),
        ("POST", r"/api/(bms|balancers)/refresh"),
        ("POST", r"/api/bms/[123]/(refresh|charge|discharge)"),
        ("POST", r"/api/balancers/[123]/refresh"),
        ("POST", r"/api/bms/set-all/(charge|discharge)-(on|off)"),
        ("POST", r"/api/bms/[123]/set-soc-(100|charge|discharge|value)"),   # SOC calibration, with a choice dialog in the app
        ("POST", r"/api/bms/set-all-soc/(100|charge|discharge|value)"),
        ("POST", r"/api/control/(inverter|charger|ac-limit|ac-support|mode|alternator)"),
        ("POST", r"/api/control/device/(charger_start|charger_bow|engine_ecu|solar)"),
    ],
    "anchor": [  # Orca Core 2 anchor watch
        ("GET", r"/api/(state|track)"),
        ("GET", r"/tiles/[a-z]+/\d{1,2}/\d{1,7}/\d{1,7}\.(png|jpg)"),
        ("POST", r"/api/command"),
    ],
    "guard": [  # BoatGuard
        ("GET", r"/api/(status|log)"),
        ("POST", r"/api/(enabled|settings|notify-test|test)"),
    ],
    "washer": [  # VIOMI W1 controller
        ("GET", r"/api/(status|schedule|start-check)"),
        ("GET", r"/api/diagnostics"),   # ?recheck=1 re-reads the config and re-runs the startup checks
        ("GET", r"/diagnostics/export"),
        ("POST", r"/api/(power/on|power/off|start|pause|schedule|schedule/cancel)"),
        ("POST", r"/api/(program|temperature|spin|rinses)/\d{1,3}"),
    ],
}
COMPILED = {m: [(meth, re.compile(p + r"$")) for meth, p in rs] for m, rs in ROUTES.items()}
# Extra headers the upstream needs from its "own page"; the gateway adds them after its own checks.
UPSTREAM_HEADERS = {"washer": {"X-Viomi-Request": "1"}}
GET_TIMEOUT, POST_TIMEOUT = 12, 90   # BMS/MOSFET writes over Bluetooth and the camera test can take long
MAX_BODY = 64 * 1024
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json"}
DEFAULT_CONFIG = {
    "bind": "127.0.0.1", "port": 8100, "allowed_hosts": [],
    "certfile": None, "keyfile": None, "ca_file": None,
    "supervise": False,   # keep the module servers running (supervisor.py); only the live config turns it on
    "modules": {
        "power": {"name": "Energy", "url": "https://127.0.0.1:8000", "classic": None},
        "anchor": {"name": "Anchor watch", "url": "https://127.0.0.1:8766", "classic": None},
        "guard": {"name": "BoatGuard", "url": "https://127.0.0.1:8095", "classic": None},
        "washer": {"name": "Washer", "url": "http://127.0.0.1:8080", "classic": None},
    },
}


def check_bind(addr: str) -> None:
    """Only loopback or a private LAN address: the gateway has no login and must never listen on a public interface."""
    ip = ipaddress.ip_address(addr)
    if not (ip.is_loopback or (ip.is_private and not ip.is_unspecified and not ip.is_link_local)):
        raise SystemExit(f"bind {addr}: only localhost or a private LAN address (10.x, 172.16-31.x, 192.168.x) is allowed")


def route_allowed(module: str, method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in COMPILED.get(module, ()))


def host_allowed(host_header: str, extra: list[str]) -> bool:
    """IP literals, localhost, this PC's own name (also .local) and configured names; anything else may be DNS rebinding."""
    h = (host_header or "").strip().lower()
    h = h[1:h.find("]")] if h.startswith("[") else h.rsplit(":", 1)[0]
    if not h: return False
    try: ipaddress.ip_address(h); return True
    except ValueError: pass
    own = socket.gethostname().lower()
    return h in {"localhost", own, own + ".local", *(x.lower() for x in extra)}


def load_config(path: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for k, v in user.items():
            if k == "modules":
                for m, mv in v.items():
                    if m in cfg["modules"]: cfg["modules"][m].update(mv)
            else: cfg[k] = v
    for k in ("certfile", "keyfile", "ca_file"):   # relative paths are relative to this folder, not the working directory
        if cfg.get(k) and not Path(cfg[k]).is_absolute(): cfg[k] = str(HERE / cfg[k])
    for m, mv in cfg["modules"].items():
        u = urlsplit(mv["url"])
        if u.scheme not in ("http", "https") or not u.hostname: raise SystemExit(f"modules.{m}.url: not an http(s) URL")
    return cfg


class Upstreams:
    """Plain HTTP(S) client for the module servers. A new connection per request: they are on this PC, and a
    stuck connection to one server then never affects another."""

    def __init__(self, cfg: dict):
        self.mods = cfg["modules"]
        self.ctx = ssl.create_default_context(cafile=cfg.get("ca_file")) if cfg.get("ca_file") else ssl.create_default_context()
        self.status = {m: {"ok": None, "error": None, "t": None, "ms": None} for m in self.mods}
        self.lock = threading.Lock()

    def request(self, module: str, method: str, path: str, query: str, body: bytes | None, ctype: str | None, gzip_ok: bool = False):
        u = urlsplit(self.mods[module]["url"]); timeout = GET_TIMEOUT if method == "GET" else POST_TIMEOUT
        conn = (http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=self.ctx) if u.scheme == "https"
                else http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout))
        headers = {"Host": u.netloc, "Accept": "*/*", **UPSTREAM_HEADERS.get(module, {})}
        if gzip_ok: headers["Accept-Encoding"] = "gzip"   # passed through untouched (MasterVolt's history is ~2.5 MB of JSON)
        if body is not None: headers["Content-Type"] = ctype or "application/json"
        t0 = time.monotonic()
        try:
            conn.request(method, (u.path.rstrip("/") + path) + (f"?{query}" if query else ""), body=body, headers=headers)
            r = conn.getresponse(); data = r.read()
            self._mark(module, True, None, t0)
            return (r.status, r.getheader("Content-Type") or "application/octet-stream", r.getheader("Content-Disposition"), data,
                    r.getheader("Content-Encoding"))
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            self._mark(module, False, f"{type(e).__name__}: {e}", t0); raise
        finally: conn.close()

    def _mark(self, module, ok, err, t0):
        with self.lock: self.status[module] = {"ok": ok, "error": err, "t": time.time(), "ms": round((time.monotonic() - t0) * 1000)}


def make_precheck(up: Upstreams):
    """Before a restart from the app: refuse while MasterVolt runs a BMS control or Float is latched, or while the anchor
    watch has an alarm. A server that does not answer at all is stuck or gone, so restarting it is allowed."""
    def get(module, path):
        code, _, _, data, _ = up.request(module, "GET", path, "", None, None)
        if code != 200: raise OSError(f"{path}: HTTP {code}")
        return json.loads(data)

    def check(name):
        try:
            if name == "energy":
                if (get("power", "/api/bms").get("control_status") or {}).get("busy"): raise ValueError("a BMS control is running: try again later")
                if (get("power", "/api/energy").get("high_soc_float_policy") or {}).get("float_latched"): raise ValueError("Float is latched: do not restart now")
            elif name == "anchor":
                alarms = get("anchor", "/api/state").get("alarms") or []
                if alarms: raise ValueError("anchor alarm active (" + ", ".join(a.get("text", "?") for a in alarms) + "): do not restart now")
        except ValueError: raise
        except Exception as e: log.warning("restart %s: pre-check not possible (%s); the server does not answer, restarting anyway", name, e)
    return check


def make_handler(cfg: dict, up: Upstreams, sup=None):
    extra_hosts = list(cfg.get("allowed_hosts") or [])
    systems = {m: {"name": mv["name"], "classic": mv.get("classic")} for m, mv in cfg["modules"].items()}

    class H(BaseHTTPRequestHandler):
        timeout = 30                 # a stalled client (or TLS handshake) only ties up its own thread
        protocol_version = "HTTP/1.1"

        def log_message(self, *a): pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json", cache: str = "no-store", extra: dict | None = None):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(body))); self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers()
            try: self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError): pass

        def _json(self, obj, code: int = 200): self._send(code, json.dumps(obj).encode())

        def _guard(self) -> bool:
            if not host_allowed(self.headers.get("Host", ""), extra_hosts):
                log.warning("blocked host %r for %s", self.headers.get("Host"), self.path); self._json({"error": "host not allowed"}, 403); return False
            return True

        def do_GET(self):
            if not self._guard(): return
            path, _, query = self.path.partition("?")
            if path.startswith("/api/") and path.count("/") >= 2 and path.split("/")[2] in up.mods:
                return self._proxy("GET", path, query)
            if path == "/api/systems":
                with up.lock: st = {m: dict(v) for m, v in up.status.items()}
                return self._json({"version": VERSION, "systems": systems, "upstream": st,
                                   "supervisor": sup.snapshot() if sup else {"enabled": False}})
            if path == "/": path = "/index.html"
            f = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() in f.parents and f.is_file() and f.suffix in STATIC_TYPES:
                cache = "no-cache" if f.suffix in (".html", ".js", ".css", ".webmanifest") else "max-age=86400"
                extra = {"Service-Worker-Allowed": "/"} if f.name == "sw.js" else None
                return self._send(200, f.read_bytes(), STATIC_TYPES[f.suffix], cache, extra)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._guard(): return
            path, _, query = self.path.partition("?")
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                log.warning("blocked origin %s for %s", origin, path); return self._json({"error": "cross-origin request rejected"}, 403)
            if self.headers.get("X-Drifter-Request") != "1": return self._json({"error": "request not sent by the Drifter page"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json": return self._json({"error": "json only"}, 415)
            if path == "/api/supervisor/restart": return self._restart()
            if not (path.startswith("/api/") and path.count("/") >= 2 and path.split("/")[2] in up.mods): return self._json({"error": "not found"}, 404)
            self._proxy("POST", path, query)

        def _restart(self):
            if not sup: return self._json({"error": "the supervisor is off"}, 409)
            n = int(self.headers.get("Content-Length") or 0)
            try: name = json.loads(self.rfile.read(min(n, MAX_BODY)) or b"{}").get("module")
            except (ValueError, AttributeError): return self._json({"error": "invalid JSON"}, 400)
            try: sup.restart(str(name))
            except ValueError as e: return self._json({"error": str(e)}, 409)
            log.info("restart of %s requested from the app", name); return self._json({"ok": True, "module": name}, 202)

        def _proxy(self, method: str, path: str, query: str):
            module = path.split("/")[2]; sub = path[len(f"/api/{module}"):] or "/"
            if not route_allowed(module, method, sub): return self._json({"error": "not found"}, 404)
            body = None
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY: return self._json({"error": "request too large"}, 413)
                body = self.rfile.read(n) if n else b"{}"
                try: json.loads(body)
                except ValueError: return self._json({"error": "invalid JSON"}, 400)
            gz = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
            try: code, ctype, disp, data, enc = up.request(module, method, sub, query, body, "application/json", gz)
            except Exception as e:
                return self._json({"error": f"{systems[module]['name']} not reachable", "detail": str(e), "upstream_down": True}, 502)
            if method == "POST": log.info("%s %s -> %d", module, sub, code)
            tile = sub.startswith(("/tiles/", "/vendor/"))
            extra = {k: v for k, v in (("Content-Disposition", disp), ("Content-Encoding", enc if gz else None)) if v}
            self._send(code, data, ctype, "max-age=86400" if tile and code == 200 else "no-store", extra or None)

    return H


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Phones dropping connections and clients that do not trust the certificate are normal, not crashes.
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)): return
        super().handle_error(request, client_address)


def serve(cfg: dict, supervisor=None) -> Server:
    check_bind(cfg["bind"])
    up = Upstreams(cfg)
    if supervisor is None and cfg.get("supervise"):
        from supervisor import Supervisor
        supervisor = Supervisor(precheck=make_precheck(up)); supervisor.start_thread()
    srv = Server((cfg["bind"], int(cfg["port"])), make_handler(cfg, up, supervisor))
    scheme = "http"
    if cfg.get("certfile"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cfg["certfile"], cfg["keyfile"])
        # Handshake in the request thread, not in accept(), so one slow client cannot block the others.
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False); scheme = "https"
    log.info("Drifter Boat Systems %s on %s://%s:%d/", VERSION, scheme, cfg["bind"], cfg["port"])
    return srv


def main():
    ap = argparse.ArgumentParser(description="Drifter Boat Systems gateway (one app for the boat's systems)")
    ap.add_argument("--config", default=str(HERE / "config.json"), help="config file (see config.example.json)")
    ap.add_argument("--bind", help="localhost or this PC's private LAN address (overrides the config)")
    ap.add_argument("--port", type=int, help="port (overrides the config)")
    a = ap.parse_args()
    log_file = None
    if sys.stderr is None:               # pythonw (scheduled task): no console, so log to logs/drifter.log
        (HERE / "logs").mkdir(exist_ok=True); log_file = HERE / "logs" / "drifter.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
                        **({"filename": log_file, "encoding": "utf-8"} if log_file else {}))
    cfg = load_config(Path(a.config))
    if a.bind: cfg["bind"] = a.bind
    if a.port: cfg["port"] = a.port
    if bool(cfg.get("certfile")) != bool(cfg.get("keyfile")): raise SystemExit("certfile and keyfile go together")
    srv = serve(cfg)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally: srv.server_close()


if __name__ == "__main__":
    main()
