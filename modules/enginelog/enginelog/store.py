"""The engine log in one JSON file: {"fuel": [...], "maintenance": [...]}, newest first.

A fuel fill: date (YYYY-MM-DD), engine hours, litres, amount paid (optional), the position (lat/lon, optional), country and
marina (text, optional); fills of 1.0.0 had a time, which is read as its date. A maintenance entry: date (YYYY-MM-DD), engine hours (optional) and text. Every entry has a 12-hex id. The file is written to a temporary
file and renamed, so a power cut never leaves half a log; positions stay on the boat PC (never in the repository).
"""
from __future__ import annotations

import json, math, re, secrets, threading
from datetime import date, datetime
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{12}$")
KINDS = ("fuel", "maintenance")
SETTINGS = {"tank_capacity_l": None}     # the fuel tank's capacity in litres (None: not set)


def _num(value, name: str, lo: float, hi: float, required: bool = True) -> float | None:
    if value is None or value == "":
        if required: raise ValueError(f"{name} is missing")
        return None
    if isinstance(value, bool): raise ValueError(f"{name} must be a number")
    try: v = float(value)
    except (TypeError, ValueError): raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(v) or not lo <= v <= hi: raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v


def _text(value, name: str, limit: int, required: bool = False) -> str:
    v = " ".join(str(value or "").split()) if name != "Text" else str(value or "").strip()
    if required and not v: raise ValueError(f"{name} is missing")
    if len(v) > limit: raise ValueError(f"{name} may be at most {limit} characters")
    return v


def clean_fuel(d: dict) -> dict:
    try: day = date.fromisoformat(str(d.get("date") or str(d.get("time") or "")[:10]))
    except ValueError: raise ValueError("Date must be like 2026-11-06") from None
    lat, lon = _num(d.get("lat"), "Latitude", -90, 90, False), _num(d.get("lon"), "Longitude", -180, 180, False)
    if (lat is None) != (lon is None): raise ValueError("A position needs both latitude and longitude")
    return {"date": day.isoformat(), "engine_hours": _num(d.get("engine_hours"), "Engine hours", 0, 100000),
            "litres": _num(d.get("litres"), "Litres", 0.1, 5000), "amount": _num(d.get("amount"), "Amount", 0, 100000, False), "lat": lat, "lon": lon,
            "country": _text(d.get("country"), "Country", 60), "marina": _text(d.get("marina"), "Marina", 100)}


def clean_maintenance(d: dict) -> dict:
    try: day = date.fromisoformat(str(d.get("date") or ""))
    except ValueError: raise ValueError("Date must be like 2026-11-06") from None
    return {"date": day.isoformat(), "engine_hours": _num(d.get("engine_hours"), "Engine hours", 0, 100000, False),
            "text": _text(d.get("text"), "Text", 2000, True)}


CLEAN = {"fuel": clean_fuel, "maintenance": clean_maintenance}
ORDER = {"fuel": lambda e: (e["date"], e.get("created", "")), "maintenance": lambda e: (e["date"], e.get("created", ""))}


class Store:
    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try: d = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError: d = {}
        out = {k: list(d.get(k) or []) for k in KINDS}
        for e in out["fuel"]:     # 1.0.0 kept a time: only the date matters
            if "time" in e: e["date"] = e.pop("time")[:10]
            e.setdefault("amount", None)
        out["settings"] = {**SETTINGS, **{k: v for k, v in (d.get("settings") or {}).items() if k in SETTINGS}}
        return out

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _sort(self, kind: str) -> None:
        self.data[kind].sort(key=lambda e: ORDER[kind](e), reverse=True)

    def all(self) -> dict:
        with self.lock: return {k: [dict(e) for e in self.data[k]] for k in KINDS}

    def settings(self) -> dict:
        with self.lock: return dict(self.data["settings"])

    def set_settings(self, body: dict) -> dict:
        cap = _num(body.get("tank_capacity_l"), "Fuel tank capacity", 1, 10000, False)
        with self.lock:
            self.data["settings"]["tank_capacity_l"] = cap; self._save()
            return dict(self.data["settings"])

    def _check_hours(self, entry: dict, skip: str | None = None) -> None:
        """The engine hours are the meter's running total: never fewer than at an earlier fill, never more than at a later one."""
        t, h = entry["date"], entry["engine_hours"]
        for e in self.data["fuel"]:
            if e["id"] == skip: continue
            if e["date"] < t and e["engine_hours"] > h:
                raise ValueError(f"Engine hours: at least {e['engine_hours']:g} h, the meter showed that at the fill of {e['date']}")
            if e["date"] > t and e["engine_hours"] < h:
                raise ValueError(f"Engine hours: at most {e['engine_hours']:g} h, the meter showed that at the later fill of {e['date']}")

    def create(self, kind: str, body: dict) -> dict:
        entry = {"id": secrets.token_hex(6), **CLEAN[kind](body), "created": datetime.now().astimezone().isoformat(timespec="seconds")}
        with self.lock:
            if kind == "fuel": self._check_hours(entry)
            self.data[kind].append(entry); self._sort(kind); self._save()
        return dict(entry)

    def _find(self, kind: str, entry_id: str) -> int:
        for i, e in enumerate(self.data[kind]):
            if e["id"] == entry_id: return i
        raise KeyError(entry_id)

    def update(self, kind: str, entry_id: str, body: dict) -> dict:
        clean = CLEAN[kind](body)
        with self.lock:
            i = self._find(kind, entry_id)
            if kind == "fuel": self._check_hours(clean, skip=entry_id)
            self.data[kind][i] = {**self.data[kind][i], **clean, "changed": datetime.now().astimezone().isoformat(timespec="seconds")}
            entry = dict(self.data[kind][i]); self._sort(kind); self._save()
        return entry

    def delete(self, kind: str, entry_id: str) -> None:
        with self.lock:
            del self.data[kind][self._find(kind, entry_id)]; self._save()


def fuel_stats(fuel: list[dict]) -> dict:
    """The tiles: the last fill, how long ago, and the average use in litres per engine hour (the litres of every fill
    after the first, over the engine hours between the first and the last fill)."""
    if not fuel: return {"last_litres": None, "last_date": None, "last_hours": None, "avg_l_per_h": None, "fills": 0, "litres_total": 0.0, "amount_total": 0.0}
    by_time = sorted(fuel, key=lambda e: (e["date"], e["engine_hours"]))
    span = by_time[-1]["engine_hours"] - by_time[0]["engine_hours"]
    used = sum(e["litres"] for e in by_time[1:])
    return {"last_litres": by_time[-1]["litres"], "last_date": by_time[-1]["date"], "last_hours": by_time[-1]["engine_hours"],
            "amount_total": round(sum(e.get("amount") or 0 for e in fuel), 2),
            "avg_l_per_h": round(used / span, 2) if len(by_time) > 1 and span > 0 else None, "fills": len(fuel),
            "litres_total": round(sum(e["litres"] for e in fuel), 1)}
