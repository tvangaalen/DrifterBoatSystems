"""drifterd: the Drifter Boat Systems service.

Starts the gateway and the four module servers as its own child processes, each in its own kill-on-close job object
(stopping a server, or drifterd ending, also ends everything it started), writes their output to
<data>\\logs\\<module>.console.log, keeps them running (supervisor.py: start after a crash with back-off, never stop on its
own), checks their health for the System page (display only), and answers the gateway on a local control API.

    python drifterd.py run         in the foreground (development; never next to the service)
    python drifterd.py service     how Windows starts it (installed by tools/install_service.ps1, service "Drifter")

Control API on 127.0.0.1:8099, every request with the header X-Drifterd-Token = <data>\\drifterd.token (made at the first
start; only the gateway on this PC reads it): GET /status, GET /log?module=&lines=, POST /restart {"module"},
POST /shutdown. Pre-checks (BMS busy, anchor alarm) are the gateway's job before it asks; drifterd only executes.
"Switch all systems off" ends drifterd itself after the modules and the gateway: the service then stays stopped until the
desktop icon (or a boot) starts it. A crash makes Windows restart the service (recovery actions).
Stdlib only: it runs on the plain python.org Python, not in a virtual environment.
"""
from __future__ import annotations

import ctypes, json, logging, os, secrets, ssl, subprocess, sys, threading, time, urllib.request
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from common import logs, proc  # noqa: E402
from common.web import QuietServer  # noqa: E402
import modules as M  # noqa: E402
import supervisor as S  # noqa: E402

VERSION = "1.0.0"
CONTROL = ("127.0.0.1", 8099)
SERVICE_NAME = "Drifter"
log = logging.getLogger("drifter")


def token_file(data: Path) -> Path: return Path(data) / "drifterd.token"


def ensure_token(data: Path) -> str:
    f = token_file(data)
    try:
        t = f.read_text(encoding="ascii").strip()
        if len(t) >= 32: return t
    except OSError: pass
    f.parent.mkdir(parents=True, exist_ok=True); t = secrets.token_hex(32); f.write_text(t, encoding="ascii"); return t


class Children:
    """The servers as children of drifterd, each in its own job object. An adopted server (running before drifterd
    started) is stopped through its listener and the launchers above it."""

    def __init__(self, resolve=M.resolve):
        self.resolve, self.jobs, self.procs, self.lock = resolve, {}, {}, threading.Lock()

    def start(self, name: str) -> None:
        m = self.resolve(name); folder = Path(m["folder"])
        for r in m["requires"]:
            if not (folder / r).exists(): raise RuntimeError(f"{folder / r} missing: not started")
        logf = Path(m["log"]); logf.parent.mkdir(parents=True, exist_ok=True); proc.rotate(logf)
        cmd = list(m["command"]); exe = folder / cmd[0]
        if exe.exists(): cmd[0] = str(exe)              # .venv\Scripts\python.exe relative to the module folder
        elif cmd[0].startswith(".venv"): raise RuntimeError(f"{exe} missing: build it with tools/sync_envs.py")
        job = proc.new_job()
        with open(logf, "a", encoding="utf-8") as out:
            out.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start by drifterd: {' '.join(m['command'])} in {folder}\n"); out.flush()
            p = proc.start_in_job(job, cmd, cwd=folder, env={**os.environ, **m["env"]}, stdout=out, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, creationflags=proc.NO_WINDOW)
        with self.lock:
            old = self.jobs.pop(name, None)
            if old: proc.end_job(old)
            self.jobs[name], self.procs[name] = job, p

    def running(self, name: str) -> bool:
        p = self.procs.get(name); return bool(p and p.poll() is None)

    def stop(self, name: str, port: int, wait: float = 20) -> None:
        with self.lock: job = self.jobs.pop(name, None); p = self.procs.pop(name, None)
        if job:
            proc.end_job(job)
            if p:
                try: p.wait(10)                       # gone for sure: its files (the log) are free again
                except subprocess.TimeoutExpired: pass
        else:                                            # adopted: the listener and the launchers above it
            pid = proc.listener_pid(port)
            if pid:
                for p in proc.chain(pid): proc.kill(p)
        deadline = time.monotonic() + wait
        while port in S.listening_ports():
            if time.monotonic() > deadline: raise RuntimeError(f"port {port} still in use")
            time.sleep(0.5)

    def stop_all(self) -> None:
        with self.lock: jobs = list(self.jobs.values()); procs = list(self.procs.values()); self.jobs.clear(); self.procs.clear()
        for j in jobs: proc.end_job(j)
        for p in procs:
            try: p.wait(10)
            except subprocess.TimeoutExpired: pass


