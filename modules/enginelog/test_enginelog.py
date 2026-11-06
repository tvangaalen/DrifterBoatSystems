"""Engine log: create, read, change and delete fuel fills and maintenance entries, validation, the stats, the module
contract, and the country/marina lookup (with a fake: no test reaches the internet)."""
import tempfile, unittest
from pathlib import Path

from enginelog import VERSION  # noqa: F401  (puts common/ on sys.path)
from fastapi.testclient import TestClient

from enginelog.api import create_app
from enginelog.lookup import Lookup
from enginelog.store import Store, fuel_stats

TOKEN = {"X-Drifter-Token": "t"}
FILL = {"time": "2026-11-06T14:20:00+01:00", "engine_hours": 2315, "litres": 182, "lat": 10.5, "lon": -20.25, "country": "Testland", "marina": "Test Marina"}


class FakeGet:
    def __init__(self, fail=False): self.urls, self.fail = [], fail

    def __call__(self, url, timeout=10):
        self.urls.append(url)
        if self.fail: raise OSError("no internet")
        if "nominatim" in url: return {"address": {"country": "Testland"}}
        return {"elements": [{"tags": {"name": "Far Marina"}, "lat": 10.6, "lon": -20.25},
                             {"tags": {"name": "Near Marina"}, "center": {"lat": 10.51, "lon": -20.25}}, {"tags": {}, "lat": 10.5, "lon": -20.25}]}


class EngineLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.path = Path(self.dir.name) / "log.json"
        self.get = FakeGet()
        self.c = TestClient(create_app(Store(self.path), Lookup(self.get), token="t"))

    def tearDown(self): self.dir.cleanup()

    def post(self, path, body=None): return self.c.post(path, json=body if body is not None else {}, headers=TOKEN)

    def test_needs_the_gateway_token(self):
        self.assertEqual(self.c.get("/api/log").status_code, 403)
        self.assertEqual(self.c.get("/health").json()["module"], "enginelog")

    def test_fuel_crud(self):
        r = self.post("/api/fuel", FILL); self.assertEqual(r.status_code, 200, r.text); e = r.json()
        self.assertRegex(e["id"], r"^[0-9a-f]{12}$"); self.assertEqual((e["litres"], e["marina"], e["time"]), (182.0, "Test Marina", "2026-11-06T14:20+01:00"))
        r = self.post(f"/api/fuel/{e['id']}", {**FILL, "litres": 190, "marina": "  Other   Marina "}); self.assertEqual(r.json()["litres"], 190.0)
        self.assertEqual(r.json()["marina"], "Other Marina")
        log = self.c.get("/api/log", headers=TOKEN).json(); self.assertEqual(len(log["fuel"]), 1); self.assertEqual(log["fuel"][0]["litres"], 190.0)
        self.assertEqual(Store(self.path).all()["fuel"][0]["litres"], 190.0)        # saved to the file
        self.assertEqual(self.post(f"/api/fuel/{e['id']}/delete").status_code, 200)
        self.assertEqual(self.c.get("/api/log", headers=TOKEN).json()["fuel"], [])
        self.assertEqual(self.post(f"/api/fuel/{e['id']}/delete").status_code, 404)

    def test_maintenance_crud_and_order(self):
        a = self.post("/api/maintenance", {"date": "2026-10-15", "text": "Impeller replaced"}).json()
        self.post("/api/maintenance", {"date": "2026-11-02", "text": "Oil and oil filter changed\nat 2 300 h"})
        log = self.c.get("/api/log", headers=TOKEN).json()["maintenance"]
        self.assertEqual([m["date"] for m in log], ["2026-11-02", "2026-10-15"]); self.assertIn("\n", log[0]["text"])
        self.assertEqual(self.post(f"/api/maintenance/{a['id']}", {"date": "2026-10-16", "text": "Impeller and gasket"}).json()["text"], "Impeller and gasket")
        self.assertEqual(self.post(f"/api/maintenance/{a['id']}/delete").status_code, 200)
        self.assertEqual(len(self.c.get("/api/log", headers=TOKEN).json()["maintenance"]), 1)

    def test_validation(self):
        for bad, why in (({**FILL, "litres": 0}, "Litres"), ({**FILL, "engine_hours": "x"}, "Engine hours"), ({**FILL, "time": "2026-11-06T14:20"}, "time zone"),
                         ({**FILL, "lat": None}, "both"), ({**FILL, "marina": "x" * 101}, "Marina")):
            r = self.post("/api/fuel", bad); self.assertEqual(r.status_code, 400, bad); self.assertIn(why, r.json()["detail"])
        self.assertEqual(self.post("/api/maintenance", {"date": "2026-11-06", "text": "  "}).status_code, 400)
        self.assertEqual(self.post("/api/maintenance", {"date": "6-11-2026", "text": "x"}).status_code, 400)
        self.assertEqual(self.post("/api/other", {}).status_code, 404)
        self.assertEqual(self.post("/api/fuel/000000000000", FILL).status_code, 404)
        ok = {**FILL, "lat": None, "lon": None, "country": "", "marina": ""}
        self.assertEqual(self.post("/api/fuel", ok).status_code, 200)        # no position, no place: still fine

    def test_engine_hours_only_rise(self):     # the meter's running total
        self.post("/api/fuel", FILL)
        r = self.post("/api/fuel", {**FILL, "time": "2026-11-20T10:00:00+01:00", "engine_hours": 2300}); self.assertEqual(r.status_code, 400)
        self.assertIn("at least 2315", r.json()["detail"])
        r = self.post("/api/fuel", {**FILL, "time": "2026-10-01T10:00:00+01:00", "engine_hours": 2400}); self.assertIn("at most 2315", r.json()["detail"])
        e = self.post("/api/fuel", {**FILL, "time": "2026-11-20T10:00:00+01:00", "engine_hours": 2330}).json()
        self.assertEqual(self.post(f"/api/fuel/{e['id']}", {**FILL, "time": "2026-11-20T10:00:00+01:00", "engine_hours": 2320}).status_code, 200)

    def test_settings(self):
        self.assertEqual(self.c.get("/api/log", headers=TOKEN).json()["settings"], {"tank_capacity_l": None})
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": 400}).json(), {"tank_capacity_l": 400.0})
        self.assertEqual(Store(self.path).settings(), {"tank_capacity_l": 400.0})
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": 0}).status_code, 400)
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": None}).json(), {"tank_capacity_l": None})

    def test_stats(self):
        self.assertIsNone(fuel_stats([])["avg_l_per_h"])
        fills = [{"time": "2026-10-01T10:00+00:00", "engine_hours": 2200, "litres": 150}, {"time": "2026-10-20T10:00+00:00", "engine_hours": 2250, "litres": 160},
                 {"time": "2026-11-06T10:00+00:00", "engine_hours": 2300, "litres": 180}]
        s = fuel_stats(fills)
        self.assertEqual((s["last_litres"], s["avg_l_per_h"], s["fills"], s["litres_total"]), (180, 3.4, 3, 490.0))

    def test_lookup(self):
        r = self.c.get("/api/lookup?lat=10.5&lon=-20.25", headers=TOKEN).json()
        self.assertEqual((r["country"], r["marina"], r["error"]), ("Testland", "Near Marina", None)); self.assertLess(r["marina_distance_m"], 1500)
        self.c.get("/api/lookup?lat=10.5001&lon=-20.2501", headers=TOKEN)
        self.assertEqual(len(self.get.urls), 2)                                  # cached per ~100 m
        self.assertTrue(all("DrifterBoatSystems" not in u for u in self.get.urls))
        failing = TestClient(create_app(Store(self.path), Lookup(FakeGet(fail=True)), token="t"))
        r = failing.get("/api/lookup?lat=1&lon=1", headers=TOKEN).json()
        self.assertEqual((r["country"], r["marina"]), ("", "")); self.assertIn("country", r["error"])
        self.assertEqual(self.c.get("/api/lookup?lat=91&lon=0", headers=TOKEN).status_code, 400)


if __name__ == "__main__":
    unittest.main()
