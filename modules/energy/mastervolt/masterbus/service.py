"""The MasterBus side of the application, assembled from its parts.

    BusIO              serialised USB Link access + the value cache          (io.py)
    DeviceControls     verified switching with read-back                     (controls.py)
    EnergyModel        the dashboard picture from the cache                  (energy.py)
    FloatProtection    server-side Float/Bulk policy on cell voltage         (float_policy.py)
    MasterShuntConfig  battery type/capacity found by field name             (shunt_config.py)
    SettingsStore      user settings                                         (../settings.py)

`MasterBusService` wires them together, runs the background poller that keeps the cache fresh, and is the one object
the API talks to.
"""

from __future__ import annotations

import logging
import threading
import time

from ..config import PATHS, Paths
from ..logs import warn_once
from ..settings import SettingsStore
from .controls import DeviceControls, load_control_maps
from .energy import EnergyModel
from .float_policy import FloatProtection
from .io import BusIO
from .registry import (
    ALTERNATOR,
    BOW_SHUNT,
    CHARGER_BOW,
    CHARGER_START,
    COMBIMASTER,
    HOUSE_SHUNT,
    SOLAR,
    START_SHUNT,
    YANMAR,
)
from .shunt_config import MasterShuntConfig

# The measurement fields polled continuously (docs/VERIFIED_FIELD_MAP.txt; Solar, Alpha Pro, Mass Charger and Yanmar fields
# verified later - see docs/hardware-notes.md). The mapped ON/OFF control fields are added so the UI status is immediate.
POLLED_FIELDS = {
    COMBIMASTER: (1, 2, 3, 4, 5, 6, 8, 11, 12, 19, 21, 23, 47, 48, 49, 50, 54),
    HOUSE_SHUNT: (0, 1, 2, 3, 5),
    START_SHUNT: (0, 1, 2),
    BOW_SHUNT: (0, 1, 2),
    SOLAR: (3, 4, 5, 6),
    ALTERNATOR: (5, 6, 8, 11, 12, 14, 32),
    CHARGER_START: (1, 4, 5, 6, 7),
    CHARGER_BOW: (1, 4, 5, 6, 7),
    YANMAR: (39, 40, 41),
}
POLL_READ_TIMEOUT = 0.40
POLL_FIELD_GAP = 0.015
POLL_CYCLE_SECONDS = 0.35
IO_ERROR_LIMIT = 5  # consecutive bus errors (not mere time-outs) before the USB Link is closed and opened again
REOPEN_PAUSE_SECONDS = 5.0

log = logging.getLogger("mastervolt.masterbus")


class MasterBusService:
    def __init__(self, paths: Paths = PATHS, bus=None):
        self.stop_event = threading.Event()
        self.io = BusIO(bus)
        self.settings = SettingsStore(paths.settings_file)
        self.controls = DeviceControls(self.io, load_control_maps(paths.control_maps_file), self.settings.get)
        self.shunts = MasterShuntConfig(self.io, paths.mastershunt_maps_file)
        self.energy_model = EnergyModel(self.io, self.shunts)
        self.float_protection = FloatProtection(self.io, self.settings.get, self.stop_event)
        self.settings.subscribe(lambda values: self.float_protection.status.update(enabled=values["float_protection_enabled"]))
        self.discovery_status = "not_started"

    # ---- lifecycle ------------------------------------------------------------------------------------------
    def open(self) -> None:
        self.io.open()

    def close(self) -> None:
        self.stop_event.set()
        self.io.close()

    def start(self) -> None:
        """Open the USB Link - retrying until it is there - and start the background jobs. Returns at once."""
        threading.Thread(target=self._run, daemon=True, name="masterbus-cache").start()

    def _run(self) -> None:
        if self._open_link(reopen=False):
            self.initialize_background()

    def _open_link(self, reopen: bool) -> bool:
        """(Re)open the USB Link until it works or the service stops. A Link that is unplugged or not yet powered must not need
        a server restart: the dashboard shows blanks meanwhile and recovers by itself."""
        while not self.stop_event.is_set():
            try:
                with self.io.io_lock:
                    if reopen:
                        self.io.bus.close()
                    self.io.bus.open()
                log.info("MasterBus USB Link %s", "reopened" if reopen else "opened")
                return True
            except Exception as exc:
                warn_once(
                    log,
                    "usb-open",
                    f"MasterBus USB Link not available ({exc}); trying again every {REOPEN_PAUSE_SECONDS:g} s",
                    exc_info=False,
                )
                if self.stop_event.wait(REOPEN_PAUSE_SECONDS):
                    break
        return False

    def initialize_background(self) -> None:
        """Start the background jobs, then poll on this thread (the caller runs it in its own thread)."""
        self.discovery_status = "fixed-map"  # measurement fields are fixed; no heuristic discovery at start-up
        threading.Thread(target=self.shunts.discover, args=(self.stop_event,), daemon=True, name="mastershunt-config").start()
        threading.Thread(target=self.float_protection.run, daemon=True, name="high-soc-float-policy").start()
        self.refresh_loop()

    def poll_fields(self) -> list[tuple[int, int]]:
        fields = {(addr, field) for addr, items in POLLED_FIELDS.items() for field in items}
        for config in self.controls.control_maps.values():
            if not config:
                continue
            try:
                address = config["address"]
                addr = int(address, 16) if isinstance(address, str) else int(address)
                if config.get("protocol", "btm1") == "btm1":
                    fields.add((addr, int(config["field"])))
            except Exception:
                pass
        fields.update(self.shunts.extra_poll_fields())
        return sorted(fields)

    def refresh_loop(self) -> None:
        io_errors = 0  # consecutive errors other than "the device did not answer"
        while not self.stop_event.is_set():
            started = time.monotonic()
            for addr, field in self.poll_fields():
                if self.stop_event.is_set():
                    break
                try:
                    self.io.read_field(addr, field, POLL_READ_TIMEOUT)
                    io_errors = 0
                except TimeoutError:
                    io_errors = 0  # the bus works; this device/field just did not answer
                except Exception:
                    io_errors += 1
                time.sleep(POLL_FIELD_GAP)
                if io_errors >= IO_ERROR_LIMIT:
                    warn_once(log, "usb-lost", "MasterBus USB Link lost; reopening it", exc_info=False)
                    if not self._open_link(reopen=True):
                        return
                    io_errors = 0
            try:
                self.controls.ac_support_enabled = self.io.read_btm3(COMBIMASTER, 11, 0.55)
            except Exception:
                pass
            elapsed = time.monotonic() - started
            if elapsed < POLL_CYCLE_SECONDS:
                self.stop_event.wait(POLL_CYCLE_SECONDS - elapsed)

    # ---- settings -------------------------------------------------------------------------------------------
    def get_settings(self) -> dict:
        return self.settings.get()

    def update_settings(self, values: dict) -> dict:
        return self.settings.update(values)

    # ---- the dashboard --------------------------------------------------------------------------------------
    def energy(self) -> dict:
        data = self.energy_model.measure(self.controls.ac_support_enabled)
        info = self.io.bus.device_info or {}
        data.update(
            {
                "settings": self.get_settings(),
                "high_soc_float_policy": dict(self.float_protection.status),
                "discovery_status": self.discovery_status,
                "cache_items": self.io.cache_size,
                "active_mode": self.controls.active_mode,
                "controls": self.controls.capabilities(),
                "usb": {"product": info.get("product_string"), "serial": info.get("serial_number")},
            }
        )
        return data
