"""MasterBus behaviour must be identical to the hardware-verified 1.22.2 release (see tests/golden_masterbus.py).

py -m tests.test_masterbus_golden                        # verify the current code against tests/golden/masterbus.json
py -m tests.test_masterbus_golden --generate <old-tree>  # regenerate the golden file from an old checkout (v1.22.2)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden" / "masterbus.json"


def old_factory(tree: str):
    """Adapter over the flat-module v1.22.2 MasterBusService found in `tree` (only used to generate the golden file)."""
    sys.path.insert(0, tree)
    from masterbus_service import MasterBusService

    class OldAdapter:
        def __init__(self, bus):
            self.service = MasterBusService()
            self.service.bus = bus

        def set_inverter(self, on):
            return self.service.set_inverter(on)

        def set_charger(self, on):
            return self.service.set_charger(on)

        def set_ac_limit(self, amps):
            return self.service.set_ac_limit(amps)

        def set_ac_support(self, on):
            return self.service.set_ac_support(on)

        def set_device_control(self, name, on):
            return self.service.set_device_control(name, on)

        def set_alternator_enabled(self, on):
            return self.service.set_alternator_enabled(on)

        def set_operating_mode(self, mode):
            return self.service.set_operating_mode(mode)

        def force_float(self, *args):
            return self.service._force_float(*args)

        def force_bulk(self, *args):
            return self.service._force_bulk(*args)

        def active_mode(self):
            return self.service.active_mode

        def energy_modes(self):
            return self.service.active_mode

        def energy(self):
            return self.service.energy()

        def set_float_status_defaults(self):
            pass

        def load_cache(self, cache):
            self.service.cache.clear()
            for (addr, field), value in cache.items():
                self.service._put(addr, field, value)

        def put_cache(self, addr, field, value):
            self.service._put(addr, field, value)

        def configure_float(self, enabled, trigger, resume):
            self.service.settings.update(float_protection_enabled=enabled, float_cell_trigger_mv=trigger, float_cell_resume_mv=resume)

        def set_float_callback(self, callback):
            self.service.float_started_callback = callback

        def set_details_getter(self, getter):
            self.service.house_soc_details_getter = getter

        def float_status(self):
            return self.service.float_policy_status

        def run_float_loop(self, steps, before, after):
            self.service.stop_event = _StepStop(steps, before, after)
            self.service.enforce_high_soc_float()

    return OldAdapter, MasterBusService


class _StepStop:
    """Stand-in for the service's stop event: lets the Float loop run exactly `steps` iterations."""

    def __init__(self, steps, before, after):
        self.steps, self.before, self.after, self.count = steps, before, after, 0

    def wait(self, timeout=None):
        if self.count:
            self.after()
        if self.count >= self.steps:
            return True
        self.count += 1
        self.before()
        return False

    def is_set(self):
        return False

    def set(self):
        pass


def new_factory():
    from tests.new_adapter import NewAdapter, update_settings_factory, validate_settings

    return NewAdapter, validate_settings, update_settings_factory


def collect(make_adapter, validate, update):
    from tests import golden_masterbus as g

    return {
        "controls": g.run_controls(make_adapter),
        "energy": g.run_energy(make_adapter),
        "float_enabled": g.run_float_loop(make_adapter, True),
        "float_disabled": g.run_float_loop(make_adapter, False),
        "settings": g.run_settings(validate, update),
    }


def generate(tree: str):
    Adapter, Service = old_factory(tree)
    tmp = tempfile.mkdtemp()
    service = Service()
    service.settings_file = Path(tmp) / "user_settings.json"
    result = collect(Adapter, Service._validate_settings, service.update_settings)
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(f"golden file written: {GOLDEN} ({GOLDEN.stat().st_size} bytes)")


def differences(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                yield f"{path}/{key}: missing in {'expected' if key not in a else 'actual'}"
            else:
                yield from differences(a[key], b[key], f"{path}/{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield f"{path}: length {len(a)} != {len(b)}"
        for index, (x, y) in enumerate(zip(a, b)):
            yield from differences(x, y, f"{path}[{index}]")
    elif a != b:
        yield f"{path}: expected {a!r}, got {b!r}"


def main():
    if "--generate" in sys.argv:
        generate(sys.argv[sys.argv.index("--generate") + 1])
        return
    NewAdapter, validate, update_factory = new_factory()
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(collect(NewAdapter, validate, update_factory()), sort_keys=True))
    problems = list(differences(expected, actual))
    for line in problems[:40]:
        print("DIFFERENCE", line)
    assert not problems, f"{len(problems)} differences from the verified 1.22.2 behaviour"
    scenarios = len(expected["controls"])
    print(
        f"MasterBus golden test: {scenarios} control scenarios, {len(expected['energy'])} energy states, "
        f"{len(expected['float_enabled']['steps'])} Float steps, {len(expected['settings']['partial'])} settings cases - identical to 1.22.2: OK"
    )


if __name__ == "__main__":
    main()
