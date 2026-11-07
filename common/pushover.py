"""Posting to the Pushover API (https://pushover.net/api), and the shared keys. Each module keeps its own queue and retry
policy: the anchor watch's alarms must never wait for BoatGuard's notifications or the other way round.

The keys: one file for every system, `<DRIFTER_DATA>\\pushover.json` = {"app_token": "...", "user_key": "..."} (the
Pushover application "Drifter boat systems"), written by the System page through the gateway and never committed (it
lives outside the repository). A module finds it next to its own data folder (`shared_file`), and only when that folder
really is inside DRIFTER_DATA, so a test or scratch instance never reaches the real keys. A module's own older key file
is the fallback until the shared one is filled in.

Each notification's priority and sound are the module's own settings; `SOUNDS` and `PRIORITIES` are the choices.
"""
from __future__ import annotations

import json, os, re, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.pushover.net/1"
KEY_RE = re.compile(r"^[A-Za-z0-9]{30}$")    # app tokens and user keys are 30 letters/digits
SHARED_NAME = "pushover.json"
# Pushover's built-in sounds; "" = the sound chosen in the Pushover app.
SOUNDS = ["", "pushover", "bike", "bugle", "cashregister", "classical", "cosmic", "falling", "gamelan", "incoming",
          "intermission", "magic", "mechanical", "pianobar", "siren", "spacealarm", "tugboat", "alien", "climb",
          "persistent", "echo", "updown", "vibrate", "none"]
# 2 (emergency) repeats until acknowledged in the app; each module decides which of its notifications may use it.
PRIORITIES = {-2: "Lowest", -1: "Quiet", 0: "Normal", 1: "High", 2: "Emergency"}


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


# ---------------------------------------------------------------- the keys

def shared_file(own_dir: Path | str | None) -> Path | None:
    """<DRIFTER_DATA>\\pushover.json for a module whose data folder is `own_dir` (DRIFTER_DATA\\<module>); None when
    DRIFTER_DATA is not set or own_dir is not directly inside it (a test or scratch instance)."""
    data = os.environ.get("DRIFTER_DATA", "").strip()
    if not (data and own_dir): return None
    try:
        if Path(own_dir).resolve().parent != Path(data).resolve(): return None
    except OSError: return None
    return Path(data) / SHARED_NAME


def read_keys(path: Path | str | None) -> dict | None:
    """{"token", "user"} from a key file in either layout ({"app_token", "user_key"} or {"token", "user"}), or None."""
    if not path: return None
    try: d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError): return None
    if not isinstance(d, dict): return None
    tok = str(d.get("app_token") or d.get("token") or "").strip(); usr = str(d.get("user_key") or d.get("user") or "").strip()
    return {"token": tok, "user": usr} if KEY_RE.match(tok) and KEY_RE.match(usr) else None


def find_keys(*paths) -> tuple[dict, Path] | None:
    """The first usable keys of `paths` (the shared file first), with the file they came from."""
    for p in paths:
        k = read_keys(p)
        if k: return k, Path(p)
    return None


def write_keys(path: Path | str, app_token: str | None, user_key: str | None) -> dict:
    """Saves the shared keys (an empty or None value keeps what is there); atomic. Returns the masked status."""
    path = Path(path)
    try: cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): cur = {}
    if not isinstance(cur, dict): cur = {}
    for name, v in (("app_token", app_token), ("user_key", user_key)):
        v = str(v or "").strip()
        if not v: continue
        if not KEY_RE.match(v): raise ValueError(f"{'API token' if name == 'app_token' else 'User key'} must be the 30 letters and digits Pushover shows")
        cur[name] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8"); tmp.replace(path)
    return masked(path)


def masked(path: Path | str | None) -> dict:
    """What the page may see of a key file: whether each key is there and its last 4 characters, never the key."""
    try: d = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError): d = {}
    if not isinstance(d, dict): d = {}
    out = {}
    for name in ("app_token", "user_key"):
        v = str(d.get(name) or "").strip()
        out[name] = ("…" + v[-4:]) if KEY_RE.match(v) else ""
    return {**out, "configured": bool(out["app_token"] and out["user_key"])}


# ---------------------------------------------------------------- priority and sound per notification

def clean_prefs(body, defaults: dict, current: dict | None = None, emergency=()) -> dict:
    """Validates {event: {"on": bool, "priority": p, "sound": s}} against `defaults` (same shape); events in `emergency`
    may use priority 2. Missing events or fields keep `current` (else the default). Raises ValueError with a readable text."""
    out = {e: {**d, **((current or {}).get(e) or {})} for e, d in defaults.items()}
    if body is None: return out
    if not isinstance(body, dict): raise ValueError("notifications must be an object per notification")
    for e, v in body.items():
        if e not in defaults: raise ValueError(f"unknown notification {e}")
        if not isinstance(v, dict): raise ValueError(f"{e}: priority and sound expected")
        if "priority" in v:
            p = v["priority"]
            if isinstance(p, bool) or not isinstance(p, (int, float)) or p != int(p) or int(p) not in PRIORITIES:
                raise ValueError(f"{e}: priority must be -2, -1, 0, 1 or 2")
            if int(p) == 2 and e not in emergency: raise ValueError(f"{e}: emergency priority is not allowed for this notification")
            out[e]["priority"] = int(p)
        if "sound" in v:
            if v["sound"] not in SOUNDS: raise ValueError(f"{e}: unknown sound {v['sound']!r}")
            out[e]["sound"] = v["sound"]
        if "on" in v:
            if not isinstance(v["on"], bool): raise ValueError(f"{e}: on must be true or false")
            out[e]["on"] = v["on"]
    return out
