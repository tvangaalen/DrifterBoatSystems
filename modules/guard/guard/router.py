"""Presence from the UDR Max 5G's live Wi-Fi station tables (read-only SSH, `wlanconfig <ap> list sta`)."""
from __future__ import annotations

import re, subprocess
from pathlib import Path

MAC_RE = re.compile(r"^([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.M)
# Lists every associated station on every SSID of every radio; the UDR uses Qualcomm `wlanconfig`.
STATION_CMD = 'for i in $(ls /sys/class/net | grep -E "^wifi[0-9]+ap[0-9]+$"); do wlanconfig $i list sta 2>/dev/null; done; echo BOATGUARD_OK'
UNREACHABLE = ("connection refused", "timed out", "no route to host", "network is unreachable", "could not resolve",
               "connection reset", "connection closed", "broken pipe", "host is down")
AUTH = ("permission denied", "host key verification failed", "remote host identification has changed", "no such file")


class RouterError(Exception):
    """The router's Wi-Fi clients could not be read. kind: "unreachable" (offline or restarting),
    "auth" (the router refused the SSH key: needs action) or "other"."""
    def __init__(self, kind: str, detail: str):
        super().__init__(detail); self.kind, self.detail = kind, detail


def classify_ssh_error(stderr: str) -> RouterError:
    lines = [ln for ln in stderr.splitlines() if ln.strip() and "post-quantum" not in ln and "openssh.com/pq" not in ln
             and "upgraded" not in ln.lower() and "vulnerable" not in ln.lower()]
    detail = lines[-1].strip() if lines else "no output"
    low = stderr.lower()
    if any(s in low for s in AUTH): return RouterError("auth", detail)
    if any(s in low for s in UNREACHABLE) or not lines: return RouterError("unreachable", detail)
    return RouterError("other", detail)


def stations(cfg: dict) -> set[str]:
    """MAC addresses currently associated to the router's Wi-Fi. Raises RouterError if the router can't be read."""
    r = cfg["router"]
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", f"ConnectTimeout={r.get('timeout_s', 10)}",
           "-i", str(Path(r["key"]).expanduser()), f"{r['user']}@{r['host']}", STATION_CMD]
    try: res = subprocess.run(cmd, capture_output=True, text=True, timeout=r.get("timeout_s", 10) + 20,
                              stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired: raise RouterError("unreachable", "no answer within the time limit") from None
    except OSError as e: raise RouterError("other", f"ssh could not start: {e}") from None
    if "BOATGUARD_OK" not in res.stdout: raise classify_ssh_error(res.stderr)
    return {m.lower() for m in MAC_RE.findall(res.stdout)}
