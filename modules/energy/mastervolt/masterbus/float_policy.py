"""Float protection: keep the charging sources in Float while any battery cell is too high.

Runs on the server every 3 s, independent of any browser. Once the highest single cell of any of the three DALY BMS
units reaches the trigger voltage, every *charging* source (house charger, solar, alternator) is forced to Float and
verified; once every cell is back at or below the resume level they are returned to Bulk. The decision itself is the
pure function `soc.float_decision`; this module applies it to the hardware.

Rules (CLAUDE.md, docs/hardware-notes.md): only fresh BMS data is trusted, unknown data never starts Float and holds
it while latched, inactive sources are never switched on, and the cell voltages come from the BMS units only - never
from the balancers. When Float freshly starts, every battery's SOC is also set to 100% once (`started_callback`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..soc import float_decision
from .io import SETTLE_SECONDS, BusIO
from .labels import state_number
from .registry import ALTERNATOR, COMBIMASTER, SOLAR

CHECK_INTERVAL_SECONDS = 3.0
RETRY_COOLDOWN_SECONDS = 20.0  # between two Float attempts on the same source that did not verify

# name, device, Float event / commit, Bulk event / commit, charger-state field (verified on the hardware)
SOURCES = (
    ("charger_house", COMBIMASTER, 42, 43, 38, 39, 1),
    ("solar", SOLAR, 18, 19, 14, 15, 3),
    ("alternator", ALTERNATOR, 37, 38, 33, 34, 5),
)
FLOAT_STATE, BULK_STATE = 3, 1


class FloatProtection:
    def __init__(self, io: BusIO, get_settings: Callable[[], dict], stop_event: threading.Event):
        self.io, self.get_settings, self.stop_event = io, get_settings, stop_event
        settings = get_settings()
        self.status = {
            "enabled": settings["float_protection_enabled"],
            "cell_trigger_mv": settings["float_cell_trigger_mv"],
            "cell_resume_mv": settings["float_cell_resume_mv"],
            "active": False,
            "house_soc": None,
            "max_cell_mv": None,
            "max_cell_battery": None,
            "max_spread_mv": None,
            "max_spread_battery": None,
            "trigger": None,
            "sources": {},
            "event_id": 0,
            "bulk_event_id": 0,
            "float_latched": False,
            "server_side": True,
            "check_interval_seconds": 3,
            "last_check_at": None,
        }
        self.last_attempt: dict[str, float] = {}
        self.details_getter: Callable[[], dict] | None = None  # house_bms_soc_details: fresh DALY readings
        self.soc_getter: Callable[[], float | None] | None = None  # fallback: just the SOC
        self.started_callback: Callable[[], None] | None = None  # called once when Float freshly latches

    # ---- the two verified commands --------------------------------------------------------------------------
    def _force_state(self, label: str, name: str, target: float, addr, command_field, commit_field, state_field) -> dict:
        before = self.io.read_field(addr, state_field, 0.7)
        number = state_number(before)
        if number == int(target):
            return {"changed": False, "state": before}
        self.io.write_bool(addr, command_field, commit_field, True)
        time.sleep(SETTLE_SECONDS)
        reached, value, samples = self.io.wait_for(addr, state_field, target, timeout=5)
        if not reached:
            raise RuntimeError(f"{name} {label} verify failed: {samples}")
        return {"changed": True, "state": value, "samples": samples}

    def force_float(self, name, addr, command_field, commit_field, state_field) -> dict:
        """Issue the device's Float event and verify charger state 3."""
        return self._force_state("Float", name, float(FLOAT_STATE), addr, command_field, commit_field, state_field)

    def force_bulk(self, name, addr, command_field, commit_field, state_field) -> dict:
        """Issue the device's Bulk event and verify charger state 1."""
        return self._force_state("Bulk", name, float(BULK_STATE), addr, command_field, commit_field, state_field)

    # ---- one pass of the policy -----------------------------------------------------------------------------
    def _read_details(self):
        """(details, soc) from the fresh DALY readings; both None when they are unavailable."""
        try:
            if callable(self.details_getter):
                details = self.details_getter()
                return details, details["soc"]
            return None, self.soc_getter() if callable(self.soc_getter) else None
        except Exception:
            return None, None

    def _publish(self, settings: dict, details, soc, held: bool, active: bool, trigger) -> None:
        status = self.status
        soc_source = "stale_hold" if held else ("daly_bms" if soc is not None else "unavailable")
        try:
            soc_value = None if soc is None else float(soc)
        except (TypeError, ValueError):
            soc_value = None
        get = (lambda key: None) if details is None else details.get
        status.update(
            enabled=settings["float_protection_enabled"],
            cell_trigger_mv=settings["float_cell_trigger_mv"],
            cell_resume_mv=settings["float_cell_resume_mv"],
            house_soc=soc_value,
            soc_source=soc_source,
            soc_held=held,
            soc_fresh_batteries=get("fresh_batteries"),
            soc_age_seconds=get("youngest_age_seconds"),
            soc_stale=bool(details and soc_value is None and details.get("stale_batteries")),
            last_known_soc=get("last_known_soc"),
            max_cell_mv=get("max_cell_mv"),
            max_cell_battery=get("max_cell_battery"),
            max_spread_mv=get("max_spread_mv"),
            max_spread_battery=get("max_spread_battery"),
            active=active,
            trigger=trigger,
        )

    def _state_of(self, addr, state_field):
        return state_number(self.io.cached(addr, state_field))

    def _resume_bulk(self) -> None:
        changed = False
        for name, addr, _float_field, _float_commit, bulk_field, bulk_commit, state_field in SOURCES:
            state = self._state_of(addr, state_field)
            item = {"state": state, "status": "inactive"}
            if state == FLOAT_STATE:
                try:
                    item["result"] = self.force_bulk(name, addr, bulk_field, bulk_commit, state_field)
                    item["status"] = "bulk"
                    changed = changed or bool(item["result"].get("changed"))
                except Exception as exc:
                    item["status"] = "error"
                    item["error"] = str(exc)
            self.status["sources"][name] = item
        if changed:
            self.status["bulk_event_id"] += 1
        self.status["float_latched"] = False

    def _hold_float(self) -> None:
        now = time.monotonic()
        changed = False
        for name, addr, command_field, commit_field, _bulk_field, _bulk_commit, state_field in SOURCES:
            state = self._state_of(addr, state_field)
            item = {"state": state, "status": "unavailable"}
            if state == FLOAT_STATE:
                item["status"] = "float"
            elif state not in (1, 2):
                # Never switch on an unavailable, stopped or night-time source: it is forced to Float as soon as it starts charging.
                item["status"] = "inactive"
            elif now - self.last_attempt.get(name, 0) < RETRY_COOLDOWN_SECONDS:
                item["status"] = "retry_wait"
            else:
                self.last_attempt[name] = now
                try:
                    item["result"] = self.force_float(name, addr, command_field, commit_field, state_field)
                    item["status"] = "float"
                    changed = changed or bool(item["result"].get("changed"))
                except Exception as exc:
                    item["status"] = "error"
                    item["error"] = str(exc)
            self.status["sources"][name] = item
        if changed:
            self.status["event_id"] += 1

    def check_once(self) -> None:
        settings = self.get_settings()
        self.status["last_check_at"] = time.time()
        details, soc = self._read_details()
        enabled = settings["float_protection_enabled"]
        # A missing or stale cell reading (DALY link down) is "unknown": while Float is latched that holds the sources in
        # Float and never resumes Bulk on old data; it never starts Float by itself. The pack-average SOC is informational.
        max_cell_mv = None if details is None else details.get("max_cell_mv")
        was_latched = self.status.get("float_latched")
        active, resume, held, trigger = float_decision(
            enabled, was_latched, max_cell_mv, settings["float_cell_trigger_mv"], settings["float_cell_resume_mv"]
        )
        self._publish(settings, details, soc, held, active, trigger)
        if not enabled:
            self.status["sources"] = {}
            self.status["float_latched"] = False
        if not active:
            if resume:
                self._resume_bulk()
            return
        self.status["float_latched"] = True
        if not was_latched and callable(self.started_callback):
            # Float just switched on (a fresh cell-voltage trigger, never a hold): the cells are effectively full, so
            # bring every battery's SOC to 100% instead of leaving a stale coulomb-counted value.
            try:
                self.started_callback()
            except Exception:
                pass
        self._hold_float()

    def run(self) -> None:
        while not self.stop_event.wait(CHECK_INTERVAL_SECONDS):
            self.check_once()
