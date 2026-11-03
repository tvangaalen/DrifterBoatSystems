"""Drifter Boat Systems: one web app for the boat's systems (energy, anchor watch, BoatGuard, washer).

The gateway serves the app and passes the page's requests on to the four existing servers, which keep running
unchanged and keep all their own logic (Float protection, anchor alarm, arming, washer schedule). The gateway makes
no decisions and talks to no hardware itself. With "supervise" on (the live setting) the System page talks to drifterd,
the service that runs and keeps running every server (DrifterdClient below): states, logs, restart and switch-off,
after this gateway's pre-checks.

Safety:
- Only routes listed in ROUTES are passed on (method + path pattern per module); everything else gets 404.
- Binds only to localhost or a private (RFC 1918) address (`check_bind`). No login: never expose it to the internet.
- Requests must address the gateway by IP, localhost, this PC's name or a configured name (blocks DNS rebinding).
- A POST must be JSON and carry `X-Drifter-Request: 1` from the gateway's own origin, so another web page in a
  browser on the boat Wi-Fi cannot send commands through it (a custom header needs a CORS preflight, never approved).
Stdlib only.
"""
from __future__ import annotations

import argparse, http.client, json, logging, os, re, ssl, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from common import logs, pushover
from common.net import check_bind, host_allowed, same_origin   # noqa: F401  (check_bind/host_allowed: also used by the tests)
from common.pushover import KEY_RE
from common.web import QuietServer as Server, tls_context, use_tls

VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE / "tools"))              # tools/backup.py for "Backup keys and tokens"
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
# Every upstream request carries the module token (common/service.py), added after the gateway's own checks; drifterd
# gives it in DRIFTER_TOKEN. Modules not yet on the module contract ignore it.
TOKEN_HEADER = "X-Drifter-Token"
GET_TIMEOUT, POST_TIMEOUT = 12, 90   # BMS/MOSFET writes over Bluetooth and the camera test can take long
MAX_BODY = 64 * 1024
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".webmanifest": "application/manifest+json", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json"}
DEFAULT_CONFIG = {
    "bind": "127.0.0.1", "port": 8100, "allowed_hosts": [],
    "certfile": None, "keyfile": None, "ca_file": None,
    "supervise": False,   # the System page talks to drifterd (the service); only the live config turns it on
    "drifterd": "http://127.0.0.1:8099", "drifterd_token": "C:/DrifterData/drifterd.token",
    "alerts_pushover": None,   # Pushover keys for the watchdog; default <DRIFTER_DATA>\\gateway\\pushover.json (live only)
    "modules": {
        "power": {"name": "Energy", "url": "http://127.0.0.1:8000", "classic": None},
        "anchor": {"name": "Anchor watch", "url": "http://127.0.0.1:8766", "classic": None},
        "guard": {"name": "BoatGuard", "url": "http://127.0.0.1:8095", "classic": None},
        "washer": {"name": "Washer", "url": "http://127.0.0.1:8080", "classic": None},
    },
}


def route_allowed(module: str, method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in COMPILED.get(module, ()))


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
        self.mods = cfg["modules"]; self.token = os.environ.get("DRIFTER_TOKEN", "")
        self.ctx = ssl.create_default_context(cafile=cfg.get("ca_file")) if cfg.get("ca_file") else ssl.create_default_context()
        self.status = {m: {"ok": None, "error": None, "t": None, "ms": None} for m in self.mods}
        self.lock = threading.Lock()

    def request(self, module: str, method: str, path: str, query: str, body: bytes | None, ctype: str | None, gzip_ok: bool = False):
        u = urlsplit(self.mods[module]["url"]); timeout = GET_TIMEOUT if method == "GET" else POST_TIMEOUT
        conn = (http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=self.ctx) if u.scheme == "https"
                else http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout))
        headers = {"Host": u.netloc, "Accept": "*/*", TOKEN_HEADER: self.token}
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


