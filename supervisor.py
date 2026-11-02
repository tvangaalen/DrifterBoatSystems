"""Supervisor: keeps the module servers (energy, anchor, guard, washer) running, shows their state, restarts on request.

Rules (see CLAUDE.md):
- It never starts a server as its own child: the gateway runs as a scheduled task, and Windows ends a task's whole
  process tree when the task stops (a gateway restart would take MasterVolt down). Every start goes through
  `start_all.ps1 -Only <module> -NoWait`, which creates the process outside this tree (or starts the module's task).
- A server that is already running is adopted, never touched. The supervisor only *starts* a module that has not been
  listening for GRACE_S, then waits up to START_WAIT_S for its port, and backs off (BACKOFF) when starts keep failing.
- It never stops a server by itself. Only `restart()` stops one, on the user's explicit request from the app, after the
  module's pre-check (energy: no BMS control busy, Float not latched; anchor: no alarm).
- `<data>\\hold\\<module>` (set by switch_module.ps1 while a module is being moved) means: leave it alone.
- `shutdown_all()` ("Switch all systems off" in the app) is the other stop the user asks for: after the same pre-checks
  for every module it stops the loop (nothing is started again), stops every module server, then lets the gateway end.
- Console windows (MasterVolt, anchor watch) are shown or hidden as the user chose in the app (`<data>\\consoles.json`,
  default hidden); start_all.ps1 starts them that way and the loop puts a window back when it differs.
Stdlib only.
"""
from __future__ import annotations

import ctypes, json, logging, os, subprocess, sys, threading, time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tools"))
import modules as M  # noqa: E402

log = logging.getLogger("drifter")
GRACE_S, START_WAIT_S, STABLE_S, TICK_S = 30, 150, 600, 5
BACKOFF = [60, 120, 300, 600, 900]          # s between failed start attempts
SUPERVISED = ("energy", "anchor", "guard", "washer")   # the gateway cannot supervise itself (its task restarts it)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SHUTDOWN_ORDER = ("washer", "guard", "anchor", "energy")
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4


