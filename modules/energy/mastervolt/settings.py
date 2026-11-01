"""User settings: one declarative table drives defaults, validation, the API model and the saved file.

Adding a setting means adding one `Setting` row here (plus a control on the Settings page). The error messages are shown
verbatim in the UI, so they are part of the behaviour.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("mastervolt.settings")


@dataclass(frozen=True)
class Setting:
    name: str
    kind: type  # int (whole numbers only), float or bool
    default: object
    low: float | None
    high: float | None
    message: str  # shown when the value is not acceptable


# The order is the order of the saved file and of the API documentation.
SETTINGS: tuple[Setting, ...] = (
    Setting("default_ac_limit", int, 15, 3, 15, "Default AC limit must be a whole number from 3 to 15 A"),
    Setting("float_protection_enabled", bool, True, None, None, "Float protection must be on or off"),
    Setting("float_cell_trigger_mv", float, 3500.0, 3300, 3650, "Float cell-voltage trigger must be between 3300 and 3650 mV"),
    Setting("float_cell_resume_mv", float, 3420.0, 3200, 3650, "Float cell-voltage resume level must be between 3200 and 3650 mV"),
    Setting("bms_refresh_interval", int, 30, 5, 300, "BMS refresh interval must be a whole number from 5 to 300 seconds"),
    Setting("bms_popup_seconds", int, 3, 1, 60, "BMS pop-up duration must be a whole number from 1 to 60 seconds"),
    Setting("bms_connection_retry_seconds", int, 5, 1, 300, "BMS connection retry interval must be a whole number from 1 to 300 seconds"),
    Setting("balancer_refresh_interval", int, 30, 5, 300, "Balancer refresh interval must be a whole number from 5 to 300 seconds"),
    Setting(
        "balancer_connection_retry_seconds",
        int,
        30,
        5,
        300,
        "Balancer connection retry interval must be a whole number from 5 to 300 seconds",
    ),
    Setting("history_retention_days", int, 7, 1, 365, "Save history period must be a whole number from 1 to 365 days"),
)
BY_NAME = {setting.name: setting for setting in SETTINGS}
DEFAULTS = {setting.name: setting.default for setting in SETTINGS}

# When several values are wrong at once, the first problem found in this order is reported.
_CHECK_ORDER = (
    "default_ac_limit",
    "float_protection_enabled",
    "float_cell_trigger_mv",
    "float_cell_resume_mv",
    "bms_refresh_interval",
    "bms_popup_seconds",
    "bms_connection_retry_seconds",
    "balancer_connection_retry_seconds",
    "balancer_refresh_interval",
    "history_retention_days",
)
MIN_RESUME_GAP_MV = 30

# Settings removed in earlier releases. An older user_settings.json that still has them must keep loading.
LEGACY_KEYS = ("bulk_resume_delta", "house_battery_soc", "bulk_resume_soc", "warning_popup_seconds")


def _acceptable(setting: Setting, value) -> bool:
    if setting.kind is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if setting.kind is int and int(value) != value:
        return False
    number = int(value) if setting.kind is int else float(value)
    return setting.low <= number <= setting.high


def validate(values: dict, partial: bool = False) -> None:
    """Raise ValueError (with a message fit for the UI) when `values` is not an acceptable settings document."""
    if not partial and set(values) != set(BY_NAME):
        raise ValueError("All settings fields are required")
    unknown = set(values) - set(BY_NAME)
    if unknown:
        raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
    for name in _CHECK_ORDER:
        if name in values and not _acceptable(BY_NAME[name], values[name]):
            raise ValueError(BY_NAME[name].message)
        both = name == "float_cell_resume_mv" and "float_cell_trigger_mv" in values and name in values
        if both and float(values["float_cell_resume_mv"]) > float(values["float_cell_trigger_mv"]) - MIN_RESUME_GAP_MV:
            raise ValueError(f"Float cell-voltage resume level must be at least {MIN_RESUME_GAP_MV} mV below the trigger")


def normalize(values: dict) -> dict:
    """The validated values as the exact Python types that are stored (int, float, bool), in file order."""
    return {setting.name: setting.kind(values[setting.name]) for setting in SETTINGS}


class SettingsStore:
    """Thread-safe settings that survive a restart (`user_settings.json`, written atomically)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._values = dict(DEFAULTS)
        self._listeners: list[Callable[[dict], None]] = []
        self._load()

    def _load(self) -> None:
        """Read the saved file. A value that is missing or not acceptable falls back to its default; one bad entry (or an
        unknown key from another version) never discards the other settings - in particular not the history retention,
        whose default is much shorter than the one normally configured."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key in LEGACY_KEYS:
            raw.pop(key, None)
        for name, setting in BY_NAME.items():
            if name not in raw:
                continue
            try:
                validate({name: raw[name]}, partial=True)
            except (ValueError, TypeError):
                log.warning("Ignoring invalid saved setting %s=%r; using the default %r", name, raw[name], setting.default)
                continue
            self._values[name] = setting.kind(raw[name])
        if self._values["float_cell_resume_mv"] > self._values["float_cell_trigger_mv"] - MIN_RESUME_GAP_MV:
            log.warning("Saved Float thresholds are inconsistent; using the defaults")
            self._values["float_cell_trigger_mv"] = DEFAULTS["float_cell_trigger_mv"]
            self._values["float_cell_resume_mv"] = DEFAULTS["float_cell_resume_mv"]

    def get(self) -> dict:
        with self._lock:
            return dict(self._values)

    def update(self, values: dict) -> dict:
        validate(values)
        normalized = normalize(values)
        with self._lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            self._values = normalized
        for listener in list(self._listeners):
            listener(dict(normalized))
        return dict(normalized)

    def subscribe(self, listener: Callable[[dict], None]) -> None:
        """Call `listener(new_settings)` after every successful save."""
        self._listeners.append(listener)
