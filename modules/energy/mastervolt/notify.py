"""Phone notifications through Pushover (https://pushover.net/api): "Chargers switched to float" when Float protection
starts, and "Shore power ON" / "Shore power OFF" when shore power has been connected or disconnected for 30 s (a flicker
is ignored; the state found after a start is the baseline, not a change). Priority (normal by default, never emergency)
and sound per notification are the user's choice on the Energy settings page.

The on/off switches and the priority and sound are kept in its own small file (data/notifications.json), not in the
settings table, so the settings API stays as it was. The Pushover keys: the shared DRIFTER_DATA/pushover.json (the System
page fills it in), else this module's own data/pushover.json, else the anchor watch's older file
(DRIFTER_DATA/anchor/pushover.json), all {"app_token": "...", "user_key": "..."}; the keys are never logged or returned.
MasterVolt does not import common/, so the sound list here is a copy of common/pushover.py SOUNDS.
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
SWITCH_EVENT = {"float_notification": "float", "shore_notification": "shore"}
EVENTS = {"float": "Chargers switched to float", "shore": "Shore power ON / OFF"}
PREF_DEFAULTS = {"float": {"priority": 0, "sound": ""}, "shore": {"priority": 0, "sound": ""}}
PRIORITIES = (-2, -1, 0, 1)      # Lowest, Quiet, Normal, High: never emergency
SOUNDS = ["", "pushover", "bike", "bugle", "cashregister", "classical", "cosmic", "falling", "gamelan", "incoming",
          "intermission", "magic", "mechanical", "pianobar", "siren", "spacealarm", "tugboat", "alien", "climb",
          "persistent", "echo", "updown", "vibrate", "none"]


def clean_prefs(body, current: dict | None = None) -> dict:
    """{event: {"priority", "sound"}} checked against PREF_DEFAULTS; missing parts keep `current`. ValueError when wrong."""
    out = {e: {**d, **((current or {}).get(e) or {})} for e, d in PREF_DEFAULTS.items()}
    if body is None:
        return out
    if not isinstance(body, dict):
        raise ValueError("prefs must be an object per notification")
    for e, v in body.items():
        if e not in PREF_DEFAULTS or not isinstance(v, dict):
            raise ValueError(f"unknown notification {e}")
        if "on" in v and not isinstance(v["on"], bool):
            raise ValueError(f"{e}: on must be true or false")
        if "priority" in v:
            pr = v["priority"]
            if isinstance(pr, bool) or not isinstance(pr, (int, float)) or pr != int(pr) or int(pr) not in PRIORITIES:
                raise ValueError(f"{e}: priority must be -2, -1, 0 or 1")
            out[e]["priority"] = int(pr)
        if "sound" in v:
            if v["sound"] not in SOUNDS:
                raise ValueError(f"{e}: unknown sound")
            out[e]["sound"] = v["sound"]
    return out


class Notifier:
    def __init__(self, data_dir: Path, extra_keys: Path | None = None, post=None, shared: Path | None = None):
        self.data_dir = Path(data_dir)
        self.extra_keys = extra_keys
        self.shared = shared
        self.settings_file = self.data_dir / "notifications.json"
        self._post = post or self._http_post        # tests pass their own
        self.last_sent: float | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._shore_state: bool | None = None       # the last stable shore state (None: not known yet)
        self._shore_seen: tuple[bool, float] | None = None  # a new state and since when

    # ---- the switch --------------------------------------------------------------------------------------------
    def _saved(self) -> dict:
        try:
            saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        return saved if isinstance(saved, dict) else {}

    def _switches(self) -> dict:
        saved = self._saved()
        return {key: saved.get(key, True) is not False for key in SWITCHES}  # on unless switched off

    def prefs(self) -> dict:
        try:
            return clean_prefs(self._saved().get("prefs") or {})
        except ValueError:
            return clean_prefs(None)

    def _write(self, values: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(values), encoding="utf-8")
        tmp.replace(self.settings_file)

    def set_prefs(self, body) -> dict:
        """Priority and sound per notification; an "on" in it is the notification's switch."""
        with self._lock:
            new = clean_prefs(body, self.prefs())
            sw = self._switches()
            for key, e in SWITCH_EVENT.items():
                if isinstance((body or {}).get(e), dict) and "on" in body[e]:
                    sw[key] = body[e]["on"]
            self._write({**sw, "prefs": new})
        return new

    def enabled(self, key: str) -> bool:
        return self._switches()[key]

    def float_enabled(self) -> bool:
        return self.enabled("float_notification")

    def set_enabled(self, key: str, enabled: bool) -> None:
        with self._lock:
            self._write({**self._switches(), key: bool(enabled), "prefs": self.prefs()})

    def set_float_enabled(self, enabled: bool) -> None:
        self.set_enabled("float_notification", enabled)

    # ---- the keys ----------------------------------------------------------------------------------------------
    def _key_files(self) -> list[Path]:
        return [*([self.shared] if self.shared else []), self.data_dir / "pushover.json", *([self.extra_keys] if self.extra_keys else [])]

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
        sw = self._switches()
        prefs = {e: {"on": sw[k], **self.prefs()[e]} for k, e in SWITCH_EVENT.items()}
        return {**sw, "prefs": prefs, "events": EVENTS, "pushover_configured": self.keys() is not None, "shore_connected": self._shore_state,
                "last_sent": self.last_sent, "last_error": self.last_error}

    # ---- sending -----------------------------------------------------------------------------------------------
    def test(self, event: str, sound: str | None = None, priority=None) -> dict:
        """A test of one notification with the sound and priority given (else its saved ones), sent once and waited for,
        even when the notification is switched off. ValueError when the choice is wrong or the keys are missing."""
        if event not in EVENTS:
            raise ValueError(f"unknown notification {event}")
        cur = self.prefs()[event]
        pref = clean_prefs({event: {"priority": cur["priority"] if priority is None else priority, "sound": cur["sound"] if sound is None else sound}}, self.prefs())[event]
        keys = self.keys()
        if keys is None:
            raise ValueError("Pushover is not set up (no keys)")
        fields = {"token": keys[0], "user": keys[1], "title": f'Drifter energy: test of "{EVENTS[event]}"', "message": "This is how this notification arrives.",
                  "priority": pref["priority"], "timestamp": int(time.time())}
        if pref["sound"]:
            fields["sound"] = pref["sound"]
        try:
            self._post(fields)
        except urllib.error.HTTPError as exc:
            self.last_error = f"Pushover refused: HTTP {exc.code}"
            raise ValueError(self.last_error) from None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise ValueError(self.last_error) from None
        self.last_sent, self.last_error = time.time(), None
        log.info("Pushover test: %s", EVENTS[event])
        return {"sent": True}

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
        t = threading.Thread(target=self._send, args=(keys, "Drifter energy", message, self.prefs()[SWITCH_EVENT[key]]), daemon=True, name="energy-push")
        t.start()
        if wait:
            t.join()

    def _send(self, keys, title: str, message: str, pref: dict | None = None) -> None:
        pref = pref or {"priority": 0, "sound": ""}
        fields = {"token": keys[0], "user": keys[1], "title": title, "message": message, "priority": pref["priority"], "timestamp": int(time.time())}
        if pref["sound"]:
            fields["sound"] = pref["sound"]
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
