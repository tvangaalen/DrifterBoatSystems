"""The BoatGuard package (2.x): the API contract of test_api_contract.py, Drifter's module contract (token, /health) and
the configuration schema. Fake router, camera, notifier and clock: nothing reaches the router, the camera or Pushover."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient  # noqa: E402

from test_api_contract import CFG, ApiContract, Cam, Notifier, folder  # noqa: E402
from guard import VERSION, config  # noqa: E402
from guard.api import create_app  # noqa: E402
from guard.core import Guard  # noqa: E402

TOKEN = "g" * 48
H = {"X-Drifter-Token": TOKEN}


def build(d, cam, seen, t, note):
    g = Guard(config.load(d / "config.json"), cam, d / "state.json", d / "config.json", stations=lambda c: seen[0], clock=lambda: t[0], notifier=note)
    return g, TestClient(create_app(g, d / "logs" / "boatguard.log", token=TOKEN))


class GuardContract(ApiContract, unittest.TestCase):
    def make(self, d, cam, seen, t, note):
        g, client = build(d, cam, seen, t, note)

        def get(path):
            r = client.get(path, headers=H); return r.status_code, r.json()

        def post(path, body=None, ctype="application/json"):
            data = body if isinstance(body, str) else json.dumps(body if body is not None else {})
            r = client.post(path, headers={**H, "Content-Type": ctype}, content=data); return r.status_code, r.json()

        return get, post, g


class ModuleContractTest(unittest.TestCase):
    def test_token_and_health(self):
        g, client = build(folder(), Cam(), [set()], [1000.0], Notifier())
        for headers in ({}, {"X-Drifter-Token": "wrong"}):
            self.assertEqual(client.get("/api/status", headers=headers).status_code, 403)
            self.assertEqual(client.post("/api/enabled", headers=headers, json={"enabled": False}).status_code, 403)
        self.assertTrue(g.enabled)
        r = client.get("/health"); self.assertEqual((r.status_code, r.json()["module"], r.json()["version"]), (200, "guard", VERSION))
        for path in ("/", "/docs", "/openapi.json"): self.assertEqual(client.get(path, headers=H).status_code, 404)


class ConfigTest(unittest.TestCase):
    def test_schema(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config.json"
            with self.assertRaisesRegex(SystemExit, "missing"): config.load(f)
            f.write_text(json.dumps({**CFG, "web": {"port": 8095}}), encoding="utf-8"); cfg = config.load(f)
            self.assertEqual((cfg["away_after_s"], cfg["router"]["timeout_s"], cfg["ezviz"]["region_url"]), (300, 10, "apiieu.ezvizlife.com"))
            self.assertNotIn("web", cfg)
            for bad, where in [({"phone_macs": ["phone"]}, "phone_macs"), ({"phone_macs": []}, "phone_macs"), ({"away_after_s": 5}, "away_after_s"),
                               ({"router": {"user": "root"}}, "router.host")]:
                f.write_text(json.dumps({**CFG, **bad}), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, where): config.load(f)
            f.write_text("{oops", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "not valid JSON"): config.load(f)


if __name__ == "__main__":
    unittest.main()
