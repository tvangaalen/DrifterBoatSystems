"""A simulated MasterBus USB Link for hardware-free tests.

`FakeBus` answers Btm1 monitoring requests and Btm3 reads from a table of device values, applies the writes the
real devices accept (including the few side effects the application relies on, such as Float/Bulk events changing a
charger's state) and logs every frame that is sent. `FakeClock` replaces `time.sleep`/`time.monotonic`/`time.time`
so the 0.35 s settle times and 4 s verification loops run instantly and deterministically.
"""

from __future__ import annotations

import contextlib
import struct
import time

COMMIT_TOKEN = bytes([0x14, 0x9F, 0x3C, 0x02])

COMBIMASTER, SOLAR, ALTERNATOR, YANMAR = 0x1B7CE1, 0x31B483, 0x329B8C, 0x3AE394
HOUSE = 0x6DB09B
CHARGER_BOW, CHARGER_START = 0x61CA96, 0x63D010


class Frame:
    """Same attributes as the real CanFrame (can_id, data, can_class, address)."""

    def __init__(self, can_id: int, data: bytes):
        self.can_id, self.data = can_id, bytes(data)

    @property
    def can_class(self) -> int:
        return (self.can_id >> 24) & 0x1F

    @property
    def address(self) -> int:
        return self.can_id & 0xFFFFFF


class FakeClock:
    """Deterministic time: sleeping and blocking reads advance it, nothing really waits."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start
        self.base_wall = 1_790_000_000.0

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, float(seconds))

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.base_wall + (self.now - 1_000_000.0)

    @contextlib.contextmanager
    def installed(self):
        saved = time.sleep, time.monotonic, time.time
        time.sleep, time.monotonic, time.time = self.sleep, self.monotonic, self.time
        try:
            yield self
        finally:
            time.sleep, time.monotonic, time.time = saved


# Float / Bulk event command fields -> (device, state field, resulting state). The application's own table.
EVENT_EFFECTS = {
    (COMBIMASTER, 42): (COMBIMASTER, 1, 3.0),
    (COMBIMASTER, 38): (COMBIMASTER, 1, 1.0),
    (SOLAR, 18): (SOLAR, 3, 3.0),
    (SOLAR, 14): (SOLAR, 3, 1.0),
    (ALTERNATOR, 37): (ALTERNATOR, 5, 3.0),
    (ALTERNATOR, 33): (ALTERNATOR, 5, 1.0),
}


class FakeBus:
    device_info = {"product_string": "Fake MasterBus USB Link", "serial_number": "TEST"}

    def __init__(self, clock: FakeClock, values=None, btm3=None, ignore_writes=False, solar_reverts=False, alternator_stuck=False):
        self.clock = clock
        self.values = dict(values or {})
        self.btm3 = dict(btm3 or {})
        self.ignore_writes, self.solar_reverts, self.alternator_stuck = ignore_writes, solar_reverts, alternator_stuck
        self.sent: list[tuple[str, str]] = []
        self.pending: list[Frame] = []
        self.broken = False  # every I/O call raises OSError (a vanished USB device) until the Link is opened again
        self.open_failures = 0  # the next N open() calls fail (the Link is not plugged in yet)
        self.opens = self.closes = 0

    # --- the MasterBusUsb interface -------------------------------------------------------------
    def open(self):
        if self.open_failures > 0:
            self.open_failures -= 1
            raise RuntimeError("MasterBus USB Link not found")
        self.opens += 1
        self.broken = False

    def close(self):
        self.closes += 1

    def _check(self):
        if self.broken:
            raise OSError("read error (simulated unplugged device)")

    def drain(self, quiet_ms=30, max_ms=250):
        self._check()
        self.pending.clear()
        return 0

    def read_frames(self, timeout_ms=500):
        self._check()
        if self.pending:
            frames, self.pending = self.pending, []
            return frames
        self.clock.now += timeout_ms / 1000.0  # a real blocking read that times out
        return []

    def send_frame(self, can_id, data):
        self._check()
        data = bytes(data)
        self.sent.append((f"{can_id:08X}", data.hex()))
        klass, addr = (can_id >> 24) & 0x1F, can_id & 0xFFFFFF
        if klass == 0x18:
            if len(data) == 2:  # Btm1 monitoring request
                field = data[0]
                value = self.values.get((addr, field))
                self.pending.append(
                    Frame((0x08 << 24) | addr, bytes([field, data[1]]) + struct.pack("<f", float("nan") if value is None else float(value)))
                )
            elif len(data) == 6 and data[2:6] != COMMIT_TOKEN:  # Btm1 write
                self._write(addr, data[0], struct.unpack("<f", data[2:6])[0])
        elif klass == 0x1B:
            base = addr & ~0x800000
            field = data[0] | (data[1] << 8)
            if len(data) == 2:  # Btm3 read
                value = self.btm3.get((base, field))
                self.pending.append(
                    Frame(
                        (0x0B << 24) | addr, bytes([data[0], data[1]]) + struct.pack("<f", float("nan") if value is None else float(value))
                    )
                )
            elif len(data) == 6 and not self.ignore_writes:  # Btm3 write
                self.btm3[(base, field)] = struct.unpack("<f", data[2:6])[0]

    # --- what the simulated devices do with a write --------------------------------------------
    def _write(self, addr, field, value):
        if self.ignore_writes:
            return
        if (addr, field) in EVENT_EFFECTS:
            device, state_field, state = EVENT_EFFECTS[(addr, field)]
            if value >= 0.5:
                self.values[(device, state_field)] = state
            return
        if (addr, field) == (ALTERNATOR, 39):  # Stop charge
            if not self.alternator_stuck:
                self.values[(ALTERNATOR, 5)] = 5.0 if value >= 0.5 else 1.0
            return
        if (addr, field) == (SOLAR, 12) and value >= 0.5 and self.solar_reverts:
            self.values[(addr, field)] = 0.0  # the SCM falls straight back to OFF without PV
            return
        self.values[(addr, field)] = value


def default_values(rng) -> dict:
    """Plausible values for every field the application reads, from a seeded random.Random."""
    values = {}
    for addr in (COMBIMASTER, SOLAR, ALTERNATOR, YANMAR, CHARGER_BOW, CHARGER_START, 0x6DB09B, 0x6D59B9, 0x6D9E99):
        for field in range(0, 70):
            values[(addr, field)] = round(rng.uniform(0, 50), 3)
    values.update(
        {
            (COMBIMASTER, 19): 0.0,
            (COMBIMASTER, 21): 1.0,
            (COMBIMASTER, 23): 15.0,
            (COMBIMASTER, 1): 1.0,
            (SOLAR, 3): 1.0,
            (SOLAR, 12): 1.0,
            (ALTERNATOR, 5): 1.0,
            (ALTERNATOR, 39): 0.0,
            (CHARGER_START, 64): 1.0,
            (CHARGER_BOW, 64): 1.0,
            (YANMAR, 43): 1.0,
        }
    )
    return values
