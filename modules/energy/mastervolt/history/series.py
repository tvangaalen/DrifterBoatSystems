"""Compact chart points extracted from the stored JSON payloads (what the History charts and totals are drawn from)."""

from __future__ import annotations

import json

from ..bluetooth.daly_protocol import BATTERY_NAMES

SOURCE_KEYS = ("shore", "charger_house", "alternator", "solar")
LOAD_KEYS = ("inverter", "charger_start", "charger_bow", "engine_ecu", "alternator_field", "other_dc")


def bms_point(record_id: int, captured_at: str, device, encoded: str):
    """One BMS sample as a compact point, or None when the row is not a usable BMS reading."""
    try:
        payload = json.loads(encoded)
        battery = str(device or payload.get("battery") or "").upper()
        if battery not in BATTERY_NAMES:
            return None
        return {
            "id": record_id,
            "captured_at": captured_at,
            "battery": battery,
            "voltage": payload.get("pack_voltage_v"),
            "current": payload.get("current_a"),
            "remaining": payload.get("remaining_capacity_ah"),
            "cells": payload.get("cells_mv") or [],
            "cell_spread": payload.get("cell_spread_mv"),
            "alarms": payload.get("alarms") or [],
            "charge_mos": payload.get("charge_mosfet_on"),
            "discharge_mos": payload.get("discharge_mosfet_on"),
        }
    except (TypeError, ValueError):
        return None


def dashboard_point(record_id: int, captured_at: str, encoded: str):
    """One dashboard sample as a compact point (source/load power and current vectors plus the condition figures), or None."""
    try:
        payload = json.loads(encoded)
        sources, loads = payload.get("sources") or {}, payload.get("consumers") or {}
        shore, alternator, solar = sources.get("shore") or {}, sources.get("alternator") or {}, sources.get("solar") or {}
        inverter, ac = loads.get("inverter") or {}, loads.get("house_ac") or {}
        return {
            "id": record_id,
            "captured_at": captured_at,
            "source_power": [(sources.get(key) or {}).get("power") for key in SOURCE_KEYS[1:]],
            "source_current": [(sources.get(key) or {}).get("current") for key in SOURCE_KEYS[1:]],
            "shore_voltage": shore.get("voltage"),
            "shore_current": shore.get("current"),
            "shore_power": shore.get("power"),
            "shore_connected": shore.get("connected"),
            "solar_panel_voltage": solar.get("panel_voltage"),
            "alternator_temperature": alternator.get("temperature"),
            "alternator_running": alternator.get("running"),
            "load_power": [(loads.get(key) or {}).get("power") for key in LOAD_KEYS],
            "load_current": [(loads.get(key) or {}).get("current") for key in LOAD_KEYS],
            "ac_power": ac.get("power"),
            "ac_frequency": ac.get("output_frequency"),
            "inverting": inverter.get("inverting"),
            "supporting": inverter.get("supporting"),
        }
    except (TypeError, ValueError):
        return None
