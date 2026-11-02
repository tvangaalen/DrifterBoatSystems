"""The washer controller's behaviour, as the Drifter app sees it, pinned down at HTTP level with a fake washer and a fixed
clock: every route, status code and message, the schedule's life cycle, diagnostics and the export. ApiContract runs
against an implementation through a small adapter (make); it passed against the Flask controller 3.8 and against
the FastAPI package 4.0 before 3.8 was removed (Drifter 0.16.0). Nothing is sent to a real washer."""
import copy, json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 2, 10, 0, 0, tzinfo=TZ)
PROPS = {"power": (2, 1), "status": (2, 2), "mode": (2, 3), "fault": (2, 4), "left_time": (2, 5), "temperature": (2, 6),
         "spin": (2, 7), "rinses": (2, 9), "locked": (3, 1)}


class FakeWasher:
    """MIoT replies like the VIOMI W1's: get/set_properties and the start (2,1) / pause (2,2) actions."""
    def __init__(self, **state):
        self.state = {"power": True, "status": 1, "mode": 36, "fault": 0, "left_time": 45, "temperature": 30, "spin": 700, "rinses": 2,
                      "locked": False, **state}
        self.sent, self.fail, self.bad_code = [], None, {}

    def send(self, method, params):
        if self.fail: raise OSError(self.fail)
        self.sent.append((method, copy.deepcopy(params)))
        by_id = {v: k for k, v in PROPS.items()}
        if method == "get_properties":
            return [{"siid": p["siid"], "piid": p["piid"], "code": self.bad_code.get(by_id[(p["siid"], p["piid"])], 0),
                     "value": self.state[by_id[(p["siid"], p["piid"])]]} for p in params]
        if method == "set_properties":
            for p in params: self.state[by_id[(p["siid"], p["piid"])]] = p["value"]
            return [{"siid": p["siid"], "piid": p["piid"], "code": 0} for p in params]
        raise AssertionError(method)

    def call_action_by(self, siid, aiid, params):
        if self.fail: raise OSError(self.fail)
        self.sent.append(("action", (siid, aiid)))
        self.state["status"] = 7 if aiid == 1 else 26
        return {"code": 0}

    def info(self):
        return type("Info", (), {"model": "viomi.washer.w1", "firmware_version": "1.0.0"})()


