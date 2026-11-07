"""Engine log: create, read, change and delete fuel fills and maintenance entries, validation, the stats, the module
contract, the live engine data (Core messages fed by hand) and the engine alarms (YD RAW lines of the YDEN-02 fed by
hand): no test reaches the Core, the YDEN or the internet."""
import json, struct, tempfile, unittest
from pathlib import Path

from enginelog import VERSION  # noqa: F401  (puts common/ on sys.path)
from fastapi.testclient import TestClient

from enginelog.api import create_app
from enginelog.engine import Engine
from enginelog.yden import FastPackets, YdenListener, decode, parse_line, status_names
from enginelog.store import Store, fuel_stats

TOKEN = {"X-Drifter-Token": "t"}
FILL = {"date": "2026-11-06", "engine_hours": 2315, "litres": 182, "amount": 301.95, "lat": 10.5, "lon": -20.25}


class EngineLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.path = Path(self.dir.name) / "log.json"
        self.c = TestClient(create_app(Store(self.path), token="t"))

    def tearDown(self): self.dir.cleanup()

    def post(self, path, body=None): return self.c.post(path, json=body if body is not None else {}, headers=TOKEN)

    def test_needs_the_gateway_token(self):
        self.assertEqual(self.c.get("/api/log").status_code, 403)
        self.assertEqual(self.c.get("/health").json()["module"], "enginelog")

    def test_fuel_crud(self):
        r = self.post("/api/fuel", FILL); self.assertEqual(r.status_code, 200, r.text); e = r.json()
        self.assertRegex(e["id"], r"^[0-9a-f]{12}$"); self.assertEqual((e["litres"], e["lat"], e["date"], e["amount"]), (182.0, 10.5, "2026-11-06", 301.95))
        self.assertNotIn("marina", e); self.assertNotIn("country", self.post("/api/fuel", {**FILL, "date": "2026-11-07", "country": "X"}).json())
        self.post(f"/api/fuel/{self.c.get('/api/log', headers=TOKEN).json()['fuel'][0]['id']}/delete")
        r = self.post(f"/api/fuel/{e['id']}", {**FILL, "litres": 190}); self.assertEqual(r.json()["litres"], 190.0)
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
        self.assertIsNone(a["engine_hours"])
        h = self.post(f"/api/maintenance/{a['id']}", {"date": "2026-10-16", "engine_hours": 2290.5, "text": "Impeller"}).json()
        self.assertEqual(h["engine_hours"], 2290.5)
        self.assertEqual(self.post("/api/maintenance", {"date": "2026-11-06", "engine_hours": -1, "text": "x"}).status_code, 400)
        self.assertEqual(self.post(f"/api/maintenance/{a['id']}/delete").status_code, 200)
        self.assertEqual(len(self.c.get("/api/log", headers=TOKEN).json()["maintenance"]), 1)

    def test_validation(self):
        for bad, why in (({**FILL, "litres": 0}, "Litres"), ({**FILL, "engine_hours": "x"}, "Engine hours"), ({**FILL, "date": "06-11-2026"}, "Date"), ({**FILL, "amount": -1}, "Amount"),
                         ({**FILL, "lat": None}, "both")):
            r = self.post("/api/fuel", bad); self.assertEqual(r.status_code, 400, bad); self.assertIn(why, r.json()["detail"])
        self.assertEqual(self.post("/api/maintenance", {"date": "2026-11-06", "text": "  "}).status_code, 400)
        self.assertEqual(self.post("/api/maintenance", {"date": "6-11-2026", "text": "x"}).status_code, 400)
        self.assertEqual(self.post("/api/other", {}).status_code, 404)
        self.assertEqual(self.post("/api/fuel/000000000000", FILL).status_code, 404)
        ok = {**FILL, "lat": None, "lon": None}
        self.assertEqual(self.post("/api/fuel", ok).status_code, 200)        # no position: still fine

    def test_engine_hours_only_rise(self):     # the meter's running total
        self.post("/api/fuel", FILL)
        r = self.post("/api/fuel", {**FILL, "date": "2026-11-20", "engine_hours": 2300}); self.assertEqual(r.status_code, 400)
        self.assertIn("at least 2315", r.json()["detail"])
        r = self.post("/api/fuel", {**FILL, "date": "2026-10-01", "engine_hours": 2400}); self.assertIn("at most 2315", r.json()["detail"])
        e = self.post("/api/fuel", {**FILL, "date": "2026-11-20", "engine_hours": 2330}).json()
        self.assertEqual(self.post(f"/api/fuel/{e['id']}", {**FILL, "date": "2026-11-20", "engine_hours": 2320}).status_code, 200)

    def test_settings(self):
        base = {"tank_capacity_l": None, "temp_high_c": 95.0, "oil_low_bar": 1.0}
        self.assertEqual(self.c.get("/api/log", headers=TOKEN).json()["settings"], base)
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": 400}).json(), {**base, "tank_capacity_l": 400.0})
        self.assertEqual(Store(self.path).settings()["tank_capacity_l"], 400.0)
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": 0}).status_code, 400)
        self.assertEqual(self.post("/api/settings", {"temp_high_c": 200}).status_code, 400)
        self.assertEqual(self.post("/api/settings", {"temp_high_c": None}).status_code, 400)
        self.assertEqual(self.post("/api/settings", {"tank_capacity_l": None, "temp_high_c": 90, "oil_low_bar": 0.8}).json(),
                         {"tank_capacity_l": None, "temp_high_c": 90.0, "oil_low_bar": 0.8})

    def test_stats(self):
        self.assertIsNone(fuel_stats([])["avg_l_per_h"])
        fills = [{"date": "2026-10-01", "engine_hours": 2200, "litres": 150, "amount": 240}, {"date": "2026-10-20", "engine_hours": 2250, "litres": 160},
                 {"date": "2026-11-06", "engine_hours": 2300, "litres": 180, "amount": 300}]
        s = fuel_stats(fills)
        self.assertEqual((s["last_litres"], s["avg_l_per_h"], s["fills"], s["litres_total"], s["amount_total"], s["last_date"]), (180, 3.4, 3, 490.0, 540, "2026-11-06"))
        self.assertEqual(s["avg_price"], round(540 / 330, 3)); self.assertIsNone(fuel_stats([{**fills[1]}])["avg_price"])

    def test_old_fills_with_a_time_read_as_their_date(self):
        self.path.write_text(json.dumps({"fuel": [{"id": "a1b2c3d4e5f6", "time": "2026-07-20T12:00+02:00", "engine_hours": 19, "litres": 280, "lat": None, "lon": None,
                                                  "country": "", "marina": "Imported"}]}), encoding="utf-8")
        e = Store(self.path).all()["fuel"][0]
        self.assertEqual((e["date"], e["amount"]), ("2026-07-20", None)); self.assertNotIn("time", e); self.assertNotIn("marina", e)



