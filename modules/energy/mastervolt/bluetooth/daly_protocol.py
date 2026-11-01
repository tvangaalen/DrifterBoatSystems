"""The DALY legacy `0xA5` protocol: frame building, stream reassembly, decoding, alarms and voltage-derived SOC.

BMS units and balancers speak the same protocol over the same characteristics (notifications on FFF1, writes on FFF2).
A request is a 13-byte frame `A5 40 <command> 08 <8 zero bytes> <checksum>`; the answer to each of the nine status
commands `0x90`..`0x98` arrives as one or more 13-byte notification frames. Nothing here talks to Bluetooth: it is pure
bytes-in/values-out, which is why it is covered by exact-match tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
COMMANDS = range(0x90, 0x99)
BATTERY_NAMES = ("BATTERY 1", "BATTERY 2", "BATTERY 3")
BALANCER_NAMES = ("DL-BAL1", "DL-BAL2", "DL-BAL3")
FRAME_LENGTH = 13

# Reference LiFePO4 curves: (average cell mV, SOC %). These are comparison indicators; "Set SOC - charge/discharge"
# writes the same values to the BMS.
SOC_DISCHARGING_POINTS = (
    (2500, 0),
    (3000, 10),
    (3200, 20),
    (3220, 30),
    (3250, 40),
    (3260, 50),
    (3270, 60),
    (3300, 70),
    (3320, 80),
    (3350, 90),
    (3400, 100),
)
SOC_CHARGING_POINTS = (
    (2750, 0),
    (3000, 10),
    (3100, 20),
    (3200, 30),
    (3250, 40),
    (3300, 50),
    (3350, 60),
    (3400, 70),
    (3450, 80),
    (3500, 90),
    (3600, 100),
)


def soc_from_average_mv(cell_mv: float, points=SOC_DISCHARGING_POINTS) -> float:
    """Interpolate SOC from the average cell voltage using the selected charging or discharging curve."""
    if cell_mv <= points[0][0]:
        return 0.0
    if cell_mv >= points[-1][0]:
        return 100.0
    for (low_mv, low_soc), (high_mv, high_soc) in zip(points, points[1:], strict=False):
        if cell_mv <= high_mv:
            return low_soc + (cell_mv - low_mv) * (high_soc - low_soc) / (high_mv - low_mv)
    return 100.0


def status_request(command: int) -> bytes:
    """A read request: these commands never change a setting."""
    frame = bytearray((0xA5, 0x40, command, 0x08, 0, 0, 0, 0, 0, 0, 0, 0))
    frame.append(sum(frame) & 0xFF)
    return bytes(frame)


def write_frame(command: int, data: bytes) -> bytes:
    """The confirmed DALY write frame (source byte 0x80) used by the BMS controls."""
    payload = data.ljust(8, b"\0")[:8]
    frame = bytearray((0xA5, 0x80, command, 0x08)) + bytearray(payload)
    frame.append(sum(frame) & 0xFF)
    return bytes(frame)


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def decode(frame: bytes) -> tuple[int, dict]:
    """(command, values) of one valid 13-byte frame."""
    command, data = frame[2], frame[4:12]
    values: dict = {}
    if command == 0x90:
        values = {
            "pack_voltage_v": u16(data, 0) / 10,
            "acquisition_voltage_v": u16(data, 2) / 10,
            "current_a": (u16(data, 4) - 30000) / 10,
            "state_of_charge_percent": u16(data, 6) / 10,
        }
    elif command == 0x91:
        values = {
            "highest_cell_mv": u16(data, 0),
            "highest_cell_number": data[2],
            "lowest_cell_mv": u16(data, 3),
            "lowest_cell_number": data[5],
        }
    elif command == 0x92:
        values = {"highest_temperature_c": data[0] - 40, "lowest_temperature_c": data[2] - 40}
    elif command == 0x93:
        values = {
            "mosfet_status": data[0],
            "charge_mosfet_on": bool(data[1]),
            "discharge_mosfet_on": bool(data[2]),
            "remaining_capacity_mah": int.from_bytes(data[4:8], "big"),
        }
    elif command == 0x94:
        values = {
            "cell_count": data[0],
            "temperature_sensor_count": data[1],
            "charger_connected": bool(data[2]),
            "load_connected": bool(data[3]),
            "charge_discharge_cycles": u16(data, 5),
        }
    elif command == 0x95:
        values = {"frame_number": data[0], "cell_voltages_mv": [u16(data, 1), u16(data, 3), u16(data, 5)]}
    elif command == 0x96:
        values = {"frame_number": data[0], "temperatures_c": [value - 40 for value in data[1:8]]}
    elif command == 0x97:
        # DALY defines payload bit 0 as cell 1 through bit 47 as cell 48 (little-endian bit significance across the six bytes).
        bits = int.from_bytes(data[:6], "little")
        values = {"balancing_cells": [n + 1 for n in range(48) if bits & (1 << n)], "balancing_raw_hex": data[:6].hex(" ").upper()}
    elif command == 0x98:
        values = {"alarm_bytes_hex": data.hex(" ").upper()}
    return command, values


ALARM_BITS = (
    (
        "Cell voltage high – level 1",
        "Cell voltage high – level 2",
        "Cell voltage low – level 1",
        "Cell voltage low – level 2",
        "Pack voltage high – level 1",
        "Pack voltage high – level 2",
        "Pack voltage low – level 1",
        "Pack voltage low – level 2",
    ),
    (
        "Charge temperature high – level 1",
        "Charge temperature high – level 2",
        "Charge temperature low – level 1",
        "Charge temperature low – level 2",
        "Discharge temperature high – level 1",
        "Discharge temperature high – level 2",
        "Discharge temperature low – level 1",
        "Discharge temperature low – level 2",
    ),
    (
        "Charge overcurrent – level 1",
        "Charge overcurrent – level 2",
        "Discharge overcurrent – level 1",
        "Discharge overcurrent – level 2",
        "SOC high – level 1",
        "SOC high – level 2",
        "SOC low – level 1",
        "SOC low – level 2",
    ),
    (
        "Cell voltage difference – level 1",
        "Cell voltage difference – level 2",
        "Temperature difference – level 1",
        "Temperature difference – level 2",
        None,
        None,
        None,
        None,
    ),
    (
        "Charge MOS temperature high",
        "Discharge MOS temperature high",
        "Charge MOS temperature sensor error",
        "Discharge MOS temperature sensor error",
        "Charge MOS adhesion error",
        "Discharge MOS adhesion error",
        None,
        None,
    ),
    (
        "Charge MOS open-circuit error",
        "Discharge MOS open-circuit error",
        "AFE acquisition module error",
        "Voltage sensor module error",
        "Temperature sensor module error",
        "EEPROM error",
        "RTC error",
        "Precharge failure",
    ),
    (
        "Current module fault",
        "Pack-voltage detection fault",
        "Short-circuit protection fault",
        "Charging forbidden by low voltage",
        None,
        None,
        None,
        None,
    ),
)


def decode_alarm_bytes(alarm_hex: str) -> list[str]:
    """Every active DALY 0x98 alarm as a separate readable label."""
    try:
        data = bytes.fromhex(alarm_hex or "")
    except ValueError:
        return [f"Unknown alarm value: {alarm_hex}"] if alarm_hex else []
    alarms = []
    for byte_index, labels in enumerate(ALARM_BITS):
        value = data[byte_index] if byte_index < len(data) else 0
        for bit, label in enumerate(labels):
            if label and value & (1 << bit):
                alarms.append(label)
    if len(data) > 7 and data[7]:
        alarms.append(f"Fault code {data[7]}")
    return alarms


def snapshot_from_frames(name_fragment: str, device_name: str, frames: list[bytes]) -> dict:
    """The BMS status document published for one battery, from the frames answering the nine status commands.

    Raises RuntimeError when the summary (0x90) or the cell/sensor counts (0x94) are missing: a half-read status must
    never be published (it would leave holes in the history)."""
    by_command: dict[int, list[dict]] = {}
    for frame in frames:
        command, values = decode(frame)
        by_command.setdefault(command, []).append(values)
    first = lambda command: (by_command.get(command) or [{}])[0]  # noqa: E731
    summary, range_values, mosfet, status = first(0x90), first(0x91), first(0x93), first(0x94)
    if not summary or not status:
        raise RuntimeError(f"{name_fragment} returned incomplete DALY status data")
    cells = []
    for group in by_command.get(0x95, []):
        cells.extend(group.get("cell_voltages_mv", []))
    temperatures = []
    for group in by_command.get(0x96, []):
        temperatures.extend(group.get("temperatures_c", []))
    cells = cells[: status.get("cell_count", 0)]
    temperatures = temperatures[: status.get("temperature_sensor_count", 0)]
    balance_data = first(0x97)
    balancing = [cell for cell in balance_data.get("balancing_cells", []) if cell <= status.get("cell_count", 0)]
    spread_mv = None
    if cells:
        spread_mv = max(cells) - min(cells)
    elif range_values.get("highest_cell_mv") is not None:
        spread_mv = range_values["highest_cell_mv"] - range_values.get("lowest_cell_mv", 0)
    return {
        "state": "connected",
        "battery": name_fragment,
        "device_name": device_name or name_fragment,
        "captured_at": datetime.now(UTC).isoformat(),
        "pack_voltage_v": summary.get("pack_voltage_v"),
        "current_a": summary.get("current_a"),
        "state_of_charge_percent": summary.get("state_of_charge_percent"),
        "remaining_capacity_ah": None if mosfet.get("remaining_capacity_mah") is None else mosfet["remaining_capacity_mah"] / 1000,
        "temperatures_c": temperatures,
        "cells_mv": cells,
        "cell_spread_mv": spread_mv,
        "charge_mosfet_on": mosfet.get("charge_mosfet_on"),
        "discharge_mosfet_on": mosfet.get("discharge_mosfet_on"),
        "balancing_cells": balancing,
        "balancing_raw_hex": balance_data.get("balancing_raw_hex"),
        "alarms": decode_alarm_bytes(first(0x98).get("alarm_bytes_hex", "")),
        "cycles": status.get("charge_discharge_cycles"),
        "valid_frame_count": len(frames),
    }


class FrameAssembler:
    """Reassembles 13-byte frames from the arbitrary chunks a notification stream delivers.

    A frame starts with 0xA5, has length byte 8 and ends with the low byte of the sum of the first 12 bytes. Bytes that do
    not form a valid frame are skipped one at a time, so a single lost or corrupted byte costs one frame, not the stream.
    """

    def __init__(self):
        self.buffer = bytearray()

    def clear(self) -> None:
        self.buffer.clear()

    def feed(self, payload) -> list[bytes]:
        buffer = self.buffer
        buffer.extend(payload)
        frames = []
        while len(buffer) >= FRAME_LENGTH:
            try:
                start = buffer.index(0xA5)
            except ValueError:
                buffer.clear()
                break
            if start:
                del buffer[:start]
            if len(buffer) < FRAME_LENGTH:
                break
            frame = bytes(buffer[:FRAME_LENGTH])
            if frame[3] == 8 and (sum(frame[:12]) & 0xFF) == frame[12]:
                frames.append(frame)
                del buffer[:FRAME_LENGTH]
            else:
                del buffer[0]
        return frames
