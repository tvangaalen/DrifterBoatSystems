"""Clock texts: always the 24-hour clock, never the locale's default (no AM/PM)."""
from __future__ import annotations

import time

HM, HMS, STAMP = "%H:%M", "%H:%M:%S", "%Y-%m-%d %H:%M:%S"


def hm(t: float | None = None) -> str: return time.strftime(HM, time.localtime(t))
def hms(t: float | None = None) -> str: return time.strftime(HMS, time.localtime(t))
def stamp(t: float | None = None) -> str: return time.strftime(STAMP, time.localtime(t))
