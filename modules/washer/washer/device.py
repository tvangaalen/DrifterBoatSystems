"""The VIOMI W1 over MIoT: properties (siid, piid), the start/pause actions and the readable names of its codes."""
from __future__ import annotations

import threading
from pathlib import Path

from washer import config

try:
    from miio.miot_device import MiotDevice
    MIIO_IMPORT_ERROR = None
except Exception as exc:                       # the controller still serves its diagnostics without the library
    MiotDevice, MIIO_IMPORT_ERROR = None, str(exc)

PROPS = {"power": (2, 1), "status": (2, 2), "mode": (2, 3), "fault": (2, 4), "left_time": (2, 5), "temperature": (2, 6),
         "spin": (2, 7), "rinses": (2, 9), "locked": (3, 1)}
STATUS_MAP = {0: "Standby", 1: "Standby", 7: "Washing", 9: "Rinsing", 11: "Spinning", 17: "Finished", 26: "Paused", 27: "Stopped / Fault"}
TEMPERATURE_VALUES = {0, 30, 40, 60, 80}
SPIN_VALUES = {400, 600, 700}
RINSE_VALUES = {1, 2, 3, 4}
PROGRAM_CAPABILITIES = {
    0: {"temperatures": [40], "spin": 700, "rinses": [2]},
    16: {"temperatures": [60], "spin": 700, "rinses": [1, 2, 3, 4]},
    4: {"temperatures": [0], "spin": 700, "rinses": [0]},
    13: {"temperatures": [0, 30, 40, 60], "spin": 700, "rinses": [1, 2, 3, 4]},
    22: {"temperatures": [0], "spin": 700, "rinses": [1, 2, 3, 4]},
    23: {"temperatures": [80], "spin": 700, "rinses": [2]},
    29: {"temperatures": [80], "spin": 700, "rinses": [1, 2, 3, 4]},
    31: {"temperatures": [0, 30, 40], "spin": 600, "rinses": [1, 2, 3, 4]},
    36: {"temperatures": [0, 30, 40], "spin": 700, "rinses": [1, 2, 3, 4]},
    37: {"temperatures": [0, 30, 40, 60], "spin": 700, "rinses": [1, 2, 3, 4]},
    38: {"temperatures": [0, 30, 40], "spin": 400, "rinses": [1, 2, 3, 4]},
    39: {"temperatures": [80], "spin": 700, "rinses": [1, 2, 3, 4]},
    40: {"temperatures": [0, 30, 40, 60], "spin": 700, "rinses": [1, 2, 3, 4]},
}
MODE_MAP = {0: "Golden Wash", 16: "Antibacterial", 4: "Spin", 13: "Underwear", 22: "Rinse + Spin", 23: "Drum Clean", 29: "Boil Wash",
            31: "Delicate", 36: "New Clothes", 37: "Socks", 38: "Bra", 39: "Towel Boil Wash", 40: "Gloves"}
STATE_NAMES = {0: "READY", 1: "READY", 4: "DELAY", 7: "WASHING", 9: "RINSING", 11: "SPINNING", 17: "FINISHED", 25: "WEIGHING", 26: "PAUSED", 27: "FAULT"}
IDLE = (0, 1, 17)
RUNNING = (7, 9, 11, 25, 26)


def state_name(status, power) -> str:
    return "OFF" if not power else STATE_NAMES.get(int(status), f"STATUS {status}")


class Washer:
    """The configured washer. `reload()` re-reads the configuration and creates the MIoT device again (diagnostics)."""

    def __init__(self, folder: Path, device_factory=None):
        self.config_path = Path(folder) / "viomi_config.json"
        self.device_factory = device_factory if device_factory is not None else MiotDevice
        self.lock = threading.Lock()                   # one MIoT transaction at a time
        self.model = self.firmware = None
        self.reload()

    def reload(self) -> None:
        self.config, self.config_error = config.load(self.config_path)
        self.ip, self.token, self.expected_pc_ip = self.config.washer_ip, self.config.token, self.config.expected_pc_ip
        self.device = None
        if self.device_factory is not None and self.token:
            try: self.device = self.device_factory(self.ip, self.token)
            except Exception: self.device = None

    def _require(self):
        if self.device is None: raise RuntimeError("Washer device is not initialized. Open the startup diagnostics page.")
        return self.device

    def read_all(self) -> dict:
        dev = self._require()
        with self.lock: raw = dev.send("get_properties", [{"siid": s, "piid": p} for s, p in PROPS.values()])
        by_id = {v: k for k, v in PROPS.items()}; result, errors = {}, {}
        for item in raw:
            key = by_id.get((item.get("siid"), item.get("piid")))
            if not key: continue
            if item.get("code", 0) == 0: result[key] = item.get("value")
            else: result[key] = None; errors[key] = f"MIoT error {item.get('code')}"
        for key in PROPS: result.setdefault(key, None)
        result["power_text"] = "On" if result["power"] is True else "Off" if result["power"] is False else "Unknown"
        result["status_text"] = STATUS_MAP.get(result["status"], f"Code {result['status']}")
        result["mode_text"] = MODE_MAP.get(result["mode"], f"Program code {result['mode']}")
        result["fault_text"] = "No fault" if result["fault"] == 0 else f"Fault code {result['fault']}"
        result["locked_text"] = "Yes" if result["locked"] is True else "No" if result["locked"] is False else "Unknown"
        result["errors"] = errors
        return result

    def set_property(self, siid: int, piid: int, value):
        """Direct MIoT set_properties, so that a numeric zero stays a valid value."""
        dev = self._require()
        with self.lock: reply = dev.send("set_properties", [{"siid": siid, "piid": piid, "value": value}])
        if not isinstance(reply, list) or not reply: raise RuntimeError(f"Unexpected MIoT reply: {reply!r}")
        if reply[0].get("code", 0) != 0: raise RuntimeError(f"MIoT error {reply[0].get('code')}")
        return reply[0]

    def action(self, siid: int, aiid: int, params=None):
        dev = self._require()
        with self.lock: return dev.call_action_by(siid, aiid, params or [])

    def info(self):
        dev = self._require()
        with self.lock: return dev.info()
