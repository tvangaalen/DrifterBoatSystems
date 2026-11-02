"""The server-side schedule: start at, or finish at, a clock time with the program set on the washer now.

Life cycle: pending -> starting -> started -> running -> finished; or missed (more than MISSED_GRACE_S late), failed
(fault, or the start did not work) or interrupted (a manual change while it runs). The record survives a restart
(viomi_schedule.json). At the start the washer is woken if it powered itself off, the saved settings are put back, then
Start is sent; "finished" counts only after the washer was seen running."""
from __future__ import annotations

import json, threading, time
from datetime import datetime, timedelta
from pathlib import Path

from washer.device import IDLE, MODE_MAP, PROGRAM_CAPABILITIES, RUNNING, state_name

MISSED_GRACE_S, MONITOR_INTERVAL_S = 60, 3.0


def now_local() -> datetime: return datetime.now().astimezone()


def next_clock_time(hhmm: str, now: datetime) -> datetime:
    try:
        hh, mm = [int(x) for x in hhmm.split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
    except Exception: raise ValueError("Time must be HH:MM")
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return target + timedelta(days=1) if target <= now else target


class Scheduler:
    def __init__(self, washer, events, path: Path, clock=now_local, sleep=time.sleep, monotonic=time.monotonic):
        self.washer, self.events, self.path = washer, events, Path(path)
        self.clock, self.sleep, self.monotonic = clock, sleep, monotonic
        self.lock = threading.Lock(); self.state = None; self.last_monitor = 0.0
        self.stop_event = threading.Event(); self.thread = None
        self.load()

    # ---- the record
    def _save(self) -> None:
        if self.state is None:
            self.path.unlink(missing_ok=True); return
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8"); tmp.replace(self.path)

    def load(self) -> None:
        with self.lock:
            try: self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
            except Exception as exc: self.events.log("SCHEDULE", f"Could not load schedule: {exc}"); self.state = None

    def public(self) -> dict | None:
        with self.lock:
            if not self.state: return None
            s = dict(self.state); s.pop("config", None); return s

    def _mark(self, status: str, error: str = "", **fields) -> None:
        with self.lock:
            if not self.state: return
            self.state.update(status=status, last_error=error, **fields)
            self.state["updated_at"] = self.clock().isoformat(timespec="seconds"); self._save()

    def cancel(self, reason: str = "Cancelled") -> None:
        with self.lock:
            if self.state: self.events.log("SCHEDULE", reason)
            self.state = None; self._save()

    def interrupt(self, reason: str) -> bool:
        """An already started cycle, deliberately interrupted; it does not block a new schedule."""
        with self.lock:
            if not self.state or self.state.get("status") not in ("started", "running"): return False
            now = self.clock().isoformat(timespec="seconds")
            self.state.update(status="interrupted", last_error=str(reason), interrupted_at=now, updated_at=now); self._save()
        self.events.log("SCHEDULE INTERRUPTED", reason); return True

    def create(self, mode: str, hhmm: str) -> dict | None:
        state = self.washer.read_all()
        if state.get("power") is not True: raise RuntimeError("Washer must be powered on before scheduling")
        if int(state.get("fault") or 0) != 0: raise RuntimeError(f"Washer has fault {state.get('fault')}")
        if int(state.get("status") or 0) not in IDLE: raise RuntimeError("Washer must be idle before scheduling")
        duration = int(state.get("left_time") or 0)
        if duration <= 0: raise RuntimeError("Washer did not provide a valid program duration")
        now = self.clock()
        if mode == "start":
            start_at = next_clock_time(hhmm, now); finish_at = start_at + timedelta(minutes=duration)
        elif mode == "finish":
            finish_at = next_clock_time(hhmm, now); start_at = finish_at - timedelta(minutes=duration)
            if start_at <= now:                       # today's finish is too close: tomorrow
                finish_at += timedelta(days=1); start_at = finish_at - timedelta(minutes=duration)
        else: raise ValueError("Schedule mode must be 'start' or 'finish'")
        if not PROGRAM_CAPABILITIES.get(int(state["mode"])): raise RuntimeError("Unknown program capabilities")
        record = {"status": "pending", "mode": mode, "requested_time": hhmm, "created_at": now.isoformat(timespec="seconds"),
                  "start_at": start_at.isoformat(timespec="seconds"), "finish_at": finish_at.isoformat(timespec="seconds"),
                  "expected_duration": duration, "program_name": MODE_MAP.get(state["mode"], str(state["mode"])),
                  "config": {"program": int(state["mode"]), "temperature": int(state["temperature"]), "spin": int(state["spin"]),
                             "rinses": int(state["rinses"])}, "last_error": ""}
        with self.lock: self.state = record; self._save()
        self.events.log("SCHEDULE", f"{mode.upper()} {hhmm} · start {start_at.strftime('%H:%M')} · finish ~{finish_at.strftime('%H:%M')}")
        return self.public()

    # ---- the start
    def _apply_config(self, cfg: dict) -> None:
        program = int(cfg["program"]); cap = PROGRAM_CAPABILITIES[program]
        self.washer.set_property(2, 3, program); self.sleep(0.8)
        if len(cap["temperatures"]) > 1: self.washer.set_property(2, 6, int(cfg["temperature"]))
        if len(cap["rinses"]) > 1: self.washer.set_property(2, 9, int(cfg["rinses"]))
        self.sleep(0.5)

    def _power_on(self, timeout: float = 8.0) -> dict:
        """The washer can power itself off while a schedule waits: wake it before restoring the settings."""
        state = self.washer.read_all()
        if state.get("power") is True: return state
        self.washer.set_property(2, 1, True); self.events.log("SCHEDULE POWER ON", "Waking washer before scheduled start")
        deadline = self.monotonic() + timeout
        while self.monotonic() < deadline:
            self.sleep(0.5); state = self.washer.read_all()
            if state.get("power") is True: self.sleep(0.5); return state
        raise RuntimeError("Washer did not power on for scheduled start")

    def execute_due(self) -> None:
        with self.lock:
            if not self.state or self.state.get("status") != "pending": return
            record = json.loads(json.dumps(self.state))
        now = self.clock(); start_at = datetime.fromisoformat(record["start_at"]) if record.get("start_at") else None
        if not start_at or now < start_at: return
        late = (now - start_at).total_seconds()
        if late > MISSED_GRACE_S:
            msg = f"Start time missed by {int(late)} seconds"; self._mark("missed", msg); self.events.log("SCHEDULE MISSED", msg); return
        self._mark("starting")                        # first, so that no second pass starts it again
        try:
            state = self._power_on()
            if int(state.get("fault") or 0) != 0: raise RuntimeError(f"Washer fault {state.get('fault')}")
            if int(state.get("status") or 0) not in IDLE: raise RuntimeError(f"Washer is not idle (status {state.get('status')})")
            self._apply_config(record["config"]); self.washer.action(2, 1)
            self._mark("started", started_at=self.clock().isoformat(timespec="seconds"), run_observed=False)
            self.events.log("SCHEDULE START", record.get("program_name", "Program"))
        except Exception as exc:
            self._mark("failed", str(exc)); self.events.log("SCHEDULE FAILED", str(exc))

    # ---- following it to the end
    def monitor(self) -> None:
        now_mono = self.monotonic()
        if now_mono - self.last_monitor < MONITOR_INTERVAL_S: return
        self.last_monitor = now_mono
        with self.lock:
            if not self.state or self.state.get("status") not in ("started", "running"): return
            record = json.loads(json.dumps(self.state))
        try: state = self.washer.read_all()
        except Exception as exc: self.events.log("SCHEDULE MONITOR", f"Status read failed: {exc}"); return   # keep the life cycle
        status, fault = int(state.get("status") or 0), int(state.get("fault") or 0)
        if fault != 0 or status == 27:
            msg = f"Washer fault {fault or status} during scheduled program"; self._mark("failed", msg); self.events.log("SCHEDULE FAILED", msg); return
        if status in RUNNING:                          # seen running: only then may "finished" count
            if record.get("status") != "running" or not record.get("run_observed"):
                self._mark("running", run_observed=True, run_observed_at=record.get("run_observed_at") or self.clock().isoformat(timespec="seconds"))
                self.events.log("SCHEDULE RUNNING", state_name(status, True))
            return
        if status == 17 and record.get("run_observed"):
            actual = self.clock(); planned = datetime.fromisoformat(record["finish_at"]) if record.get("finish_at") else None
            detail = f"Actual {actual.strftime('%H:%M')}"
            if planned:
                delta = int(round((actual - planned).total_seconds() / 60.0))
                detail += " · on time" if delta == 0 else f" · {delta} min late" if delta > 0 else f" · {abs(delta)} min early"
            self._mark("finished", actual_finish_at=actual.isoformat(timespec="seconds")); self.events.log("SCHEDULE FINISHED", detail)

    def tick(self) -> None:
        try: self.execute_due(); self.monitor()
        except Exception as exc: self.events.log("SCHEDULER ERROR", str(exc))

    def start(self) -> None:
        if self.thread and self.thread.is_alive(): return
        def loop():
            while not self.stop_event.wait(1.0): self.tick()
        self.thread = threading.Thread(target=loop, name="washer-scheduler", daemon=True); self.thread.start()
