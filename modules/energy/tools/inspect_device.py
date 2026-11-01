"""Read-only inspection of MasterBus devices: what fields they expose, their values and which ones look like on/off controls.

    py -m tools.inspect_device snapshot --device 3AE394           # every field of a device with protocol, type, writability and value
    py -m tools.inspect_device candidates                         # writable on/off-looking fields of the Mass Chargers and the Yanmar ECU
    py -m tools.inspect_device writable                           # writable fields (and dropdown options) of the Solar controller and the Alpha Pro
    py -m tools.inspect_device controls                           # the fields around the verified Mass Charger / ECU controls

A MasterBus field number is never guessed (CLAUDE.md): use this to find out what a device reports, then verify it against the
hardware or a MasterAdjust capture before using it. No writes are issued.
"""

from __future__ import annotations

import argparse

from mastervolt.masterbus.discovery import ControlDiscovery
from mastervolt.masterbus.registry import ALTERNATOR, CHARGER_BOW, CHARGER_START, DEVICE_INFO, SOLAR, YANMAR
from tools.common import masterbus, number

CONTROL_DEVICES = (("charger_start", CHARGER_START), ("charger_bow", CHARGER_BOW), ("engine_ecu", YANMAR))
CONTROL_FIELDS = {"charger_start": range(60, 68), "charger_bow": range(60, 68), "engine_ecu": range(54, 59)}


def read(service, addr, field):
    try:
        return service.io.read_field(addr, field, 0.8)
    except Exception:
        return None


def snapshot(service, args):
    addr = int(args.device, 16)
    max_index = args.max_index if args.max_index is not None else int(DEVICE_INFO.get(addr, {}).get("max_index", 255))
    if not 0 <= max_index <= 255:
        raise SystemExit("--max-index must be between 0 and 255")
    print(f"Device  : {DEVICE_INFO.get(addr, {}).get('name', 'Unknown device')} [{addr:06X}]\nScan    : fields 0..{max_index}\n")
    fields = ControlDiscovery(service.io).fields(addr, max_index)
    if not fields:
        raise SystemExit(f"No field metadata discovered for {addr:06X}")
    print(f"{len(fields)} fields discovered\n IDX  PROTO  VIZ             RW   VALUE              NAME\n" + "-" * 78)
    for field in fields:
        value = read(service, addr, field["index"])
        rw = "RW" if field.get("writable") else "RO"
        print(
            f"{field['index']:4d}  {field['protocol']:<5}  {field.get('viz') or '?':<14}  {rw:<2}   {number(value):<18} {field.get('name') or ''}"
        )


def candidates(service, args):
    discovery = ControlDiscovery(service.io)
    for key, addr in CONTROL_DEVICES:
        info = DEVICE_INFO[addr]
        print("=" * 72 + f"\n{key}: {info['name']} [{addr:06X}]")
        found = discovery.control_candidates(discovery.fields(addr, info["max_index"]))
        if not found:
            print("No safe-looking writable ON/OFF candidate found.")
        for c in found[:10]:
            print(
                f"  protocol={c['protocol']:<4} field={c['index']:>3} viz={c['viz']!s:<13} writable={c['writable']} score={c['score']:>2} name={c['name']!r}"
            )


def writable(service, args):
    discovery = ControlDiscovery(service.io)
    for addr in (SOLAR, ALTERNATOR):
        info = DEVICE_INFO[addr]
        print("=" * 88 + f"\n{info['name']} [{addr:06X}]\n" + "=" * 88)
        fields = [f for f in discovery.fields(addr, info["max_index"]) if f.get("writable")]
        if not fields:
            print("No writable fields discovered.\n")
        for f in fields:
            index = int(f["index"])
            print(f"{index:>3}  {f.get('viz', '')!s:<13} value={number(read(service, addr, index)):<12} name={f.get('name', '')!r}")
            if str(f.get("viz", "")).lower() == "dropdown":
                try:
                    options = discovery.list_options(addr, index, f.get("protocol", "btm1"))
                except Exception as exc:
                    print(f"     options: error: {exc}")
                else:
                    if options:
                        print("     options: " + ", ".join(f"{o.get('index')}={o.get('label')!r}" for o in options))
        print()


def controls(service, args):
    discovery = ControlDiscovery(service.io)
    for key, addr in CONTROL_DEVICES:
        info = DEVICE_INFO[addr]
        indices = CONTROL_FIELDS[key]
        print("=" * 78 + f"\n{key}: {info['name']} [{addr:06X}]\nInspecting fields {min(indices)}..{max(indices)}\n")
        by_index = {f["index"]: f for f in discovery.fields(addr, info["max_index"])}
        for index in indices:
            f, value = by_index.get(index), read(service, addr, index)
            if f is None and value is None:
                print(f"  {index:>3}: no metadata / no readable value")
                continue
            f = f or {}
            print(
                f"  {index:>3}  protocol={f.get('protocol', ''):<4} viz={f.get('viz')!s:<13} writable={f.get('writable')!s:<5} value={number(value):<10} name={f.get('name', '')!r}"
            )
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="all fields of one device")
    snap.add_argument("--device", required=True, help="6-digit hexadecimal MasterBus address")
    snap.add_argument("--max-index", type=int, default=None, help="highest field number to scan (default: the device's known maximum)")
    for name, help_text in (
        ("candidates", "on/off-looking writable fields"),
        ("writable", "writable fields of Solar and Alpha Pro"),
        ("controls", "fields around the verified controls"),
    ):
        sub.add_parser(name, help=help_text)
    args = parser.parse_args(argv)
    with masterbus() as service:
        {"snapshot": snapshot, "candidates": candidates, "writable": writable, "controls": controls}[args.command](service, args)
        print("\nNo writes were issued.")


if __name__ == "__main__":
    main()
