"""Supervisor tests: adopt, grace, start, back-off, hold, restart on request, pre-checks and the API. Fakes only:
no process is started or stopped and no port is opened except the gateway's own test server."""
import http.client, json, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import drifter, supervisor as S  # noqa: E402


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t
    def go(self, s): self.t += s


class Rig:
    """A supervisor with fake ports, starts and stops."""
    def __init__(self, up=("energy", "anchor", "guard", "washer"), precheck=None):
        self.tmp = tempfile.TemporaryDirectory(); self.data = Path(self.tmp.name)
        self.ports = {"energy": 8000, "anchor": 8766, "guard": 8095, "washer": 8080}
        self.up = {self.ports[n] for n in up}; self.started, self.stopped = [], []; self.clock = Clock()
        self.logs = {n: self.data / "logs" / f"{n}.console.log" for n in S.LOG_NAMES}
        self.sup = S.Supervisor(ports=self.ports, data=self.data, listening=lambda: set(self.up), start=self.started.append,
                                stop=self._stop, precheck=precheck, clock=self.clock, logs=self.logs, start_async=False)

    def _stop(self, n): self.stopped.append(n); self.up.discard(self.ports[n])
    def tick(self, after=0): self.clock.go(after); self.sup.tick()
    def state(self, n): return self.sup.mods[n]["state"]
    def hold(self, n, on=True):
        f = self.data / "hold" / n; f.parent.mkdir(exist_ok=True)
        f.write_text("test") if on else f.unlink()


