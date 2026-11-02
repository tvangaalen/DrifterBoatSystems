"""drifterd: children in job objects (start, stop, adopted, requires), the gateway keeper, health checks, the control
API with its token, the gateway's DrifterdClient, and that `drifterd.py service` refuses to run outside Windows' service
manager. Throw-away Python HTTP servers on free ports only: nothing on the boat is touched."""
import http.client, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import drifter, drifterd as D, supervisor as S  # noqa: E402


def free_port():
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def wait(cond, timeout=15):
    t = time.monotonic() + timeout
    while time.monotonic() < t:
        if cond(): return True
        time.sleep(0.1)
    return False


def listening(port): return port in S.listening_ports()


class Specs:
    """resolve() for made-up servers: python -m http.server on a free port, in a temp folder."""
    def __init__(self, tmp: Path):
        self.tmp, self.ports = tmp, {}

    def __call__(self, name):
        port = self.ports.setdefault(name, free_port())
        return {"name": name, "folder": str(self.tmp), "port": port, "log": str(self.tmp / "logs" / f"{name}.console.log"),
                "command": [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], "env": {"DRIFTER_DATA": str(self.tmp)},
                "requires": ["needed.txt"] if name == "picky" else []}


class ChildrenTest(unittest.TestCase):
    def setUp(self):
        self.tmpd = tempfile.TemporaryDirectory(); self.addCleanup(self.tmpd.cleanup); self.tmp = Path(self.tmpd.name)
        self.specs = Specs(self.tmp); self.c = D.Children(resolve=self.specs); self.addCleanup(self.c.stop_all)

    def test_start_logs_and_stop_ends_the_whole_job(self):
        self.c.start("a"); port = self.specs.ports["a"]
        self.assertTrue(wait(lambda: listening(port))); self.assertTrue(self.c.running("a"))
        self.assertIn("start by drifterd", (self.tmp / "logs" / "a.console.log").read_text(encoding="utf-8"))
        pid = self.c.procs["a"].pid
        self.c.stop("a", port); self.assertFalse(listening(port)); self.assertFalse(self.c.running("a"))
        self.assertNotIn(str(pid), subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout)

    def test_requires_blocks_the_start(self):
        with self.assertRaisesRegex(RuntimeError, "needed.txt missing"): self.c.start("picky")
        (self.tmp / "needed.txt").write_text("x"); self.c.start("picky")
        self.assertTrue(wait(lambda: listening(self.specs.ports["picky"])))

    def test_adopted_server_is_stopped_without_touching_this_process(self):
        port = free_port()
        p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(p.kill); self.assertTrue(wait(lambda: listening(port)))
        self.c.stop("adopted", port)                                   # this test's own python is its parent: protected
        self.assertIsNotNone(p.wait(10)); self.assertFalse(listening(port))


class FakeChildren:
    def __init__(self): self.started, self.alive = [], False
    def start(self, name): self.started.append(name); self.alive = True
    def running(self, name): return self.alive
    def stop(self, name, port): self.alive = False


class GatewayTest(unittest.TestCase):
    def test_kept_running_with_back_off(self):
        clock = [1000.0]; ch = FakeChildren(); g = D.Gateway(ch, 8100, listening=set, clock=lambda: clock[0])
        g.tick(); self.assertEqual(ch.started, ["gateway"])
        g.tick(); self.assertEqual(g.state, "running")
        ch.alive = False; g.tick(); self.assertEqual(ch.started, ["gateway"])   # back-off: not at once again
        clock[0] += 10; g.tick(); self.assertEqual(ch.started, ["gateway", "gateway"])
        g.paused = True; ch.alive = False; clock[0] += 100; g.tick(); self.assertEqual(len(ch.started), 2)


