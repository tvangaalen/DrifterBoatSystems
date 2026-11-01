"""Non-hardware self-test for BluetoothCoordinator (priority, exclusion, FIFO, lease expiry, degraded readiness)."""

import asyncio
import threading
import time

from mastervolt.bluetooth.coordinator import BluetoothCoordinator

BMS = ("BATTERY 1", "BATTERY 2", "BATTERY 3")


def ready(c, names=BMS):
    for name in names:
        c.mark_bms(name, True)
        c.mark_bms_refreshed(name)


def main():
    # ---- 1. exclusion and priority order
    c = BluetoothCoordinator()
    ready(c)
    order, first = [], c.acquire("bms_read", 1)
    assert first

    def waiter(kind, tag):
        token = c.acquire(kind, 10)
        assert token
        order.append(tag)
        time.sleep(0.03)
        c.release(kind, token)

    threads = []
    for kind, tag in (
        ("balancer", "balancer"),
        ("bms_read", "read"),
        ("bms", "connect"),
        ("bms_control", "control"),
        ("bms_manual_read", "manual"),
    ):
        t = threading.Thread(target=waiter, args=(kind, tag))
        t.start()
        threads.append(t)
        time.sleep(0.05)
    assert c.snapshot()["active"] == "bms_read" and order == []
    c.release("bms_read", first)
    for t in threads:
        t.join()
    assert order == ["control", "manual", "connect", "read", "balancer"], order
    print("Exclusion and priority order (control > manual > connect > read > balancer): OK")

    # ---- 2. FIFO within the same priority
    c = BluetoothCoordinator()
    ready(c)
    held = c.acquire("bms_read", 1)
    served = []

    def reader(tag):
        token = c.acquire("bms_read", 10)
        served.append(tag)
        time.sleep(0.02)
        c.release("bms_read", token)

    threads = []
    for i in range(1, 7):
        t = threading.Thread(target=reader, args=(i,))
        t.start()
        threads.append(t)
        time.sleep(0.03)
    c.release("bms_read", held)
    for t in threads:
        t.join()
    assert served == [1, 2, 3, 4, 5, 6], served
    print("Waiters of equal priority are served in arrival order: OK")

    # ---- 3. a hung lease is taken back; a late release must not free the new holder
    c = BluetoothCoordinator(max_hold={"balancer": 0.4})
    ready(c)
    stuck = c.acquire("balancer", 1)
    t = time.monotonic()
    control = c.acquire("bms_control", 3)
    waited = time.monotonic() - t
    assert control and 0.3 < waited < 1.5, (control, waited)
    assert c.snapshot()["forced_releases"] == 1 and c.snapshot()["active"] == "bms_control"
    c.release("balancer", stuck)  # the hung operation finally returns: must be ignored
    assert c.snapshot()["active"] == "bms_control", "a stale release freed the new holder"
    c.release("bms_control", control)
    assert c.snapshot()["active"] is None
    print(f"Hung lease is taken back after its maximum hold (user control waited {waited:.1f} s), stale release ignored: OK")

    # ---- 4. time-out without a grant
    c = BluetoothCoordinator()
    ready(c)
    c.acquire("bms_control", 1)
    t = time.monotonic()
    assert c.acquire("bms", 0.3) == 0 and 0.25 < time.monotonic() - t < 1.0
    assert c.snapshot()["waiting"]["bms"] == 0, "a timed-out waiter must leave the queue"
    print("Time-out leaves the queue clean: OK")

    # ---- 5. balancer readiness: full, short outage, degraded, recovery
    c = BluetoothCoordinator(degraded_after=0.5)
    assert not c.bms_ready()
    ready(c)
    assert c.bms_ready() and not c.snapshot()["degraded"]
    c.mark_bms("BATTERY 2", False)
    assert not c.bms_ready(), "a short BMS drop must pause the balancers"
    assert c.acquire("balancer", 0.2) == 0
    time.sleep(0.6)
    assert c.bms_ready() and c.snapshot()["degraded"], "a long BMS outage must not block the balancers for ever"
    token = c.acquire("balancer", 1)
    assert token
    c.release("balancer", token)
    c.mark_bms("BATTERY 3", False)
    assert not c.bms_ready(), "with two batteries down the balancers stay off"
    c.mark_bms("BATTERY 3", True)
    c.mark_bms_refreshed("BATTERY 3")
    assert c.bms_ready() and c.snapshot()["degraded"]
    c.mark_bms("BATTERY 2", True)
    assert not c.bms_ready(), "a reconnecting BMS must be read once before the balancers resume"
    c.mark_bms_refreshed("BATTERY 2")
    assert c.bms_ready() and not c.snapshot()["degraded"]
    print("Balancer readiness: full, paused on a short drop, degraded after a long outage, off with two down, recovers: OK")

    # ---- 6. the async lease waits in a thread and releases
    async def check():
        c = BluetoothCoordinator()
        ready(c)
        ticks = []

        async def ticker():
            for _ in range(8):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        holder = c.acquire("bms_control", 1)
        task = asyncio.create_task(ticker())
        threading.Timer(0.3, c.release, args=("bms_control", holder)).start()
        async with c.alease("balancer", 3) as token:
            assert token and c.snapshot()["active"] == "balancer"
        await task
        assert c.snapshot()["active"] is None
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.2, "the event loop was blocked while waiting for the radio"

    asyncio.run(check())
    print("Async lease: event loop keeps running while waiting, radio released on exit: OK")
    print("All Bluetooth coordinator checks: OK")


if __name__ == "__main__":
    main()
