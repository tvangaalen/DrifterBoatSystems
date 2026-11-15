"""Clock texts: always the 24-hour clock, never the locale's default (no AM/PM).

On Windows a process reads the time zone once, when it starts: after the zone is changed in Windows' settings (on
2026-11-13, from UTC+1 to UTC+2) a server that kept running wrote its log and its messages an hour off. `follow_windows_tz`
watches Windows' zone and lets the C runtime read it again when it changes."""
from __future__ import annotations

import ctypes, logging, sys, threading, time

HM, HMS, STAMP = "%H:%M", "%H:%M:%S", "%Y-%m-%d %H:%M:%S"


def hm(t: float | None = None) -> str: return time.strftime(HM, time.localtime(t))
def hms(t: float | None = None) -> str: return time.strftime(HMS, time.localtime(t))
def stamp(t: float | None = None) -> str: return time.strftime(STAMP, time.localtime(t))


TZ_CHECK_S = 30
_follow = threading.Lock(); _following = False


def _windows_zone() -> bytes:
    """Windows' current zone (bias, names and daylight rules) as bytes, to see when it changes."""
    buf = ctypes.create_string_buffer(512)   # DYNAMIC_TIME_ZONE_INFORMATION is 432 bytes
    if ctypes.windll.kernel32.GetDynamicTimeZoneInformation(buf) == 0xFFFFFFFF: return b""
    return buf.raw


def refresh_if_changed(last: bytes, zone=None, tzset=None) -> bytes:
    """When Windows' zone differs from `last`, have the C runtime (Python's time.localtime) read it again."""
    now = (zone or _windows_zone)()
    if now and last and now != last:
        (tzset or ctypes.cdll.ucrtbase._tzset)()
        logging.getLogger(__name__).info("Windows time zone changed: local time is now %s", stamp())
    return now or last


def follow_windows_tz() -> None:
    """Once per process, on Windows: a daemon thread that checks the zone every TZ_CHECK_S seconds."""
    global _following
    if sys.platform != "win32": return
    with _follow:
        if _following: return
        _following = True

    def run():
        last = b""
        while True:
            try: last = refresh_if_changed(last)
            except Exception: logging.getLogger(__name__).exception("time zone check failed")
            time.sleep(TZ_CHECK_S)
    threading.Thread(target=run, name="tz-follow", daemon=True).start()
