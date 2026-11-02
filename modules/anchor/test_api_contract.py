"""The anchor watch's HTTP API as the Drifter app sees it: state, track, commands (with every error path) and map
tiles, with a fake watch and fake tiles. ApiContract runs against an implementation through make(watch, tiles) -> call;
it passed against the stdlib server of 1.17 and the FastAPI package (2.0). The alarm logic behind it is covered by
test_anchor_watch.py, which runs unchanged against the package."""
import json, unittest

SENTINEL = object()


class FakeWatch:
    def __init__(self): self.commands = []
    def state(self): return {"anchor": None, "alarms": [], "odd": SENTINEL}          # not JSON-serialisable: sent as null
    def track_since(self, t, gen): return {"gen": 1, "points": [[t, gen]]}
    def command(self, c):
        if c.get("action") == "bad": raise ValueError("Unknown action 'bad'")
        if c.get("action") == "boom": raise KeyError("lost")
        self.commands.append(c)


class FakeTiles:
    def get(self, layer, z, x, y): return (b"PNG" + bytes([z]), "image/png") if layer == "osm" else (b"JPG", "image/jpeg") if layer == "satellite" and z < 18 else None


class ApiContract:
    """make(watch, tiles) -> call(method, path, body=None) -> (status, content type, cache-control, bytes)."""

    def setUp(self):
        self.watch = FakeWatch(); self.call = self.make(self.watch, FakeTiles())

    def js(self, method, path, body=None):
        code, ctype, cache, data = self.call(method, path, body)
        self.assertTrue(ctype.startswith("application/json"), (path, ctype)); return code, json.loads(data), cache

    def test_state(self):
        code, j, cache = self.js("GET", "/api/state")
        self.assertEqual((code, j, cache), (200, {"anchor": None, "alarms": [], "odd": None}, "no-store"))

    def test_track(self):
        self.assertEqual(self.js("GET", "/api/track?since=12.5&gen=3")[:2], (200, {"gen": 1, "points": [[12.5, 3]]}))
        self.assertEqual(self.js("GET", "/api/track")[:2], (200, {"gen": 1, "points": [[0.0, -1]]}))
        self.assertEqual(self.js("GET", "/api/track?since=abc")[:2], (400, {"error": "bad query"}))

    def test_tiles(self):
        self.assertEqual(self.call("GET", "/tiles/osm/16/100/200.png", None), (200, "image/png", "max-age=86400", b"PNG\x10"))
        self.assertEqual(self.call("GET", "/tiles/satellite/16/100/200.jpg", None)[:3], (200, "image/jpeg", "max-age=86400"))
        code, _, cache, data = self.call("GET", "/tiles/satellite/18/100/200.jpg", None)
        self.assertEqual((code, cache, data), (404, "max-age=300", b""))
        for p in ("/tiles/nope/16/1/2.png", "/tiles/osm/123/1/2.png", "/tiles/osm/1/2/3.gif", "/"):
            self.assertEqual(self.call("GET", p, None)[0], 404, p)

    def test_command(self):
        code, j, _ = self.js("POST", "/api/command", {"action": "silence", "minutes": 5})
        self.assertEqual((code, j["ok"], j["state"]["alarms"]), (200, True, [])); self.assertEqual(self.watch.commands[-1], {"action": "silence", "minutes": 5})
        self.assertEqual(self.js("POST", "/api/command", {"action": "bad"})[:2], (400, {"ok": False, "error": "Unknown action 'bad'"}))
        self.assertEqual(self.js("POST", "/api/command", {"action": "boom"})[:2], (500, {"ok": False, "error": "KeyError: 'lost'"}))
        self.assertEqual(self.js("POST", "/api/command", "x" * 10001)[:2], (400, {"ok": False, "error": "request too large"}))
        code, j, _ = self.js("POST", "/api/command", "{not json"); self.assertEqual((code, j["ok"]), (400, False))
        self.assertEqual(self.call("POST", "/api/other", {})[0], 404)
        self.assertEqual(len(self.watch.commands), 1)


if __name__ == "__main__":
    unittest.main()