class ApiContract:
    """make(fake, now) -> (get(path) -> (code, json), post(path, body=None) -> (code, json), impl). impl offers
    tick() (one scheduler pass), set_now(dt), events() (newest first) and checks(fake_result) for diagnostics."""

    def setUp(self):
        self.fake = FakeWasher(); self.now = NOW
        self.get, self.post, self.impl = self.make(self.fake, NOW)

    # ---- status and commands
    def test_status(self):
        code, j = self.get("/api/status")
        self.assertEqual(code, 200)
        for k, v in {"power": True, "power_text": "On", "status": 1, "status_text": "Standby", "mode": 36, "mode_text": "New Clothes",
                     "fault": 0, "fault_text": "No fault", "left_time": 45, "locked": False, "locked_text": "No", "errors": {}, "schedule": None}.items():
            self.assertEqual(j[k], v, k)
        self.fake.bad_code["locked"] = -4001
        j = self.get("/api/status")[1]; self.assertIsNone(j["locked"]); self.assertEqual(j["locked_text"], "Unknown")
        self.assertEqual(j["errors"], {"locked": "MIoT error -4001"})
        self.fake.state.update(status=99, mode=77, fault=3); j = self.get("/api/status")[1]
        self.assertEqual((j["status_text"], j["mode_text"], j["fault_text"]), ("Code 99", "Program code 77", "Fault code 3"))

    def test_status_offline(self):
        self.fake.fail = "timed out"
        code, j = self.get("/api/status"); self.assertEqual(code, 503); self.assertIn("timed out", j["error"])
        self.assertTrue(any(e["event"] == "CONNECTIVITY" for e in self.impl.events()))

    def test_state_changes_are_logged(self):
        self.get("/api/status"); self.fake.state["status"] = 7; self.get("/api/status")
        self.assertIn(("STATE", "READY → WASHING"), [(e["event"], e["detail"]) for e in self.impl.events()])
        self.fake.state["fault"] = 3; self.get("/api/status")
        self.assertIn(("STATE", "WASHING → DOOR OPEN"), [(e["event"], e["detail"]) for e in self.impl.events()])

    def test_power(self):
        self.fake.state["power"] = False
        self.assertEqual(self.post("/api/power/on"), (200, {"ok": True})); self.assertIs(self.fake.state["power"], True)
        self.assertEqual(self.post("/api/power/off"), (200, {"ok": True})); self.assertIs(self.fake.state["power"], False)
        self.assertEqual([e["event"] for e in self.impl.events()][:2], ["POWER OFF", "POWER ON"])
        self.fake.fail = "no reply"; code, j = self.post("/api/power/on")
        self.assertEqual((code, j["ok"]), (500, False)); self.assertIn("no reply", j["error"])

    def test_settings_are_validated(self):
        self.assertEqual(self.post("/api/program/13"), (200, {"ok": True, "value": 13, "program": "Underwear"}))
        self.assertEqual(self.post("/api/program/5"), (400, {"ok": False, "error": "Unsupported program code: 5"}))
        self.assertEqual(self.post("/api/temperature/60"), (200, {"ok": True, "value": 60}))
        self.assertEqual(self.post("/api/temperature/50"), (400, {"ok": False, "error": "Unsupported temperature: 50"}))
        self.assertEqual(self.post("/api/spin/400"), (200, {"ok": True, "value": 400}))
        self.assertEqual(self.post("/api/spin/1200"), (400, {"ok": False, "error": "Unsupported spin speed: 1200"}))
        self.assertEqual(self.post("/api/rinses/3"), (200, {"ok": True, "value": 3}))
        self.assertEqual(self.post("/api/rinses/9"), (400, {"ok": False, "error": "Unsupported rinse count: 9"}))
        self.assertEqual((self.fake.state["mode"], self.fake.state["temperature"], self.fake.state["spin"], self.fake.state["rinses"]), (13, 60, 400, 3))
        self.assertEqual(self.post("/api/temperature/0")[0], 200); self.assertEqual(self.fake.state["temperature"], 0)   # zero is a value

    def test_start_pause_start_check(self):
        self.assertEqual(self.post("/api/start"), (200, {"ok": True})); self.assertEqual(self.fake.sent[-1], ("action", (2, 1)))
        code, j = self.get("/api/start-check"); self.assertEqual((code, j["status"]), (200, 7))
        self.assertEqual(self.post("/api/pause"), (200, {"ok": True})); self.assertEqual(self.fake.sent[-1], ("action", (2, 2)))

    # ---- the schedule
    def test_schedule_finish_and_start_modes(self):
        code, j = self.post("/api/schedule", {"mode": "finish", "time": "18:00"})
        self.assertEqual(code, 200); s = j["schedule"]
        self.assertEqual((s["status"], s["mode"], s["requested_time"], s["expected_duration"], s["program_name"]), ("pending", "finish", "18:00", 45, "New Clothes"))
        self.assertEqual((s["start_at"], s["finish_at"]), ("2026-11-02T17:15:00+01:00", "2026-11-02T18:00:00+01:00"))
        self.assertNotIn("config", s); self.assertEqual(self.get("/api/schedule"), (200, {"ok": True, "schedule": s}))
        self.assertEqual(self.get("/api/status")[1]["schedule"], s)
        s = self.post("/api/schedule", {"mode": "START", "time": "09:30"})[1]["schedule"]                     # past today: tomorrow
        self.assertEqual((s["start_at"], s["finish_at"]), ("2026-11-03T09:30:00+01:00", "2026-11-03T10:15:00+01:00"))
        s = self.post("/api/schedule", {"mode": "finish", "time": "10:30"})[1]["schedule"]                   # too close: tomorrow
        self.assertEqual(s["finish_at"], "2026-11-03T10:30:00+01:00")

    def test_schedule_refused(self):
        for body, msg in [({"mode": "later", "time": "18:00"}, "Schedule mode must be 'start' or 'finish'"),
                          ({"mode": "start", "time": "25:00"}, "Time must be HH:MM"), ({"mode": "start"}, "Time must be HH:MM")]:
            self.assertEqual(self.post("/api/schedule", body), (400, {"ok": False, "error": msg}))
        for state, msg in [({"power": False}, "Washer must be powered on before scheduling"), ({"fault": 3}, "Washer has fault 3"),
                           ({"status": 7}, "Washer must be idle before scheduling"), ({"left_time": 0}, "Washer did not provide a valid program duration"),
                           ({"mode": 77}, "Unknown program capabilities")]:
            fake = FakeWasher(**state); get, post, _ = self.make(fake, NOW)
            self.assertEqual(post("/api/schedule", {"mode": "start", "time": "18:00"}), (400, {"ok": False, "error": msg}), msg)

    def test_cancel_and_manual_actions(self):
        self.post("/api/schedule", {"mode": "start", "time": "18:00"})
        self.assertEqual(self.post("/api/schedule/cancel"), (200, {"ok": True})); self.assertIsNone(self.get("/api/schedule")[1]["schedule"])
        self.post("/api/schedule", {"mode": "start", "time": "18:00"}); self.post("/api/start")
        self.assertIsNone(self.get("/api/schedule")[1]["schedule"]); self.assertIn("Cancelled by manual Start", [e["detail"] for e in self.impl.events()])
        self.post("/api/schedule", {"mode": "start", "time": "18:00"}); self.post("/api/power/off")
        self.assertIsNone(self.get("/api/schedule")[1]["schedule"])

    def test_due_schedule_runs_and_is_followed_to_the_end(self):
        self.post("/api/schedule", {"mode": "start", "time": "10:05"})
        self.fake.state.update(power=False, mode=13, temperature=60, rinses=4)       # the washer powered itself off meanwhile
        self.impl.set_now(NOW + timedelta(minutes=5, seconds=10)); self.impl.tick()
        s = self.get("/api/schedule")[1]["schedule"]       # one pass starts it and already sees it washing
        self.assertEqual((s["status"], s["run_observed"]), ("running", True)); self.assertIn("started_at", s); self.assertIn("run_observed_at", s)
        self.assertEqual((self.fake.state["power"], self.fake.state["mode"], self.fake.state["temperature"], self.fake.state["rinses"]), (True, 36, 30, 2))
        self.assertIn(("action", (2, 1)), self.fake.sent)
        self.assertEqual([e["event"] for e in self.impl.events()][:3], ["SCHEDULE RUNNING", "SCHEDULE START", "SCHEDULE POWER ON"])
        self.fake.state["status"] = 17; self.impl.set_now(NOW + timedelta(minutes=52)); self.impl.tick()
        s = self.get("/api/schedule")[1]["schedule"]; self.assertEqual(s["status"], "finished")
        self.assertIn("Actual 10:52 · 2 min late", [e["detail"] for e in self.impl.events()])

    def test_missed_and_failed_schedules(self):
        self.post("/api/schedule", {"mode": "start", "time": "10:05"})
        self.impl.set_now(NOW + timedelta(minutes=7)); self.impl.tick()
        s = self.get("/api/schedule")[1]["schedule"]; self.assertEqual((s["status"], s["last_error"]), ("missed", "Start time missed by 120 seconds"))
        self.impl.set_now(NOW); self.post("/api/schedule", {"mode": "start", "time": "10:05"})
        self.fake.state["fault"] = 3; self.impl.set_now(NOW + timedelta(minutes=5)); self.impl.tick()
        s = self.get("/api/schedule")[1]["schedule"]; self.assertEqual((s["status"], s["last_error"]), ("failed", "Washer fault 3"))

    def test_manual_change_interrupts_a_running_schedule(self):
        self.post("/api/schedule", {"mode": "start", "time": "10:05"}); self.impl.set_now(NOW + timedelta(minutes=5)); self.impl.tick()
        self.assertEqual(self.post("/api/program/13")[0], 200)
        s = self.get("/api/schedule")[1]["schedule"]; self.assertEqual((s["status"], s["last_error"]), ("interrupted", "Interrupted by manual SET/program change"))
        self.assertEqual(self.post("/api/schedule", {"mode": "start", "time": "18:00"}), (400, {"ok": False, "error": "Washer must be idle before scheduling"}))
        self.fake.state["status"] = 1                                                                   # once idle, an interrupted one does not block a new one
        self.assertEqual(self.post("/api/schedule", {"mode": "start", "time": "18:00"})[0], 200)

    def test_schedule_survives_a_restart(self):
        self.post("/api/schedule", {"mode": "start", "time": "18:00"})
        get, post, impl = self.make(self.fake, NOW, keep_data=True)
        self.assertEqual(get("/api/schedule")[1]["schedule"]["start_at"], "2026-11-02T18:00:00+01:00")

    # ---- diagnostics
    def test_diagnostics(self):
        code, j = self.get("/api/diagnostics")
        self.assertEqual(code, 200)
        names = [c["name"] for c in j["checks"]]
        for n in ("Python runtime", "python-miio", "Configuration file", "Washer IP", "MIoT token", "Washer network", "MIoT communication"): self.assertIn(n, names)
        for k in ("summary", "summary_class", "controller_version", "uptime", "washer_ip", "expected_model", "model", "firmware", "timings_ms", "ok",
                  "critical_count", "warning_count", "pc_ip"): self.assertIn(k, j)
        self.assertNotIn("0123456789abcdef", json.dumps(j))
        code, body, headers = self.impl.export()
        self.assertEqual(code, 200); self.assertIn('attachment; filename="viomi_diagnostics.json"', headers.get("content-disposition", ""))
        report = json.loads(body)
        for k in ("generated_at", "controller_version", "checks", "recent_events", "schedule", "timings_ms"): self.assertIn(k, report)
        self.assertNotIn("0123456789abcdef", body)

    def test_diagnostics_summary(self):
        for result, summary in [({"ok": True, "critical_count": 0, "warning_count": 0}, ("All systems ready", "ok")),
                                ({"ok": True, "critical_count": 0, "warning_count": 2}, ("Ready with 2 warning(s)", "warn")),
                                ({"ok": False, "critical_count": 1, "warning_count": 0}, ("1 startup issue(s) found", "bad"))]:
            self.assertEqual(self.impl.summary(result), summary)


CONFIG = {"washer_ip": "192.0.2.10", "token": "0123456789abcdef0123456789abcdef"}   # made up; privacy: ok


def data_dir(keep=None):
    d = keep or tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "washer"), exist_ok=True)
    with open(os.path.join(d, "washer", "viomi_config.json"), "w", encoding="utf-8") as f: json.dump(CONFIG, f)
    return d


if __name__ == "__main__":
    unittest.main()
