"""WRITES to a device: switch it to the opposite state, verify, then restore it and verify again.

    py -m tools.reversible_write_test charger_start            # dry run: shows what would happen, sends nothing
    py -m tools.reversible_write_test engine_ecu --confirm-write

Devices: charger_start, charger_bow (Mass Charger On/Standby, field 64), engine_ecu (Yanmar field 43), solar (SCM field 12).
It uses the same verified control code as the web app (`DeviceControls.set_device_control`, with read-back). Stop the web server
first. Switching the Engine ECU or a charger on a live boat has real effects: do this only when that is safe.
"""

from __future__ import annotations

import argparse
import time

from mastervolt.masterbus.controls import device_address
from tools.common import masterbus, number

DEVICES = ("charger_start", "charger_bow", "engine_ecu", "solar")


def state(value) -> str:
    return "?" if value is None else ("ON" if float(value) >= 0.5 else "OFF/STANDBY")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("device", choices=DEVICES)
    parser.add_argument("--confirm-write", action="store_true", help="required: without it nothing is written")
    args = parser.parse_args(argv)
    with masterbus() as service:
        config = service.controls.control_maps[args.device]
        addr, field = device_address(config), int(config["field"])
        original = service.io.read_field(addr, field, 0.8)
        target = 0.0 if original >= 0.5 else 1.0
        print(
            f"Device   : {args.device}\nField    : {field} {config.get('name')}\nOriginal : {state(original)} ({number(original)})\nTest     : {state(target)} ({number(target)})\n"
        )
        if not args.confirm_write:
            print("DRY RUN ONLY. No write sent. Re-run with --confirm-write to test and automatically restore.")
            return
        for label, wanted in (("Writing", target), ("Restoring", original)):
            print(f"{label:<9}: {state(wanted)}")
            print("Result   :", service.controls.set_device_control(args.device, wanted >= 0.5))
            time.sleep(0.5)
            actual = service.io.read_field(addr, field, 0.8)
            print(f"Readback : {state(actual)} ({number(actual)})\n")
            # Solar ON may legitimately fall straight back to OFF without PV (night); everything else must match.
            if abs(actual - wanted) > 0.05 and not (args.device == "solar" and wanted >= 0.5):
                raise SystemExit(f"VERIFY FAILED: expected {number(wanted)}, got {number(actual)}")
        print("Restore  : OK")


if __name__ == "__main__":
    main()
