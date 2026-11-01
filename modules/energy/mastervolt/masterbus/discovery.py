"""Read-only discovery of what a MasterBus device exposes: field names, units, types and dropdown options.

Used at start-up only to find the MasterShunt battery type/capacity fields by name, and by the diagnostic tools in
`tools/`. The dashboard itself never runs discovery: its measurement fields are fixed (docs/VERIFIED_FIELD_MAP.txt).
Nothing here writes to a device.
"""

from __future__ import annotations

import struct
import time

VIZ = {
    1: "Float",
    2: "GrayFloat",
    3: "DropDown",
    4: "Eventable",
    5: "CheckBox",
    6: "Text",
    7: "Time",
    8: "Date",
    9: "DeviceList",
    10: "EventCommand",
    11: "SwitchVariant",
}


class _Query:
    """A request/answer exchange on the bus, under the shared I/O lock. `io` is a `BusIO`."""

    TIMEOUT = 0.30
    READ_MS = 50

    def __init__(self, io):
        self.io = io

    def _request(self, can_id, payload, predicate, timeout=None, retries=2):
        timeout = self.TIMEOUT if timeout is None else timeout
        for _ in range(retries + 1):
            with self.io.io_lock:
                self.io.bus.drain()
                self.io.bus.send_frame(can_id, payload)
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    for frame in self.io.bus.read_frames(self.READ_MS):
                        if predicate(frame):
                            return frame
            time.sleep(0.01)  # let the poller in between two attempts (the lock is not fair)
        return None

    def _string(self, addr, string_id):
        """A device string table entry, fetched in 4-byte chunks until the terminating NUL."""
        raw = bytearray()
        for seq in range(64):
            payload = bytes([0x30, string_id & 0xFF, (string_id >> 8) & 0xFF, seq])
            frame = self._request(
                (0x07 << 24) | addr,
                payload,
                lambda f, payload=payload: f.can_class == 0x06 and f.address == addr and len(f.data) >= 4 and bytes(f.data[:4]) == payload,
            )
            if frame is None:
                break
            chunk = bytes(frame.data[4:8])
            end = chunk.find(b"\x00")
            if end >= 0:
                raw.extend(chunk[:end])
                break
            raw.extend(chunk)
        return raw.decode("latin-1", errors="replace").strip()


class Discovery(_Query):
    """Field names and units (Btm1 metadata opcodes 0x28 and 0x2C)."""

    def meta(self, addr, opcode, index):
        wire = (addr | 0x800000) & 0xFFFFFF
        payload = bytes([opcode, index & 255, (index >> 8) & 255])
        frame = self._request(
            (0x18 << 24) | wire,
            payload,
            lambda x: x.can_class == 0x08
            and x.address == wire
            and len(x.data) >= 3
            and x.data[0] == opcode
            and x.data[1] == (index & 255)
            and x.data[2] == ((index >> 8) & 255),
        )
        return None if frame is None else frame.data

    def schema(self, addr, max_index):
        out = []
        for index in range(max_index + 1):
            name_meta, unit_meta = self.meta(addr, 0x28, index), self.meta(addr, 0x2C, index)
            if name_meta is None and unit_meta is None:
                continue
            name = unit = ""
            if name_meta and len(name_meta) >= 6:
                string_id = int.from_bytes(name_meta[4:6], "little")
                if string_id:
                    name = self._string(addr, string_id)
            if unit_meta and len(unit_meta) >= 6:
                string_id = int.from_bytes(unit_meta[4:6], "little")
                if string_id:
                    unit = self._string(addr, string_id)
            out.append({"index": index, "name": name, "unit": unit})
        return out


