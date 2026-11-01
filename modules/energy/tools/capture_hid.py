"""Listen to the MasterBus USB Link's raw HID input reports for a while and print them (nothing is transmitted).

    py -m tools.capture_hid [--seconds 30]

For a capture of what MasterAdjust sends use USBPcap instead (docs/hardware-notes.md, "Repeating the capture"). The Link can only
be held by one program: stop the web server first.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

from mastervolt.masterbus.usb import PID, VID


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    import hid

    devices = hid.enumerate(VID, PID)
    if not devices:
        raise SystemExit("MasterBus USB Link not found")
    info = devices[0]
    print(
        f"Opening: {info.get('product_string')}  serial {info.get('serial_number')}\nListening for {args.seconds:g} s. NO DATA WILL BE TRANSMITTED.\n"
    )
    device = hid.device()
    device.open_path(info["path"])
    device.set_nonblocking(False)
    count, end = 0, time.time() + args.seconds
    try:
        while time.time() < end:
            data = device.read(256, 1000)
            if data:
                count += 1
                print(
                    f"{count:5d}  {datetime.now().strftime('%H:%M:%S.%f')[:-3]}  len={len(data):3d}  {' '.join(f'{b:02X}' for b in data)}"
                )
    finally:
        device.close()
    print(f"\nCapture finished. Received {count} HID reports.")


if __name__ == "__main__":
    main()
