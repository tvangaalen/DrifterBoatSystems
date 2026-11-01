"""Runs the battery health report for the web app.

battery_health.py runs in a separate, low-priority process so that reading and analysing the history
can never slow down the server's MasterBus/Bluetooth threads (GIL) or the Float protection. Only one
report runs at a time; the latest result stays in memory until the server restarts.
"""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_DAYS = 365
PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # the folder that contains the `mastervolt` package


def _now():
    return datetime.now(timezone.utc).isoformat()


class BatteryHealthReports:
    def __init__(self, project, script=None, timeout_seconds=300):
        self.project = Path(project)
        self.script = Path(script) if script else None  # None: run the report module (python -m mastervolt.reports.battery_health)
        self.timeout = timeout_seconds
        self.lock = threading.Lock()
        self._state = {"state": "idle", "days": None, "started_at": None, "finished_at": None,
                       "duration_seconds": None, "markdown": None, "error": None}

    def status(self):
        with self.lock:
            return dict(self._state)

    def start(self, days):
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
            raise ValueError(f"days must be a whole number from 1 to {MAX_DAYS}")
        with self.lock:
            if self._state["state"] == "running":
                raise RuntimeError("A battery health report is already being generated")
            self._state = {"state": "running", "days": days, "started_at": _now(), "finished_at": None,
                           "duration_seconds": None, "markdown": None, "error": None}
        threading.Thread(target=self._run, args=(days,), daemon=True, name="battery-health-report").start()
        return self.status()

    def _run(self, days):
        started = time.monotonic()
        markdown = error = None
        try:
            if self.script is not None and not self.script.exists():
                raise FileNotFoundError(f"{self.script.name} was not found next to the application")
            target = [str(self.script)] if self.script else ["-m", "mastervolt.reports.battery_health"]
            # BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW on Windows.
            flags = 0x00004000 | 0x08000000 if os.name == "nt" else 0
            proc = subprocess.run(
                [sys.executable, *target, "--project", str(self.project), "--days", str(days)],
                capture_output=True, timeout=self.timeout, creationflags=flags, cwd=str(PACKAGE_ROOT),
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
            if proc.returncode != 0:
                lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(" ".join(lines[-3:]) if lines else f"The report failed (exit code {proc.returncode})")
            markdown = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")  # Windows text mode wrote CRLF
        except subprocess.TimeoutExpired:
            error = f"The report took longer than {self.timeout} s and was stopped. Try fewer days."
        except Exception as exc:
            error = str(exc).strip() or type(exc).__name__
        with self.lock:
            self._state.update({"state": "error" if error else "done", "finished_at": _now(),
                                "duration_seconds": round(time.monotonic() - started, 1),
                                "markdown": markdown, "error": error})
