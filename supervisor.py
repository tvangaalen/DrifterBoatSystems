"""Supervisor: keeps the module servers (energy, anchor, guard, washer, enginelog) running, shows their state, restarts on request.
It runs inside drifterd (the service), which gives it start/stop functions that run each server as drifterd's child in
its own job object.

Rules (see CLAUDE.md):
- A server that is already running is adopted, never touched. The supervisor only *starts* a module that is not
  listening (at once when the supervisor starts, after GRACE_S when it stops later), waits up to START_WAIT_S for its
  port, and backs off (BACKOFF) when starts keep failing.
- It never stops a server by itself. Only `restart()` and `shutdown_all()` stop servers, on the user's explicit request
  from the app, after the gateway's pre-checks (energy: no BMS control busy, Float not latched for a restart; anchor:
  no alarm).
- `<data>\\hold\\<module>` means: leave it alone (not started by the supervisor).
- A restart puts a new Python environment in place when tools/sync_envs.py built one (`<folder>/.venv-next`).
- `log_tail()` reads `<data>\\logs\\<module>.console.log` for the app's log window.
Stdlib only.
"""
from __future__ import annotations

import logging, os, shutil, subprocess, sys, threading, time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tools"))
import modules as M  # noqa: E402

log = logging.getLogger("drifter")
# START_WAIT_S: after a boot without anybody logged on MasterVolt listened 177 s after its start (2026-11-02); a start
# declared failed too early gets a second one, and two MasterVolts would fight over the USB Link.
GRACE_S, START_WAIT_S, STABLE_S, TICK_S = 30, 300, 600, 5
BACKOFF = [60, 120, 300, 600, 900]          # s between failed start attempts
SUPERVISED = M.MODULES                                  # the gateway is kept running by drifterd itself
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SHUTDOWN_ORDER = ("enginelog", "washer", "guard", "anchor", "energy")
LOG_NAMES = M.NAMES


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


class Supervisor:
    def __init__(self, names=SUPERVISED, ports=None, data=None, listening=listening_ports, start=None, stop=None,
                 precheck=None, clock=time.time, logs=None, start_async=True, folders=None):
        self.names = list(names)
        self.ports = ports or {n: M.resolve(n)["port"] for n in self.names}
        self.data = Path(data or M.DATA)
        if start is None or stop is None: raise ValueError("the supervisor needs start and stop functions (drifterd gives them)")
        self.listening, self.start_fn, self.stop_fn, self.precheck, self.clock = listening, start, stop, precheck, clock
        self.start_async = start_async        # starts run in their own thread, so one slow start never holds up the others
        # Log file per module (and the gateway): <data>\\logs\\<module>.console.log, written by drifterd
        self.logs = logs or {n: Path(M.resolve(n)["log"]) for n in LOG_NAMES}
        # module code folders, for swapping in a new Python environment at a restart (none for tests: no `ports` given)
        self.folders = folders if folders is not None else {} if ports else {n: Path(M.resolve(n)["folder"]) for n in self.names}
        self.lock = threading.Lock(); self.events = deque(maxlen=200); self._stop = threading.Event()
        self.mods = {n: {"state": "unknown", "since": None, "down_since": None, "last_start": None, "attempts": 0, "next_try": 0.0,
                         "starts": 0, "busy": None, "last_event": None} for n in self.names}
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
                s["down_since"] = now - (GRACE_S if s["state"] == "unknown" else 0)   # down at the supervisor's start: at once
                if s["state"] != "failed": s["state"] = "down"; self.event(n, "not running", "warn")
            if now >= max(s["down_since"] + GRACE_S, s["next_try"]): self._start(n, now)

    def _start(self, n, now=None):
        s = self.mods[n]; s.update(state="starting", last_start=self.clock()); s["starts"] += 1
        self.event(n, "starting")
        def go():
            try: self.start_fn(n)
            except Exception as e: self.event(n, f"start failed: {e}", "warn")   # counted as a failed attempt after START_WAIT_S
        if self.start_async: threading.Thread(target=go, daemon=True, name=f"start-{n}").start()
        else: go()

    def run(self):
        log.info("supervisor started for %s", ", ".join(self.names))
        while not self._stop.is_set():
            self.tick(); self._stop.wait(TICK_S)

    # ---- log files for the app
    def log_tail(self, name: str, lines: int = 400) -> dict:
        """The last `lines` lines of a module's log file (newest last); reads at most the last 512 KB."""
        if name not in self.logs: raise ValueError(f"unknown log {name}")
        f = Path(self.logs[name]); lines = max(1, min(int(lines), 5000))
        try:
            with open(f, "rb") as fh:
                size = fh.seek(0, 2); fh.seek(max(0, size - 512 * 1024)); data = fh.read()
        except FileNotFoundError: return {"module": name, "file": str(f), "exists": False, "lines": [], "size": 0}
        text = data.decode("utf-8", errors="replace").splitlines()
        if size > len(data): text = text[1:]                     # the first line is cut off
        return {"module": name, "file": str(f), "exists": True, "size": size, "lines": text[-lines:]}

    # ---- switch everything off on the user's request
    def shutdown_all(self, on_done=None) -> None:
        """Checks every module, then stops them all in the background and calls on_done (the gateway ends itself).
        Raises ValueError (refused) before anything is stopped."""
        if self.shutdown and self.shutdown["state"] == "running": raise ValueError("already switching off")
        busy = [n for n in self.names if self.mods[n]["busy"]]
        if busy: raise ValueError(f"{', '.join(busy)}: a restart is running; try again in a minute")
        if self.precheck:
            for n in self.names: self.precheck(n, "shutdown")    # raises ValueError with the reason
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

    def _swap_env(self, name):
        """A restart puts a new Python environment in place when tools/sync_envs.py built one (<folder>/.venv-next):
        only the supervisor, in the servers' own session, can stop them, so the swap happens here, between stop and start."""
        folder = self.folders.get(name)
        if not folder or not (folder / ".venv-next").exists(): return
        nxt, cur, old = folder / ".venv-next", folder / ".venv", folder / ".venv-old"
        for _ in range(20):                           # a launcher may hold files for a moment after the server ended
            try:
                if old.exists(): shutil.rmtree(old)
                if cur.exists(): os.replace(cur, old)
                os.replace(nxt, cur); self.event(name, "new Python environment in place (.venv-next)"); return
            except OSError: time.sleep(1)
        self.event(name, "could not swap in .venv-next (files in use); starting with the old environment", "warn")

    def _restart(self, name):
        s = self.mods[name]
        try:
            self.event(name, "restart requested from the app: stopping")
            self.stop_fn(name)
            self._swap_env(name)
            (self.data / "starting" / name).unlink(missing_ok=True)   # stopped for sure: a new start is allowed
            s.update(attempts=0, next_try=0.0, down_since=None)
            self._start(name, self.clock())
        except Exception as e:
            self.event(name, f"restart failed: {e}; the supervisor will start it again", "bad")
            s.update(state="down", down_since=self.clock() - GRACE_S)   # start at the next tick
        finally: s["busy"] = None