def core(values, full=False, ages=None):
    """A Core sensor message as the propulsion stream sends it (keys propulsion.<source>.<instance>.<field>, SI units)."""
    return {"event_type": "full" if full else "delta", "values": {f"propulsion.3.0.{k}": v for k, v in values.items()},
            "values_age": {f"propulsion.3.0.{k}": a for k, a in (ages or {}).items()}}


def yd_lines(rpm=1800.0, temp_c=80.0, oil_bar=3.5, status1=0, status2=0, hours=331.4, src=3, seq=5):
    """YD RAW lines as the YDEN-02 sends them: PGN 127488 (one frame) and PGN 127489 (a fast packet of 4 frames)."""
    rapid = struct.pack("<BHHb", 0, round(rpm / 0.25), 0, 0x7F) + b"\xff\xff"
    dyn = struct.pack("<BHHHhhIHHBHHbb", 0, round(oil_bar * 1000), 0xFFFF, round((temp_c + 273.15) * 100), 1410, 32, round(hours * 3600),
                      0xFFFF, 0xFFFF, 0x7F, status1, status2, 40, 0x7F)
    frames = [bytes([seq << 5, len(dyn)]) + dyn[:6]] + [bytes([seq << 5 | n + 1]) + dyn[6 + 7 * n:13 + 7 * n] for n in range(3)]
    frames[-1] += b"\xff" * (8 - len(frames[-1]))
    line = lambda pgn, data: f"10:00:00.000 R {(2 << 26) | (pgn << 8) | src:08X} " + " ".join(f"{b:02X}" for b in data)
    return [line(127488, rapid)] + [line(127489, f) for f in frames]


