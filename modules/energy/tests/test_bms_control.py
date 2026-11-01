"""Non-hardware regression checks for verified DALY MOS controls."""

import asyncio
import types

from mastervolt.bluetooth.bms import BatteryWorker


class FakeService:
    def __init__(self):
        self.value = {"cells_mv": [3300] * 4, "charge_mosfet_on": True, "discharge_mosfet_on": True}
        self.encodings = {}

    def get_battery(self, _name):
        return dict(self.value)

    def progress(self, _detail):
        pass

    def mos_encoding(self, name, action):
        return self.encodings.get((name, action))

    def remember_mos_encoding(self, name, action, value):
        self.encodings[(name, action)] = value


class FakeClient:
    is_connected = True

    def __init__(self, service, one_means_on=None):
        self.service = service
        self.commands = []
        self.one_means_on = one_means_on or {"charge": True, "discharge": True}

    async def write_gatt_char(self, _uuid, frame, response=False):
        command, enabled = frame[2], bool(frame[4])
        self.commands.append((command, enabled))
        if command == 0xD9:
            state = enabled if self.one_means_on["discharge"] else not enabled
            self.service.value["discharge_mosfet_on"] = state
            if not state:
                self.service.value["charge_mosfet_on"] = False
        elif command == 0xDA:
            self.service.value["charge_mosfet_on"] = enabled if self.one_means_on["charge"] else not enabled


async def main():
    service = FakeService()
    worker = BatteryWorker(service, "BATTERY 3", 2)
    worker.operation_lock = asyncio.Lock()
    worker.client = FakeClient(service)

    async def refresh(self, *_args, **_kwargs):
        return True

    worker._refresh_unlocked = types.MethodType(refresh, worker)

    result = await worker.control("discharge", False)
    assert result["verified"] is True
    assert service.value["discharge_mosfet_on"] is False
    assert service.value["charge_mosfet_on"] is True
    assert worker.client.commands == [(0xD9, False), (0xDA, True)]
    print("DALY MOS command mapping: OK (Charge=0xDA, Discharge=0xD9)")
    print("Unrelated MOS preservation and verification: OK")

    inverted = FakeService()
    worker2 = BatteryWorker(inverted, "BATTERY 2", 1)
    worker2.operation_lock = asyncio.Lock()
    worker2.client = FakeClient(inverted, {"charge": False, "discharge": True})
    worker2._refresh_unlocked = types.MethodType(refresh, worker2)
    result = await worker2.control("charge", False)
    assert result["verified"] is True
    assert inverted.value["charge_mosfet_on"] is False
    assert inverted.encodings[("BATTERY 2", "charge")] is False
    assert worker2.client.commands == [(0xDA, False), (0xDA, True)]
    await worker2.control("charge", True)
    assert inverted.value["charge_mosfet_on"] is True
    assert worker2.client.commands[-1] == (0xDA, False)
    print("Per-device inverted MOS encoding detection and reuse: OK")

    # Regression for v1.4.22: a previously learned mapping must not cause the
    # same ineffective payload to be sent twice. The retry remains Charge-only.
    stale = FakeService()
    stale.encodings[("BATTERY 3", "charge")] = True
    worker3 = BatteryWorker(stale, "BATTERY 3", 2)
    worker3.operation_lock = asyncio.Lock()
    worker3.client = FakeClient(stale, {"charge": False, "discharge": True})
    worker3._refresh_unlocked = types.MethodType(refresh, worker3)
    await worker3.control("charge", False)
    assert stale.value["charge_mosfet_on"] is False
    assert stale.value["discharge_mosfet_on"] is True
    assert worker3.client.commands == [(0xDA, False), (0xDA, True)]
    assert all(command == 0xDA for command, _value in worker3.client.commands)
    print("Stale learned Charge encoding retries the opposite payload without touching Discharge: OK")


if __name__ == "__main__":
    asyncio.run(main())
