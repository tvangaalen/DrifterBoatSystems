"""Phone notifications through Pushover. Sent from a background thread with retries, so a slow or unreachable internet
connection never holds up the poll loop or the camera."""
from __future__ import annotations

import logging, threading, time
from pathlib import Path

from common import pushover
from guard.camera import load_json

EMERGENCY_RETRY_S, EMERGENCY_EXPIRE_S = 60, 3600
log = logging.getLogger("boatguard")


class Pushover:
    def __init__(self, path: Path):
        self.path = Path(path)                           # {"token": app token, "user": user key}; never logged

    @property
    def configured(self) -> bool:
        k = load_json(self.path, None) or {}
        return bool(k.get("token") and k.get("user"))

    def send(self, title: str, message: str, priority: int = 0, url: str | None = None, wait: bool = False,
             sound: str | None = None, expire: int | None = None) -> bool | None:
        k = load_json(self.path, None) or {}
        if not (k.get("token") and k.get("user")): return None
        data = {"token": k["token"], "user": k["user"], "title": title, "message": message, "priority": priority,
                "timestamp": int(time.time())}            # shows when it happened, even if delivery was delayed
        if url: data.update(url=url, url_title="Open BoatGuard")
        if sound: data["sound"] = sound                   # empty: the sound chosen in the Pushover app
        if priority == 2: data.update(retry=EMERGENCY_RETRY_S, expire=expire or EMERGENCY_EXPIRE_S)   # required by Pushover

        def post() -> bool:
            for attempt in range(5):
                try: pushover.post("messages.json", data, "BoatGuard"); log.info("notification sent: %s", title); return True
                except pushover.PushoverError as e:
                    if e.code < 500:                      # wrong key/token: retrying won't help
                        log.error("notification rejected by Pushover (%d): %s", e.code, e.detail); return False
                    err = e
                except Exception as e: err = e
                time.sleep(min(60, 5 * 2 ** attempt))
            log.error("notification not sent after 5 tries: %s (%s)", title, err); return False

        if wait: return post()
        threading.Thread(target=post, daemon=True, name="pushover").start(); return None
