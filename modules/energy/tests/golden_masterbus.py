"""Scenario runner behind tests/test_masterbus_golden.py.

The scenarios drive a `MasterBusService` against the simulated bus (`masterbus_fakes`) and record, per scenario, the
returned value or error and every CAN frame that was sent. `tests/golden/masterbus.json` holds what the v1.22.2 code
(the last release before the 2.0 refactor, whose hardware behaviour was verified on the boat) produced; the current
code must reproduce it exactly: same decisions, same frames in the same order, same numbers.

`python -m tests.test_masterbus_golden --generate <old-tree>` regenerates the file from an old checkout. Never do that
to make a failing test pass: a difference means the control or measurement behaviour changed.
"""

from __future__ import annotations

import copy
import json
import random

from tests.masterbus_fakes import (
    ALTERNATOR,
    CHARGER_BOW,
    CHARGER_START,
    COMBIMASTER,
    SOLAR,
    YANMAR,
    FakeBus,
    FakeClock,
    default_values,
)

HOUSE_SHUNT, START_SHUNT, BOW_SHUNT = 0x6DB09B, 0x6D59B9, 0x6D9E99


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


class Adapter:
    """What the scenarios need from a service. `OldAdapter`/`NewAdapter` map it onto the real class."""

    def __init__(self, service):
        self.service = service

    # filled by subclasses: bus, set_*, energy, force_float, force_bulk, run_float_loop, settings helpers


def frames(bus):
    return [list(item) for item in bus.sent]


def record(adapter, bus, call):
    try:
        result = jsonable(call())
        error = None
    except Exception as exc:  # noqa: BLE001 - the message is part of the contract
        result, error = None, f"{type(exc).__name__}: {exc}"
    return {"result": result, "error": error, "frames": frames(bus)}


