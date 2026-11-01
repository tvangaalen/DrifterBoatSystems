"""Simulated Bluetooth layer (fake bleak) shared by the Bluetooth self-tests. Test support only, no hardware."""

import asyncio
import time
from collections import Counter

NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
COUNT = Counter()
BEHAVIOUR = {}
PRESENT = set()
RSSI = {}  # per device name: advertised signal strength in dBm (default -60)
SCAN_DELAY = 0.0  # seconds before a scan reports anything
SCAN_CALLBACKS = True  # False: the detection callback never fires; devices are only in the scanner's collected results


def frame(command, data):
    body = bytes((0xA5, 0x01, command, 8)) + bytes(data).ljust(8, b"\0")[:8]
    return body + bytes([sum(body) & 0xFF])


def answers(command):
    def u16(v):
        return v.to_bytes(2, "big")

    if command == 0x90:
        return [frame(command, u16(132) + u16(132) + u16(30000) + u16(800))]
    if command == 0x91:
        return [frame(command, u16(3320) + bytes((1,)) + u16(3310) + bytes((4,)))]
    if command == 0x92:
        return [frame(command, bytes((65, 1, 62, 2)))]
    if command == 0x93:
        return [frame(command, bytes((0, 1, 1, 0, 0, 0, 0, 0x55)))]
    if command == 0x94:
        return [frame(command, bytes((4, 1, 0, 0, 0)) + u16(5))]
    if command == 0x95:
        return [frame(command, bytes((1,)) + u16(3320) + u16(3315) + u16(3312)), frame(command, bytes((2,)) + u16(3310) + u16(0) + u16(0))]
    if command == 0x96:
        return [frame(command, bytes((1, 65)))]
    if command == 0x97:
        return [frame(command, bytes((0b0101, 0, 0, 0, 0, 0)))]
    return [frame(command, bytes(8))]


class Char:
    def __init__(self, uuid, properties, description=""):
        self.uuid, self.properties, self.description = uuid, properties, description


class Service:
    def __init__(self, uuid, characteristics):
        self.uuid, self.characteristics = uuid, characteristics


class Device:
    def __init__(self, name):
        self.name, self.address = name, "AA:BB:" + name


class Advertisement:
    def __init__(self, name):
        self.local_name = name
        self.rssi = RSSI.get(name, -60)


class Sender:
    def __init__(self, uuid):
        self.uuid = uuid


class FakeClient:
    """Behaviour per device name in BEHAVIOUR: connect_hang, fail_connect (count), notify_hang, hang_write, hang_write_once,
    drop_once / drop_always (sets of commands that are not answered), disconnect_hang, cancel_connect (count)."""

    def __init__(self, device, timeout=None, disconnected_callback=None, winrt=None):
        self.device, self.b = device, BEHAVIOUR[device.name]
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.services = [
            Service(
                "0000180a-0000-1000-8000-00805f9b34fb",
                [Char("00002a24-0000-1000-8000-00805f9b34fb", ["read"]), Char("00002a25-0000-1000-8000-00805f9b34fb", ["read"])],
            ),
            Service("0000fff0-0000-1000-8000-00805f9b34fb", [Char(NOTIFY_UUID, ["notify"]), Char(WRITE_UUID, ["write-without-response"])]),
        ]
        self.callback = None

    async def connect(self):
        COUNT[(self.device.name, "connect")] += 1
        if self.b.get("connect_hang"):
            await asyncio.sleep(3600)
        if self.b.get("cancel_connect", 0) > 0:  # bleak/WinRT can end connect() with a CancelledError nobody asked for
            self.b["cancel_connect"] -= 1
            raise asyncio.CancelledError()
        if self.b.get("fail_connect", 0) > 0:
            self.b["fail_connect"] -= 1
            raise RuntimeError("connect failed (simulated)")
        self.is_connected = True

    async def disconnect(self):
        COUNT[(self.device.name, "disconnect")] += 1
        if self.b.get("disconnect_hang"):
            await asyncio.sleep(3600)
        self.is_connected = False

    async def start_notify(self, uuid, callback):
        if self.b.get("notify_hang"):
            await asyncio.sleep(3600)
        self.callback = callback

    async def read_gatt_char(self, char):
        COUNT[(self.device.name, "static_read")] += 1
        return b"DL-BAL"

    async def write_gatt_char(self, uuid, data, response=False):
        command = data[2]
        COUNT[(self.device.name, "write")] += 1
        if self.b.get("hang_write"):
            await asyncio.sleep(3600)
        if self.b.get("hang_write_once"):
            self.b["hang_write_once"] = False
            await asyncio.sleep(3600)
        if command in self.b.get("drop_once", set()):
            self.b["drop_once"].discard(command)
            return
        if command in self.b.get("drop_always", set()):
            return
        loop = asyncio.get_running_loop()
        for item in answers(command):
            loop.call_later(0.003, self.callback, Sender(NOTIFY_UUID), bytearray(item))


class FakeScanner:
    """`BleakScanner(detection_callback=cb)` as an async context manager (the way the application scans), plus the
    static `discover` / `find_device_by_filter` helpers. Every device in PRESENT advertises a few ms after the scan starts."""

    def __init__(self, detection_callback=None, **options):
        self.callback = detection_callback

    async def __aenter__(self):
        COUNT[("scanner", "scan")] += 1
        if SCAN_DELAY:
            await asyncio.sleep(SCAN_DELAY)
        loop = asyncio.get_running_loop()
        if SCAN_CALLBACKS:
            for name in sorted(PRESENT):
                loop.call_later(0.005, self.callback, Device(name), Advertisement(name))
        return self

    async def __aexit__(self, *exc):
        COUNT[("scanner", "stopped")] += 1

    @property
    def discovered_devices_and_advertisement_data(self):
        """What the scanner has collected so far (also when the detection callback never fired)."""
        return {name: (Device(name), Advertisement(name)) for name in PRESENT}

    @staticmethod
    async def discover(timeout=5, return_adv=False):
        await asyncio.sleep(0.01)
        COUNT[("scanner", "discover")] += 1
        return {name: (Device(name), Advertisement(name)) for name in PRESENT}

    @staticmethod
    async def find_device_by_filter(callback, timeout=10):
        await asyncio.sleep(0.01)
        COUNT[("scanner", "find")] += 1
        for name in sorted(PRESENT):
            device, advertisement = Device(name), Advertisement(name)
            if callback(device, advertisement):
                return device
        return None


def wait(condition, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False