class ControlDiscovery(_Query):
    """Field types, writability and dropdown options for Btm1 and Btm3 devices."""

    TIMEOUT = 0.35
    READ_MS = 60

    def _meta(self, addr, index, opcode, protocol, extra_byte=None):
        if protocol == "btm1":
            wire, request_class, response_class = (addr | 0x800000) & 0xFFFFFF, 0x18, 0x08
        else:
            wire, request_class, response_class = addr, 0x1C, 0x0C
        payload = bytes([opcode, index & 0xFF, (index >> 8) & 0xFF] + ([] if extra_byte is None else [extra_byte & 0xFF]))
        minimum = 5 if extra_byte is None else 6

        def answers(f):
            return (
                f.can_class == response_class
                and f.address == wire
                and len(f.data) >= minimum
                and f.data[0] == opcode
                and f.data[1] == (index & 0xFF)
                and f.data[2] == ((index >> 8) & 0xFF)
                and (extra_byte is None or f.data[3] == (extra_byte & 0xFF))
            )

        frame = self._request((request_class << 24) | wire, payload, answers)
        return None if frame is None else frame.data

    def _meta_with_extra(self, addr, index, opcode, protocol, extra_byte):
        return self._meta(addr, index, opcode, protocol, extra_byte)

    def fields(self, addr, max_index):
        results = []
        for protocol in ("btm1", "btm3"):
            any_found = False
            for index in range(max_index + 1):
                viz = self._meta(addr, index, 0x02, protocol)
                writable = self._meta(addr, index, 0x0B, protocol)
                name_meta = self._meta(addr, index, 0x28, protocol)
                if viz is None and writable is None and name_meta is None:
                    continue
                any_found = True
                name = ""
                if name_meta and len(name_meta) >= 6:
                    string_id = int.from_bytes(name_meta[4:6], "little")
                    if string_id:
                        name = self._string(addr, string_id)
                results.append(
                    {
                        "protocol": protocol,
                        "index": index,
                        "name": name,
                        "viz_code": None if not viz or len(viz) < 5 else viz[4],
                        "viz": None if not viz or len(viz) < 5 else VIZ.get(viz[4], f"0x{viz[4]:02X}"),
                        "writable": None if not writable or len(writable) < 5 else writable[4] != 0,
                    }
                )
            if any_found:
                break
        return results

    def list_options(self, addr, field_index, protocol="btm1"):
        """Dropdown/list option labels. Metadata 0x07 is the maximum (or count), 0x26 the string id of one option."""
        maximum = self._meta(addr, field_index, 0x07, protocol)
        if not maximum or len(maximum) < 8:
            return []
        raw_max = struct.unpack("<f", bytes(maximum[4:8]))[0]
        count_hint = max(0, min(int(round(raw_max)), 32))
        options = []
        misses = 0
        # Probe a little beyond the advertised maximum: devices differ on whether 0x07 is a count or the highest index.
        for option_index in range(0, count_hint + 2):
            data = self._meta_with_extra(addr, field_index, 0x26, protocol, option_index)
            if not data or len(data) < 6:
                misses += 1
                if misses >= 2 and options:
                    break
                continue
            string_id = int.from_bytes(data[4:6], "little")
            label = "" if string_id == 0 else self._string(addr, string_id)
            options.append({"index": option_index, "string_id": string_id, "label": label})
            misses = 0
        return options

    @staticmethod
    def control_candidates(fields):
        """Rank writable on/off-like fields by how much their name looks like a power switch (for the inspection tools)."""
        positive = ("on", "off", "enable", "enabled", "activate", "active", "switch", "charger", "charge", "power")
        negative = ("alarm", "reset", "test", "finish", "setup", "save", "language", "limit", "voltage", "current", "temperature")
        out = []
        for field in fields:
            if not field.get("writable"):
                continue
            if field.get("viz") not in ("CheckBox", "Eventable", "SwitchVariant", "DropDown"):
                continue
            name = (field.get("name") or "").lower().strip()
            score = sum(3 for word in positive if word in name) - sum(5 for word in negative if word in name)
            if name in ("on", "enabled", "enable", "power"):
                score += 10
            if score > 0:
                item = dict(field)
                item["score"] = score
                out.append(item)
        return sorted(out, key=lambda item: (-item["score"], item["index"]))
