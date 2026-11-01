"""BoatGuard API tests with a fake guard (no router, no camera, no Pushover): no page, JSON-only commands, localhost bind."""
import http.client, json, logging, ssl, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boatguard_web as W  # noqa: E402


class FakeGuard:
    enabled, test_running, armed_by_us = True, False, False
    def __init__(self): self.calls = []
    def status(self): return {"enabled": self.enabled, "present": True}
    def camera_status(self): return {"armed": False}
    def set_enabled(self, on): self.calls.append(("enabled", on)); self.enabled = on


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = FakeGuard(); cls.records = []
        h = logging.Handler(); h.emit = lambda r: cls.records.append(r.getMessage()); W.log.addHandler(h); W.log.setLevel(logging.INFO)
        W.tls_context = lambda: None                     # plain HTTP for the test
        W.serve(cls.guard, {"web": {"port": 0}})
        line = next(m for m in cls.records if m.startswith("web on "))
        cls.host, cls.port = line.rsplit("/", 2)[-2].replace("http://", "").rsplit(":", 1)[0], None
        cls.listening = [m for m in cls.records if m.startswith("web on ")]

    def test_localhost_only_by_default(self):
        self.assertEqual(len(self.listening), 1); self.assertIn("127.0.0.1", self.listening[0])

    def test_public_or_odd_host_refused(self):
        self.records.clear(); W.serve(self.guard, {"web": {"port": 0, "host": "8.8.8.8"}})
        self.assertTrue(any("not a private LAN address" in m for m in self.records))
        self.assertEqual([m for m in self.records if m.startswith("web on ")], ["web on http://127.0.0.1:0/"])

    def request(self, method, path, body=None, ctype="application/json"):
        srv = W.ThreadingHTTPServer(("127.0.0.1", 0), W.make_handler(self.guard))
        import threading; threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        c.request(method, path, body=body, headers={"Content-Type": ctype} if body is not None else {})
        r = c.getresponse(); d = r.read(); srv.shutdown(); return r.status, d

    def test_no_page(self):
        for p in ("/", "/index.html"): self.assertEqual(self.request("GET", p)[0], 404)

    def test_status_and_commands(self):
        code, d = self.request("GET", "/api/status"); self.assertEqual(code, 200); self.assertTrue(json.loads(d)["enabled"])
        self.assertEqual(self.request("POST", "/api/enabled", "enabled=0", "application/x-www-form-urlencoded")[0], 415)
        self.assertEqual(self.request("POST", "/api/enabled", json.dumps({"enabled": False}))[0], 200)
        self.assertIn(("enabled", False), self.guard.calls)


if __name__ == "__main__":
    unittest.main()
