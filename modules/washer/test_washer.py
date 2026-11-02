"""The washer package (4.x): the API contract of test_api_contract.py, Drifter's module contract (token, /health, no-store,
bind), the configuration schema and the runtime folder. Fake washer, fixed clock: nothing is sent to a real washer."""
import json, os, sys, tempfile, types, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient  # noqa: E402

from test_api_contract import ApiContract, FakeWasher, NOW, data_dir  # noqa: E402
from washer import VERSION, config  # noqa: E402
from washer.api import Controller, create_app  # noqa: E402
from washer.diagnostics import summary  # noqa: E402

TOKEN = "t" * 48
H = {"X-Drifter-Token": TOKEN}


def build(fake, now, folder):
    clock = {"now": now, "mono": 1000.0}
    c = Controller(Path(folder) / "washer", device_factory=lambda ip, token: fake, clock=lambda: clock["now"],
                   sleep=lambda s: clock.__setitem__("mono", clock["mono"] + s), monotonic=lambda: clock["mono"],
                   handshake=lambda ip, timeout=2.0: True, pc_ip=lambda: "192.0.2.20")
    return c, TestClient(create_app(c, token=TOKEN)), clock


class WasherContract(ApiContract, unittest.TestCase):
    dir = None

    def make(self, fake, now, keep_data=False):
        self.dir = data_dir(self.dir if keep_data else None)
        c, client, clock = build(fake, now, self.dir)

        def get(path):
            r = client.get(path, headers=H); return r.status_code, r.json()

        def post(path, body=None):
            r = client.post(path, headers=H, json=body if body is not None else {}); return r.status_code, r.json()

        def export():
            r = client.get("/diagnostics/export", headers=H); return r.status_code, r.text, {k.lower(): v for k, v in r.headers.items()}

        def tick():
            clock["mono"] += 5; c.schedule.tick()

        impl = types.SimpleNamespace(tick=tick, set_now=lambda dt: clock.__setitem__("now", dt), events=lambda: list(c.events.items),
                                     export=export, summary=summary)
        return get, post, impl


class ModuleContractTest(unittest.TestCase):
    def setUp(self):
        self.c, self.client, _ = build(FakeWasher(), NOW, data_dir())

    def test_token_required_except_health(self):
        for method, path in (("get", "/api/status"), ("post", "/api/start"), ("get", "/diagnostics/export")):
            for headers in ({}, {"X-Drifter-Token": "wrong"}):
                r = getattr(self.client, method)(path, headers=headers)
                self.assertEqual(r.status_code, 403, (path, headers)); self.assertFalse(r.json()["ok"])
        r = self.client.get("/health"); self.assertEqual(r.status_code, 200)
        self.assertEqual({k: r.json()[k] for k in ("ok", "module", "version")}, {"ok": True, "module": "washer", "version": VERSION})

    def test_no_token_configured_refuses_everything(self):
        client = TestClient(create_app(self.c, token=""))
        self.assertEqual(client.get("/api/status", headers={"X-Drifter-Token": ""}).status_code, 403)
        self.assertEqual(client.get("/health").status_code, 200)

    def test_json_not_cached_and_no_docs(self):
        r = self.client.get("/api/schedule", headers=H); self.assertEqual(r.headers["cache-control"], "no-store")
        for path in ("/docs", "/openapi.json", "/"): self.assertEqual(self.client.get(path, headers=H).status_code, 404)

    def test_bind(self):
        from common import net
        old = os.environ.pop("WASHER_BIND", None)
        try:
            self.assertEqual(net.check_bind(os.environ.get("WASHER_BIND") or "127.0.0.1", "WASHER_BIND"), "127.0.0.1")
            for bad in ("0.0.0.0", "8.8.8.8"):
                with self.assertRaises(SystemExit): net.check_bind(bad, "WASHER_BIND")
        finally:
            if old: os.environ["WASHER_BIND"] = old


class ConfigTest(unittest.TestCase):
    def test_schema(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "viomi_config.json"
            cfg, err = config.load(f); self.assertIn("not found", err); self.assertEqual(cfg.washer_ip, config.DEFAULT_IP)
            f.write_text(json.dumps({"washer_ip": "192.0.2.11", "token": "a" * 32, "allowed_hosts": ["x"]}), encoding="utf-8")
            cfg, err = config.load(f); self.assertIsNone(err); self.assertEqual((cfg.washer_ip, cfg.token), ("192.0.2.11", "a" * 32))
            f.write_text(json.dumps({"washer_ip": 5}), encoding="utf-8"); cfg, err = config.load(f); self.assertIn("washer_ip", err)
            f.write_text("{not json", encoding="utf-8"); cfg, err = config.load(f); self.assertIn("Configuration file error", err)

    def test_runtime_folder_follows_drifter_data(self):
        old = os.environ.get("DRIFTER_DATA")
        try:
            os.environ["DRIFTER_DATA"] = r"C:\somewhere"; self.assertEqual(config.data_dir(), Path(r"C:\somewhere") / "washer")
        finally:
            if old is None: os.environ.pop("DRIFTER_DATA", None)
            else: os.environ["DRIFTER_DATA"] = old


if __name__ == "__main__":
    unittest.main()
