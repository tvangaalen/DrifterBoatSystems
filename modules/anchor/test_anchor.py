"""The FastAPI package (2.0) against ApiContract, plus the module contract (token, /health)."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor  # noqa: E402,F401  (puts the repository root on sys.path)
from fastapi.testclient import TestClient  # noqa: E402

from anchor import VERSION  # noqa: E402
from anchor.api import create_app  # noqa: E402
from test_api_contract import ApiContract, FakeTiles, FakeWatch  # noqa: E402

TOKEN = "test-token-not-secret"  # privacy: ok


class FastApiContract(ApiContract, unittest.TestCase):
    def make(self, watch, tiles):
        client = TestClient(create_app(watch, tiles, token=TOKEN), headers={"X-Drifter-Token": TOKEN})

        def call(method, path, body=None):
            data = None if body is None else body if isinstance(body, str) else __import__("json").dumps(body)
            r = client.request(method, path, content=data, headers={"Content-Type": "application/json"} if data is not None else {})
            return r.status_code, r.headers.get("content-type", ""), r.headers.get("cache-control", ""), r.content
        return call


class ModuleContract(unittest.TestCase):
    def test_token_and_health(self):
        c = TestClient(create_app(FakeWatch(), FakeTiles(), token=TOKEN))
        self.assertEqual(c.get("/api/state").status_code, 403)
        self.assertEqual(c.post("/api/command", json={"action": "raise"}, headers={"X-Drifter-Token": "wrong"}).status_code, 403)
        self.assertEqual(c.get("/tiles/osm/16/1/2.png").status_code, 403)
        h = c.get("/health").json(); self.assertEqual((h["ok"], h["module"], h["version"]), (True, "anchor", VERSION))
        self.assertEqual(TestClient(create_app(FakeWatch(), FakeTiles(), token="")).get("/api/state", headers={"X-Drifter-Token": ""}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
