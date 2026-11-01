"""Serialised access to the MasterBus: field reads, writes and the value cache.

One `BusIO` owns the USB Link. Every transaction (drain, send, wait for the answer) happens under `io_lock`, so the
background poller, the controls and the Float protection never interleave their frames. Reads also fill a small
cache (value + timestamp) that the dashboard is built from, so a browser request never waits for the bus.
"""

from __future__ import annotations

import threading
import time

from .protocol import (
    btm3_address,
    btm3_read_request,
    btm3_write_float,
    decode_btm3_value,
    decode_monitoring,
    encode_commit,
    encode_set_float,
    monitoring_request,
)
from .usb import MasterBusUsb

COMMIT_GAP_SECONDS = 0.05  # between a value write and its commit frame, as MasterAdjust does
SETTLE_SECONDS = 0.35  # after a write, before the first verifying read


class BusIO:
    def __init__(self, bus=None):
        self.bus = bus or MasterBusUsb()
        self.io_lock = threading.RLock()
        self._cache_lock = threading.RLock()
        self._cache: dict[tuple[int, int], dict] = {}

    # ---- connection ---------------------------------------------------------------------------------------
    def open(self) -> None:
        with self.io_lock:
            self.bus.open()

    def close(self) -> None:
        with self.io_lock:
            self.bus.close()

    # ---- cache --------------------------------------------------------------------------------------------
    def put(self, addr: int, field: int, value) -> None:
        with self._cache_lock:
            self._cache[(addr, field)] = {"value": value, "ts": time.time()}

    def cached(self, addr: int, field: int, max_age: float = 20):
        """The last value read for the field, or None when there is none or it is older than `max_age` seconds."""
        with self._cache_lock:
            item = self._cache.get((addr, field))
        if not item or time.time() - item["ts"] > max_age:
            return None
        return item["value"]

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    # ---- reads --------------------------------------------------------------------------------------------
    def read_field(self, addr: int, field: int, timeout_s: float = 0.55):
        """Read a Btm1 monitoring field from the bus (and cache it). Raises TimeoutError without an answer."""
        with self.io_lock:
            self.bus.drain()
            can_id, payload = monitoring_request(addr, field, 0)
            self.bus.send_frame(can_id, payload)
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                for frame in self.bus.read_frames(70):
                    decoded = decode_monitoring(frame)
                    if decoded and frame.address == addr and decoded[0] == field and decoded[1] == 0:
                        self.put(addr, field, decoded[2])
                        return decoded[2]
        raise TimeoutError(f"No response {addr:06X}:{field}")

    def read_btm3(self, addr: int, field: int, timeout_s: float = 0.8):
        """Read a Btm3 field (the CombiMaster's `AC IN support` lives there). Raises TimeoutError without an answer."""
        with self.io_lock:
            self.bus.drain()
            can_id, payload = btm3_read_request(addr, field)
            self.bus.send_frame(can_id, payload)
            answer_address = btm3_address(addr)
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                for frame in self.bus.read_frames(80):
                    if frame.can_class == 0x0B and frame.address == answer_address:
                        value = decode_btm3_value(frame)
                        if value is not None:
                            return value
        raise TimeoutError(f"No Btm3 response {addr:06X}:{field}")

    def wait_for(self, addr: int, field: int, target: float, timeout: float = 4, tolerance: float = 0.05):
        """Poll until the field has been at `target` twice in a row. Returns (reached, last value, samples)."""
        end = time.monotonic() + timeout
        hits = 0
        samples: list = []
        last = None
        while time.monotonic() < end:
            try:
                value = self.read_field(addr, field, 0.8)
            except Exception:
                time.sleep(0.1)
                continue
            samples.append(value)
            last = value
            if value is not None and abs(value - target) <= tolerance:
                hits += 1
                if hits >= 2:
                    return True, last, samples
            else:
                hits = 0
            time.sleep(0.12)
        return False, last, samples

    # ---- writes -------------------------------------------------------------------------------------------
    def write_float(self, addr: int, field: int, value: float, commit_field: int | None = None) -> None:
        """Write a Btm1 float, then (when `commit_field` is given) the commit token to that adjacent field."""
        with self.io_lock:
            self.bus.drain()
            self.bus.send_frame(*encode_set_float(addr, field, value))
            if commit_field is not None:
                time.sleep(COMMIT_GAP_SECONDS)
                self.bus.send_frame(*encode_commit(addr, commit_field))

    def write_bool(self, addr: int, field: int, commit_field: int, value: bool) -> None:
        """A Btm1 on/off setting: 1.0/0.0 followed by the commit token."""
        self.write_float(addr, field, 1.0 if value else 0.0, commit_field)

    def write_btm3(self, addr: int, field: int, value: float) -> None:
        with self.io_lock:
            self.bus.drain()
            self.bus.send_frame(*btm3_write_float(addr, field, value))
