"""Phone notifications through Pushover (https://pushover.net/api), priority normal: "Chargers switched to float" when Float
protection starts, and "Shore power ON" / "Shore power OFF" when shore power has been connected or disconnected for 30 s
(a flicker is ignored; the state found after a start is the baseline, not a change).

The on/off switches are kept in its own small file (data/notifications.json), not in the settings table, so the settings
API stays as it was. The Pushover keys are this module's own data/pushover.json, or else the anchor watch's file
(DRIFTER_DATA/anchor/pushover.json), both {"app_token": "...", "user_key": "..."}; the keys are never logged or returned.
Sending runs in its own thread: a slow or absent internet link never delays the 3 s Float loop.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__

log = logging.getLogger("mastervolt")
API = "https://api.pushover.net/1/messages.json"
KEY_RE = re.compile(r"^[A-Za-z0-9]{30}$")
FLOAT_MESSAGE = "Chargers switched to float"
SHORE_STABLE_SECONDS = 30
SWITCHES = ("float_notification", "shore_notification")


class Notifier:
    def __init__(self, data_dir: Path, extra_keys: Path | None = None, post=None):
        self.data_dir = Path(data_dir)
        self.extra_keys = extra_keys
        self.settings_file = self.data_dir / "notifications.json"
        self._post = post or self._http_post        # tests pass their own
        self.last_sent: float | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._shore_state: bool | None = None       # the last stable shore state (None: not known yet)
        self._shore_seen: tuple[bool, float] | None = None  # a new state and since when

    # ---- the switch --------------------------------------------------------------------------------------------
    def _switches(self) -> dict:
        try:
            saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        return {key: saved.get(key, True) is not False for key in SWITCHES}  # on unless switched off

    def enabled(self, key: str) -> bool:
        return self._switches()[key]

    def float_enabled(self) -> bool:
        return self.enabled("float_notification")

    def set_enabled(self, key: str, enabled: bool) -> None:
        with self._lock:
            values = {**self._switches(), key: bool(enabled)}
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.settings_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(values), encoding="utf-8")
            tmp.replace(self.settings_file)

    def set_float_enabled(self, enabled: bool) -> None:
        self.set_enabled("float_notification", enabled)

    # ---- the keys ----------------------------------------------------------------------------------------------
    def _key_files(self) -> list[Path]:
        return [self.data_dir / "pushover.json", *([self.extra_keys] if self.extra_keys else [])]

    def keys(self) -> tuple[str, str] | None:
        for path in self._key_files():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            token, user = str(d.get("app_token", "")).strip(), str(d.get("user_key", "")).strip()
            if KEY_RE.match(token) and KEY_RE.match(user):
                return token, user
        return None

    def status(self) -> dict:
        return {**self._switches(), "pushover_configured": self.keys() is not None, "shore_connected": self._shore_state,
                "last_sent": self.last_sent, "last_error": self.last_error}

    # ---- sending -----------------------------------------------------------------------------------------------
    def float_started(self, wait: bool = False) -> None:
        """Float protection just latched. Sends the notification when it is switched on and the keys are there."""
        self._notify("float_notification", FLOAT_MESSAGE, wait)

    def shore_seen(self, connected, now: float | None = None, wait: bool = False) -> None:
        """One reading of shore power (every 10 s, from the history recorder). A new state counts once it has lasted
        SHORE_STABLE_SECONDS; the first stable state is the baseline. An unknown reading (None) changes nothing."""
        if connected is None:
            return
        connected, now = bool(connected), time.time() if now is None else now
        if connected == self._shore_state:
            self._shore_seen = None
            return
        if self._shore_seen is None or self._shore_seen[0] != connected:
            self._shore_seen = (connected, now)
        if now - self._shore_seen[1] < SHORE_STABLE_SECONDS:
            return
        was, self._shore_state, self._shore_seen = self._shore_state, connected, None
        if was is not None:
            self._notify("shore_notification", f"Shore power {'ON' if connected else 'OFF'}", wait)

    def _notify(self, key: str, message: str, wait: bool) -> None:
        if not self.enabled(key):
            return
        keys = self.keys()
        if keys is None:
            self.last_error = "Pushover is not set up (no pushover.json)"
            return
        t = threading.Thread(target=self._send, args=(keys, "Drifter energy", message), daemon=True, name="energy-push")
        t.start()
        if wait:
            t.join()

    def _send(self, keys, title: str, message: str) -> None:
        fields = {"token": keys[0], "user": keys[1], "title": title, "message": message, "priority": 0, "timestamp": int(time.time())}
        for delay in (0, 5, 15, 45):
            time.sleep(delay)
            try:
                self._post(fields)
                self.last_sent, self.last_error = time.time(), None
                log.info("Pushover: %s", message)
                return
            except urllib.error.HTTPError as exc:
                self.last_error = f"Pushover refused: HTTP {exc.code}"
                if exc.code < 500:
                    break                             # a wrong key: retrying will not help
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
        log.warning("Pushover notification failed: %s", self.last_error)

    @staticmethod
    def _http_post(fields: dict) -> None:
        req = urllib.request.Request(API, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                     headers={"User-Agent": f"Drifter-Energy/{__version__}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