def control_scenarios():
    """(name, bus keyword overrides, initial value overrides, callable(adapter))."""
    s = []
    for state in (True, False):
        s.append((f"inverter_{state}", {}, {(COMBIMASTER, 19): 0.0 if state else 1.0}, lambda a, st=state: a.set_inverter(st)))
        s.append((f"inverter_already_{state}", {}, {(COMBIMASTER, 19): 1.0 if state else 0.0}, lambda a, st=state: a.set_inverter(st)))
        s.append((f"charger_{state}", {}, {(COMBIMASTER, 21): 0.0 if state else 1.0}, lambda a, st=state: a.set_charger(st)))
        s.append(
            (f"ac_support_{state}", {"btm3": {(COMBIMASTER, 11): 0.0 if state else 1.0}}, {}, lambda a, st=state: a.set_ac_support(st))
        )
        s.append((f"alternator_{state}", {}, {(ALTERNATOR, 5): 5.0 if state else 1.0}, lambda a, st=state: a.set_alternator_enabled(st)))
        s.append(
            (
                f"alternator_stuck_{state}",
                {"alternator_stuck": True},
                {(ALTERNATOR, 5): 5.0 if state else 1.0},
                lambda a, st=state: a.set_alternator_enabled(st),
            )
        )
        for device in ("charger_start", "charger_bow", "engine_ecu", "solar"):
            s.append(
                (
                    f"device_{device}_{state}",
                    {},
                    {
                        (SOLAR, 12): 0.0 if state else 1.0,
                        (YANMAR, 43): 0.0 if state else 1.0,
                        (CHARGER_START, 64): 0.0 if state else 1.0,
                        (CHARGER_BOW, 64): 0.0 if state else 1.0,
                    },
                    lambda a, d=device, st=state: a.set_device_control(d, st),
                )
            )
    s.append(("solar_on_reverts", {"solar_reverts": True}, {(SOLAR, 12): 0.0}, lambda a: a.set_device_control("solar", True)))
    s.append(("device_unknown", {}, {}, lambda a: a.set_device_control("toaster", True)))
    for amps in (10, 15, 3, 2, 16, True):
        s.append((f"ac_limit_{amps}", {}, {(COMBIMASTER, 23): 15.0}, lambda a, v=amps: a.set_ac_limit(v)))
    s.append(("inverter_verify_fails", {"ignore_writes": True}, {(COMBIMASTER, 19): 0.0}, lambda a: a.set_inverter(True)))
    s.append(("charger_verify_fails", {"ignore_writes": True}, {(COMBIMASTER, 21): 0.0}, lambda a: a.set_charger(True)))
    s.append(("ac_limit_verify_fails", {"ignore_writes": True}, {(COMBIMASTER, 23): 15.0}, lambda a: a.set_ac_limit(8)))
    s.append(("ac_support_verify_fails", {"ignore_writes": True, "btm3": {(COMBIMASTER, 11): 0.0}}, {}, lambda a: a.set_ac_support(True)))
    s.append(
        ("device_verify_fails", {"ignore_writes": True}, {(CHARGER_START, 64): 0.0}, lambda a: a.set_device_control("charger_start", True))
    )
    for name, addr, command, commit, state_field, start in (
        ("charger_house", COMBIMASTER, 42, 43, 1, 1.0),
        ("solar", SOLAR, 18, 19, 3, 1.0),
        ("alternator", ALTERNATOR, 37, 38, 5, 2.0),
    ):
        s.append(
            (
                f"force_float_{name}",
                {},
                {(addr, state_field): start},
                lambda a, n=name, ad=addr, c=command, cm=commit, sf=state_field: a.force_float(n, ad, c, cm, sf),
            )
        )
        s.append(
            (
                f"force_float_{name}_already",
                {},
                {(addr, state_field): 3.0},
                lambda a, n=name, ad=addr, c=command, cm=commit, sf=state_field: a.force_float(n, ad, c, cm, sf),
            )
        )
        s.append(
            (
                f"force_float_{name}_fails",
                {"ignore_writes": True},
                {(addr, state_field): start},
                lambda a, n=name, ad=addr, c=command, cm=commit, sf=state_field: a.force_float(n, ad, c, cm, sf),
            )
        )
    for name, addr, bulk, commit, state_field in (
        ("charger_house", COMBIMASTER, 38, 39, 1),
        ("solar", SOLAR, 14, 15, 3),
        ("alternator", ALTERNATOR, 33, 34, 5),
    ):
        s.append(
            (
                f"force_bulk_{name}",
                {},
                {(addr, state_field): 3.0},
                lambda a, n=name, ad=addr, c=bulk, cm=commit, sf=state_field: a.force_bulk(n, ad, c, cm, sf),
            )
        )
        s.append(
            (
                f"force_bulk_{name}_already",
                {},
                {(addr, state_field): 1.0},
                lambda a, n=name, ad=addr, c=bulk, cm=commit, sf=state_field: a.force_bulk(n, ad, c, cm, sf),
            )
        )
    for mode in ("motor", "anchor", "marina", "sail", "MOTOR ", "regatta", None):
        s.append(
            (
                f"mode_{mode}",
                {},
                {
                    (COMBIMASTER, 19): 1.0,
                    (COMBIMASTER, 21): 0.0,
                    (ALTERNATOR, 5): 5.0,
                    (SOLAR, 12): 0.0,
                    (YANMAR, 43): 0.0,
                    (CHARGER_START, 64): 0.0,
                    (CHARGER_BOW, 64): 0.0,
                    (COMBIMASTER, 23): 12.0,
                },
                lambda a, m=mode: (a.set_operating_mode(m), a.energy_modes())[0],
            )
        )
    s.append(("mode_marina_partial_failure", {"ignore_writes": True}, {(COMBIMASTER, 19): 0.0}, lambda a: a.set_operating_mode("marina")))
    return s


def run_controls(make_adapter):
    out = {}
    for name, bus_kwargs, overrides, call in control_scenarios():
        clock = FakeClock()
        with clock.installed():
            rng = random.Random(7)
            values = default_values(rng)
            values.update(overrides)
            bus = FakeBus(clock, values=values, **bus_kwargs)
            adapter = make_adapter(bus)
            out[name] = record(adapter, bus, lambda: call(adapter))
            out[name]["active_mode"] = adapter.active_mode()
            out[name]["values_after"] = sorted(
                [f"{a:06X}:{f}", round(v, 4)]
                for (a, f), v in bus.values.items()
                if v is not None
                and (a, f) in overrides
                or (a, f)
                in {
                    (COMBIMASTER, 19),
                    (COMBIMASTER, 21),
                    (COMBIMASTER, 23),
                    (ALTERNATOR, 5),
                    (SOLAR, 12),
                    (YANMAR, 43),
                    (CHARGER_START, 64),
                    (CHARGER_BOW, 64),
                }
            )
    return out


