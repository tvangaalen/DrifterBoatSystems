"""BoatGuard's API as the Drifter app sees it, pinned down at HTTP level with the real presence logic and a fake router,
camera, notifier and clock: status, log, monitoring on/off, settings (with every refusal), notification tests and the
camera test. ApiContract runs against an implementation through make(); it passed against the stdlib server
(boatguard_web.py) and the FastAPI package (guard 2.0). Nothing reaches the router, the camera or Pushover."""
import json, tempfile, time, unittest
from pathlib import Path

PHONE = "02:00:00:aa:bb:cc"   # a locally administered, made-up MAC; privacy: ok
CFG = {"phone_macs": [PHONE], "away_after_s": 300, "poll_s": 30, "disarm_on_return": True, "test_settle_s": 0,
       "router": {"host": "192.0.2.1", "user": "root", "key": "x", "timeout_s": 10}, "ezviz": {"camera_serial": "X"},
       "sounds": {"armed": "", "disarmed": "", "unguarded": ""}, "priorities": {"armed": 0, "disarmed": 0, "unguarded": 1}}


class Cam:
    def __init__(self): self.calls, self.armed, self.fail = [], False, None
    def set_armed(self, a):
        if self.fail: raise RuntimeError(self.fail)
        self.calls.append(a); self.armed = a
    def status(self):
        if self.fail: raise RuntimeError(self.fail)
        return {"armed": self.armed, "battery": 80, "online": True}


class Notifier:
    def __init__(self): self.sent, self.configured = [], True
    def send(self, title, message, **kw): self.sent.append((title, message, kw))


