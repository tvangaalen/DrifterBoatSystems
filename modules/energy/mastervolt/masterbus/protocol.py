"""MasterBus frame encoding and decoding (Btm1 monitoring/commands and Btm3 reads/writes).

Requests are returned as `(can_id, payload)` pairs ready for `MasterBusUsb.send_frame`. Every writable field on this
boat is a 32-bit little-endian float; the commit token is the fixed 4-byte value MasterAdjust writes to the adjacent
hidden field to apply a Btm1 setting.
"""

from __future__ import annotations

import math
import struct

COMMIT_TOKEN = bytes([0x14, 0x9F, 0x3C, 0x02])

CLASS_BTM1_REQUEST = 0x18
CLASS_BTM1_RESPONSE = 0x08
CLASS_BTM3_REQUEST = 0x1B
CLASS_BTM3_RESPONSE = 0x0B


def _can_id(frame_class: int, address: int) -> int:
    return (frame_class << 24) | (address & 0xFFFFFF)


def monitoring_request(addr: int, field: int, tab: int = 0):
    """Ask a device for the current value of one monitoring field."""
    return _can_id(CLASS_BTM1_REQUEST, addr), bytes([field & 0xFF, tab & 0xFF])


def encode_set_float(addr: int, field: int, value: float):
    return _can_id(CLASS_BTM1_REQUEST, addr), bytes([field & 0xFF, 0]) + struct.pack("<f", float(value))


def encode_set_boolean(addr: int, field: int, value: bool):
    return encode_set_float(addr, field, 1.0 if value else 0.0)


def encode_commit(addr: int, field: int):
    return _can_id(CLASS_BTM1_REQUEST, addr), bytes([field & 0xFF, 0]) + COMMIT_TOKEN


def _finite(value: float):
    return None if math.isnan(value) or math.isinf(value) else value


def decode_monitoring(frame):
    """(field, tab, value) of a Btm1 monitoring response, or None for any other frame. NaN/infinity become None."""
    if frame.can_class != CLASS_BTM1_RESPONSE or len(frame.data) < 6:
        return None
    value = _finite(struct.unpack("<f", bytes(frame.data[2:6]))[0])
    return frame.data[0], frame.data[1], value


def btm3_address(addr: int) -> int:
    """Btm3 devices answer on the same address with the high bit of the 24-bit address set."""
    return (addr | 0x800000) & 0xFFFFFF


def btm3_read_request(addr: int, field: int):
    return _can_id(CLASS_BTM3_REQUEST, btm3_address(addr)), bytes([field & 0xFF, (field >> 8) & 0xFF])


def btm3_write_float(addr: int, field: int, value: float):
    return (
        _can_id(CLASS_BTM3_REQUEST, btm3_address(addr)),
        bytes([field & 0xFF, (field >> 8) & 0xFF]) + struct.pack("<f", float(value)),
    )


def decode_btm3_value(frame):
    """The float carried by a Btm3 response (the last four data bytes), or None for another frame or NaN/infinity."""
    if frame.can_class != CLASS_BTM3_RESPONSE or len(frame.data) < 4:
        return None
    return _finite(struct.unpack("<f", bytes(frame.data[-4:]))[0])
