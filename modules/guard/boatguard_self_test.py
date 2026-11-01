"""Hardware-free test of BoatGuard's presence state machine (fake router, fake camera, fake clock)."""
import tempfile
from pathlib import Path

from boatguard import Guard, RouterError, classify_ssh_error

PHONE = "02:00:00:aa:bb:cc"
CFG = {"phone_macs": [PHONE.upper()], "away_after_s": 300, "disarm_on_return": True, "test_settle_s": 0, "ezviz": {"camera_serial": "X"}}


class Cam:
    def __init__(self): self.calls, self.fail, self.armed = [], False, False
    def set_armed(self, a):
        if self.fail: raise RuntimeError("cloud down")
        self.calls.append(a); self.armed = a
    def status(self): return {"armed": self.armed, "battery": 50, "online": True}


def make(tmp, seen, t, cam=None):
    cam = cam or Cam()
    g = Guard(CFG, cam, stations=lambda c: seen[0], clock=lambda: t[0], state_path=Path(tmp) / "s.json")
    return g, cam


def test():
    with tempfile.TemporaryDirectory() as tmp:
        seen, t = [{PHONE}], [1000.0]
        g, cam = make(tmp, seen, t)
        g.tick(); assert cam.calls == [], "aboard: nothing happens"
        seen[0] = set(); t[0] += 120; g.tick(); assert cam.calls == [], "short drop-out is ignored"
        seen[0] = None; t[0] += 600; g.tick(); assert cam.calls == [], "router unreadable: never arm"
        seen[0] = {"aa:bb:cc:dd:ee:ff"}; g.tick(); assert cam.calls == [True], "away > grace: arm"
        t[0] += 60; g.tick(); assert cam.calls == [True], "arm only once"
        # restart while away keeps state; no re-arm
        g2, cam2 = make(tmp, seen, t); g2.tick(); assert cam2.calls == [] and g2.armed_by_us
        seen[0] = {PHONE}; g2.tick(); assert cam2.calls == [False], "return: disarm"
        g2.tick(); assert cam2.calls == [False], "disarm only once"
        # cloud failure is retried on the next poll
        cam2.fail = True; seen[0] = set(); t[0] += 400; g2.tick(); assert not g2.armed_by_us
        cam2.fail = False; g2.tick(); assert cam2.calls == [False, True] and g2.armed_by_us
    with tempfile.TemporaryDirectory() as tmp:
        seen, t = [set()], [5000.0]
        g, cam = make(tmp, seen, t)
        g.tick(); assert cam.calls == [], "fresh start without phone: full grace period first"
        t[0] += 301; g.tick(); assert cam.calls == [True]
        # manual arm by the user is not undone: we only disarm what we armed
        g.armed_by_us = False; seen[0] = {PHONE}; g.tick(); assert cam.calls == [True]
    with tempfile.TemporaryDirectory() as tmp:
        seen, t = [set()], [9000.0]
        g, cam = make(tmp, seen, t)
        g.set_enabled(False); t[0] += 1000; g.tick(); assert cam.calls == [], "monitoring off: never arm"
        assert make(tmp, seen, t)[0].enabled is False, "off survives a restart"
        g.set_enabled(True); g.tick(); assert cam.calls == [True], "back on while away: arm"
        assert g.status()["arm_at"] is None and g.status()["armed_by_us"]
        assert g.test()["ok"] is False and cam.calls == [True], "no test while armed for real"
        g.set_enabled(False); assert cam.calls == [True, False] and not g.armed_by_us, "off disarms what we armed"
        seen[0] = {PHONE}; g.set_enabled(True); g.tick()
        r = g.test(); assert r["ok"] and cam.calls[-2:] == [True, False] and not cam.armed, "test arms, then disarms"
        cam.fail = True; r = g.test(); assert not r["ok"] and r["error"] and not g.test_running, "failed test reported"
        cam.fail = False; seen[0] = set(); t[0] += 10; g.tick(); assert g.status()["arm_at"] == t[0] - 10 + 300, "countdown shown"
    with tempfile.TemporaryDirectory() as tmp:
        import json
        cfgp = Path(tmp) / "config.json"; cfgp.write_text(json.dumps({"away_after_s": 300, "poll_s": 30, "other": "kept"}))
        g, cam = make(tmp, [set()], [0.0]); g.cfg = dict(CFG, poll_s=30)
        for bad in ({"away_after_s": 10}, {"poll_s": 301}, {"poll_s": 12.5}, {"poll_s": True}, {"poll_s": "30"},
                    {"away_after_s": 60, "poll_s": 120}, {"secret": 1}):
            try: g.update_settings(bad, cfgp); raise AssertionError(f"accepted {bad}")
            except ValueError: pass
        assert g.cfg["away_after_s"] == 300 and json.loads(cfgp.read_text())["away_after_s"] == 300, "rejected input changes nothing"
        g.update_settings({"away_after_s": 120, "poll_s": 15}, cfgp)
        disk = json.loads(cfgp.read_text())
        assert g.cfg["away_after_s"] == 120 and g.cfg["poll_s"] == 15 and disk == {"away_after_s": 120, "poll_s": 15, "other": "kept"}
        assert g.wake.is_set(), "poll loop is woken so the new interval applies at once"
    with tempfile.TemporaryDirectory() as tmp:  # EZVIZ cloud lag after BoatGuard's own change
        seen, t = [set()], [0.0]
        g, cam = make(tmp, seen, t); cloud = {"armed": True}
        cam.status = lambda: {"armed": cloud["armed"], "battery": 50, "online": True}
        g.armed_by_us = True; g.set_enabled(False); assert cam.calls == [False]
        cs = g.camera_status(); assert cs["armed"] is False and cs["pending"], "shown disarmed at once, pending"
        t[0] += 11; cs = g.camera_status(); assert cs["armed"] is False and cs["pending"], "stale cloud 'armed' ignored while pending"
        cloud["armed"] = False; t[0] += 11; cs = g.camera_status(); assert cs["armed"] is False and not cs["pending"], "confirmed"
        assert g.cam_expect is None
        g.expect_camera(True); cloud["armed"] = False; t[0] += 100; cs = g.camera_status()
        assert cs["armed"] is False and not cs["pending"], "after the wait the cloud's word counts"
        # a read that started before a change is thrown away
        g.expect_camera(False)
        def racing(): g.expect_camera(True); return {"armed": False, "battery": 50, "online": True}
        cam.status = racing; t[0] += 11; cs = g.camera_status(); assert cs["armed"] is True and cs["pending"]
    with tempfile.TemporaryDirectory() as tmp:  # Pushover notifications
        import json
        class Note:
            configured = True
            def __init__(self): self.sent = []
            def send(self, title, message, priority=0, url=None, sound=None, **kw): self.sent.append((title, priority)); self.sound, self.kw = sound, kw
        note = Note(); cam = Cam(); seen, t = [{PHONE}], [0.0]
        g = Guard(CFG, cam, stations=lambda c: seen[0], clock=lambda: t[0], state_path=Path(tmp) / "s.json", notifier=note)
        g.tick(); seen[0] = set(); t[0] += 301; g.tick()
        assert note.sent == [("Camera armed", 0)]
        seen[0] = {PHONE}; g.tick(); assert note.sent[-1] == ("Camera disarmed", 0)
        g.set_enabled(False); seen[0] = set(); t[0] += 100; g.tick(); assert len(note.sent) == 2, "within delay: nothing"
        t[0] += 201; g.tick(); assert note.sent[-1] == ("Left the boat, monitoring OFF", 1), "unguarded departure warned"
        t[0] += 60; g.tick(); assert len(note.sent) == 3, "warned once per departure"
        g2 = Guard(CFG, cam, stations=lambda c: seen[0], clock=lambda: t[0], state_path=Path(tmp) / "s.json", notifier=note)
        g2.tick(); assert len(note.sent) == 3, "not again after a restart"
        seen[0] = {PHONE}; g2.tick(); seen[0] = set(); t[0] += 301; g2.tick(); assert len(note.sent) == 4, "next departure warns again"
        g2.set_enabled(True); g2.tick(); assert note.sent[-1] == ("Camera armed", 0), "monitoring on while away arms"
        g2.set_enabled(False); assert note.sent[-1] == ("Camera disarmed", 0)
        t[0] += 60; g2.tick(); assert len(note.sent) == 6, "switched off by hand while away: no warning"
        assert g2.status()["notifications"] is True
        # per-event sounds: validated, saved, used, and testable before saving
        cfgp = Path(tmp) / "c.json"; cfgp.write_text("{}"); g2.cfg = dict(CFG, poll_s=30)
        for bad in ({"sounds": {"armed": "foghorn"}}, {"sounds": {"boarded": "siren"}}, {"sounds": "siren"}):
            try: g2.update_settings(bad, cfgp); raise AssertionError(f"accepted {bad}")
            except ValueError: pass
        r = g2.update_settings({"sounds": {"armed": "siren", "unguarded": "persistent"}}, cfgp)
        assert r["sounds"] == {"armed": "siren", "unguarded": "persistent"} and json.loads(cfgp.read_text())["sounds"] == r["sounds"]
        seen[0] = {PHONE}; g2.tick(); g2.set_enabled(True); seen[0] = set(); t[0] += 301; g2.tick()
        assert note.sent[-1] == ("Camera armed", 0) and note.sound == "siren", "armed uses its sound"
        seen[0] = {PHONE}; g2.tick(); assert note.sound is None, "disarmed: app default (no sound sent)"
        g2.notify_test("disarmed", "magic"); assert note.sent[-1][0] == "Test: Camera disarmed" and note.sound == "magic"
        try: g2.notify_test("armed", "foghorn"); raise AssertionError("bad test sound accepted")
        except ValueError: pass
        # per-event priorities: defaults, validation, saving, use, and a short emergency test
        assert g2.status()["priorities"] == {"armed": 0, "disarmed": 0, "unguarded": 1}
        for bad in ({"priorities": {"armed": 3}}, {"priorities": {"armed": True}}, {"priorities": {"armed": "1"}},
                    {"priorities": {"boarded": 1}}, {"priorities": [1]}):
            try: g2.update_settings(bad, cfgp); raise AssertionError(f"accepted {bad}")
            except ValueError: pass
        r = g2.update_settings({"priorities": {"disarmed": -1, "unguarded": 2}}, cfgp)
        assert r["priorities"] == {"armed": 0, "disarmed": -1, "unguarded": 2}
        assert json.loads(cfgp.read_text())["priorities"] == {"disarmed": -1, "unguarded": 2}
        seen[0] = set(); t[0] += 301; g2.tick(); assert note.sent[-1] == ("Camera armed", 0)
        seen[0] = {PHONE}; g2.tick(); assert note.sent[-1] == ("Camera disarmed", -1), "disarmed uses its priority"
        g2.set_enabled(False); seen[0] = set(); t[0] += 301; g2.tick()
        assert note.sent[-1] == ("Left the boat, monitoring OFF", 2) and note.kw == {}, "real emergency: default expiry"
        g2.notify_test("unguarded", "siren", 2); assert note.sent[-1][1] == 2 and note.kw == {"expire": 120}, "emergency test is short"
        try: g2.notify_test("armed", "siren", 5); raise AssertionError("bad test priority accepted")
        except ValueError: pass
        class Broken(Note):
            def send(self, *a, **k): raise RuntimeError("no internet")
        g3 = Guard(CFG, Cam(), stations=lambda c: set(), clock=lambda: t[0] + 1000, state_path=Path(tmp) / "b.json", notifier=Broken())
        g3.last_seen = 0; g3.tick(); assert g3.armed_by_us, "a notification failure never blocks arming"
    # router failures: classified, logged once per outage (plus reminders), recovery logged, camera untouched
    pq = "** WARNING: connection is not using a post-quantum key exchange algorithm.\n"
    assert classify_ssh_error(pq + "ssh: connect to host 192.168.1.1 port 22: Connection refused").kind == "unreachable"
    assert classify_ssh_error("ssh: connect to host 192.168.1.1 port 22: Connection timed out").kind == "unreachable"
    assert classify_ssh_error(pq + "root@192.168.1.1: Permission denied (publickey,keyboard-interactive).").kind == "auth"
    assert classify_ssh_error("Host key verification failed.").kind == "auth"
    assert classify_ssh_error("").kind == "unreachable" and classify_ssh_error("weird").kind == "other"
    import logging
    class Cap(logging.Handler):
        def __init__(self): super().__init__(); self.lines = []
        def emit(self, r): self.lines.append((r.levelname, r.getMessage()))
    cap = Cap(); lg = logging.getLogger("boatguard"); lg.addHandler(cap); lg.setLevel(logging.INFO)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            state, t = {"r": {PHONE}}, [0.0]
            def stations(c):
                if isinstance(state["r"], RouterError): raise state["r"]
                return state["r"]
            cam = Cam(); g = Guard(CFG, cam, stations=stations, clock=lambda: t[0], state_path=Path(tmp) / "s.json")
            g.tick(); cap.lines.clear()
            state["r"] = RouterError("unreachable", "Connection refused")
            for _ in range(10): t[0] += 120; g.tick()  # 20 min outage
            warns = [m for lv, m in cap.lines if "router" in m]
            assert len(warns) == 1 and "offline or restarting" in warns[0], warns
            assert g.status()["router_error"] == "router not reachable" and g.status()["router_down_since"] == 120
            for _ in range(10): t[0] += 120; g.tick()  # past 30 min: one reminder
            assert sum("still not readable" in m for _, m in cap.lines) == 1
            state["r"] = RouterError("auth", "Permission denied (publickey)"); t[0] += 120; g.tick()
            assert cap.lines[-1][0] == "ERROR" and "refused the SSH key" in cap.lines[-1][1], "a new reason is logged at once"
            state["r"] = set(); t[0] += 120; g.tick()
            assert any("router readable again after 42 min" in m for _, m in cap.lines), cap.lines[-2:]
            assert g.status()["router_error"] is None and g.status()["router_down_since"] is None
            assert cam.calls == [True], "outage changed nothing; only the real away-arm after recovery"
    finally: lg.removeHandler(cap)
    print("boatguard self-test OK")


if __name__ == "__main__":
    test()
