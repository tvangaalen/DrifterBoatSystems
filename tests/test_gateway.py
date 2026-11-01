"""Gateway tests: route allowlist, host/origin/CSRF checks and passing requests on. Fake upstreams only, no boat."""
import http.client, json, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import drifter


class Recorder(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a): pass

    def _reply(self, body=None):
        n = int(self.headers.get("Content-Length") or 0); data = self.rfile.read(n) if n else b""
        Recorder.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": data})
        b = json.dumps(body or {"ok": True, "path": self.path}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self): self._reply()
    def do_POST(self): self._reply()


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Recorder); threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        u = f"http://127.0.0.1:{cls.up.server_address[1]}"
        cfg = drifter.load_config(drifter.Path("does-not-exist.json"))
        cfg.update(bind="127.0.0.1", port=0)
        for m in cfg["modules"].values(): m["url"] = u
        cfg["modules"]["anchor"]["url"] = "http://127.0.0.1:9"   # nothing listens: upstream down
        cls.gw = drifter.serve(cfg); threading.Thread(target=cls.gw.serve_forever, daemon=True).start()
        cls.port = cls.gw.server_address[1]

    @classmethod
    def tearDownClass(cls): cls.gw.shutdown(); cls.up.shutdown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if body is not None and "Content-Type" not in h: h["Content-Type"] = "application/json"
        c.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        r = c.getresponse(); data = r.read(); c.close(); return r.status, data

    def post(self, path, body=None, **extra):
        return self.req("POST", path, body if body is not None else {}, {"X-Drifter-Request": "1", **extra})

    def setUp(self): Recorder.seen.clear()

    def test_allowed_get_passes_on(self):
        code, data = self.req("GET", "/api/power/api/energy")
        self.assertEqual(code, 200); self.assertEqual(Recorder.seen[-1]["path"], "/api/energy")

    def test_unknown_route_is_404_and_not_sent(self):
        for path in ("/api/power/api/history/export", "/api/power/local-ca.cer", "/api/guard/", "/api/washer/api/program/abc", "/api/nope/x"):
            code, _ = self.req("GET", path); self.assertEqual(code, 404, path)
        code, _ = self.post("/api/power/api/bms/4/set-soc-100"); self.assertEqual(code, 404)   # only batteries 1-3
        code, _ = self.post("/api/power/api/bms/1/set-soc-50"); self.assertEqual(code, 404)    # a value goes in the body
        code, _ = self.post("/api/power/api/control/device/other"); self.assertEqual(code, 404)
        self.assertEqual(Recorder.seen, [])

    def test_soc_calibration_and_reports_pass(self):
        for path in ("/api/power/api/bms/2/set-soc-charge", "/api/power/api/bms/set-all-soc/value", "/api/power/api/reports/battery-health"):
            code, _ = self.post(path, {"percent": 80} if path.endswith("value") else {}); self.assertEqual(code, 200, path)
        for path in ("/api/power/manual", "/api/power/api/history/status", "/api/power/api/version"):
            self.assertEqual(self.req("GET", path)[0], 200, path)

    def test_get_is_not_a_command(self):
        code, _ = self.req("GET", "/api/power/api/control/inverter"); self.assertEqual(code, 404)

    def test_post_needs_marker_header(self):
        code, _ = self.req("POST", "/api/guard/api/test", {}); self.assertEqual(code, 403); self.assertEqual(Recorder.seen, [])

    def test_post_needs_json(self):
        code, _ = self.req("POST", "/api/guard/api/test", None, {"X-Drifter-Request": "1", "Content-Type": "text/plain"}); self.assertEqual(code, 415)
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.request("POST", "/api/guard/api/test", body=b"not json",
            headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-Drifter-Request": "1"})
        self.assertEqual(c.getresponse().status, 400); self.assertEqual(Recorder.seen, [])

    def test_cross_origin_post_rejected(self):
        code, _ = self.post("/api/guard/api/enabled", {"enabled": False}, Origin="http://evil.example"); self.assertEqual(code, 403)
        code, _ = self.post("/api/guard/api/enabled", {"enabled": False}, Origin=f"http://127.0.0.1:{self.port}"); self.assertEqual(code, 200)

    def test_rebinding_host_rejected(self):
        code, _ = self.req("GET", "/api/power/api/energy", headers={"Host": "attacker.example"}); self.assertEqual(code, 403)
        code, _ = self.req("GET", "/", headers={"Host": "attacker.example"}); self.assertEqual(code, 403)
        self.assertEqual(Recorder.seen, [])

    def test_upstream_host_and_washer_marker(self):
        self.post("/api/washer/api/start")
        h = Recorder.seen[-1]["headers"]
        self.assertEqual(h["Host"], f"127.0.0.1:{self.up.server_address[1]}"); self.assertEqual(h["X-Viomi-Request"], "1")
        self.assertNotIn("Origin", h); self.assertNotIn("X-Drifter-Request", h)
        self.post("/api/guard/api/test"); self.assertNotIn("X-Viomi-Request", Recorder.seen[-1]["headers"])

    def test_body_and_query_passed(self):
        self.post("/api/power/api/control/ac-limit", {"amps": 8})
        self.assertEqual(json.loads(Recorder.seen[-1]["body"]), {"amps": 8})
        self.req("GET", "/api/anchor/api/track?since=5&gen=2")   # anchor is down here
        self.req("GET", "/api/guard/api/log?n=50"); self.assertEqual(Recorder.seen[-1]["path"], "/api/log?n=50")

    def test_upstream_down_is_502(self):
        code, data = self.req("GET", "/api/anchor/api/state")
        self.assertEqual(code, 502); self.assertTrue(json.loads(data)["upstream_down"])
        code, data = self.req("GET", "/api/systems"); st = json.loads(data)["upstream"]
        self.assertFalse(st["anchor"]["ok"])

    def test_static_files_and_no_traversal(self):
        code, data = self.req("GET", "/"); self.assertEqual(code, 200); self.assertIn(b"Drifter", data)
        for p in ("/../drifter.py", "/%2e%2e/drifter.py", "/static/../drifter.py", "/config.json"):
            code, _ = self.req("GET", p); self.assertEqual(code, 404, p)

    def test_check_bind(self):
        for ok in ("127.0.0.1", "192.168.1.166", "10.0.0.2"): drifter.check_bind(ok)
        for bad in ("0.0.0.0", "8.8.8.8", "169.254.1.1"):
            with self.assertRaises(SystemExit): drifter.check_bind(bad)

    def test_host_allowed(self):
        self.assertTrue(drifter.host_allowed("192.168.1.166:8100", [])); self.assertTrue(drifter.host_allowed("localhost:8100", []))
        self.assertTrue(drifter.host_allowed("[::1]:8100", [])); self.assertTrue(drifter.host_allowed("boat.lan", ["boat.lan"]))
        self.assertFalse(drifter.host_allowed("boat.lan", [])); self.assertFalse(drifter.host_allowed("", []))


if __name__ == "__main__":
    unittest.main()
