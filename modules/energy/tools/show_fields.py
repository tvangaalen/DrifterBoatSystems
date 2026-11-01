"""Print the MasterBus fields and control mappings the application uses right now (taken from the code, not from a copy).

    py -m tools.show_fields

Run it before the first start after changing any control code: `engine_ecu` must show `verified True`, address 3AE394,
field 43 (see docs/hardware-notes.md, "Engine ECU power"). It does not touch the hardware.
"""

from __future__ import annotations

from mastervolt.config import PATHS
from mastervolt.masterbus.controls import load_control_maps
from mastervolt.masterbus.registry import DEVICE_INFO
from mastervolt.masterbus.service import POLLED_FIELDS


def main():
    print("Polled measurement fields (mastervolt/masterbus/service.py: POLLED_FIELDS)")
    print("-" * 78)
    for addr, fields in POLLED_FIELDS.items():
        print(f"  {DEVICE_INFO[addr]['name']:<20} [{addr:06X}]  fields {', '.join(str(f) for f in fields)}")
    print("\nControl mappings (control_maps.json)")
    print("-" * 78)
    for name, config in load_control_maps(PATHS.control_maps_file).items():
        print(name)
        if config is None:
            print("  None")
            continue
        for key in ("verified", "address", "field", "name", "protocol", "type", "commit_field"):
            print(f"  {key:<13}: {config.get(key)}")
        print()
    print("Documentation of every field and formula: docs/VERIFIED_FIELD_MAP.txt and docs/hardware-notes.md")


if __name__ == "__main__":
    main()
