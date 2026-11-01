"""The Mastervolt MasterBus USB Link: a HID device that carries CAN frames inside 64-byte reports.

Only one process can hold the device (MasterAdjust, this application and the diagnostic tools exclude each other).
All access from the application goes through `BusIO`, which serialises it with a lock.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

VID, PID = 0x1A64, 0x0000
REPORT_LEN, RECORD_LEN = 64, 14


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes

    @property
    def can_class(self) -> int:
        return (self.can_id >> 24) & 0x1F

    @property
    def address(self) -> int:
        return self.can_id & 0xFFFFFF


def decode_can_id(record) -> int:
    frame_class = record[0] >> 3
    high = ((record[0] & 7) << 5) | (((record[1] >> 5) & 7) << 2) | (record[1] & 3)
    return (frame_class << 24) | (high << 16) | (record[2] << 8) | record[3]


def parse_hid_report(report) -> list[CanFrame]:
    """Split one HID input report (a record count followed by 14-byte records) into CAN frames."""
    if not report:
        return []
    frames = []
    for index in range(report[0]):
        start = 1 + index * RECORD_LEN
        record = report[start : start + RECORD_LEN]
        if len(record) < RECORD_LEN:
            break
        length = min(record[4], 8)
        frames.append(CanFrame(decode_can_id(record), bytes(record[5 : 5 + length])))
    return frames


def build_hid_report(can_id: int, data) -> bytes:
    data = bytes(data)
    frame_class = (can_id >> 24) & 0x1F
    high = (can_id >> 16) & 0xFF
    out = bytearray(REPORT_LEN + 1)
    payload = memoryview(out)[1:]
    payload[0] = 1
    payload[1] = ((frame_class << 3) | (high >> 5)) & 0xFF
    payload[2] = ((((high >> 2) & 7) << 5) | (high & 3)) & 0xFF
    payload[3] = (can_id >> 8) & 0xFF
    payload[4] = can_id & 0xFF
    payload[5] = len(data)
    payload[6 : 6 + len(data)] = data
    return bytes(out)


class MasterBusUsb:
    def __init__(self, serial: str | None = None):
        self.serial = serial
        self._dev = None
        self.device_info = None

    def open(self) -> None:
        import hid

        devices = hid.enumerate(VID, PID)
        if self.serial:
            devices = [d for d in devices if d.get("serial_number") == self.serial]
        if not devices:
            raise RuntimeError("MasterBus USB Link not found")
        self.device_info = devices[0]
        device = hid.device()
        device.open_path(devices[0]["path"])
        device.set_nonblocking(False)
        self._dev = device

    def close(self) -> None:
        device, self._dev = self._dev, None
        if device:
            try:
                device.close()
            except Exception:  # noqa: BLE001 - a device that was unplugged may refuse to close; it is gone either way
                pass

    def __enter__(self) -> MasterBusUsb:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def read_frames(self, timeout_ms: int = 500) -> list[CanFrame]:
        if not self._dev:
            raise RuntimeError("USB Link not open")
        return parse_hid_report(bytes(self._dev.read(REPORT_LEN, timeout_ms)))

    def send_frame(self, can_id: int, data) -> None:
        if not self._dev:
            raise RuntimeError("USB Link not open")
        if self._dev.write(build_hid_report(can_id, data)) <= 0:
            raise RuntimeError("USB HID write failed")

    def drain(self, quiet_ms: int = 30, max_ms: int = 250) -> int:
        """Discard pending frames until the bus has been quiet for `quiet_ms` (at most `max_ms`); returns how many."""
        started = time.monotonic()
        dropped = 0
        while (time.monotonic() - started) * 1000 < max_ms:
            frames = self.read_frames(quiet_ms)
            if not frames:
                break
            dropped += len(frames)
        return dropped
