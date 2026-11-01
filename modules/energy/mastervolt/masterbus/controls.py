"""Switching the boat's devices: every write is followed by a read-back that must confirm it.

Safety rules kept from the hardware verification work (docs/hardware-notes.md):

* Only mapped, verified fields are written (`control_maps.json`); nothing is guessed at run time.
* A write that is already in effect is not repeated, and one that does not verify raises instead of reporting success.
* Operating modes never switch the Engine ECU off; the only mode that touches it switches it ON.
* Alternator ON clears *Stop charge* only. It sends no Bulk request: the Alpha Pro resumes by itself.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from .io import SETTLE_SECONDS, BusIO
from .labels import alternator_charge_state_label
from .registry import ALTERNATOR, COMBIMASTER, SOLAR

TOLERANCE = 0.05
DEVICE_CONTROLS = ("charger_start", "charger_bow", "engine_ecu")
CAPABILITY_DEVICES = ("charger_start", "charger_bow", "engine_ecu", "solar")


def load_control_maps(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def device_address(config: dict) -> int:
    """The bus address of a control mapping (a hex string such as \"3AE394\", or a number)."""
    address = config["address"]
    return int(address, 16) if isinstance(address, str) else int(address)


class DeviceControls:
    def __init__(self, io: BusIO, control_maps: dict, get_settings: Callable[[], dict]):
        self.io = io
        self.control_maps = control_maps
        self.get_settings = get_settings
        self.ac_support_enabled = None  # last value read from the CombiMaster's Btm3 `AC IN support` field
        self.active_mode = None  # last operating mode applied from the Control panel (not kept over a restart)

    # ---- what the dashboard may offer -----------------------------------------------------------------------
    def capabilities(self) -> dict:
        """The verified controls with their current state (from the cache, else read from the bus)."""
        out = {}
        for name in CAPABILITY_DEVICES:
            config = self.control_maps.get(name)
            if not config:
                out[name] = None
                continue
            item = dict(config)
            item["current"] = None
            item["raw_current"] = None
            try:
                addr, field = device_address(config), int(config["field"])
                if config.get("protocol") == "btm3":
                    item["current"] = self.io.read_btm3(addr, field)
                else:
                    raw = self.io.cached(addr, field)  # the poller keeps mapped fields fresh; fall back to a direct read
                    if raw is None:
                        raw = self.io.read_field(addr, field, 0.55)
                    item["raw_current"] = raw
                    if config.get("type") == "dropdown":
                        if config.get("on_index") is not None and raw is not None:
                            item["current"] = abs(float(raw) - float(config["on_index"])) <= TOLERANCE
                    else:
                        item["current"] = raw
            except Exception:
                pass
            out[name] = item
        return out

    # ---- CombiMaster ----------------------------------------------------------------------------------------
    def _set_combimaster_switch(self, label: str, field: int, commit_field: int, on: bool) -> dict:
        current = self.io.read_field(COMBIMASTER, field)
        target = 1.0 if on else 0.0
        if abs(current - target) <= TOLERANCE:
            return {"changed": False, "value": on}
        self.io.write_bool(COMBIMASTER, field, commit_field, on)
        time.sleep(SETTLE_SECONDS)
        reached, value, samples = self.io.wait_for(COMBIMASTER, field, target)
        if not reached:
            raise RuntimeError(f"{label} verify failed: {samples}")
        return {"changed": True, "value": value >= 0.5, "samples": samples}

    def set_inverter(self, on: bool) -> dict:
        return self._set_combimaster_switch("Inverter", 19, 20, on)

    def set_charger(self, on: bool) -> dict:
        return self._set_combimaster_switch("Charger", 21, 22, on)

    def set_ac_limit(self, amps) -> dict:
        if isinstance(amps, bool) or int(amps) != amps or not 3 <= int(amps) <= 15:
            raise ValueError("AC input limit must be a whole number from 3 to 15 A")
        amps = int(amps)
        current = self.io.read_field(COMBIMASTER, 23)
        if abs(current - amps) <= TOLERANCE:
            return {"changed": False, "value": current}
        self.io.write_float(COMBIMASTER, 23, amps)
        time.sleep(SETTLE_SECONDS)
        reached, value, samples = self.io.wait_for(COMBIMASTER, 23, amps)
        if not reached:
            raise RuntimeError(f"AC input limit verify failed: {samples}")
        return {"changed": True, "value": value, "samples": samples}

    def set_ac_support(self, enabled: bool) -> dict:
        """CombiMaster Btm3 field 11, metadata name `AC IN support` (the `SUP` button)."""
        target = 1.0 if enabled else 0.0
        current = self.io.read_btm3(COMBIMASTER, 11)
        self.ac_support_enabled = current
        if abs(float(current) - target) <= TOLERANCE:
            return {"changed": False, "value": bool(enabled), "raw_value": current}
        self.io.write_btm3(COMBIMASTER, 11, target)
        time.sleep(SETTLE_SECONDS)
        samples = []
        end = time.monotonic() + 4.0
        while time.monotonic() < end:
            try:
                actual = self.io.read_btm3(COMBIMASTER, 11)
                samples.append(actual)
                self.ac_support_enabled = actual
                if abs(float(actual) - target) <= TOLERANCE:
                    return {"changed": True, "value": bool(enabled), "raw_value": actual, "samples": samples}
            except Exception:
                pass
            time.sleep(0.15)
        raise RuntimeError(f"AC IN support verify failed: {samples}")

    # ---- mapped on/off controls (Mass Chargers, Engine ECU) and the solar controller ------------------------
    def set_device_control(self, name: str, enabled: bool) -> dict:
        if name == "solar":
            return self.set_solar_enabled(enabled)
        if name not in DEVICE_CONTROLS:
            raise ValueError("Unknown device control")
        return self._set_mapped_control(name, enabled)

    def _set_mapped_control(self, name: str, enabled: bool) -> dict:
        config = self.control_maps.get(name)
        if not config or not config.get("verified"):
            raise RuntimeError(f"{name} ON/OFF control is not verified yet")
        addr, field = device_address(config), int(config["field"])
        protocol = config.get("protocol", "btm1")
        dropdown = config.get("type") == "dropdown"
        if dropdown:
            if config.get("on_index") is None or config.get("off_index") is None:
                raise RuntimeError(f"{name} dropdown semantics are not verified")
            target = float(config["on_index"] if enabled else config["off_index"])
        else:
            target = 1.0 if enabled else 0.0

        if protocol == "btm3":
            current = self.io.read_btm3(addr, field)
            if abs(current - target) <= TOLERANCE:
                return {"changed": False, "value": enabled}
            self.io.write_btm3(addr, field, target)
            time.sleep(SETTLE_SECONDS)
            actual = self.io.read_btm3(addr, field)
        else:
            current = self.io.read_field(addr, field)
            if abs(current - target) <= TOLERANCE:
                return {"changed": False, "value": enabled}
            self.io.write_float(addr, field, target, config.get("commit_field"))  # a commit only where the mapping asks for one
            time.sleep(SETTLE_SECONDS)
            actual = self.io.read_field(addr, field)
        if abs(actual - target) > TOLERANCE:
            raise RuntimeError(f"{name} verify failed: expected {target}, got {actual}")
        return {"changed": True, "value": enabled, "raw_value": actual}

    def set_solar_enabled(self, enabled: bool) -> dict:
        """SCM Solar field 12 (On/Off) written together with the commit token on the companion field 13.

        ON is permissive: with too little PV the controller can legitimately fall straight back to OFF, as MasterView
        shows. OFF is strict: field 12 must actually read 0 afterwards.
        """
        field, commit_field = 12, 13
        target = 1.0 if enabled else 0.0
        before = None
        try:
            before = self.io.read_field(SOLAR, field, 0.7)
        except Exception:
            pass
        self.io.write_bool(SOLAR, field, commit_field, bool(enabled))
        time.sleep(SETTLE_SECONDS)
        actual = None
        try:
            actual = self.io.read_field(SOLAR, field, 0.9)
        except Exception:
            pass
        if not enabled:
            if actual is None:
                raise RuntimeError("solar OFF verify failed: no field 12 readback")
            if abs(float(actual)) > TOLERANCE:
                raise RuntimeError(f"solar OFF verify failed: expected 0.0, got {actual}")
        return {
            "changed": before is None or abs(float(before) - target) > TOLERANCE,
            "requested": bool(enabled),
            "requested_raw": target,
            "actual_raw": actual,
            "actual": None if actual is None else bool(float(actual) >= 0.5),
            "commit_field": commit_field,
            "note": (
                "SCM may immediately return to OFF when PV input is insufficient."
                if enabled and actual is not None and float(actual) < 0.5
                else None
            ),
        }

    # ---- alternator -----------------------------------------------------------------------------------------
    def set_alternator_enabled(self, enabled: bool) -> dict:
        """Alpha Pro *Stop charge* (field 39, commit 40). OFF sets it to 1; ON clears it and requests nothing else.

        Field 5 is the actual charger state: 5 = Stopped, 1/2/3 = charging. Success is confirmed against it for up to 3 s.
        """
        self.io.write_float(ALTERNATOR, 39, 0.0 if enabled else 1.0, commit_field=40)
        requested_mode = "Clear Stop charge" if enabled else "Stop charge"
        deadline = time.monotonic() + 3.0
        last_state = None
        while time.monotonic() < deadline:
            try:
                last_state = self.io.read_field(ALTERNATOR, 5, 0.55)
                number = int(round(float(last_state)))
                if (number in (1, 2, 3)) if enabled else (number == 5):
                    return {
                        "changed": True,
                        "requested": bool(enabled),
                        "requested_mode": requested_mode,
                        "state_raw": last_state,
                        "state": alternator_charge_state_label(last_state),
                        "actual": bool(enabled),
                        "field": 39,
                        "commit_field": 40,
                    }
            except Exception:
                pass
            time.sleep(0.20)
        actual_on = last_state is not None and int(round(float(last_state))) in (1, 2, 3)
        return {
            "changed": True,
            "requested": bool(enabled),
            "requested_mode": requested_mode,
            "state_raw": last_state,
            "state": alternator_charge_state_label(last_state),
            "actual": actual_on,
            "field": 39,
            "commit_field": 40,
            "pending": actual_on != bool(enabled),
            "note": "Stop Charge was cleared; no Bulk command was sent." if enabled else None,
        }

    # ---- operating modes ------------------------------------------------------------------------------------
    def _mode_plan(self, mode: str) -> list[tuple[str, Callable, object]]:
        def device(name):
            return lambda enabled: self.set_device_control(name, enabled)

        inverter, charger, alternator = self.set_inverter, self.set_charger, self.set_alternator_enabled
        solar, start, bow, ecu = device("solar"), device("charger_start"), device("charger_bow"), device("engine_ecu")
        if mode == "motor":
            return [
                ("inverter OFF", inverter, False),
                ("Engine ECU ON", ecu, True),
                ("Solar ON", solar, True),
                ("Charger Start ON", start, True),
                ("Charger Bowthruster ON", bow, True),
                ("Alternator ON", alternator, True),
                ("Charger House OFF", charger, False),
            ]
        if mode == "anchor":
            return [
                ("inverter OFF", inverter, False),
                ("Charger House OFF", charger, False),
                ("Alternator OFF", alternator, False),
                ("Solar ON", solar, True),
                ("Charger Start OFF", start, False),
                ("Charger Bowthruster OFF", bow, False),
            ]
        if mode == "marina":
            limit = self.get_settings()["default_ac_limit"]
            return [
                ("inverter ON", inverter, True),
                ("AC IN support ON", self.set_ac_support, True),
                (f"AC limit {limit} A", self.set_ac_limit, limit),
                ("Alternator OFF", alternator, False),
                ("Solar ON", solar, True),
                ("Charger Start ON", start, True),
                ("Charger Bowthruster ON", bow, True),
                ("Charger House ON", charger, True),
            ]
        if mode == "sail":
            return [
                ("inverter OFF", inverter, False),
                ("Charger House OFF", charger, False),
                ("Alternator OFF", alternator, False),
                ("Solar ON", solar, True),
                ("Charger Start OFF", start, False),
                ("Charger Bowthruster OFF", bow, False),
                ("Engine ECU ON", ecu, True),
            ]
        raise ValueError("Unknown mode; use motor, anchor, marina or sail")

    def set_operating_mode(self, mode) -> dict:
        """Apply a named onboard mode with verified controls only.

        The Engine ECU is never switched off by a mode: Motor and Sail switch it on, Anchor and Marina leave it as it is.
        Every action is attempted; failures are collected and reported together.
        """
        mode = str(mode or "").strip().lower()
        plan = self._mode_plan(mode)
        results, failures = [], []
        for label, action, enabled in plan:
            try:
                results.append({"action": label, "result": action(enabled)})
            except Exception as exc:
                failures.append(f"{label}: {exc}")
        if failures:
            raise RuntimeError(f"{mode.title()} mode partially applied; " + "; ".join(failures))
        self.active_mode = mode
        return {"mode": mode, "ok": True, "actions": results}

    def clear_active_mode(self) -> None:
        """An individual device was switched directly: no named mode is active any more."""
        self.active_mode = None