def listening_ports() -> set[int]:
    """Ports with a listening TCP socket on this PC (any address), from netstat."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
    ports = set()
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[0] == "TCP" and p[3] == "LISTENING":
            try: ports.add(int(p[1].rsplit(":", 1)[1]))
            except ValueError: pass
    return ports


def _ps(script: str, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / script), *args],
                          capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def start_module(name: str) -> None:
    r = _ps("start_all.ps1", "-Only", name, "-NoWait")
    if r.returncode: raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or f"start_all exit {r.returncode}")


def stop_module(name: str) -> None:
    r = _ps("tools/stop_module.ps1", name)
    if r.returncode: raise RuntimeError((r.stdout or r.stderr).strip()[-300:] or f"stop_module exit {r.returncode}")


def listener_pid(port: int) -> int | None:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[0] == "TCP" and p[3] == "LISTENING" and p[1].rsplit(":", 1)[-1] == str(port): return int(p[4])
    return None


class _PE(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32), ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


def parents() -> dict[int, int]:
    """pid -> parent pid of every process (Toolhelp snapshot)."""
    k = ctypes.windll.kernel32; k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k.CreateToolhelp32Snapshot(2, 0); e = _PE(); e.dwSize = ctypes.sizeof(_PE); out = {}
    try:
        ok = k.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
        while ok: out[e.th32ProcessID] = e.th32ParentProcessID; ok = k.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
    finally: k.CloseHandle(ctypes.c_void_p(snap))
    return out


def find_console(port: int):
    """The console window of the server listening on `port`: the ConsoleWindowClass window owned by that process or one
    of its launchers (cmd of the start script). Not by title: a stale window of an earlier start may have the same title."""
    if os.name != "nt": return None
    pid = listener_pid(port)
    if not pid: return None
    par, chain = parents(), set()
    while pid and pid not in chain and len(chain) < 12: chain.add(pid); pid = par.get(pid)
    u = ctypes.windll.user32; found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        owner = ctypes.c_uint32(); u.GetWindowThreadProcessId(ctypes.c_void_p(h), ctypes.byref(owner))
        if owner.value in chain:
            cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(ctypes.c_void_p(h), cls, 64)
            if cls.value == "ConsoleWindowClass": found.append(h); return False
        return True
    u.EnumWindows(proto(cb), None)
    return found[0] if found else None


def window_alive(h) -> bool: return bool(ctypes.windll.user32.IsWindow(ctypes.c_void_p(h)))
def window_visible(h) -> bool: return bool(ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(h)))
def show_window(h, show: bool) -> None: ctypes.windll.user32.ShowWindow(ctypes.c_void_p(h), SW_SHOWNOACTIVATE if show else SW_HIDE)


class Supervisor:
    def __init__(self, names=SUPERVISED, ports=None, data=None, listening=listening_ports, start=start_module, stop=stop_module,
                 precheck=None, clock=time.time, consoles=None, find=find_console, alive=window_alive, visible=window_visible, show=show_window):
        self.names = list(names)
        self.ports = ports or {n: M.resolve(n)["port"] for n in self.names}
        self.data = Path(data or M.DATA)
        self.listening, self.start_fn, self.stop_fn, self.precheck, self.clock = listening, start, stop, precheck, clock
        # Modules with a console window. Default: from modules.json, but only for the real supervisor (no `ports` given),
        # so a test never touches a real window.
        self.consoles = set(consoles) if consoles is not None else set() if ports else {n for n in self.names if M.resolve(n)["console"]}
        self.find_fn, self.alive_fn, self.visible_fn, self.show_fn = find, alive, visible, show
        self.hwnd: dict = {}
        self.lock = threading.Lock(); self.events = deque(maxlen=200); self._stop = threading.Event()
        self.mods = {n: {"state": "unknown", "since": None, "down_since": None, "last_start": None, "attempts": 0, "next_try": 0.0,
                         "starts": 0, "busy": None, "last_event": None, "console": None} for n in self.names}
        self.shutdown: dict | None = None

    # ---- events and state
    def event(self, name, text, kind="info"):
        t = self.clock(); e = {"t": t, "module": name, "text": text, "kind": kind}
        with self.lock: self.events.append(e); self.mods[name]["last_event"] = e
        (log.warning if kind != "info" else log.info)("supervisor: %s: %s", name, text)

    def held(self, name) -> bool:
        return (self.data / "hold" / name).exists() or bool(self.mods[name]["busy"])

    def snapshot(self) -> dict:
        now = self.clock()
        with self.lock:
            mods = {n: {**{k: v for k, v in s.items() if k != "last_event"}, "port": self.ports[n], "held": self.held(n),
                        "uptime_s": round(now - s["since"]) if s["state"] == "running" and s["since"] else None,
                        "next_try_in": max(0, round(s["next_try"] - now)) if s["state"] == "failed" else None,
                        "last_event": s["last_event"]} for n, s in self.mods.items()}
            return {"enabled": True, "modules": mods, "events": list(self.events)[-60:],
                    "shutdown": dict(self.shutdown, stopped=list(self.shutdown["stopped"]), failed=dict(self.shutdown["failed"])) if self.shutdown else None}

    # ---- the loop
    def tick(self):
        try: up = self.listening()
        except Exception as e: log.warning("supervisor: cannot read listening ports (%s)", e); return
        now = self.clock()
        for n in self.names:
            s = self.mods[n]
            if s["busy"]: continue                     # a restart is running: it sets the state itself
            if self.ports[n] in up:
                self._console(n)
                if s["state"] != "running":
                    self.event(n, "running" + (f" ({now - s['last_start']:.0f} s after start)" if s["state"] == "starting" else
                                               " (adopted)" if s["state"] == "unknown" else ""))
                    s.update(state="running", since=now, down_since=None)
                if s["attempts"] and now - s["since"] > STABLE_S: s["attempts"] = 0
                continue
            if (self.data / "hold" / n).exists():
                if s["state"] != "held": self.event(n, "on hold: not started by the supervisor"); s.update(state="held", down_since=None)
                continue
            if s["state"] == "starting":
                if now - s["last_start"] < START_WAIT_S: continue
                s["attempts"] += 1; wait = BACKOFF[min(s["attempts"] - 1, len(BACKOFF) - 1)]
                s.update(state="failed", next_try=now + wait)
                self.event(n, f"did not start within {START_WAIT_S} s; next try in {wait // 60} min", "warn"); continue
            if s["down_since"] is None:
                s["down_since"] = now
                if s["state"] != "failed": s["state"] = "down"; self.event(n, "not running", "warn")
            if now >= max(s["down_since"] + GRACE_S, s["next_try"]): self._start(n, now)

    def _start(self, n, now):
        s = self.mods[n]; s.update(state="starting", last_start=now); s["starts"] += 1
        self.event(n, "starting")
        try: self.start_fn(n)
        except Exception as e: self.event(n, f"start failed: {e}", "warn")   # counted as a failed attempt after START_WAIT_S

    def run(self):
        log.info("supervisor started for %s", ", ".join(self.names))
        while not self._stop.is_set():
            self.tick(); self._stop.wait(TICK_S)

    # ---- console windows, shown or hidden as the user chose (default hidden)
    def console_prefs(self) -> dict:
        try: return json.loads((self.data / "consoles.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): return {}

    def _console(self, n):
        """Puts module n's console window in the chosen state; records whether there is one. Never raises."""
        if n not in self.consoles: return
        want = bool(self.console_prefs().get(n, False))
        try:
            h = self.hwnd.get(n)
            if not (h and self.alive_fn(h)): h = self.hwnd[n] = self.find_fn(self.ports[n])   # found once per server start
            if h and self.visible_fn(h) != want: self.show_fn(h, want)
            self.mods[n]["console"] = {"show": want, "window": bool(h)}
        except Exception as e:
            log.warning("supervisor: %s console window: %s", n, e); self.mods[n]["console"] = {"show": want, "window": None}

    def set_console(self, name: str, show: bool) -> None:
        if name not in self.consoles: raise ValueError(f"{name} has no console window")
        prefs = self.console_prefs(); prefs[name] = bool(show)
        self.data.mkdir(parents=True, exist_ok=True); f = self.data / "consoles.json"; tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs, indent=2), encoding="utf-8"); os.replace(tmp, f)
        self._console(name); self.event(name, f"console window {'shown' if show else 'hidden'}")

    # ---- switch everything off on the user's request
    def shutdown_all(self, on_done=None) -> None:
        """Checks every module, then stops them all in the background and calls on_done (the gateway ends itself).
        Raises ValueError (refused) before anything is stopped."""
        if self.shutdown and self.shutdown["state"] == "running": raise ValueError("already switching off")
        busy = [n for n in self.names if self.mods[n]["busy"]]
        if busy: raise ValueError(f"{', '.join(busy)}: a restart is running; try again in a minute")
        if self.precheck:
            for n in self.names: self.precheck(n)    # raises ValueError with the reason
        self.stop_loop()                               # from now on nothing is started again
        for n in self.names: self.mods[n]["busy"] = "shutdown"
        self.shutdown = {"state": "running", "started": self.clock(), "total": len(self.names), "stopped": [], "failed": {}}
        threading.Thread(target=self._shutdown, args=(on_done,), daemon=True, name="shutdown").start()

    def _shutdown(self, on_done):
        order = [n for n in SHUTDOWN_ORDER if n in self.names] + [n for n in self.names if n not in SHUTDOWN_ORDER]
        for n in order:
            self.event(n, "switch all off: stopping")
            try:
                self.stop_fn(n); (self.data / "starting" / n).unlink(missing_ok=True)
                self.shutdown["stopped"].append(n); self.mods[n].update(state="stopped", since=None); self.event(n, "stopped")
            except Exception as e:
                self.shutdown["failed"][n] = str(e); self.event(n, f"could not be stopped: {e}", "bad")
        self.shutdown["state"] = "failed" if self.shutdown["failed"] else "done"; self.shutdown["finished"] = self.clock()
        log.info("supervisor: switch all off %s", self.shutdown["state"])
        if on_done: on_done()

    def start_thread(self):
        threading.Thread(target=self.run, daemon=True, name="supervisor").start()

    def stop_loop(self): self._stop.set()

    # ---- restart on the user's request
    def restart(self, name: str) -> None:
        """Checks and starts a restart in the background. Raises ValueError (refused) before anything is stopped."""
        if name not in self.mods: raise ValueError(f"unknown module {name}")
        s = self.mods[name]
        if s["busy"]: raise ValueError(f"{name}: a restart is already running")
        if (self.data / "hold" / name).exists(): raise ValueError(f"{name} is on hold (being moved)")
        if self.precheck: self.precheck(name)          # raises ValueError with the reason
        s["busy"] = "restart"
        threading.Thread(target=self._restart, args=(name,), daemon=True, name=f"restart-{name}").start()

    def _restart(self, name):
        s = self.mods[name]
        try:
            self.event(name, "restart requested from the app: stopping")
            self.stop_fn(name)
            (self.data / "starting" / name).unlink(missing_ok=True)   # stopped for sure: a new start is allowed
            s.update(attempts=0, next_try=0.0, down_since=None)
            self._start(name, self.clock())
        except Exception as e:
            self.event(name, f"restart failed: {e}; the supervisor will start it again", "bad")
            s.update(state="down", down_since=self.clock() - GRACE_S)   # start at the next tick
        finally: s["busy"] = None