class HealthTest(unittest.TestCase):
    def test_states(self):
        port = free_port()
        p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(p.kill); self.assertTrue(wait(lambda: listening(port)))
        h = D.Health({"ok": ("http", "/"), "bad": ("http", "/missing")})
        h.run_once({"ok": port, "bad": port, "plain": port, "down": free_port()})
        self.assertTrue(h.state["ok"]["ok"]); self.assertTrue(h.state["bad"]["ok"])        # 404 is an answer: the server lives
        self.assertEqual(h.state["plain"]["detail"], "port only"); self.assertIsNone(h.state["down"]["ok"])
        self.assertFalse(D.Health({"x": ("https", "/")}).check("x", port, {port})["ok"])   # no TLS there: not answering


class FakeDaemon:
    """What the control API needs of a Daemon, with a supervisor on fake ports."""
    def __init__(self, tmp):
        self.token = "t" * 64; self.control = ("127.0.0.1", 0); self.stopped = []; self.finished = threading.Event()
        self.sup = S.Supervisor(ports={"energy": 8000, "washer": 8080}, names=("energy", "washer"), data=tmp, listening=lambda: {8000, 8080},
                                start=lambda n: None, stop=self.stopped.append, logs={"energy": Path(tmp) / "e.log"}, start_async=False)
        (Path(tmp) / "e.log").write_text("09:00 line 1\n09:01 line 2\n", encoding="utf-8")
        self.sup.tick(); self.gateway = D.Gateway(FakeChildren(), 8100, listening=set)
    def status(self): return {"drifterd": {"version": D.VERSION}, "gateway": self.gateway.snapshot(), **self.sup.snapshot()}
    def finish_shutdown(self): self.finished.set()


class ControlApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpd = tempfile.TemporaryDirectory(); self.addCleanup(self.tmpd.cleanup)
        self.d = FakeDaemon(self.tmpd.name); self.srv = D.Daemon.serve_control(self.d); self.addCleanup(self.srv.shutdown)
        (Path(self.tmpd.name) / "token").write_text(self.d.token, encoding="ascii")
        self.prechecks = []
        def pre(n, why="restart"):
            self.prechecks.append((n, why))
            if n == "anchor" and why == "restart": raise ValueError("anchor alarm active: do not restart now")
        self.client = drifter.DrifterdClient(f"http://127.0.0.1:{self.srv.server_address[1]}", Path(self.tmpd.name) / "token", pre,
                                             modules=("energy", "washer"))

    def raw(self, method, path, token):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request(method, path, body=b"{}" if method == "POST" else None, headers={"X-Drifterd-Token": token}); r = c.getresponse(); r.read(); c.close(); return r.status

    def test_token_required(self):
        self.assertEqual(self.raw("GET", "/status", "wrong"), 403); self.assertEqual(self.raw("POST", "/shutdown", ""), 403)
        self.assertEqual(self.d.stopped, [])

    def test_status_log_restart_shutdown_through_the_client(self):
        snap = self.client.snapshot(); self.assertTrue(snap["enabled"]); self.assertEqual(snap["modules"]["energy"]["state"], "running")
        self.assertEqual(self.client.log_tail("energy", 1)["lines"], ["09:01 line 2"])
        with self.assertRaisesRegex(ValueError, "unknown log"): self.client.log_tail("nope", 5)
        self.client.restart("washer"); self.assertTrue(wait(lambda: self.d.stopped == ["washer"]))
        with self.assertRaisesRegex(ValueError, "anchor alarm"): self.client.restart("anchor")    # the gateway's pre-check refuses first
        with self.assertRaisesRegex(ValueError, "unknown module"): self.client.restart("nope")
        self.client.shutdown_all(); self.assertTrue(self.d.finished.wait(5))
        self.assertIn(("energy", "shutdown"), self.prechecks); self.assertEqual(sorted(self.d.stopped), ["energy", "washer", "washer"])

    def test_drifterd_down(self):
        self.srv.shutdown(); self.srv.server_close()
        snap = self.client.snapshot(); self.assertIn("not reachable", snap["error"]); self.assertEqual(snap["modules"], {})
        with self.assertRaisesRegex(ValueError, "not reachable"): self.client.restart("washer")


class ServiceTest(unittest.TestCase):
    def test_refuses_outside_the_service_manager(self):
        r = subprocess.run([sys.executable, str(ROOT / "drifterd.py"), "service"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0); self.assertIn("not started by Windows as a service", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
