"""Adapter that lets the golden scenarios (tests/golden_masterbus.py) drive the current `MasterBusService`."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from mastervolt.config import PATHS, Paths
from mastervolt.masterbus.service import MasterBusService
from mastervolt.settings import SettingsStore
from mastervolt.settings import validate as validate_settings

__all__ = ["NewAdapter", "update_settings_factory", "validate_settings"]


class StepStop:
    """Stand-in for the stop event: lets the Float loop run exactly `steps` iterations."""

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


def _scratch_paths() -> Paths:
    """A temporary project folder with only the tracked mapping files (never the real user_settings.json)."""
    folder = Path(tempfile.mkdtemp())
    for name in ("control_maps.json", "mastershunt_config_maps.json"):
        shutil.copy(PATHS.base / name, folder / name)
    return Paths(folder)


def update_settings_factory():
    store = SettingsStore(_scratch_paths().settings_file)
    return store.update


class NewAdapter:
    def __init__(self, bus):
        self.service = MasterBusService(_scratch_paths(), bus=bus)

    def set_inverter(self, on):
        return self.service.controls.set_inverter(on)

    def set_charger(self, on):
        return self.service.controls.set_charger(on)

    def set_ac_limit(self, amps):
        return self.service.controls.set_ac_limit(amps)

    def set_ac_support(self, on):
        return self.service.controls.set_ac_support(on)

    def set_device_control(self, name, on):
        return self.service.controls.set_device_control(name, on)

    def set_alternator_enabled(self, on):
        return self.service.controls.set_alternator_enabled(on)

    def set_operating_mode(self, mode):
        return self.service.controls.set_operating_mode(mode)

    def force_float(self, *args):
        return self.service.float_protection.force_float(*args)

    def force_bulk(self, *args):
        return self.service.float_protection.force_bulk(*args)

    def active_mode(self):
        return self.service.controls.active_mode

    def energy_modes(self):
        return self.service.controls.active_mode

    def energy(self):
        return self.service.energy()

    def set_float_status_defaults(self):
        pass

    def load_cache(self, cache):
        self.service.io.clear_cache()
        for (addr, field), value in cache.items():
            self.service.io.put(addr, field, value)

    def put_cache(self, addr, field, value):
        self.service.io.put(addr, field, value)

    def configure_float(self, enabled, trigger, resume):
        self.service.settings.update(
            {
                **self.service.settings.get(),
                "float_protection_enabled": enabled,
                "float_cell_trigger_mv": trigger,
                "float_cell_resume_mv": resume,
            }
        )

    def set_float_callback(self, callback):
        self.service.float_protection.started_callback = callback

    def set_details_getter(self, getter):
        self.service.float_protection.details_getter = getter

    def float_status(self):
        return self.service.float_protection.status

    def run_float_loop(self, steps, before, after):
        self.service.float_protection.stop_event = StepStop(steps, before, after)
        self.service.float_protection.run()
