"""Distances and positions on the sphere."""
import math
from anchor.settings import EARTH


# ---------------------------------------------------------------- geometry (flat earth is fine for < a few km)


def dist_bearing_m(lat1, lon1, lat2, lon2):
    """Metres and true bearing (deg) from point 1 to point 2."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * EARTH * math.asin(min(1, math.sqrt(a)))
    b = math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
    return d, b


def offset(lat, lon, bearing_deg, metres):
    b = math.radians(bearing_deg)
    return (lat + math.degrees(metres * math.cos(b) / EARTH),
            lon + math.degrees(metres * math.sin(b) / (EARTH * math.cos(math.radians(lat)))))


def num(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
