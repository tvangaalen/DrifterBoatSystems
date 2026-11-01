"""The dashboard's energy picture, built from the MasterBus value cache (no bus traffic of its own).

Sources (shore, house charger, alternator, solar), storage (three batteries) and loads (AC, inverter, the two Mass
chargers, the engine ECU, the alternator regulator and "other DC") are derived from verified fields only.

The one non-trivial part is the DC current model (docs/hardware-notes.md, "DC current model"): the alternator has no
trustworthy output-current field, and alternator current and the total house load cannot both be solved from one
instantaneous shunt balance. So the total house load is learned (low-pass filtered) while the alternator is not
charging and held while it is, which gives the alternator current from the house-bus balance. Sign convention: the
House MasterShunt current is positive into the battery.
"""

from __future__ import annotations

import time

from .labels import alternator_charge_state_label, charger_state_label, source_charge_state_label, state_number
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

ECU_EFFICIENCY = 0.85  # the Yanmar interface has no input-current field; 85% is a conservative DC/DC efficiency at its tiny load
BASELINE_FILTER = 0.25  # weight of each new observation of the total house load while the alternator is stopped


def _product(a, b):
    """Power from voltage and current, never negative; None while either is unknown."""
    return None if a is None or b is None else max(0.0, float(a) * float(b))


