"""Bluetooth event log and per-device counters for the DALY BMS and balancer links.

The measurement history only records *successful* readings, so connection trouble left no trace. Every
connect, read, timeout and watchdog action is logged here: to a rotating file (logs/bluetooth.log), to a small
in-memory ring buffer and into per-device counters that the API exposes (/api/bluetooth-events).
The same counters hold *timings* (how long connect, notifications, a status read, a disconnect, a scan, the wait for the
radio and the time the radio was held took), so time-outs can be chosen from measurements instead of guesses, and the
advertisement *signal strength* (RSSI, dBm) of every DALY device seen in a scan, to tell a weak link from other causes.
Logging must never disturb the Bluetooth code, so every failure to log is swallowed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

SLOW_CONNECT_SECONDS = 8.0  # a connect that succeeds but takes this long is written to the log file as well
TIMING_SAMPLES = 200  # most recent samples per device and kind that the percentiles are calculated from
SIGNAL_SAMPLES = 100  # most recent advertisement signal strengths (dBm) per device


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


class BleEventLog:
    def __init__(self, path=None, keep=300):
        self.lock = threading.Lock()
        self.events = deque(maxlen=keep)
        self.counters = {}
        self.timings = {}
        self.signals = {}
        self._logger = None
        if path:
            self.configure(path)

    def configure(self, path):
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            logger = logging.getLogger("mastervolt.bluetooth")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
            handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
            self._logger = logger
        except Exception:
            self._logger = None

    def _counter(self, device):
        return self.counters.setdefault(
            device,
            {
                "events": {},
                "failures": {},
                "consecutive_failures": 0,
                "last_success_epoch": None,
                "last_error": None,
                "last_error_epoch": None,
            },
        )

    def log(self, device, kind, detail="", success=False, failure=False, quiet=False):
        """Record one event. `success` resets the failure streak; `failure` extends it.
        `quiet` events (the routine successes, thousands per day) only update the counters, not the ring buffer or the file."""
        now = time.time()
        entry = {
            "time": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds"),
            "device": device,
            "kind": kind,
            "detail": str(detail)[:300],
        }
        with self.lock:
            counter = self._counter(device)
            counter["events"][kind] = counter["events"].get(kind, 0) + 1
            if success:
                counter["consecutive_failures"] = 0
                counter["last_success_epoch"] = now
            if failure:
                counter["consecutive_failures"] += 1
                counter["failures"][kind] = counter["failures"].get(kind, 0) + 1
                counter["last_error"] = entry["detail"] or kind
                counter["last_error_epoch"] = now
            if not quiet:
                self.events.append(entry)
        if self._logger and not quiet:
            try:
                self._logger.info("%s %s%s", device, kind, f" | {entry['detail']}" if entry["detail"] else "")
            except Exception:
                pass

    def timing(self, device, kind, seconds, ok=True):
        """Record how long one operation took and whether it succeeded (time-outs count as failed samples)."""
        try:
            seconds = max(0.0, float(seconds))
            with self.lock:
                item = self.timings.setdefault(device, {}).setdefault(
                    kind,
                    {
                        "count": 0,
                        "ok": 0,
                        "sum_ok": 0.0,
                        "max_ok": 0.0,
                        "max_failed": 0.0,
                        "last": None,
                        "recent": deque(maxlen=TIMING_SAMPLES),
                    },
                )
                item["count"] += 1
                item["last"] = (round(seconds, 2), bool(ok))
                item["recent"].append((seconds, bool(ok)))
                if ok:
                    item["ok"] += 1
                    item["sum_ok"] += seconds
                    item["max_ok"] = max(item["max_ok"], seconds)
                else:
                    item["max_failed"] = max(item["max_failed"], seconds)
            if ok and kind == "connect" and seconds >= SLOW_CONNECT_SECONDS:
                self.log(device, "slow_connect", f"connected after {seconds:.1f} s")
        except Exception:
            pass

    def rssi(self, device, dbm):
        """Record the signal strength (dBm) of one advertisement seen during a scan. Values that cannot be right are ignored."""
        try:
            dbm = int(dbm)
            if not -127 <= dbm <= 20:
                return
            with self.lock:
                item = self.signals.setdefault(
                    device,
                    {"count": 0, "sum": 0, "min": dbm, "max": dbm, "last": dbm, "last_epoch": None, "recent": deque(maxlen=SIGNAL_SAMPLES)},
                )
                item["count"] += 1
                item["sum"] += dbm
                item["min"] = min(item["min"], dbm)
                item["max"] = max(item["max"], dbm)
                item["last"] = dbm
                item["last_epoch"] = time.time()
                item["recent"].append(dbm)
        except Exception:
            pass

    @contextmanager
    def timed(self, device, kind):
        """`with ble_log.timed(name,"connect"): await ...` - the sample is a success unless the block raises (also on a time-out)."""
        started = time.monotonic()
        ok = False
        try:
            yield
            ok = True
        finally:
            self.timing(device, kind, time.monotonic() - started, ok)

    def _timing_summary(self, item):
        good = [s for s, ok in item["recent"] if ok]
        bad = [s for s, ok in item["recent"] if not ok]
        summary = {
            "count": item["count"],
            "ok": item["ok"],
            "failed": item["count"] - item["ok"],
            "last_seconds": item["last"][0] if item["last"] else None,
            "last_ok": item["last"][1] if item["last"] else None,
            "max_ok_seconds": round(item["max_ok"], 2),
            "max_failed_seconds": round(item["max_failed"], 2),
            "avg_ok_seconds": round(item["sum_ok"] / item["ok"], 2) if item["ok"] else None,
        }
        if good:
            summary.update(p50_ok_seconds=round(_percentile(good, 0.5), 2), p95_ok_seconds=round(_percentile(good, 0.95), 2))
        if bad:
            summary["median_failed_seconds"] = round(_percentile(bad, 0.5), 2)
        return summary

    def snapshot(self, limit=100):
        with self.lock:
            counters = {
                device: {**counter, "events": dict(counter["events"]), "failures": dict(counter["failures"])}
                for device, counter in self.counters.items()
            }
            for device, kinds in self.timings.items():
                counters.setdefault(device, {**self._counter_defaults()})["timings"] = {
                    kind: self._timing_summary(item) for kind, item in kinds.items()
                }
            for device, item in self.signals.items():
                recent = list(item["recent"])
                counters.setdefault(device, {**self._counter_defaults()})["signal"] = {
                    "count": item["count"],
                    "last_dbm": item["last"],
                    "last_seen_epoch": item["last_epoch"],
                    "avg_dbm": round(item["sum"] / item["count"], 1),
                    "recent_avg_dbm": round(sum(recent) / len(recent), 1),
                    "min_dbm": item["min"],
                    "max_dbm": item["max"],
                }
            return {"counters": counters, "events": list(self.events)[-max(1, min(int(limit), 300)) :]}

    def clear(self):
        with self.lock:
            self.events.clear()
            self.counters.clear()
            self.timings.clear()
            self.signals.clear()

    @staticmethod
    def _counter_defaults():
        return {
            "events": {},
            "failures": {},
            "consecutive_failures": 0,
            "last_success_epoch": None,
            "last_error": None,
            "last_error_epoch": None,
        }


ble_log = BleEventLog()
