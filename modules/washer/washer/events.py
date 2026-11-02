"""The controller's own event list (newest first, the last 50) and the washer's state changes."""
from __future__ import annotations

from collections import deque

from common import timefmt
from washer.device import state_name


class Events:
    def __init__(self):
        self.items: deque = deque(maxlen=50)
        self.last_state = self.connected = None

    def log(self, event, detail="", duration_ms=None) -> None:
        entry = {"time": timefmt.hms(), "event": str(event), "detail": str(detail)}
        if duration_ms is not None: entry["duration_ms"] = int(duration_ms)
        self.items.appendleft(entry)

    def observe(self, status: dict) -> None:
        """A successful read: log reconnects and changes of state (a door left open is fault 3)."""
        fault = int(status.get("fault") or 0)
        current = "DOOR OPEN" if fault == 3 else state_name(status.get("status", 0), bool(status.get("power")))
        if self.connected is False: self.log("CONNECTIVITY", "OFFLINE → ONLINE")
        self.connected = True
        if self.last_state is not None and current != self.last_state: self.log("STATE", f"{self.last_state} → {current}")
        self.last_state = current

    def offline(self) -> None:
        if self.connected is not False: self.log("CONNECTIVITY", "ONLINE → OFFLINE" if self.connected else "OFFLINE")
        self.connected = False
