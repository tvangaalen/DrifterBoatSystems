"""Tests for the shared Bluetooth building blocks (mastervolt/bluetooth/link.py): Wakeup, Supervisor and the scanner."""

import asyncio
import threading
import time

import bleak

from mastervolt.bluetooth import link
from mastervolt.bluetooth.daly_protocol import BALANCER_NAMES, FrameAssembler, status_request
from tests import ble_fakes
from tests.ble_fakes import COUNT, PRESENT, RSSI, FakeScanner, wait


async def wakeup_checks():
    wake = link.Wakeup()
    wake.set()  # set before the loop exists: not lost
    wake.bind()
    assert wake.is_set() and await wake.wait(5) is True
    wake.clear()
    started = time.monotonic()
    assert await wake.wait(0.15) is False and 0.1 <= time.monotonic() - started < 1.0
    threading.Timer(0.1, wake.set).start()  # a thread wakes the waiting task well before the timeout
    started = time.monotonic()
    assert await wake.wait(5) is True and time.monotonic() - started < 1.0
    wake.clear()
    wake.set()
    wake.clear()  # a set that was cleared again must not make wait() return early
    started = time.monotonic()
    assert await wake.wait(0.15) is False and time.monotonic() - started >= 0.1


def supervisor_checks():
    stop = threading.Event()
    runs, crashes, restarts = [], [], []

    async def run(epoch):
        runs.append(epoch)
        if len(runs) == 1:
            raise RuntimeError("first crash")
        if len(runs) == 2:
            raise asyncio.CancelledError()  # not an Exception: used to end the thread for good
        if len(runs) == 3:
            raise link.WorkerRestart("asked to restart")
        while not stop.is_set():
            await asyncio.sleep(0.01)

    sup = link.Supervisor(
        run,
        stop,
        name="test-worker",
        device="TEST",
        crash_backoff=0.01,
        monitor_seconds=0.05,
        on_crash=crashes.append,
        on_restart=restarts.append,
    )
    sup.start()
    assert wait(lambda: len(runs) >= 4), runs
    assert len(crashes) == 2 and isinstance(crashes[1], asyncio.CancelledError) and len(restarts) == 1
    assert sup.alive and sup.current(runs[-1]) and not sup.current(runs[-1] + 5)
    stop.set()
    sup.join(3)
    assert not sup.alive
    assert not sup.current(runs[-1]), "a stopped supervisor accepts no worker"


def scanner_checks():
    bleak.BleakScanner = FakeScanner
    PRESENT.clear()
    PRESENT.update(BALANCER_NAMES)
    COUNT.clear()
    RSSI.clear()
    RSSI["DL-BAL2"] = -81

    async def scan(wanted, timeout):
        started = time.monotonic()
        found, signal = await link.scan_for(wanted, BALANCER_NAMES, timeout)
        return found, signal, time.monotonic() - started

    found, signal, took = asyncio.run(scan(["DL-BAL1", "DL-BAL2"], 5))
    assert set(found) == {"DL-BAL1", "DL-BAL2"} and took < 1.0, "the scan must end as soon as every wanted device was seen"
    assert signal["DL-BAL2"] == -81 and COUNT[("scanner", "scan")] == 1 and COUNT[("scanner", "stopped")] == 1
    PRESENT.clear()
    PRESENT.add("DL-BAL3")
    found, signal, took = asyncio.run(scan(["DL-BAL1"], 0.3))
    assert found == {} and 0.25 <= took < 1.5, "a device that is not there ends the scan at the time-out, not before"
    assert "DL-BAL3" in signal, "the signal of devices that were not looked for is still recorded"
    # a scanner whose detection callback never fires still delivers through the results it collected (as a plain timed scan did)
    ble_fakes.SCAN_CALLBACKS = False
    PRESENT.clear()
    PRESENT.update(BALANCER_NAMES)
    found, signal, took = asyncio.run(scan(["DL-BAL1", "DL-BAL2"], 0.3))
    assert set(found) == {"DL-BAL1", "DL-BAL2"} and "DL-BAL3" in signal, (found, signal)
    ble_fakes.SCAN_CALLBACKS = True
    RSSI.clear()


def assembler_checks():
    request = status_request(0x90)
    stream = FrameAssembler()
    assert stream.feed(request[:5]) == [] and stream.feed(request[5:]) == [request], "a frame split over two notifications is reassembled"
    assert stream.feed(request + request) == [request, request]
    garbage = b"\x00\x11\xa5\xa5" + request  # junk, and a false start byte right before a real frame
    assert FrameAssembler().feed(garbage) == [request], "bytes that are not a frame are skipped one at a time"
    corrupt = bytearray(request)
    corrupt[5] ^= 0xFF
    assert FrameAssembler().feed(bytes(corrupt) + request) == [request], "a frame with a bad checksum costs one frame, not the stream"


def main():
    asyncio.run(wakeup_checks())
    print("Wakeup: set before bind, set from a thread, timeout, cleared set: OK")
    supervisor_checks()
    print("Supervisor: restarts after an Exception, a CancelledError and a WorkerRestart; stops cleanly: OK")
    scanner_checks()
    print("Scanner: ends when the wanted devices are seen, at the time-out when they are not, records every signal: OK")
    assembler_checks()
    print("Frame assembler: split frames, junk, false start bytes and bad checksums: OK")


if __name__ == "__main__":
    main()