class SupervisorTest(unittest.TestCase):
    def test_running_servers_are_adopted_and_never_touched(self):
        r = Rig(); r.tick()
        for n in r.ports: self.assertEqual(r.state(n), "running")
        for _ in range(100): r.tick(60)
        self.assertEqual(r.started, []); self.assertEqual(r.stopped, [])
        self.assertIn("adopted", r.sup.mods["energy"]["last_event"]["text"])

    def test_down_at_start_is_started_at_once(self):
        r = Rig(up=("anchor", "guard", "washer")); r.tick()                   # e.g. after a boot: nobody else starts it
        self.assertEqual(r.started, ["energy"]); self.assertEqual(r.state("energy"), "starting")
        r.tick(S.TICK_S); self.assertEqual(r.started, ["energy"])              # no second start while it comes up
        r.up.add(8000); r.tick(40); self.assertEqual(r.state("energy"), "running"); self.assertEqual(r.sup.mods["energy"]["starts"], 1)

    def test_a_slow_start_does_not_hold_up_the_others(self):
        r = Rig(up=()); gate, seen = threading.Event(), []
        def start(n):
            seen.append(n)
            if n == "energy": gate.wait(5)                                    # start_all.ps1 took 90 s in session 0 after a boot
        r.sup.start_fn, r.sup.start_async = start, True
        t0 = time.monotonic(); r.tick(); self.assertLess(time.monotonic() - t0, 1)
        for _ in range(100):
            if len(seen) == 4: break
            time.sleep(0.01)
        self.assertEqual(sorted(seen), ["anchor", "energy", "guard", "washer"]); gate.set()
        self.assertEqual(r.sup.mods["washer"]["last_start"], r.clock.t)      # timed from its own start, not from a stale tick time

    def test_module_that_stops_later_is_started_after_grace(self):
        r = Rig(); r.tick(); r.up.discard(8000); r.tick(S.TICK_S)
        self.assertEqual(r.state("energy"), "down"); self.assertEqual(r.started, [])
        r.tick(S.GRACE_S - 1); self.assertEqual(r.started, [])
        r.tick(1); self.assertEqual(r.started, ["energy"]); self.assertEqual(r.state("energy"), "starting")

    def test_failed_starts_back_off(self):
        r = Rig(up=()); r.tick(); r.tick(S.GRACE_S)
        self.assertEqual(r.started.count("washer"), 1)
        r.tick(S.START_WAIT_S); self.assertEqual(r.state("washer"), "failed")
        r.tick(S.BACKOFF[0] - 5); self.assertEqual(r.started.count("washer"), 1)
        r.tick(5); self.assertEqual(r.started.count("washer"), 2)
        r.tick(S.START_WAIT_S); r.tick(S.BACKOFF[1] - 5); self.assertEqual(r.started.count("washer"), 2)
        r.tick(5); self.assertEqual(r.started.count("washer"), 3)
        for _ in range(20): r.tick(S.START_WAIT_S); r.tick(S.BACKOFF[-1])
        self.assertLessEqual(r.started.count("washer"), 3 + 20)               # never faster than the longest back-off
        r.up.add(8080); r.tick(); self.assertEqual(r.state("washer"), "running")
        r.tick(S.STABLE_S + 1); self.assertEqual(r.sup.mods["washer"]["attempts"], 0)

    def test_hold_blocks_starts(self):
        r = Rig(up=("energy", "guard", "washer")); r.hold("anchor"); r.tick()
        for _ in range(10): r.tick(60)
        self.assertEqual(r.started, []); self.assertEqual(r.state("anchor"), "held")
        r.hold("anchor", False); r.tick(); self.assertEqual(r.started, [])     # a fresh grace period after the hold
        r.tick(S.GRACE_S); self.assertEqual(r.started, ["anchor"])

    def wait_idle(self, r, n):
        for _ in range(200):
            if not r.sup.mods[n]["busy"]: return
            time.sleep(0.01)
        self.fail("restart did not finish")

    def test_restart_on_request(self):
        r = Rig(); r.tick()
        mark = r.data / "starting" / "washer"; mark.parent.mkdir(); mark.write_text("old")
        r.sup.restart("washer"); self.wait_idle(r, "washer")
        self.assertEqual(r.stopped, ["washer"]); self.assertEqual(r.started, ["washer"]); self.assertFalse(mark.exists())
        self.assertEqual(r.state("washer"), "starting")
        r.up.add(8080); r.tick(5); self.assertEqual(r.state("washer"), "running")

    def test_slow_server_after_restart_is_not_started_twice(self):
        r = Rig(); r.tick()
        gate = threading.Event()
        def slow_start(n): r.started.append(n); r.sup.tick(); gate.wait(2)   # a tick while the restart is still busy
        r.sup.start_fn = slow_start
        r.sup.restart("energy"); time.sleep(0.05); gate.set(); self.wait_idle(r, "energy")
        self.assertEqual(r.state("energy"), "starting")
        for _ in range(int((S.START_WAIT_S - 10) / 5)): r.tick(5)             # MasterVolt takes a while before it listens
        self.assertEqual(r.started, ["energy"])
        r.up.add(8000); r.tick(5); self.assertEqual(r.state("energy"), "running")

    def test_restart_refused_without_stopping(self):
        def pre(n):
            if n == "energy": raise ValueError("Float is latched: do not restart now")
        r = Rig(precheck=pre); r.tick()
        with self.assertRaisesRegex(ValueError, "Float is latched"): r.sup.restart("energy")
        r.hold("anchor")
        with self.assertRaisesRegex(ValueError, "on hold"): r.sup.restart("anchor")
        with self.assertRaisesRegex(ValueError, "unknown"): r.sup.restart("gateway")
        r.sup.mods["guard"]["busy"] = "restart"
        with self.assertRaisesRegex(ValueError, "already"): r.sup.restart("guard")
        self.assertEqual(r.stopped, []); self.assertEqual(r.started, [])

    def test_failed_stop_hands_over_to_the_loop(self):
        r = Rig(); r.tick()
        r.sup.stop_fn = lambda n: (_ for _ in ()).throw(RuntimeError("port 8095 still in use"))
        r.sup.restart("guard"); self.wait_idle(r, "guard")
        self.assertEqual(r.started, []); self.assertIn("restart failed", r.sup.mods["guard"]["last_event"]["text"])

    def test_shutdown_all_stops_everything_and_nothing_restarts(self):
        r = Rig(); r.tick(); done = threading.Event()
        r.sup.shutdown_all(on_done=done.set); self.assertTrue(done.wait(2))
        self.assertEqual(r.stopped, ["washer", "guard", "anchor", "energy"])
        snap = r.sup.snapshot()["shutdown"]; self.assertEqual((snap["state"], snap["stopped"], snap["failed"]), ("done", r.stopped, {}))
        for n in r.ports: self.assertEqual(r.state(n), "stopped")
        r.sup.run()                                                            # the loop has been stopped: returns at once
        for _ in range(20): r.tick(60)                                         # and even a tick never starts a module again
        self.assertEqual(r.started, [])

    def test_shutdown_refused_before_anything_stops(self):
        def pre(n, why="restart"):
            if n == "anchor": raise ValueError("Anchor drag: do not restart now")
        r = Rig(precheck=pre); r.tick()
        with self.assertRaisesRegex(ValueError, "Anchor drag"): r.sup.shutdown_all()
        r2 = Rig(); r2.tick(); r2.sup.mods["energy"]["busy"] = "restart"
        with self.assertRaisesRegex(ValueError, "restart is running"): r2.sup.shutdown_all()
        self.assertEqual(r.stopped + r2.stopped, []); self.assertIsNone(r.sup.shutdown)
        r.tick(S.GRACE_S); self.assertEqual(r.state("energy"), "running")    # the loop carries on after a refusal

    def test_shutdown_reports_a_module_that_would_not_stop(self):
        r = Rig(); r.tick(); done = threading.Event()
        def stop(n):
            if n == "guard": raise RuntimeError("port 8095 still in use")
            r.stopped.append(n)
        r.sup.stop_fn = stop; r.sup.shutdown_all(on_done=done.set); self.assertTrue(done.wait(2))
        snap = r.sup.snapshot()["shutdown"]
        self.assertEqual(snap["state"], "failed"); self.assertIn("guard", snap["failed"]); self.assertEqual(r.stopped, ["washer", "anchor", "energy"])

    def test_log_tail(self):
        r = Rig(); f = r.logs["anchor"]; f.parent.mkdir()
        self.assertEqual(r.sup.log_tail("anchor")["exists"], False)
        f.write_text("".join(f"10:{i:02d} line {i}\n" for i in range(50)), encoding="utf-8")
        j = r.sup.log_tail("anchor", 5); self.assertEqual(j["lines"], [f"10:{i:02d} line {i}" for i in range(45, 50)])
        f.write_bytes(("x" * 99 + "\n").encode() * 8000 + b"last \xe2\x82\xac line\n")                # 800 KB: only the tail is read
        j = r.sup.log_tail("anchor", 3); self.assertEqual(j["lines"][-1], "last \u20ac line"); self.assertEqual(len(j["lines"]), 3)
        self.assertEqual(len(r.sup.log_tail("gateway", 10)["lines"]), 0)
        with self.assertRaisesRegex(ValueError, "unknown log"): r.sup.log_tail("..\\config")

    def test_netstat_parsing(self):
        out = "  TCP    0.0.0.0:8080   0.0.0.0:0   LISTENING   3080\n  TCP  192.168.1.166:8000  0.0.0.0:0  LISTENING  1\n  TCP  10.0.0.1:5000  1.2.3.4:443  ESTABLISHED  9\n  TCP  [::]:8095  [::]:0  LISTENING  4\n"
        orig = S.subprocess.run
        S.subprocess.run = lambda *a, **k: type("R", (), {"stdout": out})()
        try: self.assertEqual(S.listening_ports(), {8080, 8000, 8095})
        finally: S.subprocess.run = orig


