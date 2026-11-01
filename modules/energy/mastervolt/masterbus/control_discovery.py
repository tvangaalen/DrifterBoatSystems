import time

VIZ = {
    1: "Float",
    2: "GrayFloat",
    3: "DropDown",
    4: "Eventable",
    5: "CheckBox",
    6: "Text",
    7: "Time",
    8: "Date",
    9: "DeviceList",
    10: "EventCommand",
    11: "SwitchVariant",
}


class ControlDiscovery:
    def __init__(self, service):
        self.s = service

    def _request(self, can_id, payload, predicate, timeout=0.35, retries=2):
        for _ in range(retries + 1):
            with self.s.io_lock:
                self.s.bus.drain()
                self.s.bus.send_frame(can_id, payload)

                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    for frame in self.s.bus.read_frames(60):
                        if predicate(frame):
                            return frame

        return None

    def _meta(self, addr, idx, opcode, proto):
        if proto == "btm1":
            wire_addr = (addr | 0x800000) & 0xFFFFFF
            req_class, resp_class = 0x18, 0x08
        else:
            wire_addr = addr
            req_class, resp_class = 0x1C, 0x0C

        payload = bytes(
            [
                opcode,
                idx & 0xFF,
                (idx >> 8) & 0xFF,
            ]
        )

        frame = self._request(
            (req_class << 24) | wire_addr,
            payload,
            lambda f: (
                f.can_class == resp_class
                and f.address == wire_addr
                and len(f.data) >= 5
                and f.data[0] == opcode
                and f.data[1] == (idx & 0xFF)
                and f.data[2] == ((idx >> 8) & 0xFF)
            ),
        )

        return None if frame is None else frame.data

    def _meta_with_extra(self, addr, idx, opcode, proto, extra_byte):
        if proto == "btm1":
            wire_addr = (addr | 0x800000) & 0xFFFFFF
            req_class, resp_class = 0x18, 0x08
        else:
            wire_addr = addr
            req_class, resp_class = 0x1C, 0x0C

        payload = bytes(
            [
                opcode,
                idx & 0xFF,
                (idx >> 8) & 0xFF,
                extra_byte & 0xFF,
            ]
        )

        frame = self._request(
            (req_class << 24) | wire_addr,
            payload,
            lambda f: (
                f.can_class == resp_class
                and f.address == wire_addr
                and len(f.data) >= 6
                and f.data[0] == opcode
                and f.data[1] == (idx & 0xFF)
                and f.data[2] == ((idx >> 8) & 0xFF)
                and f.data[3] == (extra_byte & 0xFF)
            ),
        )

        return None if frame is None else frame.data

    def _string(self, addr, sid):
        out = bytearray()

        for seq in range(64):
            payload = bytes(
                [
                    0x30,
                    sid & 0xFF,
                    (sid >> 8) & 0xFF,
                    seq,
                ]
            )

            frame = self._request(
                (0x07 << 24) | addr,
                payload,
                lambda f, payload=payload: (
                    f.can_class == 0x06 and f.address == addr and len(f.data) >= 4 and bytes(f.data[:4]) == payload
                ),
            )

            if frame is None:
                break

            chunk = bytes(frame.data[4:8])
            z = chunk.find(b"\x00")

            if z >= 0:
                out.extend(chunk[:z])
                break

            out.extend(chunk)

        return out.decode("latin-1", errors="replace").strip()

    def fields(self, addr, max_index):
        results = []

        for proto in ("btm1", "btm3"):
            any_found = False

            for idx in range(max_index + 1):
                viz = self._meta(addr, idx, 0x02, proto)
                writable = self._meta(addr, idx, 0x0B, proto)
                name_meta = self._meta(addr, idx, 0x28, proto)

                if viz is None and writable is None and name_meta is None:
                    continue

                any_found = True

                name = ""
                if name_meta and len(name_meta) >= 6:
                    sid = int.from_bytes(name_meta[4:6], "little")
                    if sid:
                        name = self._string(addr, sid)

                results.append(
                    {
                        "protocol": proto,
                        "index": idx,
                        "name": name,
                        "viz_code": None if not viz or len(viz) < 5 else viz[4],
                        "viz": (None if not viz or len(viz) < 5 else VIZ.get(viz[4], f"0x{viz[4]:02X}")),
                        "writable": (None if not writable or len(writable) < 5 else writable[4] != 0),
                    }
                )

            if any_found:
                break

        return results

    def list_options(self, addr, field_index, protocol="btm1"):
        """
        Decode MasterBus dropdown/list option labels.

        0x07: maximum / option-count metadata
        0x26: string id for an individual option
        """
        maximum = self._meta(addr, field_index, 0x07, protocol)

        if not maximum or len(maximum) < 8:
            return []

        import struct

        raw_max = struct.unpack("<f", bytes(maximum[4:8]))[0]
        count_hint = max(0, min(int(round(raw_max)), 32))

        options = []
        misses = 0

        # Probe a little beyond the advertised maximum because devices differ
        # on whether 0x07 represents count or maximum option index.
        for option_index in range(0, count_hint + 2):
            data = self._meta_with_extra(
                addr,
                field_index,
                0x26,
                protocol,
                option_index,
            )

            if not data or len(data) < 6:
                misses += 1
                if misses >= 2 and options:
                    break
                continue

            sid = int.from_bytes(data[4:6], "little")
            label = "" if sid == 0 else self._string(addr, sid)

            options.append(
                {
                    "index": option_index,
                    "string_id": sid,
                    "label": label,
                }
            )
            misses = 0

        return options

    @staticmethod
    def control_candidates(fields):
        positive = (
            "on",
            "off",
            "enable",
            "enabled",
            "activate",
            "active",
            "switch",
            "charger",
            "charge",
            "power",
        )

        negative = (
            "alarm",
            "reset",
            "test",
            "finish",
            "setup",
            "save",
            "language",
            "limit",
            "voltage",
            "current",
            "temperature",
        )

        out = []

        for field in fields:
            if not field.get("writable"):
                continue

            if field.get("viz") not in (
                "CheckBox",
                "Eventable",
                "SwitchVariant",
                "DropDown",
            ):
                continue

            name = (field.get("name") or "").lower().strip()

            score = sum(3 for word in positive if word in name) - sum(5 for word in negative if word in name)

            if name in ("on", "enabled", "enable", "power"):
                score += 10

            if score > 0:
                item = dict(field)
                item["score"] = score
                out.append(item)

        return sorted(
            out,
            key=lambda x: (-x["score"], x["index"]),
        )
