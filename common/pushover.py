"""Posting to the Pushover API (https://pushover.net/api). Each module keeps its own key file, queue and retry policy:
the anchor watch's alarms must never wait for BoatGuard's notifications or the other way round."""
from __future__ import annotations

import json, re, urllib.error, urllib.parse, urllib.request

API = "https://api.pushover.net/1"
KEY_RE = re.compile(r"^[A-Za-z0-9]{30}$")    # app tokens and user keys are 30 letters/digits


class PushoverError(Exception):
    """Pushover answered with an HTTP error. 4xx: bad key or request, retrying will not help."""
    def __init__(self, code: int, detail: str):
        super().__init__(f"Pushover refused: HTTP {code} {detail}"); self.code, self.detail = code, detail


def post(path: str, fields: dict, agent: str, timeout: float = 15) -> dict:
    """POST `fields` to API/<path> (e.g. "messages.json"); returns the JSON answer. Network errors are raised as they are."""
    req = urllib.request.Request(f"{API}/{path}", data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"User-Agent": agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: detail = "; ".join(json.loads(e.read()).get("errors", [])) or e.reason
        except Exception: detail = e.reason
        raise PushoverError(e.code, str(detail)) from None