def folder():
    d = Path(tempfile.mkdtemp()) / "guard"; (d / "logs").mkdir(parents=True)
    (d / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    (d / "logs" / "boatguard.log").write_text("".join(f"2026-11-02 10:{i:02d}:00 INFO line {i}\n" for i in range(30)), encoding="utf-8")
    return d


class ApiContract:
    """make(folder, cam, seen, clock, notifier) -> (get(path) -> (code, json), post(path, body, ctype) -> (code, json), guard)."""

    def setUp(self):
        self.dir = folder(); self.cam = Cam(); self.seen = [{PHONE}]; self.t = [1_000_000.0]; self.note = Notifier()
        self.get, self.post, self.guard = self.make(self.dir, self.cam, self.seen, self.t, self.note)

    def test_status(self):
        self.guard.tick(); code, j = self.get("/api/status")
        self.assertEqual(code, 200)
        for k, v in {"enabled": True, "present": True, "router_ok": True, "router_error": None, "away_after_s": 300, "poll_s": 30,
                     "armed_by_us": False, "arm_at": None, "test_running": False, "notifications": True, "last_test": None}.items():
            self.assertEqual(j[k], v, k)
        self.assertEqual(j["camera"]["armed"], False); self.assertEqual(j["camera"]["battery"], 80)
        self.assertEqual(j["limits"], {"away_after_s": [30, 3600], "poll_s": [10, 300]})
        self.assertEqual(j["priorities"], {"armed": 0, "disarmed": 0, "unguarded": 1}); self.assertIn("siren", j["sound_options"])
        self.assertEqual(set(j["events"]), {"armed", "disarmed", "unguarded"}); self.assertEqual(j["emergency"], {"retry_s": 60, "expire_s": 3600})
        self.seen[0] = set(); self.t[0] += 10; self.guard.tick(); j = self.get("/api/status")[1]
        self.assertEqual((j["present"], j["arm_at"]), (False, self.t[0] - 10 + 300))

    def test_router_down_and_camera_error_shown(self):
        self.seen[0] = None; self.guard.tick(); self.cam.fail = "cloud down"
        j = self.get("/api/status")[1]
        self.assertEqual((j["router_ok"], j["router_error"]), (False, "router read failed")); self.assertIn("cloud down", j["camera"]["error"])

    def test_log(self):
        code, j = self.get("/api/log?n=3")
        self.assertEqual((code, j["lines"]), (200, [f"2026-11-02 10:{i:02d}:00 INFO line {i}" for i in (27, 28, 29)]))
        self.assertEqual(len(self.get("/api/log")[1]["lines"]), 30); self.assertEqual(len(self.get("/api/log?n=0")[1]["lines"]), 1)

    def test_enabled(self):
        self.seen[0] = set(); self.guard.tick(); self.t[0] += 301; self.guard.tick(); self.assertEqual(self.cam.calls, [True])
        self.assertEqual(self.post("/api/enabled", {"enabled": False}), (200, {"enabled": False}))
        self.assertEqual(self.cam.calls, [True, False])                                    # off disarms what BoatGuard armed
        self.assertEqual(self.post("/api/enabled", {"enabled": True}), (200, {"enabled": True}))
        self.assertTrue(json.loads((self.dir / "state.json").read_text())["enabled"])

    def test_settings(self):
        code, j = self.post("/api/settings", {"away_after_s": 600, "sounds": {"armed": "siren"}, "priorities": {"unguarded": 2}})
        self.assertEqual(code, 200)
        self.assertEqual(j, {"away_after_s": 600, "poll_s": 30, "sounds": {"armed": "siren", "disarmed": "", "unguarded": ""},
                             "priorities": {"armed": 0, "disarmed": 0, "unguarded": 2}})
        disk = json.loads((self.dir / "config.json").read_text()); self.assertEqual((disk["away_after_s"], disk["sounds"]["armed"]), (600, "siren"))
        for body, msg in [({"away_after_s": 5}, "away_after_s must be a whole number of seconds between 30 and 3600"),
                          ({"poll_s": 12.5}, "poll_s must be a whole number of seconds between 10 and 300"),
                          ({"poll_s": True}, "poll_s must be a whole number of seconds between 10 and 300"),
                          ({"colour": 1}, "unknown setting colour"),
                          ({"poll_s": 300, "away_after_s": 200}, "router check interval must not exceed the arming delay"),
                          ({"sounds": {"armed": "trumpet"}}, "sounds must map armed/disarmed/unguarded to a Pushover sound"),
                          ({"priorities": {"armed": 3}}, "priorities must map armed/disarmed/unguarded to -2, -1, 0, 1 or 2")]:
            self.assertEqual(self.post("/api/settings", body), (400, {"error": msg}), msg)

    def test_notify_test(self):
        self.assertEqual(self.post("/api/notify-test", {"event": "armed", "sound": "siren", "priority": 2}), (200, {"sent": True}))
        title, message, kw = self.note.sent[-1]
        self.assertEqual((title, kw["priority"], kw["sound"], kw.get("expire")), ("Test: Camera armed", 2, "siren", 120))
        self.assertEqual(self.post("/api/notify-test", {"event": "party", "sound": ""}), (400, {"error": "unknown event or sound"}))
        self.assertEqual(self.post("/api/notify-test", {"event": "armed", "sound": "", "priority": 7}), (400, {"error": "unknown priority"}))
        self.note.configured = False
        self.assertEqual(self.post("/api/notify-test", {"event": "armed", "sound": ""}), (400, {"error": "Pushover is not set up"}))

    def test_camera_test(self):
        self.assertEqual(self.post("/api/test", {}), (200, {"started": True}))
        for _ in range(100):
            j = self.get("/api/status")[1]
            if j["last_test"]: break
            time.sleep(0.02)
        self.assertTrue(j["last_test"]["ok"]); self.assertIn("finished", j["last_test"]); self.assertEqual(self.cam.calls, [True, False])
        self.seen[0] = set(); self.guard.tick(); self.t[0] += 301; self.guard.tick()
        self.assertEqual(self.post("/api/test", {}), (409, {"error": "camera is armed by BoatGuard (phone away); test not possible now"}))
        self.guard.armed_by_us = False; self.guard.test_running = True
        self.assertEqual(self.post("/api/test", {}), (409, {"error": "test already running"}))

    def test_requests_refused(self):
        self.assertEqual(self.post("/api/enabled", {"enabled": False}, ctype="text/plain"), (415, {"error": "json only"}))
        self.assertEqual(self.post("/api/enabled", "{not json"), (400, {"error": "invalid JSON"}))
        self.assertEqual(self.post("/api/nope", {}), (404, {"error": "not found"}))
        self.assertEqual(self.get("/api/nope"), (404, {"error": "not found"}))
        self.assertTrue(self.guard.enabled)


if __name__ == "__main__":
    unittest.main()