class Watchdog:
    """A push message (Pushover) when a system has not been running, or not answering its health check, for DOWN_S, and
    one when it is back. It only reads drifterd's status every CHECK_S: it never restarts, stops or commands anything.
    Quiet while the user switched everything off and for a module on hold. The keys are {"token", "user"} in
    <DRIFTER_DATA>\\gateway\\pushover.json (`alerts_pushover` in config.json); without them it only logs."""
    DOWN_S, CHECK_S = 300, 60
    NAMES = {"energy": "Energy", "anchor": "Anchor watch", "guard": "BoatGuard", "washer": "Washer"}
    WHY = {"energy": "Float protection and the battery connections are off while it is down.",
           "anchor": "The anchor alarm and its push alerts are off while it is down."}
    HIGH = {"energy", "anchor"}                          # Pushover priority 1: sounds even in quiet hours

    def __init__(self, sup, key_file, clock=time.time, send=None):
        self.sup, self.key_file, self.clock = sup, Path(key_file), clock
        self.send = send or self._post
        self.down: dict[str, float] = {}; self.alerted: set[str] = set(); self.error = None

    def keys(self) -> dict | None:
        try: k = json.loads(self.key_file.read_text(encoding="utf-8"))
        except (OSError, ValueError): return None
        return k if all(KEY_RE.match(str(k.get(f, ""))) for f in ("token", "user")) else None

    def _post(self, title: str, message: str, priority: int) -> None:
        k = self.keys()
        if not k: log.warning("alert not sent (no Pushover keys in %s): %s", self.key_file, message); return
        try: pushover.post("messages.json", {"token": k["token"], "user": k["user"], "title": title, "message": message,
                                             "priority": priority}, agent=f"Drifter/{VERSION}"); self.error = None
        except (OSError, pushover.PushoverError) as e: self.error = str(e); log.warning("alert not sent: %s", e)

    def check(self) -> None:
        snap = self.sup.snapshot(); now = self.clock()
        if snap.get("error"): return                     # drifterd not reachable: nothing reliable to say
        if (snap.get("shutdown") or {}).get("state") in ("running", "done"): self.down.clear(); return
        for name, m in (snap.get("modules") or {}).items():
            bad = not m.get("held") and (m.get("state") != "running" or (m.get("health") or {}).get("ok") is False)
            title = self.NAMES.get(name, name)
            if bad:
                since = self.down.setdefault(name, now)
                if name not in self.alerted and now - since >= self.DOWN_S:
                    self.alerted.add(name)
                    what = "is not running" if m.get("state") != "running" else "is not answering"
                    self.send(f"Drifter: {title} down", f"{title} {what} since {time.strftime('%H:%M', time.localtime(since))}. "
                              f"{self.WHY.get(name, '')} Drifter keeps trying to start it.".replace("  ", " "), 1 if name in self.HIGH else 0)
            else:
                since = self.down.pop(name, None)
                if name in self.alerted:
                    self.alerted.discard(name)
                    self.send(f"Drifter: {title} back", f"{title} is running again (down {round((now - since) / 60)} min).", 0)

    def test(self) -> None:
        if not self.keys(): raise ValueError(f"no Pushover keys in {self.key_file}")
        self._post("Drifter: test", "Alerts from Drifter Boat Systems reach this phone.", 0)
        if self.error: raise ValueError(self.error)

    def status(self) -> dict:
        return {"configured": self.keys() is not None, "file": str(self.key_file), "error": self.error,
                "down": sorted(self.alerted), "after_min": self.DOWN_S // 60}

    def start(self) -> None:
        def loop():
            while True:
                time.sleep(self.CHECK_S)
                try: self.check()
                except Exception: log.exception("watchdog")
        threading.Thread(target=loop, daemon=True, name="watchdog").start()
        log.info("alerts: %s", "Pushover ready" if self.keys() else f"no Pushover keys in {self.key_file}: alerts are only logged")


def make_precheck(up: Upstreams):
    """Before a restart from the app: refuse while MasterVolt runs a BMS control or Float is latched, or while the anchor
    watch has an alarm. Before "switch all systems off" (why="shutdown") a latched Float does not count: the user may
    simply switch everything off. A server that does not answer at all is stuck or gone, so stopping it is allowed."""
    def get(module, path):
        code, _, _, data, _ = up.request(module, "GET", path, "", None, None)
        if code != 200: raise OSError(f"{path}: HTTP {code}")
        return json.loads(data)

    def check(name, why="restart"):
        try:
            if name == "energy":
                if (get("power", "/api/bms").get("control_status") or {}).get("busy"): raise ValueError("a BMS control is running: try again later")
                if why != "shutdown" and (get("power", "/api/energy").get("high_soc_float_policy") or {}).get("float_latched"):
                    raise ValueError("Float is latched: do not restart now")
            elif name == "anchor":
                alarms = get("anchor", "/api/state").get("alarms") or []
                if alarms: raise ValueError("anchor alarm active (" + ", ".join(a.get("text", "?") for a in alarms) + "): do not restart now")
        except ValueError: raise
        except Exception as e: log.warning("restart %s: pre-check not possible (%s); the server does not answer, restarting anyway", name, e)
    return check


class DrifterdClient:
    """The supervisor as the System page sees it, through drifterd's control API (127.0.0.1:8099, token file). Same
    methods as supervisor.Supervisor, which the mock and the tests use in-process instead."""

    def __init__(self, url: str, token_file: Path, precheck, modules=("energy", "anchor", "guard", "washer")):
        self.url, self.token_file, self.precheck, self.modules = url.rstrip("/"), Path(token_file), precheck, modules

    def _call(self, method: str, path: str, body=None, timeout: float = 15):
        req = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json", "X-Drifterd-Token": self.token_file.read_text(encoding="ascii").strip()})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except ValueError: return e.code, {"error": f"HTTP {e.code}"}

    def snapshot(self) -> dict:
        try:
            code, j = self._call("GET", "/status")
            if code == 200: return {"enabled": True, **j}
            err = j.get("error", f"HTTP {code}")
        except (OSError, ValueError) as e: err = str(e)
        return {"enabled": True, "modules": {}, "events": [], "shutdown": None, "error": f"drifterd (the Drifter service) not reachable: {err}"}

    def _post(self, path: str, body: dict) -> dict:
        try: code, j = self._call("POST", path, body)
        except (OSError, ValueError) as e: raise ValueError(f"drifterd (the Drifter service) not reachable: {e}")
        if code >= 400: raise ValueError(j.get("error", f"HTTP {code}"))
        return j

    def restart(self, name: str) -> None:
        if name != "gateway": self.precheck(name)
        self._post("/restart", {"module": name})

    def shutdown_all(self, on_done=None) -> None:
        for n in self.modules: self.precheck(n, "shutdown")
        self._post("/shutdown", {})

    def log_tail(self, name: str, lines: int = 400) -> dict:
        try: code, j = self._call("GET", f"/log?module={name}&lines={int(lines)}")
        except (OSError, ValueError) as e: raise ValueError(f"drifterd (the Drifter service) not reachable: {e}")
        if code != 200: raise ValueError(j.get("error", f"HTTP {code}"))
        return j


def backup_info() -> dict | None:
    """Where "Backup keys and tokens" copies to and when it last did (tools/backup.py), for the System page."""
    try:
        import backup
        c = backup.config(); return {"dest": str(c["dest"]), "count": len(c["files"]), "last": backup.last_copy(c["dest"], c["files"])}
    except Exception as e:                                # the page must never fail because of this
        log.warning("back-up info: %s", e); return None


def make_handler(cfg: dict, up: Upstreams, sup=None, dog=None):
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
            if path == "/api/supervisor/log":                   # the module's log file, for the app's log window
                if not sup: return self._json({"error": "the supervisor is off"}, 409)
                q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                try: return self._json(sup.log_tail(q.get("module", ""), int(q.get("lines", 400))))
                except ValueError as e: return self._json({"error": str(e)}, 404)
            if path == "/api/systems":
                with up.lock: st = {m: dict(v) for m, v in up.status.items()}
                return self._json({"version": VERSION, "systems": systems, "upstream": st,
                                   "supervisor": sup.snapshot() if sup else {"enabled": False}, "backup": backup_info(),
                                   "alerts": dog.status() if dog else None})
            if path == "/": path = "/index.html"
            f = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() in f.parents and f.is_file() and f.suffix in STATIC_TYPES:
                cache = "no-cache" if f.suffix in (".html", ".js", ".css", ".webmanifest") else "max-age=86400"
                extra = {"Service-Worker-Allowed": "/"} if f.name == "sw.js" else None
                return self._send(200, f.read_bytes(), STATIC_TYPES[f.suffix], cache, extra)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            # Read the body before any answer, also a refusal: closing with unread data resets the connection, and the
            # browser then sees a network error instead of the reason.
            try: n = int(self.headers.get("Content-Length") or 0)
            except ValueError: n = -1
            if n < 0 or n > MAX_BODY: self.close_connection = True; return self._json({"error": "request too large" if n > 0 else "bad Content-Length"}, 413 if n > 0 else 400)
            self._body = self.rfile.read(n) if n else b""
            if not self._guard(): return
            path, _, query = self.path.partition("?")
            origin = self.headers.get("Origin")
            if not same_origin(origin, self.headers.get("Host")):
                log.warning("blocked origin %s for %s", origin, path); return self._json({"error": "cross-origin request rejected"}, 403)
            if self.headers.get("X-Drifter-Request") != "1": return self._json({"error": "request not sent by the Drifter page"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json": return self._json({"error": "json only"}, 415)
            if path == "/api/supervisor/restart": return self._restart()
            if path == "/api/supervisor/shutdown": return self._shutdown()
            if path == "/api/backup-keys": return self._backup_keys()
            if path == "/api/alerts/test": return self._alert_test()
            if not (path.startswith("/api/") and path.count("/") >= 2 and path.split("/")[2] in up.mods): return self._json({"error": "not found"}, 404)
            self._proxy("POST", path, query)

        def _restart(self):
            if not sup: return self._json({"error": "the supervisor is off"}, 409)
            try: name = json.loads(self._body or b"{}").get("module")
            except (ValueError, AttributeError): return self._json({"error": "invalid JSON"}, 400)
            try: sup.restart(str(name))
            except ValueError as e: return self._json({"error": str(e)}, 409)
            log.info("restart of %s requested from the app", name); return self._json({"ok": True, "module": name}, 202)

        def _alert_test(self):
            if not dog: return self._json({"error": "alerts run only on the boat PC's live app"}, 409)
            try: dog.test()
            except ValueError as e: return self._json({"error": str(e)}, 409)
            return self._json({"ok": True})

        def _backup_keys(self):
            """The System page's "Backup keys and tokens": copies the key files to the back-up folder (tools/backup.py).
            Only where the gateway runs the live system (supervise on): a mock or test gateway never copies real keys."""
            if not cfg.get("supervise"): return self._json({"error": "only on the boat PC's live app"}, 409)
            import backup
            c = backup.config(); r = backup.copy_keys(backup.M.DATA, c["files"], c["dest"])
            log.info("keys and tokens copied to %s: %d of %d%s", r["dest"], len(r["copied"]), len(c["files"]),
                     "".join(f"; {m['file']} not copied ({m['error']})" for m in r["missing"]))
            return self._json({"ok": not r["missing"], **r}, 200 if r["copied"] else 500)

        def _shutdown(self):
            """Switch all systems off: every module server stops, then the gateway itself (see serve)."""
            if not sup: return self._json({"error": "the supervisor is off"}, 409)
            try: sup.shutdown_all()   # drifterd ends this gateway itself, 15 s after the modules
            except ValueError as e: return self._json({"error": str(e)}, 409)
            log.warning("switch all systems off requested from the app"); return self._json({"ok": True}, 202)


        def _proxy(self, method: str, path: str, query: str):
            module = path.split("/")[2]; sub = path[len(f"/api/{module}"):] or "/"
            if not route_allowed(module, method, sub): return self._json({"error": "not found"}, 404)
            body = None
            if method == "POST":
                body = self._body or b"{}"
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


def serve(cfg: dict, supervisor=None) -> Server:
    check_bind(cfg["bind"])
    up = Upstreams(cfg)
    if supervisor is None and cfg.get("supervise"):
        supervisor = DrifterdClient(cfg["drifterd"], Path(cfg["drifterd_token"]), make_precheck(up))
    dog = None
    if cfg.get("supervise") and supervisor is not None:   # the live gateway only: a mock never sends alerts
        key = cfg.get("alerts_pushover") or Path(os.environ.get("DRIFTER_DATA") or "C:/DrifterData") / "gateway" / "pushover.json"
        dog = Watchdog(supervisor, key); dog.start()
    srv = Server((cfg["bind"], int(cfg["port"])), make_handler(cfg, up, supervisor, dog))
    scheme = "http"
    if cfg.get("certfile"): use_tls(srv, tls_context(cfg["certfile"], cfg["keyfile"])); scheme = "https"
    log.info("Drifter Boat Systems %s on %s://%s:%d/", VERSION, scheme, cfg["bind"], cfg["port"])
    return srv


def main():
    ap = argparse.ArgumentParser(description="Drifter Boat Systems gateway (one app for the boat's systems)")
    ap.add_argument("--config", default=str(HERE / "config.json"), help="config file (see config.example.json)")
    ap.add_argument("--bind", help="localhost or this PC's private LAN address (overrides the config)")
    ap.add_argument("--port", type=int, help="port (overrides the config)")
    a = ap.parse_args()
    logs.setup(file=HERE / "logs" / "drifter.log" if sys.stderr is None else None)   # pythonw (scheduled task): no console
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
