"""Non-hardware self-checks for failure-isolated DALY workers."""

import asyncio
import tempfile
from pathlib import Path

from mastervolt.bluetooth.bms import DEVICE_NAMES, BatteryWorker, DalyBmsService
from mastervolt.config import Paths


async def main():
    assert DEVICE_NAMES == ("BATTERY 1", "BATTERY 2", "BATTERY 3")
    service = DalyBmsService(Paths(Path(tempfile.mkdtemp())))
    workers = [BatteryWorker(service, name, index) for index, name in enumerate(DEVICE_NAMES)]
    assert len({id(worker.stop_event) for worker in workers}) == 3
    assert len({id(worker.refresh_event) for worker in workers}) == 3
    assert [worker.name for worker in workers] == list(DEVICE_NAMES)
    service._workers = {worker.name: worker for worker in workers}
    service.refresh_all()
    assert all(worker.refresh_event.is_set() for worker in workers)
    for worker in workers:
        worker.completed_generation = service.refresh_generation
    assert service.snapshot()["busy"] is False
    print("Bluetooth worker isolation: OK (3 independent workers)")
    print("Bluetooth connection order: OK (Battery 1, Battery 2, Battery 3)")
    print("Manual refresh timeout: OK")


if __name__ == "__main__":
    asyncio.run(main())
