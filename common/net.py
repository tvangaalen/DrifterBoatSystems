"""Network checks shared by every stdlib/Flask server of the boat: LAN-only binding, DNS rebinding, same origin."""
from __future__ import annotations

import ipaddress, socket
from urllib.parse import urlsplit


def is_lan(addr) -> bool:
    """Loopback or a private (RFC 1918) LAN address; never all interfaces, link-local or a public address."""
    try: ip = ipaddress.ip_address(str(addr).strip())
    except ValueError: return False
    return ip.is_loopback or (ip.is_private and not ip.is_unspecified and not ip.is_link_local)


def check_bind(addr: str, what: str = "bind") -> str:
    """Stops the program unless `addr` is localhost or a private LAN address: these servers have no login."""
    if not is_lan(addr):
        raise SystemExit(f"{what} {addr}: only localhost or a private LAN address (10.x, 172.16-31.x, 192.168.x) is allowed")
    return str(addr).strip()


def request_host(host_header: str) -> str:
    """The host name of a Host header, without port or IPv6 brackets, lower case."""
    h = (host_header or "").strip().lower()
    return h[1:h.find("]")] if h.startswith("[") else h.rsplit(":", 1)[0]


def host_allowed(host_header: str, extra=()) -> bool:
    """IP literals, localhost, this PC's own name (also .local) and configured names; anything else may be DNS rebinding."""
    h = request_host(host_header)
    if not h: return False
    try: ipaddress.ip_address(h); return True
    except ValueError: pass
    own = socket.gethostname().lower()
    return h in {"localhost", own, own + ".local", *(str(x).lower() for x in extra or ())}


def same_origin(origin: str | None, host_header: str | None) -> bool:
    """True without an Origin header (not a browser page) or when it names the host the request was sent to."""
    return not origin or urlsplit(origin).netloc.lower() == (host_header or "").strip().lower()
