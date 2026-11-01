"""Controller tests without a washer: routes, request protection, bind address and the diagnostics API.
Runs with an empty DRIFTER_DATA folder, so no config, no token and no device: nothing is sent to a washer."""
import os, sys, tempfile, unittest
from pathlib import Path

os.environ["DRIFTER_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import viomi_web_english_v58 as v  # noqa: E402

H = {"Host": "127.0.0.1:8080"}


class ControllerTest(unittest.TestCase):
    def setUp(self): self.c = v.app.test_client()

    def test_no_pages_only_api(self):
        rules = {r.rule for r in v.app.url_map.iter_rules()}
        for gone in ("/", "/app", "/manifest.webmanifest", "/apple-touch-icon.png"):
            self.assertNotIn(gone, rules); self.assertEqual(self.c.get(gone, headers=H).status_code, 404)
        for kept in ("/api/status", "/api/diagnostics", "/diagnostics/export", "/api/start", "/api/schedule"): self.assertIn(kept, rules)

    def test_posts_need_the_marker_and_own_origin(self):
        self.assertEqual(self.c.post("/api/start", headers=H).status_code, 403)
        self.assertEqual(self.c.post("/api/start", headers={**H, "X-Viomi-Request": "1", "Origin": "http://evil.example"}).status_code, 403)

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.c.get("/api/status", headers={"Host": "evil.example:8080"}).status_code, 403)

    def test_runtime_files_follow_drifter_data(self):
        self.assertEqual(v.CONFIG_PATH.parent, Path(os.environ["DRIFTER_DATA"]) / "washer")
        self.assertEqual(v.SCHEDULE_PATH.parent, v.CONFIG_PATH.parent)

    def test_bind_address(self):
        old = os.environ.pop("VIOMI_BIND", None)
        try:
            self.assertEqual(v.bind_address(), "127.0.0.1")
            os.environ["VIOMI_BIND"] = "192.168.1.166"; self.assertEqual(v.bind_address(), "192.168.1.166")
            for bad in ("0.0.0.0", "8.8.8.8"):
                os.environ["VIOMI_BIND"] = bad
                with self.assertRaises(SystemExit): v.bind_address()
        finally:
            os.environ.pop("VIOMI_BIND", None)
            if old: os.environ["VIOMI_BIND"] = old

    def test_diagnostics_api(self):
        fake = {"checks": [{"name": "Configuration file", "ok": False, "detail": "missing", "severity": "critical"}],
                "ok": False, "critical_count": 1, "warning_count": 0, "pc_ip": "192.0.2.20"}
        calls = []
        orig = v.run_startup_checks
        v.run_startup_checks = lambda: (calls.append(1), v.__dict__.__setitem__("LAST_DIAGNOSTICS", fake), fake)[2]
        try:
            v.LAST_DIAGNOSTICS = None
            j = self.c.get("/api/diagnostics", headers=H).get_json()
            self.assertEqual(j["summary"], "1 startup issue(s) found"); self.assertEqual(j["summary_class"], "bad")
            self.assertEqual(j["controller_version"], v.CONTROLLER_VERSION); self.assertNotIn("token", str(j).lower().replace("miot token", ""))
            self.c.get("/api/diagnostics", headers=H); self.assertEqual(len(calls), 1)            # cached result
            self.c.get("/api/diagnostics?recheck=1", headers=H); self.assertEqual(len(calls), 2)   # runs again
        finally: v.run_startup_checks = orig


if __name__ == "__main__":
    unittest.main()
