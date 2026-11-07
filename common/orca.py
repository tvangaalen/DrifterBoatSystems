"""Reading the Orca Core 2's sensor stream (read-only), for the modules other than the anchor watch.

The Core sends text unescaped (2026-10-12: an AIS destination "IBIZA\\FORMENTERA" made a message invalid JSON), so every
message is parsed with `parse_message`; the anchor watch keeps the same function in its own orca_reader.py. Only GETs
and listening: never send anything on the WebSocket, never call the app's write endpoints (PUT /v1/sources,
POST :9001/imu/calibration, /v1/sync, port 8090).
"""
from __future__ import annotations

import json, re

SENSORS_URL = "ws://{host}:8089/v1/sensors/delta?interval={ms}&ns={ns}&enableUnknownSources"
_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def parse_message(raw):
    """json.loads, tolerating raw backslashes in text the Core passes through unescaped (valid escapes are kept)."""
    try: return json.loads(raw)
    except json.JSONDecodeError as e:
        if "escape" not in e.msg: raise
        return json.loads(_ESCAPE.sub(lambda m: m[0] if m[1] else "\\\\", raw))