RUNNING = {"speed": 1800.0, "temperature": 353.15, "oilPressure": 350000.0, "altenatorVoltage": 14.1, "fuelRate": 3.2, "totalHours": 1193040.0, "load": 40, "boost": 0.0}


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.path = Path(self.dir.name) / "log.json"
        self.store = Store(self.path); self.t = 1_800_000_000.0
        self.e = Engine(self.store, clock=lambda: self.t)

    def tearDown(self): self.dir.cleanup()

    def run_for(self, seconds, values=None):
        for _ in range(int(seconds)):
            if values is not None: self.e.apply(core(values))
            self.e.tick(); self.t += 1

    def yd_for(self, seconds, **kw):
        """The YDEN-02's engine data for `seconds`, once a second (kw: yd_lines' values)."""
        y = YdenListener("192.0.2.1", self.e.apply_yd, clock=lambda: self.t)
        for _ in range(int(seconds)):
            for line in yd_lines(**kw): y.feed_line(line)
            self.e.tick(); self.t += 1

    def test_values_and_hours(self):
        self.e.apply(core(RUNNING, full=True)); self.e.tick()
        s = self.e.snapshot()
        self.assertEqual((s["rpm"], s["temp_c"], s["oil_bar"], s["alt_v"], s["hours"], s["running"], s["source"]), (1800, 80.0, 3.5, 14.1, 331.4, True, "3.0"))
        self.assertEqual(Store(self.path).engine()["hours"], 331.4)        # kept: a new entry gets it with the engine off
        self.t += 120; s = self.e.snapshot()
        self.assertFalse(s["fresh"]); self.assertIsNone(s["rpm"]); self.assertEqual(s["last_hours"], 331.4)
        c = TestClient(create_app(self.store, self.e, token="t"))
        self.assertEqual(c.get("/api/log", headers=TOKEN).json()["engine"]["last_hours"], 331.4)

    def test_other_engines_and_groups_are_ignored(self):
        self.e.apply({"values": {"propulsion.3.0.speed": 800.0, "propulsion.7.0.speed": 2000.0, "navigation.position.3.latitude": 1.0}})
        self.assertEqual(self.e.snapshot()["rpm"], 800)

    def test_the_yd_raw_decoder(self):
        lines = yd_lines(rpm=800, temp_c=52.0, oil_bar=4.2, status1=0b101, hours=332.5)
        pgn, src, data = parse_line(lines[0]); self.assertEqual((pgn, src), (127488, 3))
        self.assertEqual(decode(pgn, data)[1]["rpm"], 800)
        fp, got = FastPackets(), None
        for line in lines[1:]: got = fp.add(*parse_line(line)) or got
        inst, f = decode(127489, got)
        self.assertEqual((inst, round(f["temp_c"], 1), f["oil_bar"], f["alt_v"], f["fuel_lph"], round(f["hours"], 1), f["load"]), (0, 52.0, 4.2, 14.1, 3.2, 332.5, 40))
        self.assertIsNone(f["oil_temp_c"]); self.assertIsNone(f["torque"])                 # "not available"
        self.assertEqual(status_names(f["status1"], f["status2"]), ["Check engine", "Low oil pressure"])
        fp = FastPackets()                                                                  # a frame missing: nothing
        self.assertEqual([fp.add(*parse_line(x)) for x in (lines[1], lines[3], lines[4])], [None, None, None])
        self.assertIsNone(parse_line(lines[0].replace(" R ", " T ")))                      # what the YDEN sent itself
        self.assertIsNone(parse_line("garbage")); self.assertIsNone(parse_line("10:00:00.000 R 09F20003 ZZ"))

    def test_the_yden_follows_one_engine(self):
        got = []; y = YdenListener("192.0.2.1", lambda f, now: got.append(f), clock=lambda: self.t)
        for line in yd_lines(rpm=800): y.feed_line(line)
        for line in yd_lines(rpm=2400, src=9): y.feed_line(line)
        self.assertEqual({f["rpm"] for f in got if "rpm" in f}, {800}); self.assertEqual(y.source(), "3.0")

    def test_high_temperature_alarm_is_logged_with_its_worst_value(self):
        self.yd_for(5); self.yd_for(9, temp_c=97.0)
        self.assertEqual(self.store.all()["alarms"], [])                           # shorter than HOLD_S
        self.yd_for(1, temp_c=97.0); self.yd_for(5, temp_c=100.0)
        a = self.store.all()["alarms"]; self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["name"], a[0]["end"], a[0]["engine_hours"]), ("High coolant temperature", None, 331.4))
        self.assertIn("100 °C (limit 95 °C)", a[0]["detail"])
        self.yd_for(11)
        a = self.store.all()["alarms"][0]; self.assertIsNotNone(a["end"]); self.assertLess(a["start"], a["end"])
        c = TestClient(create_app(self.store, self.e, token="t"))
        self.assertEqual(c.post(f"/api/alarms/{a['id']}/delete", json={}, headers=TOKEN).status_code, 200)
        self.assertEqual(self.store.all()["alarms"], [])
        self.assertEqual(c.post(f"/api/alarms/{a['id']}/delete", json={}, headers=TOKEN).status_code, 404)

    def test_the_core_alone_logs_no_alarm(self):
        self.run_for(30, {**RUNNING, "temperature": 380.0, "checkEngine": 1})
        self.assertEqual(self.store.all()["alarms"], [])
        src = self.e.snapshot()["alarm_source"]
        self.assertEqual((src["device"], src["fresh"], src["status"]), ("YDEN-02", False, []))

    def test_low_oil_pressure_only_while_running(self):
        self.yd_for(60, rpm=0, oil_bar=0.0); self.assertEqual(self.store.all()["alarms"], [])     # engine off: no oil pressure is normal
        self.yd_for(25, oil_bar=0.5); self.assertEqual(self.store.all()["alarms"], [])            # just started
        self.yd_for(20, oil_bar=0.5)
        a = self.store.all()["alarms"]; self.assertEqual([x["name"] for x in a], ["Low oil pressure"]); self.assertIn("0.5 bar", a[0]["detail"])
        for _ in range(70): self.e.tick(); self.t += 1                                       # the YDEN goes off: the alarm ends
        self.assertIsNotNone(self.store.all()["alarms"][0]["end"])

    def test_the_engine_status_bits_are_alarms(self):
        self.yd_for(20, rpm=0, status1=1 << 2 | 1 << 9 | 1 << 10)                 # ignition on, engine still: lamp test, preheat
        self.assertEqual(self.store.all()["alarms"], [])
        self.yd_for(12, status1=1 << 8, status2=1 << 3)                           # water in fuel, maintenance needed
        self.assertEqual(sorted(a["name"] for a in self.store.all()["alarms"]), ["Engine: Maintenance needed", "Engine: Water in fuel"])
        self.assertEqual(self.e.snapshot()["alarm_source"]["status"], ["Water in fuel", "Maintenance needed"])
        self.yd_for(12)
        self.assertTrue(all(a["end"] for a in self.store.all()["alarms"]))
        self.yd_for(40, status1=1 << 2)                                           # running 30 s: the oil pressure light counts
        self.assertIn("Engine: Low oil pressure", [a["name"] for a in self.store.all()["alarms"]])

    def test_an_alarm_open_at_a_restart_is_closed(self):
        self.yd_for(12, temp_c=100.0)
        Engine(Store(self.path), clock=lambda: self.t)
        a = Store(self.path).all()["alarms"][0]; self.assertIsNotNone(a["end"]); self.assertIn("restarted", a["detail"])


if __name__ == "__main__":
    unittest.main()