class Gateway:
    """Keeps the gateway running (it is not one of the supervisor's modules: the page talks to drifterd through it)."""
    BACKOFF = [5, 10, 30, 60]

    def __init__(self, children: Children, port: int, listening=S.listening_ports, clock=time.time):
        self.children, self.port, self.listening, self.clock = children, port, listening, clock
        self.state, self.since, self.failures, self.next_try, self.paused = "starting", clock(), 0, 0.0, False

    def tick(self) -> None:
        if self.paused: return
        now = self.clock()
        if self.children.running("gateway") or self.port in self.listening():
            if self.state != "running": self.state, self.since = "running", now
            return
        if now < self.next_try: return
        if self.state == "running": log.warning("drifterd: the gateway stopped; starting it again")
        try: self.children.start("gateway"); self.state, self.since = "starting", now
        except Exception as e: log.error("drifterd: gateway start failed: %s", e); self.state = "failed"
        self.next_try = now + self.BACKOFF[min(self.failures, len(self.BACKOFF) - 1)]; self.failures += 1

    def restart(self, sup: S.Supervisor) -> None:
        self.paused = True
        try:
            self.children.stop("gateway", self.port)
            sup.folders.setdefault("gateway", Path(M.resolve("gateway")["folder"])); sup._swap_env("gateway")
            self.failures, self.next_try = 0, 0.0
        finally: self.paused = False

    def snapshot(self) -> dict: return {"state": self.state, "since": self.since, "port": self.port}


class Health:
    """A cheap GET per module (modules.json "health") every PERIOD_S. Display only: a module that does not answer is
    shown as such on the System page; nothing is stopped or restarted because of it."""
    PERIOD_S, TIMEOUT_S = 30, 8

    def __init__(self, specs: dict, clock=time.time):
        self.specs, self.clock, self.state = specs, clock, {}
        self.ctx = ssl.create_default_context(); self.ctx.check_hostname = False; self.ctx.verify_mode = ssl.CERT_NONE   # 127.0.0.1 only

    def check(self, name: str, port: int, up: set) -> dict:
        spec = self.specs.get(name)
        if port not in up: return {"ok": None, "detail": "not listening"}
        if not spec: return {"ok": True, "detail": "port only"}
        scheme, path = spec
        try:
            with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}{path}", timeout=self.TIMEOUT_S, context=self.ctx if scheme == "https" else None) as r:
                return {"ok": True, "detail": f"HTTP {r.status}"}
        except urllib.error.HTTPError as e: return {"ok": e.code < 500, "detail": f"HTTP {e.code}"}
        except Exception as e: return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:160]}

    def run_once(self, ports: dict) -> None:
        up = S.listening_ports()
        for n, port in ports.items():
            r = self.check(n, port, up); old = self.state.get(n)
            r["since"] = old["since"] if old and old["ok"] == r["ok"] else self.clock()
            if old and old["ok"] and r["ok"] is False: log.warning("drifterd: %s does not answer its health check (%s)", n, r["detail"])
            self.state[n] = r


class Daemon:
    def __init__(self, data: Path = M.DATA):
        self.data = Path(data); self.token = ensure_token(self.data); self.stop = threading.Event(); self.started = time.time()
        self.children = Children()
        specs = {n: M.resolve(n) for n in M.NAMES}
        self.gateway = Gateway(self.children, specs["gateway"]["port"])
        self.sup = S.Supervisor(names=M.MODULES, ports={n: specs[n]["port"] for n in M.MODULES}, data=self.data,
                                start=self.children.start, stop=lambda n: self.children.stop(n, specs[n]["port"]),
                                logs={**{n: Path(specs[n]["log"]) for n in M.NAMES}, "drifterd": self.data / "logs" / "drifterd.log"}, folders={n: Path(specs[n]["folder"]) for n in M.MODULES})
        self.health = Health({n: specs[n]["health"] for n in M.NAMES if specs[n]["health"]})
        self.ports = {n: specs[n]["port"] for n in M.NAMES}

    def status(self) -> dict:
        snap = self.sup.snapshot()
        for n, m in snap["modules"].items(): m["health"] = self.health.state.get(n)
        return {"drifterd": {"version": VERSION, "pid": os.getpid(), "started": self.started},
                "gateway": {**self.gateway.snapshot(), "health": self.health.state.get("gateway")}, **snap}

    def finish_shutdown(self) -> None:
        """After "switch all systems off": the page reads the result through the gateway for 15 s, then everything ends."""
        log.warning("drifterd: all modules stopped; the gateway and drifterd end in 15 s")
        def later():
            time.sleep(15); self.gateway.paused = True
            try: self.children.stop("gateway", self.ports["gateway"])
            except Exception as e: log.error("drifterd: gateway did not stop: %s", e)
            self.stop.set()
        threading.Thread(target=later, daemon=True).start()

    def serve_control(self) -> QuietServer:
        d = self

        class H(BaseHTTPRequestHandler):
            timeout = 30
            def log_message(self, *a): pass
            def _json(self, obj, code=200):
                b = json.dumps(obj, default=str).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def _ok(self):
                if not secrets.compare_digest(self.headers.get("X-Drifterd-Token", ""), d.token): self._json({"error": "token"}, 403); return False
                return True
            def do_GET(self):
                if not self._ok(): return
                path, _, q = self.path.partition("?"); args = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
                if path == "/status": return self._json(d.status())
                if path == "/log":
                    try: return self._json(d.sup.log_tail(args.get("module", ""), int(args.get("lines", 400))))
                    except ValueError as e: return self._json({"error": str(e)}, 404)
                self._json({"error": "not found"}, 404)
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(min(n, 65536)) if n > 0 else b""
                if not self._ok(): return
                try: body = json.loads(raw or b"{}")
                except ValueError: return self._json({"error": "invalid JSON"}, 400)
                try:
                    if self.path == "/restart":
                        name = str(body.get("module"))
                        if name == "gateway":   # answer first: the request comes through the gateway itself
                            threading.Thread(target=lambda: (time.sleep(1), d.gateway.restart(d.sup)), daemon=True).start()
                        else: d.sup.restart(name)
                        return self._json({"ok": True, "module": name}, 202)
                    if self.path == "/shutdown": d.sup.shutdown_all(on_done=d.finish_shutdown); return self._json({"ok": True}, 202)
                except ValueError as e: return self._json({"error": str(e)}, 409)
                self._json({"error": "not found"}, 404)

        srv = QuietServer(getattr(self, "control", CONTROL), H); self.control = srv.server_address; threading.Thread(target=srv.serve_forever, daemon=True, name="control").start(); return srv

    def run(self) -> None:
        log.info("drifterd %s starting (pid %d)", VERSION, os.getpid())
        ctl = self.serve_control()
        self.gateway.tick()                              # the app first, then the modules (the supervisor's first tick)
        threading.Thread(target=self.sup.run, daemon=True, name="supervisor").start()
        next_health = 0.0
        try:
            while not self.stop.wait(S.TICK_S):
                self.gateway.tick()
                if time.time() >= next_health:
                    next_health = time.time() + Health.PERIOD_S
                    threading.Thread(target=self.health.run_once, args=(self.ports,), daemon=True).start()
        finally:
            log.info("drifterd: stopping every server")
            self.sup.stop_loop(); self.gateway.paused = True; ctl.shutdown()
            for n in (*S.SHUTDOWN_ORDER, "gateway"):
                if n in self.ports:
                    try: self.children.stop(n, self.ports[n], wait=10)
                    except Exception as e: log.warning("drifterd: %s: %s", n, e)
            self.children.stop_all(); log.info("drifterd stopped")