def energy_cache_states(count=70, seed=11):
    """Deterministic pseudo-random MasterBus cache contents covering charger/alternator states, missing values and negatives."""
    rng = random.Random(seed)
    fields = {
        COMBIMASTER: [1, 2, 3, 4, 5, 6, 8, 11, 12, 19, 21, 23, 47, 48, 49, 50, 54],
        HOUSE_SHUNT: [0, 1, 2, 3, 5, 19, 20],
        START_SHUNT: [0, 1, 2, 15],
        BOW_SHUNT: [0, 1, 2, 15],
        SOLAR: [3, 4, 5, 6],
        ALTERNATOR: [5, 6, 8, 11, 12, 14, 32],
        CHARGER_START: [1, 4, 5, 6, 7],
        CHARGER_BOW: [1, 4, 5, 6, 7],
        YANMAR: [39, 40, 41, 43],
    }
    states = []
    for step in range(count):
        cache = {}
        for addr, items in fields.items():
            for field in items:
                roll = rng.random()
                if roll < 0.08:
                    continue  # no reading
                if roll < 0.28:
                    cache[(addr, field)] = float(rng.choice([0, 0, 1, 2, 3, 4, 5]))
                else:
                    cache[(addr, field)] = round(rng.uniform(-30, 300), 3)
        # keep the alternator state meaningful most of the time so the stopped/charging branches both run
        if step % 3:
            cache[(ALTERNATOR, 5)] = float(rng.choice([0, 1, 2, 3, 5]))
        states.append(cache)
    return states


def energy_digest(data):
    """A checksum of the whole /api/energy document plus the figures that matter most, so a difference is readable."""
    import hashlib

    return {
        "sha1": hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest(),
        "totals": data["totals"],
        "alternator": {
            k: data["sources"]["alternator"].get(k) for k in ("current", "power", "running", "estimated", "state", "control_on")
        },
        "balance": data["alternator_balance"],
        "inverter": data["consumers"]["inverter"],
        "ecu": data["consumers"]["engine_ecu"],
        "house": {k: data["storage"]["house"].get(k) for k in ("voltage", "current", "power", "soc", "battery_type", "capacity")},
        "combimaster": data["combimaster"],
        "controls": data["controls"],
    }


def run_energy(make_adapter):
    clock = FakeClock()
    out = []
    with clock.installed():
        bus = FakeBus(clock, values=default_values(random.Random(3)))
        adapter = make_adapter(bus)
        adapter.set_float_status_defaults()
        for cache in energy_cache_states():
            adapter.load_cache(cache)
            out.append(energy_digest(jsonable(adapter.energy())))
            clock.sleep(1.0)
    return out


FLOAT_DETAILS = [
    {"max_cell_mv": 3300},
    {"max_cell_mv": 3360},
    {"max_cell_mv": 3560},
    {"max_cell_mv": 3560},
    {"max_cell_mv": 3500},
    {"max_cell_mv": 3400},
    {"max_cell_mv": 3370},
    {"max_cell_mv": None},
    {"max_cell_mv": 3560},
    {"max_cell_mv": None},
    {"max_cell_mv": 3370},
    {"max_cell_mv": 3300},
]