class FakeUp:
    def __init__(self, answers): self.answers = answers
    def request(self, module, method, path, query, body, ctype):
        a = self.answers.get(path)
        if isinstance(a, Exception): raise a
        return 200, "application/json", None, json.dumps(a).encode(), None


class PrecheckTest(unittest.TestCase):
    def test_energy_and_anchor(self):
        ok = {"/api/bms": {"control_status": {"busy": False}}, "/api/energy": {"high_soc_float_policy": {"float_latched": False}},
              "/api/state": {"alarms": []}}
        drifter.make_precheck(FakeUp(ok))("energy"); drifter.make_precheck(FakeUp(ok))("anchor"); drifter.make_precheck(FakeUp({}))("washer")
        with self.assertRaisesRegex(ValueError, "BMS control"): drifter.make_precheck(FakeUp({**ok, "/api/bms": {"control_status": {"busy": True}}}))("energy")
        latched = FakeUp({**ok, "/api/energy": {"high_soc_float_policy": {"float_latched": True}}})
        with self.assertRaisesRegex(ValueError, "latched"): drifter.make_precheck(latched)("energy")
        drifter.make_precheck(latched)("energy", "shutdown")                     # switching everything off is allowed with Float latched
        with self.assertRaisesRegex(ValueError, "BMS control"): drifter.make_precheck(FakeUp({**ok, "/api/bms": {"control_status": {"busy": True}}}))("energy", "shutdown")
        with self.assertRaisesRegex(ValueError, "Anchor drag"): drifter.make_precheck(FakeUp({**ok, "/api/state": {"alarms": [{"text": "Anchor drag"}]}}))("anchor")

    def test_unreachable_server_may_be_restarted(self):
        drifter.make_precheck(FakeUp({"/api/bms": ConnectionRefusedError(10061, "refused")}))("energy")