# ---- Windows service (ctypes: no pywin32, so it runs on the plain Python; a venv's python.exe is only a launcher)
SERVICE_WIN32_OWN_PROCESS, SERVICE_STOPPED, SERVICE_START_PENDING, SERVICE_STOP_PENDING, SERVICE_RUNNING = 0x10, 1, 2, 3, 4
SERVICE_ACCEPT_STOP, SERVICE_ACCEPT_SHUTDOWN, SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN = 1, 4, 1, 5


class _SS(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in ("dwServiceType", "dwCurrentState", "dwControlsAccepted", "dwWin32ExitCode",
                                              "dwServiceSpecificExitCode", "dwCheckPoint", "dwWaitHint")]


_MAIN = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
_HANDLER = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)


class _ENTRY(ctypes.Structure):
    _fields_ = [("lpServiceName", wintypes.LPWSTR), ("lpServiceProc", _MAIN)]


def service() -> None:
    adv = ctypes.WinDLL("advapi32", use_last_error=True); adv.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    keep = {}                                            # references the callbacks so they are not collected

    def set_state(state, exit_code=0, wait_ms=0):
        s = _SS(SERVICE_WIN32_OWN_PROCESS, state, 0 if state == SERVICE_START_PENDING else SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN,
                1066 if exit_code else 0, exit_code, 0, wait_ms)
        adv.SetServiceStatus(keep["h"], ctypes.byref(s))

    def handler(control, event, data, ctx):
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN) and "d" in keep:
            set_state(SERVICE_STOP_PENDING, wait_ms=60000); keep["d"].stop.set()
        return 0

    def main(argc, argv):
        keep["handler"] = _HANDLER(handler)
        keep["h"] = adv.RegisterServiceCtrlHandlerExW(SERVICE_NAME, keep["handler"], None)
        set_state(SERVICE_START_PENDING, wait_ms=30000); code = 0
        try:
            logs.setup(file=M.DATA / "logs" / "drifterd.log")
            keep["d"] = Daemon(); set_state(SERVICE_RUNNING); keep["d"].run()
        except Exception: log.exception("drifterd failed"); code = 1     # a non-zero exit: Windows restarts the service
        set_state(SERVICE_STOPPED, exit_code=code)

    keep["main"] = _MAIN(main)
    table = (_ENTRY * 2)(_ENTRY(SERVICE_NAME, keep["main"]), _ENTRY(None, ctypes.cast(None, _MAIN)))
    if not adv.StartServiceCtrlDispatcherW(table):
        raise SystemExit(f"not started by Windows as a service (error {ctypes.get_last_error()}); use: python drifterd.py run")


if __name__ == "__main__":
    if sys.argv[1:] == ["service"]: service()
    elif sys.argv[1:] == ["run"]:
        logs.setup(file=M.DATA / "logs" / "drifterd.log"); d = Daemon()
        try: d.run()
        except KeyboardInterrupt: d.stop.set()
    else: sys.exit(__doc__)
