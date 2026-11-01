"""Energy totals over a period (the donut charts), integrated from the full-resolution caches - never from the sampled chart data.

Energy is the time integral of power between consecutive samples. Pairs further apart than the maximum gap (the server or
Bluetooth was down) are left out and reported as missing coverage. Whole finished hours are remembered, so only the two edges
of a requested period are computed; the index behind it is rebuilt only when the caches change.

    sources / consumers : Wh per channel          shore : Wh taken in from shore power (AC)
    batteries : Wh delivered (discharge) and received (charge)
    alarms              : alarm episodes (a run of alarm samples) and alarm samples per battery
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import UTC, datetime

from ..bluetooth.daly_protocol import BATTERY_NAMES
from .chart_cache import ChartCache

MAX_GAP_DASHBOARD = 120.0  # seconds; longer gaps (server down) are not integrated
MAX_GAP_BMS = 180.0  # seconds; longer gaps (Bluetooth down) are not integrated
SOURCE_CHANNELS = ("charger_house", "alternator", "solar")
CONSUMER_CHANNELS = ("inverter", "charger_start", "charger_bow", "engine_ecu", "alternator_field", "other_dc")
SHORE_CHANNEL = len(SOURCE_CHANNELS) + len(
    CONSUMER_CHANNELS
)  # shore power intake (AC): the last channel, kept out of the DC source and consumer lists
CHANNELS = SHORE_CHANNEL + 1
FINISHED_HOUR_MARGIN = 600  # seconds: an hour is remembered once it is this long over (late samples)


def parse_utc(value) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("start and end must be ISO 8601 timestamps") from None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def battery_watts(point):
    """Pack power from the sum of the cell voltages (more exact than the pack voltage) times the current."""
    cells = point.get("cells") or []
    voltage = sum(cells) / 1000 if len(cells) >= 2 and all(isinstance(cell, (int, float)) for cell in cells) else point.get("voltage")
    current = point.get("current")
    return voltage * current if isinstance(voltage, (int, float)) and isinstance(current, (int, float)) else None


def channel_vector(point) -> list[float]:
    """Ten non-negative channel powers: 3 DC sources (charger house, alternator, solar), 6 DC consumers, and the shore power intake."""
    out = []
    for field, count in (("source_power", len(SOURCE_CHANNELS)), ("load_power", len(CONSUMER_CHANNELS))):
        values = point.get(field) or []
        out.extend(max(0.0, float(values[index] or 0.0)) if index < len(values) else 0.0 for index in range(count))
    out.append(max(0.0, float(point.get("shore_power") or 0.0)))
    return out


class EnergyTotals:
    def __init__(self, cache: ChartCache):
        self.cache = cache
        self._index_cache = None

    def _index(self) -> dict:
        """Timestamp arrays, battery power and alarm indexes over the full-resolution caches; hourly totals live inside it."""
        dash, bms = self.cache.dashboard, self.cache.bms
        signature = (
            len(dash),
            dash[0]["id"] if dash else 0,
            dash[-1]["id"] if dash else 0,
            len(bms),
            bms[0]["id"] if bms else 0,
            bms[-1]["id"] if bms else 0,
        )
        if self._index_cache and self._index_cache["signature"] == signature:
            return self._index_cache
        stamp = lambda point: datetime.fromisoformat(point["captured_at"]).timestamp()  # noqa: E731
        timed = sorted(((stamp(point), point) for point in dash), key=lambda item: item[0])
        index = {
            "signature": signature,
            "dash_t": [t for t, _ in timed],
            "dash": [point for _, point in timed],
            "battery": {},
            "alarm_samples": {},
            "alarm_starts": {},
            "hours": {},
        }
        for name in BATTERY_NAMES:
            items = sorted(((stamp(point), point) for point in bms if point.get("battery") == name), key=lambda item: item[0])
            index["battery"][name] = {"t": [t for t, _ in items], "w": [battery_watts(point) for _, point in items]}
            samples, starts, previous = [], [], False
            for t, point in items:
                active = bool(point.get("alarms"))
                if active:
                    samples.append(t)
                    if not previous:
                        starts.append(t)
                previous = active
            index["alarm_samples"][name], index["alarm_starts"][name] = samples, starts
        latest = [index["dash_t"][-1]] if index["dash_t"] else []
        latest += [data["t"][-1] for data in index["battery"].values() if data["t"]]
        index["latest"] = max(latest, default=0.0)
        self._index_cache = index
        return index

    def _raw_energy(self, index, a: float, b: float):
        """Energy of every sample pair whose first sample lies in [a, b) (so parts add up exactly).
        Returns (channel Wh x9, dashboard covered seconds, {battery: [out Wh, in Wh, covered s]})."""
        times, points = index["dash_t"], index["dash"]
        low, high = bisect_left(times, a), min(bisect_left(times, b), len(points) - 1)
        energy, covered = [0.0] * CHANNELS, 0.0
        if low < high:
            previous = channel_vector(points[low])
            for i in range(low, high):
                following = channel_vector(points[i + 1])
                dt = times[i + 1] - times[i]
                if 0 < dt <= MAX_GAP_DASHBOARD:
                    covered += dt
                    factor = dt / 7200.0
                    for k in range(CHANNELS):
                        energy[k] += (previous[k] + following[k]) * factor
                previous = following
        batteries = {}
        for name in BATTERY_NAMES:
            data = index["battery"][name]
            bt, bw = data["t"], data["w"]
            out = into = cover = 0.0
            first, last = bisect_left(bt, a), min(bisect_left(bt, b), len(bt) - 1)
            for i in range(first, last):
                w1, w2, dt = bw[i], bw[i + 1], bt[i + 1] - bt[i]
                if 0 < dt <= MAX_GAP_BMS and w1 is not None and w2 is not None:
                    cover += dt
                    power = (w1 + w2) / 2
                    if power >= 0:
                        into += power * dt / 3600
                    else:
                        out += -power * dt / 3600
            batteries[name] = [out, into, cover]
        return energy, covered, batteries

    def _hour_energy(self, index, hour: int):
        """Hourly totals are remembered once the hour is finished (10 minutes of margin for late samples)."""
        if hour in index["hours"]:
            return index["hours"][hour]
        result = self._raw_energy(index, hour * 3600.0, (hour + 1) * 3600.0)
        if (hour + 1) * 3600.0 <= index["latest"] - FINISHED_HOUR_MARGIN:
            index["hours"][hour] = result
        return result

    def contributions(self, start, end) -> dict:
        first, last = parse_utc(start), parse_utc(end)
        if last <= first:
            raise ValueError("end must be after start")
        with self.cache.lock:
            if not self.cache.loaded:
                self.cache.refresh()
            index = self._index()
        a, b = first.timestamp(), last.timestamp()
        h0, h1 = math.ceil(a / 3600), math.floor(b / 3600)
        if h1 > h0:
            parts = [
                self._raw_energy(index, a, h0 * 3600.0),
                *(self._hour_energy(index, hour) for hour in range(h0, h1)),
                self._raw_energy(index, h1 * 3600.0, b),
            ]
        else:
            parts = [self._raw_energy(index, a, b)]
        energy = [sum(part[0][k] for part in parts) for k in range(CHANNELS)]
        covered = sum(part[1] for part in parts)

        def rows(keys, values):
            return [
                {"key": key, "wh": wh, "avg_w": wh / (covered / 3600) if covered else 0.0} for key, wh in zip(keys, values, strict=False)
            ]  # noqa: E731

        batteries, alarms = [], []
        for name in BATTERY_NAMES:
            out = sum(part[2][name][0] for part in parts)
            into = sum(part[2][name][1] for part in parts)
            cover = sum(part[2][name][2] for part in parts)
            batteries.append(
                {
                    "key": name,
                    "discharge_wh": out,
                    "charge_wh": into,
                    "covered_seconds": cover,
                    "avg_discharge_w": out / (cover / 3600) if cover else 0.0,
                }
            )
            count = lambda times: bisect_left(times, b) - bisect_left(times, a)  # noqa: E731
            alarms.append({"key": name, "episodes": count(index["alarm_starts"][name]), "samples": count(index["alarm_samples"][name])})
        return {
            "start": first.isoformat(),
            "end": last.isoformat(),
            "span_seconds": b - a,
            "sources": rows(SOURCE_CHANNELS, energy[:3]),
            "shore": rows(("shore",), energy[SHORE_CHANNEL : SHORE_CHANNEL + 1])[0],
            "sources_covered_seconds": covered,
            "consumers": rows(CONSUMER_CHANNELS, energy[3:SHORE_CHANNEL]),
            "consumers_covered_seconds": covered,
            "batteries": batteries,
            "alarms": alarms,
        }