class FakeSup:
    def __init__(self): self.calls = []
    def snapshot(self): return {"enabled": True, "modules": {}, "events": []}
    def restart(self, n):
        if n == "energy": raise ValueError("Float is latched: do not restart now")
        self.calls.append(n)
    def shutdown_all(self, on_done=None):
        if self.refuse: raise ValueError("Float is latched: do not restart now")
        self.calls.append("shutdown"); self.on_done = on_done
    def log_tail(self, n, lines):
        if n not in ("energy", "gateway"): raise ValueError(f"unknown log {n}")
        return {"module": n, "lines": [f"line {i}" for i in range(lines)]}
    refuse = False


class ApiTest(unittest.TestCase):
    def serve(self, sup):
        cfg = drifter.load_config(Path("does-not-exist.json")); cfg.update(bind="127.0.0.1", port=0)
        gw = drifter.serve(cfg, supervisor=sup); threading.Thread(target=gw.serve_forever, daemon=True).start()
        self.addCleanup(gw.shutdown); return gw.server_address[1]

    def req(self, port, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, body=None if body is None else json.dumps(body), headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **(headers or {})})
        r = c.getresponse(); d = r.read(); c.close(); return r.status, json.loads(d or b"{}")

    def test_restart_endpoint(self):
        sup = FakeSup(); port = self.serve(sup)
        code, j = self.req(port, "GET", "/api/systems"); self.assertTrue(j["supervisor"]["enabled"])
        self.assertEqual(self.req(port, "POST", "/api/supervisor/restart", {"module": "washer"})[0], 403)   # no X-Drifter-Request
        self.assertEqual(self.req(port, "POST", "/api/supervisor/restart", {"module": "washer"}, {"X-Drifter-Request": "1", "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(sup.calls, [])
        self.assertEqual(self.req(port, "POST", "/api/supervisor/restart", {"module": "washer"}, {"X-Drifter-Request": "1"})[0], 202)
        code, j = self.req(port, "POST", "/api/supervisor/restart", {"module": "energy"}, {"X-Drifter-Request": "1"})
        self.assertEqual(code, 409); self.assertIn("latched", j["error"]); self.assertEqual(sup.calls, ["washer"])

    def test_shutdown_and_log_endpoints(self):
        sup = FakeSup(); port = self.serve(sup); H = {"X-Drifter-Request": "1"}
        self.assertEqual(self.req(port, "POST", "/api/supervisor/shutdown", {})[0], 403)                 # no X-Drifter-Request
        self.assertEqual(self.req(port, "POST", "/api/supervisor/shutdown", {}, {**H, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(sup.calls, [])
        self.assertEqual(self.req(port, "POST", "/api/supervisor/shutdown", {}, H)[0], 202)
        self.assertEqual(sup.calls, ["shutdown"]); self.assertTrue(callable(sup.on_done))            # the gateway ends itself afterwards
        sup.refuse = True; code, j = self.req(port, "POST", "/api/supervisor/shutdown", {}, H)
        self.assertEqual(code, 409); self.assertIn("latched", j["error"])
        code, j = self.req(port, "GET", "/api/supervisor/log?module=energy&lines=3"); self.assertEqual((code, j["lines"]), (200, ["line 0", "line 1", "line 2"]))
        self.assertEqual(self.req(port, "GET", "/api/supervisor/log?module=..%5Cconfig")[0], 404)

    def test_supervisor_off_by_default(self):
        port = self.serve(None)
        self.assertFalse(self.req(port, "GET", "/api/systems")[1]["supervisor"]["enabled"])
        self.assertEqual(self.req(port, "POST", "/api/supervisor/restart", {"module": "washer"}, {"X-Drifter-Request": "1"})[0], 409)


if __name__ == "__main__":
    unittest.main()
