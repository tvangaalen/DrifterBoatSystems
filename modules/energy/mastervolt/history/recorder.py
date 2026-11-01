"""Background recorder: writes the dashboard, the BMS units and the balancers into the history database.

Every 10 s the dashboard picture is stored; each *new* Bluetooth measurement is stored exactly once (by its capture
time). About once a minute it prunes rows past the retention period and brings the server-side chart cache up to date,
so a History page left open - or a server running for days - always shows current data (CHANGELOG 1.16.0).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..logs import warn_once

log = logging.getLogger("mastervolt.history")

RECORD_INTERVAL_SECONDS = 10
HOUSEKEEPING_EVERY = 6  # passes: prune + chart-cache sync roughly once a minute


class HistoryRecorder:
    def __init__(self, history, masterbus, bms, balancers, house_soc: Callable[[], float | None], stop: threading.Event):
        self.history, self.masterbus, self.bms, self.balancers = history, masterbus, bms, balancers
        self.house_soc, self.stop = house_soc, stop
        self._last_bms: dict[str, str] = {}
        self._last_balancers: dict[str, str] = {}

    def _guard(self, key: str, step: Callable[[], None]) -> None:
        try:
            step()
        except Exception:
            warn_once(log, key, f"History recorder step '{key}' failed")

    def _dashboard(self) -> None:
        data = self.masterbus.energy()
        if "house" in data.get("storage", {}):
            data["storage"]["house"]["soc"] = self.house_soc()
        self.history.record("dashboard", data)

    def _bms(self) -> None:
        for name, value in self.bms.snapshot().get("batteries", {}).items():
            stamp = value.get("captured_at")
            if stamp and stamp != self._last_bms.get(name):
                self.history.record("bms", value, name, stamp)
                self._last_bms[name] = stamp

    def _balancers(self) -> None:
        for name, value in self.balancers.snapshot().get("devices", {}).items():
            stamp = value.get("captured_at")
            if stamp and stamp != self._last_balancers.get(name):
                payload = {"state": value.get("state"), "status": value.get("status", {}), "error": value.get("error")}
                self.history.record("balancer", payload, name, stamp)
                self._last_balancers[name] = stamp

    def run(self) -> None:
        passes = 0
        while not self.stop.wait(RECORD_INTERVAL_SECONDS):
            passes += 1
            self._guard("dashboard", self._dashboard)
            self._guard("bms", self._bms)
            self._guard("balancers", self._balancers)
            if passes % HOUSEKEEPING_EVERY == 0:
                self._guard("prune", lambda: self.history.prune(self.masterbus.get_settings()["history_retention_days"]))
                self._guard("chart-cache", self.history.refresh_chart_cache)
