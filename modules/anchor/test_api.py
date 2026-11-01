"""Anchor watch HTTP API without a Core: no page any more, state/track/command and tiles still served. Fake watch only."""
import http.client, json, threading, unittest
from http.server import ThreadingHTTPServer

import anchor_watch as A


class FakeWatch:
    def __init__(self): self.commands = []
    def state(self): return {"anchor": None, "alarms": []}
    def track_since(self, t, gen): return {"gen": 1, "points": []}
    def command(self, c):
        if c.get("action") == "bad": raise ValueError("Unknown action 'bad'")
        self.commands.append(c)


class FakeTiles:
    def get(self, layer, z, x, y): return (b"PNG", "image/png") if layer == "osm" else None


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.watch = FakeWatch()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), A.make_handler(cls.watch, FakeTiles()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request(method, path, body=None if body is None else json.dumps(body), headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, d

    def test_no_page_or_static_files(self):
        for p in ("/", "/manifest.webmanifest", "/apple-touch-icon.png", "/vendor/leaflet/leaflet.js", "/icons/logo.svg"):
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_api_and_tiles(self):
        self.assertEqual(json.loads(self.req("GET", "/api/state")[1])["alarms"], [])
        self.assertEqual(json.loads(self.req("GET", "/api/track?since=0&gen=-1")[1])["gen"], 1)
        self.assertEqual(self.req("GET", "/tiles/osm/16/100/200.png"), (200, b"PNG"))
        self.assertEqual(self.req("GET", "/tiles/satellite/16/100/200.jpg")[0], 404)

    def test_command(self):
        code, d = self.req("POST", "/api/command", {"action": "silence", "minutes": 5})
        self.assertEqual(code, 200); self.assertTrue(json.loads(d)["ok"]); self.assertEqual(self.watch.commands[-1]["action"], "silence")
        code, d = self.req("POST", "/api/command", {"action": "bad"}); self.assertEqual(code, 400); self.assertIn("Unknown action", json.loads(d)["error"])

    def test_bind_checks(self):
        for ok in ("127.0.0.1", "192.168.1.166"): A.check_bind(ok)
        for bad in ("0.0.0.0", "8.8.8.8"):
            with self.assertRaises(SystemExit): A.check_bind(bad)


if __name__ == "__main__":
    unittest.main()
