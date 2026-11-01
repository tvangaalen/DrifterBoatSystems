"""The running application: every service, created once and wired together.

`Services` is what the API routes talk to. Wiring that crosses subsystems lives here and nowhere else:

* Float protection (MasterBus) reads its cell voltages from the BMS units (Bluetooth) through `house_soc_details`,
* a fresh Float start sets every battery's SOC to 100% once,
* the history recorder samples all of them.
"""

from __future__ import annotations

import logging
import threading
import time

from . import logs
from .bluetooth.balancers import DalyBalancerService
from .bluetooth.bms import DalyBmsService
from .bluetooth.coordinator import bluetooth_coordinator
from .bluetooth.events import ble_log
from .config import PATHS, Paths
from .history.recorder import HistoryRecorder
from .history.service import HistoryService
from .masterbus.service import MasterBusService
from .reports.service import BatteryHealthReports
from .soc import cell_voltage_stats, house_soc, max_age_seconds

log = logging.getLogger("mastervolt")


class Services:
    def __init__(self, paths: Paths = PATHS, bus=None, coordinator=None):
        logs.configure(paths.logs / "server.log")
        ble_log.configure(paths.bluetooth_log)
        self.paths = paths
        self.masterbus = MasterBusService(paths, bus=bus)
        self.coordinator = coordinator or bluetooth_coordinator  # the one gate to the Bluetooth radio, shared by BMS and balancers
        self.bms = DalyBmsService(paths, coordinator=self.coordinator)
        self.balancers = DalyBalancerService(coordinator=self.coordinator)
        self.history = HistoryService(paths.history_db)
        self.reports = BatteryHealthReports(paths.base)
        self._stop = threading.Event()
        self._recorder_thread: threading.Thread | None = None
        float_protection = self.masterbus.float_protection
        float_protection.details_getter = self.house_soc_details
        float_protection.soc_getter = self.house_soc
        float_protection.started_callback = self._start_soc_100

    # ---- House SOC from the three BMS units -----------------------------------------------------------------
    def house_soc_details(self) -> dict:
        """Average SOC plus the highest single cell and worst cell spread, all from the same *fresh* DALY readings.

        A reading older than max(120 s, 4 refresh intervals) is not used: Float protection must not act on a value the
        Bluetooth link stopped updating. The three BMS units form one bank; the cell figures exist because the average
        SOC can lag badly behind one battery's own cell (soc.py, CHANGELOG 1.13.0).
        """
        batteries = self.bms.snapshot().get("batteries", {})
        now = time.time()
        max_age = max_age_seconds(self.masterbus.get_settings()["bms_refresh_interval"])
        details = house_soc(batteries, now, max_age)
        details.update(cell_voltage_stats(batteries, now, max_age))
        return details

    def house_soc(self) -> float | None:
        return self.house_soc_details()["soc"]

    def _start_soc_100(self) -> None:
        """Called once when Float protection freshly latches: the triggering cell is at the Float voltage, so the battery
        is effectively full - bring every battery's reported SOC to 100% instead of a stale coulomb-counted value.
        Runs in its own thread so a slow Bluetooth write cannot delay the 3 s Float loop."""
        threading.Thread(target=self._set_all_soc_100, daemon=True, name="float-soc-100").start()

    def _set_all_soc_100(self) -> None:
        try:
            self.bms.control_all("set_soc_100")
        except Exception as exc:
            log.warning("Setting every battery to 100%% after the Float start failed: %s", exc)

    # ---- lifecycle ------------------------------------------------------------------------------------------
    def start(self) -> None:
        """Open the hardware and start every background job. A subsystem that fails to start never stops the others."""
        self.masterbus.start()
        try:
            self.bms.start(self.masterbus.get_settings)
        except Exception as exc:
            log.warning("BMS Bluetooth did not start: %s", exc)
        try:
            self.balancers.start(self.masterbus.get_settings)
        except Exception as exc:
            log.warning("Balancer Bluetooth did not start: %s", exc)
        self._stop.clear()
        recorder = HistoryRecorder(self.history, self.masterbus, self.bms, self.balancers, self.house_soc, self._stop)
        self._recorder_thread = threading.Thread(target=recorder.run, daemon=True, name="measurement-history")
        self._recorder_thread.start()
        threading.Thread(target=self.history.refresh_chart_cache, daemon=True, name="history-chart-cache").start()

    def stop(self) -> None:
        self._stop.set()
        if self._recorder_thread:
            self._recorder_thread.join(timeout=3)
        for name, action in (("MasterBus", self.masterbus.close), ("BMS", self.bms.stop), ("balancers", self.balancers.stop)):
            try:
                action()
            except Exception as exc:
                log.warning("Stopping %s failed: %s", name, exc)
