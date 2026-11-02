"""The startup checks: runtime, library, configuration, network, the washer's identity and one authenticated read.
They never print or export the MIoT token."""
from __future__ import annotations

import socket, sys, time

from washer import EXPECTED_MODEL
from washer.device import MIIO_IMPORT_ERROR


def valid_ipv4(value) -> bool:
    try: socket.inet_aton(value); return value.count(".") == 3
    except Exception: return False


def udp_handshake(ip: str, timeout: float = 2.0) -> bool:
    """The MIoT hello on UDP 54321; needs no token."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(bytes.fromhex("21310020" + "ff" * 28), (ip, 54321)); data, addr = s.recvfrom(1024)
        return len(data) >= 32 and addr[0] == ip
    finally: s.close()


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return "127.0.0.1"


def summary(result: dict) -> tuple[str, str]:
    if result["ok"] and result["warning_count"] == 0: return "All systems ready", "ok"
    if result["ok"]: return f"Ready with {result['warning_count']} warning(s)", "warn"
    return f"{result['critical_count']} startup issue(s) found", "bad"


class Diagnostics:
    def __init__(self, washer, timings: dict, handshake=udp_handshake, pc_ip=local_ip):
        self.washer, self.timings, self.handshake, self.pc_ip = washer, timings, handshake, pc_ip
        self.last = None

    def _timed(self, name, func, *args):
        started = time.perf_counter()
        try: return func(*args), int((time.perf_counter() - started) * 1000)
        finally: self.timings[name] = int((time.perf_counter() - started) * 1000)

    def run(self) -> dict:
        w = self.washer; w.reload(); checks = []                # re-read the configuration every time

        def add(name, ok, detail, severity="critical"):
            checks.append({"name": name, "ok": bool(ok), "detail": str(detail), "severity": severity})

        add("Python runtime", sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}")
        add("python-miio", MIIO_IMPORT_ERROR is None, "MIoT library loaded" if MIIO_IMPORT_ERROR is None else MIIO_IMPORT_ERROR)
        add("Configuration file", w.config_error is None and w.config_path.exists(), w.config_error or str(w.config_path))
        ip_ok = bool(w.ip and valid_ipv4(w.ip)); add("Washer IP", ip_ok, w.ip or "Missing")
        token_ok = bool(w.token and len(w.token) == 32 and all(c in "0123456789abcdefABCDEF" for c in w.token))
        add("MIoT token", token_ok, "32-character token configured" if token_ok else "Missing or invalid token")
        pc_ip = self.pc_ip(); pc_ok = pc_ip != "127.0.0.1"
        if w.expected_pc_ip:
            add("Windows PC IP", pc_ok and pc_ip == w.expected_pc_ip, f"{pc_ip} (expected {w.expected_pc_ip})", "warning" if pc_ok else "critical")
        else: add("Windows PC network", pc_ok, pc_ip)
        if ip_ok:
            try:
                ok, ms = self._timed("UDP handshake", self.handshake, w.ip)
                add("Washer network", ok, f"UDP 54321 response from {w.ip} · {ms} ms" if ok else f"No UDP response · {ms} ms")
            except Exception as exc: add("Washer network", False, f"No response: {exc}")
        else: add("Washer network", False, "Cannot test without a valid washer IP")
        if w.device is not None and token_ok:
            try:
                info, ms = self._timed("Device info", w.info)
                w.model = getattr(info, "model", None); w.firmware = getattr(info, "firmware_version", None) or getattr(info, "firmware", None)
                detail = f"{w.model or 'Unknown model'} · firmware {w.firmware} · {ms} ms" if w.firmware else f"{w.model or 'Unknown model'} · {ms} ms"
                add("Washer identity", w.model == EXPECTED_MODEL, detail)
                status, ms = self._timed("MIoT read", w.read_all)
                add("MIoT communication", True, f"Authenticated read OK · {status.get('power_text')} · {status.get('status_text')} · {ms} ms")
            except Exception as exc: add("MIoT communication", False, str(exc))
        else: add("MIoT communication", False, "Not tested because token/library is unavailable")
        critical = [c for c in checks if not c["ok"] and c["severity"] == "critical"]
        warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
        self.last = {"checks": checks, "ok": not critical, "critical_count": len(critical), "warning_count": len(warnings), "pc_ip": pc_ip}
        return self.last