def run_float_loop(make_adapter, enabled=True):
    """Drive enforce_high_soc_float for every step of FLOAT_DETAILS with sources starting in different states."""
    clock = FakeClock()
    out = {"steps": [], "callbacks": 0}
    with clock.installed():
        values = default_values(random.Random(5))
        values.update({(COMBIMASTER, 1): 1.0, (SOLAR, 3): 2.0, (ALTERNATOR, 5): 0.0})
        bus = FakeBus(clock, values=values)
        adapter = make_adapter(bus)
        adapter.configure_float(enabled=enabled, trigger=3500.0, resume=3420.0)
        calls = {"n": 0}

        def callback():
            out["callbacks"] += 1

        adapter.set_float_callback(callback)

        def details_getter():
            index = min(calls["n"], len(FLOAT_DETAILS) - 1)
            details = dict(FLOAT_DETAILS[index])
            details.update(
                {
                    "soc": 91.5,
                    "fresh_batteries": 3,
                    "stale_batteries": 0,
                    "youngest_age_seconds": 4.0,
                    "last_known_soc": 91.5,
                    "max_cell_battery": "BATTERY 2",
                    "max_spread_mv": 12,
                    "max_spread_battery": "BATTERY 1",
                }
            )
            return details

        adapter.set_details_getter(details_getter)

        # The cache holds the state fields the policy reads; the simulated devices keep it in sync afterwards.
        def before_step():
            for (addr, field), value in bus.values.items():
                if (addr, field) in {(COMBIMASTER, 1), (SOLAR, 3), (ALTERNATOR, 5)}:
                    adapter.put_cache(addr, field, value)

        def after_step():
            out["steps"].append({"status": jsonable(adapter.float_status()), "frames": frames(bus)})
            calls["n"] += 1
            clock.sleep(3.0)

        adapter.run_float_loop(len(FLOAT_DETAILS), before_step, after_step)
    return out


SETTINGS_CASES = [
    {},
    {"default_ac_limit": 15},
    {"default_ac_limit": 2},
    {"default_ac_limit": 16},
    {"default_ac_limit": 7.5},
    {"default_ac_limit": True},
    {"float_protection_enabled": 1},
    {"float_protection_enabled": False},
    {"float_cell_trigger_mv": 3299},
    {"float_cell_trigger_mv": 3650},
    {"float_cell_trigger_mv": 3651},
    {"float_cell_resume_mv": 3199},
    {"float_cell_resume_mv": 3400},
    {"float_cell_trigger_mv": 3500, "float_cell_resume_mv": 3471},
    {"float_cell_trigger_mv": 3500, "float_cell_resume_mv": 3470},
    {"float_cell_trigger_mv": True},
    {"bms_refresh_interval": 4},
    {"bms_refresh_interval": 300},
    {"bms_refresh_interval": 301},
    {"bms_popup_seconds": 0},
    {"bms_popup_seconds": 60},
    {"bms_connection_retry_seconds": 0},
    {"bms_connection_retry_seconds": 300},
    {"balancer_refresh_interval": 4},
    {"balancer_connection_retry_seconds": 4},
    {"balancer_connection_retry_seconds": 5},
    {"history_retention_days": 0},
    {"history_retention_days": 365},
    {"history_retention_days": 366},
    {"surprise": 1},
    {"default_ac_limit": 10, "surprise": 1},
]
FULL_SETTINGS = {
    "default_ac_limit": 12,
    "float_protection_enabled": True,
    "float_cell_trigger_mv": 3550.0,
    "float_cell_resume_mv": 3400.0,
    "bms_refresh_interval": 30,
    "bms_popup_seconds": 3,
    "bms_connection_retry_seconds": 5,
    "balancer_refresh_interval": 90,
    "balancer_connection_retry_seconds": 60,
    "history_retention_days": 31,
}


def run_settings(validate, update):
    """`validate(values, partial)` raises ValueError; `update(values)` returns the normalized, saved settings."""
    out = {"partial": [], "full": []}
    for case in SETTINGS_CASES:
        try:
            validate(copy.deepcopy(case), True)
            out["partial"].append("ok")
        except ValueError as exc:
            out["partial"].append(str(exc))
    for case in SETTINGS_CASES:
        merged = {**FULL_SETTINGS, **case} if case and set(case) <= set(FULL_SETTINGS) else (case or {})
        try:
            out["full"].append(jsonable(update(copy.deepcopy(merged))))
        except ValueError as exc:
            out["full"].append(str(exc))
    out["missing_field"] = None
    return out
