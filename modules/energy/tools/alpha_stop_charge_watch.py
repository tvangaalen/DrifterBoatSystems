"""Passive watcher for the Alpha Pro *Stop charge* field: change it in MasterView and see what changes on the bus.

    py -m tools.alpha_stop_charge_watch

Read-only. Press Ctrl+C to stop. Stop the web server first.
"""

from __future__ import annotations

import time

from mastervolt.masterbus.registry import ALTERNATOR
from tools.common import masterbus

FIELDS = {5: "Charger state", 39: "Stop charge", 40: "Stop charge companion"}


def main():
    with masterbus() as service:
        print(
            "Alpha Pro passive control watcher\nNo writes are issued.\nChange 'Stop charge' once in MasterView and watch for changes.\nPress Ctrl+C to stop.\n"
        )
        last = {}
        try:
            while True:
                stamp = time.strftime("%H:%M:%S")
                for index, name in FIELDS.items():
                    try:
                        value = service.io.read_field(ALTERNATOR, index, 0.7)
                    except Exception:
                        value = None
                    if last.get(index, object()) != value:
                        print(f"{stamp}  field {index:>2}  {name:<22} = {value}")
                        last[index] = value
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nStopped. No writes were issued.")


if __name__ == "__main__":
    main()
