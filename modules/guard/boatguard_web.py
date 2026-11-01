"""BoatGuard API for the Drifter app: status, log, monitoring on/off, settings, notification tests and a camera test.

Since 2026-11-01 the page is in Drifter Boat Systems (the Guard module); this server has no page of its own and listens
on localhost only, port `web.port` (default 8095). `web.host` may add one private LAN address on purpose.
The certificate (certs/boatguard-*.pem, made by setup_https.ps1) is signed by the Mastervolt Local CA that the
iPhone already trusts for YMS. Without it the page falls back to plain HTTP and says so in the log.
Stdlib only: no extra packages.
"""
from __future__ import annotations

import ipaddress, json, logging, os, ssl, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["DRIFTER_DATA"].strip()) / "guard" if os.environ.get("DRIFTER_DATA", "").strip() else HERE  # same rule as boatguard.py
LOG = DATA / "logs" / "boatguard.log"
CERT, KEY = HERE / "certs" / "boatguard-cert.pem", HERE / "certs" / "boatguard-key.pem"
log = logging.getLogger("boatguard")


def tail(path: Path, n: int) -> list[str]:
    try: lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError: return []
    return lines[-n:]


def make_handler(guard):
    last_test: dict = {}

    def run_test():
        last_test.clear(); last_test.update(guard.test(), finished=time.time())

    class H(BaseHTTPRequestHandler):
        timeout = 30  # a stalled client (or TLS handshake) can't hold a thread forever

        def log_message(self, *a): pass  # keep the BoatGuard log for events, not page loads

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode())

        def do_GET(self):
            path, _, q = self.path.partition("?")
            if path == "/api/status":
                return self._json(dict(guard.status(), camera=guard.camera_status(), last_test=last_test or None))
            if path == "/api/log":
                n = int(q.split("n=")[1]) if "n=" in q else 200
                return self._json({"lines": tail(LOG, max(1, min(n, 2000)))})
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            # JSON body required: a plain cross-site form post can't send application/json without a CORS preflight.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json": return self._json({"error": "json only"}, 415)
            try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError: return self._json({"error": "invalid JSON"}, 400)
            if self.path == "/api/enabled":
                guard.set_enabled(bool(body.get("enabled"))); return self._json({"enabled": guard.enabled})
            if self.path == "/api/settings":
                try: return self._json(guard.update_settings(body))
                except ValueError as e: return self._json({"error": str(e)}, 400)
            if self.path == "/api/notify-test":
                try: return self._json({"sent": guard.notify_test(str(body.get("event")), str(body.get("sound", "")), body.get("priority"))})
                except ValueError as e: return self._json({"error": str(e)}, 400)
            if self.path == "/api/test":
                if guard.test_running: return self._json({"error": "test already running"}, 409)
                if guard.armed_by_us: return self._json({"error": "camera is armed by BoatGuard (phone away); test not possible now"}, 409)
                threading.Thread(target=run_test, daemon=True).start(); return self._json({"started": True})
            self._json({"error": "not found"}, 404)

    return H


def tls_context() -> ssl.SSLContext | None:
    if not (CERT.exists() and KEY.exists()): return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT, KEY); return ctx


def serve(guard, cfg: dict) -> None:
    w = cfg.get("web", {})
    if w.get("enabled", True) is False: return
    port = w.get("port", 8095)
    hosts = {"127.0.0.1"}                       # only the Drifter gateway on this PC uses the API
    if w.get("host"):
        try:
            ip = ipaddress.ip_address(w["host"])
            if ip.is_private and not ip.is_loopback and not ip.is_unspecified and not ip.is_link_local: hosts.add(str(ip))
            else: log.warning("web: %s is not a private LAN address; serving on localhost only", ip)
        except ValueError: log.warning("web: host %r is not an IP address; serving on localhost only", w["host"])
    try: ctx = tls_context()
    except (OSError, ssl.SSLError) as e: ctx = None; log.error("web: certificate not usable (%s)", e)
    if ctx is None: log.warning("web: no HTTPS certificate, serving plain HTTP (run setup_https.ps1)")
    handler = make_handler(guard)
    for h in sorted(hosts):
        try: srv = ThreadingHTTPServer((h, port), handler)
        except OSError as e: log.error("web: cannot listen on %s:%d: %s", h, port, e); continue
        # Handshake in the request thread, not in the accept loop, so one slow client can't block the page.
        if ctx: srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
        threading.Thread(target=srv.serve_forever, daemon=True, name=f"web-{h}").start()
        log.info("web on %s://%s:%d/", "https" if ctx else "http", h, port)
