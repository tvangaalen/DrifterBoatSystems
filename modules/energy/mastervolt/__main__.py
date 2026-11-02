"""`python -m mastervolt`: the server as Drifter Boat Systems runs it (drifterd starts it with DRIFTER_DATA and
DRIFTER_TOKEN): plain HTTP on 127.0.0.1:8000 under the Drifter module contract (`api/contract.py`). The phone reaches
it through the Drifter app, whose gateway serves HTTPS, so MasterVolt needs no server certificate of its own here.

MASTERVOLT_BIND may name another address, but only localhost or a private (RFC 1918) one: the API has no login.
This is the only way the server is started (the old stand-alone launchers are gone since 3.0.1).
"""

from __future__ import annotations

import ipaddress
import os
import sys

import uvicorn

from .api.contract import add_contract
from .app import create_app

PORT = 8000


def bind_address() -> str:
    host = os.environ.get("MASTERVOLT_BIND", "").strip() or "127.0.0.1"
    try:
        address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
    except ValueError:
        sys.exit(f"MASTERVOLT_BIND={host!r} is not an IP address")
    if not (address.is_loopback or (address.is_private and not address.is_link_local and not address.is_unspecified)):
        sys.exit(f"MASTERVOLT_BIND={host}: only localhost or a private LAN address (the API has no login)")
    return host


def main() -> None:
    host = bind_address()
    # timeout_graceful_shutdown: a browser keep-alive connection must not keep the server from exiting (CLAUDE.md).
    # No access log: the gateway asks every few seconds, which made ~42,000 lines (3 MB) a day in the console log and hid
    # the real messages; the application's own log (logs\server.log) is unchanged.
    uvicorn.run(add_contract(create_app()), host=host, port=PORT, timeout_graceful_shutdown=5, access_log=False)


if __name__ == "__main__":
    main()
