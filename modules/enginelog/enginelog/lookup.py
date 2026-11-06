"""Country and the nearest marina for a position, from OpenStreetMap: Nominatim (reverse geocoding, the country) and
Overpass (leisure=marina within 15 km). Only on request, when a new fuel entry is opened: one lookup per entry, well within
both services' usage policies; answers are cached per ~100 m. Without internet the fields stay empty and are typed in.
A generic client name is sent (never personal data)."""
from __future__ import annotations

import json, math, threading, urllib.parse, urllib.request

from enginelog import VERSION

AGENT = f"DrifterBoatSystems-EngineLog/{VERSION} (https://github.com/tvangaalen/DrifterBoatSystems)"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
OVERPASS = "https://overpass-api.de/api/interpreter"
RADIUS_M = 15000


def _get(url: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read())


def distance_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dp, dl = math.radians(lat1), math.radians(lat2), math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


class Lookup:
    def __init__(self, get=_get):
        self.get, self.cache, self.lock = get, {}, threading.Lock()

    def country(self, lat: float, lon: float) -> str:
        d = self.get(f"{NOMINATIM}?{urllib.parse.urlencode({'lat': lat, 'lon': lon, 'format': 'jsonv2', 'zoom': 3, 'accept-language': 'en'})}")
        return str((d.get("address") or {}).get("country") or "")

    def marina(self, lat: float, lon: float) -> tuple[str, float | None]:
        q = f'[out:json][timeout:20];(nwr["leisure"="marina"](around:{RADIUS_M},{lat},{lon}););out center tags;'
        d = self.get(f"{OVERPASS}?{urllib.parse.urlencode({'data': q})}")
        best = None
        for el in d.get("elements") or []:
            tags, c = el.get("tags") or {}, el.get("center") or el
            name = tags.get("name:en") or tags.get("name")
            if not name or c.get("lat") is None: continue
            dist = distance_m(lat, lon, c["lat"], c["lon"])
            if best is None or dist < best[1]: best = (name, dist)
        return (best[0], round(best[1])) if best else ("", None)

    def place(self, lat: float, lon: float) -> dict:
        key = (round(lat, 3), round(lon, 3))
        with self.lock:
            if key in self.cache: return self.cache[key]
        out, errors = {"country": "", "marina": "", "marina_distance_m": None}, []
        try: out["country"] = self.country(lat, lon)
        except Exception as e: errors.append(f"country: {type(e).__name__}")
        try: out["marina"], out["marina_distance_m"] = self.marina(lat, lon)
        except Exception as e: errors.append(f"marina: {type(e).__name__}")
        out["error"] = "; ".join(errors) or None
        if not errors:
            with self.lock: self.cache[key] = out
        return out