class EnergyModel:
    def __init__(self, io, shunts: MasterShuntConfig):
        self.io = io
        self.shunts = shunts
        self.total_house_load_baseline_a = None
        self.total_house_load_baseline_ts = None

    # ---- small builders -------------------------------------------------------------------------------------
    def _battery(self, addr, label):
        voltage, current = self.io.cached(addr, 1), self.io.cached(addr, 2)
        return {
            "label": label,
            "soc": self.io.cached(addr, 0),
            "voltage": voltage,
            "current": current,
            "power": None if voltage is None or current is None else voltage * current,
        }

    def _charger_input(self, addr, label):
        """A Mass Charger is a load on the 12 V house bus, so its INPUT fields count (4 = voltage, 5 = current)."""
        voltage, current = self.io.cached(addr, 4), self.io.cached(addr, 5)
        if current is not None:
            current = max(0.0, float(current))
        raw_state = self.io.cached(addr, 1)
        return {
            "label": label,
            "kind": "DC",
            "voltage": voltage,
            "current": current,
            "power": _product(voltage, current),
            "charge_state": charger_state_label(raw_state),
            "charge_state_raw": raw_state,
        }

    def _shore(self):
        voltage, current, frequency = self.io.cached(COMBIMASTER, 2), self.io.cached(COMBIMASTER, 3), self.io.cached(COMBIMASTER, 4)
        if current is not None:
            current = max(0.0, current)
        return {
            "label": "Shore Power",
            "kind": "AC",
            "voltage": voltage,
            "current": current,
            "power": None if voltage is None or current is None else max(0.0, voltage * current),
            "input_frequency": frequency,
            "connected": bool(voltage is not None and float(voltage) != 0.0),
        }

    def _solar(self):
        panel_voltage, current, battery_voltage = self.io.cached(SOLAR, 4), self.io.cached(SOLAR, 5), self.io.cached(SOLAR, 6)
        if current is not None:
            current = max(0.0, current)
        state_raw = self.io.cached(SOLAR, 3)
        solar = {
            "label": "Solar",
            "kind": "DC",
            "voltage": battery_voltage,
            "panel_voltage": panel_voltage,
            "current": current,
            "power": None if battery_voltage is None or current is None else max(0.0, battery_voltage * current),
            "output_voltage": battery_voltage,
            "state": source_charge_state_label(state_raw),
            "state_raw": state_raw,
        }
        return solar, current

    def _engine_ecu(self):
        """Yanmar interface fields 39 = DC input voltage, 40 = DC output voltage, 41 = DC output current."""
        input_voltage, output_voltage, output_current = self.io.cached(YANMAR, 39), self.io.cached(YANMAR, 40), self.io.cached(YANMAR, 41)
        if output_current is not None:
            output_current = max(0.0, float(output_current))
        output_power = None if output_voltage is None or output_current is None else max(0.0, float(output_voltage) * output_current)
        input_power = None if output_power is None else output_power / ECU_EFFICIENCY
        input_current = None if input_power is None or input_voltage in (None, 0) else input_power / float(input_voltage)
        return {
            "label": "Engine ECU power",
            "kind": "DC",
            "voltage": input_voltage,
            "current": input_current,
            "power": input_power,
            "output_voltage": output_voltage,
            "output_current": output_current,
            "output_power": output_power,
            "efficiency_estimate": ECU_EFFICIENCY,
        }

    def _ac_loads(self):
        voltage, power, frequency = self.io.cached(COMBIMASTER, 5), self.io.cached(COMBIMASTER, 8), self.io.cached(COMBIMASTER, 6)
        if power is not None:
            power = max(0.0, power)
        current = None if voltage in (None, 0) or power is None else power / voltage
        return {"label": "AC Loads", "kind": "AC", "voltage": voltage, "current": current, "power": power, "output_frequency": frequency}

    # ---- the whole picture ----------------------------------------------------------------------------------
    def measure(self, ac_support_enabled=None) -> dict:
        cached = self.io.cached
        house = self._battery(HOUSE_SHUNT, "House Battery")
        house["temperature"] = cached(HOUSE_SHUNT, 5)
        start, bow = self._battery(START_SHUNT, "Start Battery"), self._battery(BOW_SHUNT, "Bow Battery")
        house.update(self.shunts.describe("house", HOUSE_SHUNT, "LiFePO4"))
        start.update(self.shunts.describe("start", START_SHUNT, "AGM"))
        bow.update(self.shunts.describe("bow", BOW_SHUNT, "AGM"))

        shore = self._shore()

        # Charger House: the CombiMaster's DC battery side (11 = volts, 12 = amps, 1 = charger state).
        charger_voltage, charger_raw_current = cached(COMBIMASTER, 11), cached(COMBIMASTER, 12)
        charger_current = charger_raw_current
        if charger_current is not None:
            charger_current = max(0.0, charger_current)
        charger_house = {
            "label": "Charger House",
            "kind": "DC",
            "voltage": charger_voltage,
            "current": charger_current,
            "power": None if charger_voltage is None or charger_current is None else max(0.0, charger_voltage * charger_current),
            "charge_state": charger_state_label(cached(COMBIMASTER, 1), "combi"),
            "charge_state_raw": cached(COMBIMASTER, 1),
        }

        # The inverter only draws from the DC bus while it is actually Inverting or Supporting, not merely switched on.
        inverting_raw, supporting_raw = cached(COMBIMASTER, 47), cached(COMBIMASTER, 49)
        inverting = bool(inverting_raw is not None and float(inverting_raw) >= 0.5)
        supporting = bool(supporting_raw is not None and float(supporting_raw) >= 0.5)
        inverter_actual = inverting or supporting
        inverter_voltage = charger_voltage if inverter_actual and charger_voltage is not None else 0.0
        inverter_current = abs(float(charger_raw_current)) if inverter_actual and charger_raw_current is not None else 0.0
        inverter_load = {
            "label": "Inverter",
            "kind": "DC",
            "voltage": inverter_voltage,
            "current": inverter_current,
            "power": max(0.0, float(inverter_voltage) * inverter_current),
            "enabled": bool(cached(COMBIMASTER, 19) is not None and float(cached(COMBIMASTER, 19)) >= 0.5),
            "inverting": inverting,
            "supporting": supporting,
            "actual": inverter_actual,
            "dc_current_raw": charger_raw_current,
        }

        solar, solar_current = self._solar()
        charger_start = self._charger_input(CHARGER_START, "Charger Start")
        charger_bow = self._charger_input(CHARGER_BOW, "Charger Bow")
        ecu = self._engine_ecu()
        ac = self._ac_loads()

        # ---- alternator and "Other DC": solved from the house-bus balance ---------------------------------------
        alt_voltage, alt_shaft, engine_shaft, alt_temperature = (
            cached(ALTERNATOR, 14),
            cached(ALTERNATOR, 11),
            cached(ALTERNATOR, 12),
            cached(ALTERNATOR, 32),
        )
        # The Alpha Pro's own charge state says whether it feeds the bus; shaft rotation does not (the shafts keep turning
        # after Stop charge while the output is zero).
        alt_state_raw = cached(ALTERNATOR, 5)
        alt_state = alternator_charge_state_label(alt_state_raw)
        state = state_number(alt_state_raw)
        charging, stopped = state in (1, 2, 3), state in (0, 5)
        shaft_running = bool((alt_shaft is not None and alt_shaft > 0.5) or (engine_shaft is not None and engine_shaft > 0.5))

        def amps(load):
            value = load.get("current")
            return 0.0 if value is None else max(0.0, float(value))

        # The regulator's field/excitation circuit is a separate load tile; subtract it from Other DC so nothing counts twice.
        field_voltage, field_current = cached(ALTERNATOR, 6), cached(ALTERNATOR, 8)
        if field_current is not None:
            field_current = max(0.0, float(field_current))
        field_power = None if field_voltage is None or field_current is None else max(0.0, float(field_voltage) * field_current)

        known_load_a = (
            amps(charger_start) + amps(charger_bow) + amps(ecu) + amps(inverter_load) + (0.0 if field_current is None else field_current)
        )
        battery_a = house.get("current")
        charger_house_a = 0.0 if charger_current is None else max(0.0, float(charger_current))
        solar_a = 0.0 if solar_current is None else max(0.0, float(solar_current))

        observed_total = None
        if stopped and battery_a is not None:
            observed_total = max(0.0, charger_house_a + solar_a - float(battery_a))
            if self.total_house_load_baseline_a is None:
                self.total_house_load_baseline_a = observed_total
            else:
                self.total_house_load_baseline_a = (
                    1.0 - BASELINE_FILTER
                ) * self.total_house_load_baseline_a + BASELINE_FILTER * observed_total
            self.total_house_load_baseline_ts = time.time()
        total_load_a = observed_total if stopped and observed_total is not None else self.total_house_load_baseline_a
        other_a = None if total_load_a is None else max(0.0, float(total_load_a) - known_load_a)

        alt_a, alt_estimated = 0.0, False
        if charging and battery_a is not None and total_load_a is not None:
            alt_a = max(0.0, float(battery_a) + float(total_load_a) - charger_house_a - solar_a)
            alt_estimated = True
        alt_power = None if alt_voltage is None else max(0.0, float(alt_voltage) * alt_a)
        alternator = {
            "label": "Alternator",
            "kind": "DC",
            "voltage": alt_voltage,
            "current": alt_a,
            "power": alt_power,
            "running": charging,
            "shaft_running": shaft_running,
            "estimated": alt_estimated,
            "alternator_shaft": alt_shaft,
            "engine_shaft": engine_shaft,
            "temperature": alt_temperature,
            "state": alt_state,
            "control_on": (alt_state_raw is not None and int(round(float(alt_state_raw))) in (1, 2, 3)),
            "state_raw": alt_state_raw,
        }
        alternator_load = {
            "label": "Alternator",
            "kind": "DC",
            "voltage": field_voltage,
            "current": field_current,
            "power": field_power,
            "control_on": charging,
            "state": alt_state,
            "state_raw": alt_state_raw,
        }

        other_voltage = house.get("voltage")
        other = {
            "label": "Other DC Loads",
            "kind": "DC",
            "voltage": other_voltage,
            "current": other_a,
            "power": None if other_a is None or other_voltage is None else max(0.0, float(other_voltage) * other_a),
            "estimated": charging,
        }

        sources = {"shore": shore, "charger_house": charger_house, "alternator": alternator, "solar": solar}
        loads = {
            "house_ac": ac,
            "inverter": inverter_load,
            "charger_start": charger_start,
            "charger_bow": charger_bow,
            "engine_ecu": ecu,
            "alternator_field": alternator_load,
            "other_dc": other,
        }

        def watts(item):
            return max(0.0, item.get("power") or 0.0)

        return {
            "sources": sources,
            "storage": {"house": house, "start": start, "bow": bow},
            "consumers": loads,
            # Total DC load excludes AC loads: their AC watts are shown but never enter the DC total.
            "totals": {
                "dc_input_power": watts(charger_house) + watts(alternator) + watts(solar),
                "consumer_power": sum(watts(item) for item in loads.values() if item.get("kind") == "DC"),
                "ac_consumer_power": watts(ac),
            },
            "alternator_balance": {
                "running": charging,
                "shaft_running": shaft_running,
                "charge_state_raw": alt_state_raw,
                "charge_state": alt_state,
                "total_house_load_baseline_a": self.total_house_load_baseline_a,
                "total_house_load_observed_a": observed_total,
                "other_dc_display_a": other_a,
                "known_dc_load_a": known_load_a,
                "house_battery_a": battery_a,
                "charger_house_a": charger_house_a,
                "solar_a": solar_a,
                "alternator_a": alt_a,
            },
            "combimaster": {
                "inverter_enabled": cached(COMBIMASTER, 19),
                "charger_enabled": cached(COMBIMASTER, 21),
                "ac_input_limit": cached(COMBIMASTER, 23),
                "ac_support_enabled": ac_support_enabled,
                "inverting": inverting_raw,
                "charging": cached(COMBIMASTER, 48),
                "supporting": supporting_raw,
                "ac_input_present": cached(COMBIMASTER, 50),
                "alarms": cached(COMBIMASTER, 54),
            },
        }
