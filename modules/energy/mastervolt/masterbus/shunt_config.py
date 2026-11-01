"""Battery type and capacity of the three MasterShunts, found by field *name* and remembered in a JSON file.

MasterShunt firmware revisions do not expose their configuration at identical field numbers, so nothing is guessed:
only fields whose device-provided names match a conservative allow-list are used (`discover`, run once in the
background at start-up). Until a field and a usable value are known, the dashboard shows the built-in fallback type.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from .discovery import ControlDiscovery, Discovery
from .registry import BOW_SHUNT, DEVICE_INFO, HOUSE_SHUNT, START_SHUNT

TYPE_NAMES = {"battery type", "battery technology", "battery chemistry"}
CAPACITY_NAMES = {"battery capacity", "nominal capacity", "installed capacity", "bank capacity", "capacity"}
SHUNTS = {"house": HOUSE_SHUNT, "start": START_SHUNT, "bow": BOW_SHUNT}
_ALLOWED_LABEL_CHARACTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 +-/().")


log = logging.getLogger("mastervolt.masterbus")
MAX_AGE_SECONDS = 30 * 86400  # the discovered field numbers belong to the device firmware: found once, trusted for a month


def clean_battery_type(label) -> str | None:
    """A compact chemistry/type label that is safe to show in HTML (for example MLI, AGM or LiFePO4), else None."""
    label = " ".join(str(label or "").strip().split())
    if not label or len(label) > 24:
        return None
    return label if all(ch in _ALLOWED_LABEL_CHARACTERS for ch in label) else None


class MasterShuntConfig:
    def __init__(self, io, path: Path):
        self.io, self.path = io, Path(path)
        self.maps: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.maps = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.maps = {}

    def extra_poll_fields(self) -> list[tuple[int, int]]:
        """The discovered type/capacity fields, so the background poller keeps them fresh in the cache."""
        fields = []
        for key, addr in SHUNTS.items():
            config = self.maps.get(key, {})
            for field_name in ("type_field", "capacity_field"):
                try:
                    fields.append((addr, int(config[field_name])))
                except (KeyError, TypeError, ValueError):
                    pass
        return fields

    def describe(self, key: str, addr: int, fallback_type: str) -> dict:
        config = self.maps.get(key, {})
        battery_type = None
        capacity = None
        type_field, capacity_field = config.get("type_field"), config.get("capacity_field")
        if type_field is not None:
            raw = self.io.cached(addr, int(type_field))
            if raw is not None:
                for option in config.get("type_options", []):
                    try:
                        if abs(float(option.get("index")) - float(raw)) <= 0.05:
                            battery_type = clean_battery_type(option.get("label"))
                            break
                    except (TypeError, ValueError):
                        continue
        if capacity_field is not None:
            raw = self.io.cached(addr, int(capacity_field))
            try:
                if raw is not None and 0 < float(raw) < 100000:
                    capacity = float(raw)
            except (TypeError, ValueError):
                pass
        return {
            "battery_type": battery_type or fallback_type,
            "capacity": capacity,
            "capacity_unit": config.get("capacity_unit") or "A",
            "config_discovered": bool(battery_type or capacity is not None),
        }

    def is_fresh(self) -> bool:
        """True when a non-empty discovery result was saved less than 30 days ago."""
        try:
            return bool(self.maps) and time.time() - self.path.stat().st_mtime < MAX_AGE_SECONDS
        except OSError:
            return False

    def discover(self, stop: threading.Event, force: bool = False) -> None:
        """Find the type/capacity fields by name (read-only) and remember them.

        This is a long conversation with the devices (about a minute) that competes with the poller for the bus: with the
        poller starved, the dashboard went blank for the first minute after every start. The result only changes with the
        device firmware, so it is repeated at most monthly (or with `force`)."""
        if not force and self.is_fresh():
            log.info("MasterShunt configuration found earlier is still current; skipping discovery")
            return
        discovery, options = Discovery(self.io), ControlDiscovery(self.io)
        found = {}
        for key, addr in SHUNTS.items():
            if stop.is_set():
                return
            try:
                schema = discovery.schema(addr, DEVICE_INFO[addr]["max_index"])
            except Exception:
                continue
            item = {"address": f"{addr:06X}"}
            for field in schema:
                name = " ".join((field.get("name") or "").lower().split())
                if name in TYPE_NAMES and "type_field" not in item:
                    item["type_field"] = int(field["index"])
                    item["type_name"] = field.get("name") or ""
                    try:
                        item["type_options"] = options.list_options(addr, int(field["index"]))
                    except Exception:
                        item["type_options"] = []
                if name in CAPACITY_NAMES and "capacity_field" not in item:
                    item["capacity_field"] = int(field["index"])
                    item["capacity_name"] = field.get("name") or ""
                    item["capacity_unit"] = field.get("unit") or "A"
            if "type_field" in item or "capacity_field" in item:
                found[key] = item
        if found:
            self.maps = found
            try:
                self.path.write_text(json.dumps(found, indent=2), encoding="utf-8")
            except OSError:
                pass
