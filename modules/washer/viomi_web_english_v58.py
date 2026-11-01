from flask import Flask, jsonify, render_template_string, request, send_file, Response
import ipaddress
import socket
import threading
import os
import json
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
try:
    from miio.miot_device import MiotDevice
    MIIO_IMPORT_ERROR = None
except Exception as exc:
    MiotDevice = None
    MIIO_IMPORT_ERROR = str(exc)

# Runtime files (config with the token, schedule): next to the code, or in DRIFTER_DATA\washer when Drifter Boat Systems sets it.
DATA_DIR = Path(os.environ["DRIFTER_DATA"].strip()) / "washer" if os.environ.get("DRIFTER_DATA", "").strip() else Path(__file__).resolve().parent
CONFIG_PATH = DATA_DIR / "viomi_config.json"
EXPECTED_MODEL = "viomi.washer.w1"
CONTROLLER_VERSION = "3.7-v58"
REQUEST_MARKER_HEADER = "X-Viomi-Request"

CONFIG = {}
CONFIG_ERROR = None
WASHER_IP = None
WASHER_TOKEN = None
EXPECTED_PC_IP = None
DEVICE = None
READ_LOCK = threading.Lock()
EVENT_LOG = deque(maxlen=50)
TIMINGS = {}
PROCESS_STARTED_AT = time.time()
LAST_OBSERVED_STATE = None
LAST_CONNECTIVITY = None
ACTUAL_MODEL = None
ACTUAL_FIRMWARE = None
LAST_DIAGNOSTICS = None

SCHEDULE_PATH = DATA_DIR / "viomi_schedule.json"
SCHEDULE_LOCK = threading.Lock()
SCHEDULE_STATE = None
SCHEDULER_STOP = threading.Event()
SCHEDULER_THREAD = None
SCHEDULE_MISSED_GRACE_SECONDS = 60
SCHEDULE_MONITOR_INTERVAL_SECONDS = 3.0
SCHEDULE_LAST_MONITOR_AT = 0.0


def log_event(event, detail="", duration_ms=None):
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "event": str(event),
        "detail": str(detail),
    }
    if duration_ms is not None:
        entry["duration_ms"] = int(duration_ms)
    EVENT_LOG.appendleft(entry)

def timed(name, func, *args, **kwargs):
    started = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        elapsed = int((time.perf_counter() - started) * 1000)
        TIMINGS[name] = elapsed
        return result, elapsed
    except Exception:
        elapsed = int((time.perf_counter() - started) * 1000)
        TIMINGS[name] = elapsed
        raise


def initialize_device():
    global CONFIG, CONFIG_ERROR, WASHER_IP, WASHER_TOKEN, EXPECTED_PC_IP, DEVICE

    CONFIG = {}
    CONFIG_ERROR = None
    DEVICE = None

    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                CONFIG = json.load(f)
        else:
            CONFIG_ERROR = f"Configuration file not found: {CONFIG_PATH.name}"
    except Exception as exc:
        CONFIG_ERROR = f"Configuration file error: {exc}"

    WASHER_IP = os.environ.get("VIOMI_IP") or CONFIG.get("washer_ip") or "192.0.2.10"
    WASHER_TOKEN = os.environ.get("VIOMI_TOKEN") or CONFIG.get("token")
    EXPECTED_PC_IP = CONFIG.get("expected_pc_ip")

    if MiotDevice is not None and WASHER_TOKEN:
        try:
            DEVICE = MiotDevice(WASHER_IP, WASHER_TOKEN)
        except Exception:
            DEVICE = None

initialize_device()

PROPS = {
    "power": (2, 1),
    "status": (2, 2),
    "mode": (2, 3),
    "fault": (2, 4),
    "left_time": (2, 5),
    "temperature": (2, 6),
    "spin": (2, 7),
    "rinses": (2, 9),
    "locked": (3, 1),
}

STATUS_MAP = {
    0: "Standby",
    1: "Standby",
    7: "Washing",
    9: "Rinsing",
    11: "Spinning",
    17: "Finished",
    26: "Paused",
    27: "Stopped / Fault",
}

TEMPERATURE_VALUES = {0, 30, 40, 60, 80}
SPIN_VALUES = {400, 600, 700}
RINSE_VALUES = {1, 2, 3, 4}

PROGRAM_CAPABILITIES = {
    0:  {"temperatures": [40],             "spin": 700, "rinses": [2]},
    16: {"temperatures": [60],             "spin": 700, "rinses": [1, 2, 3, 4]},
    4:  {"temperatures": [0],              "spin": 700, "rinses": [0]},
    13: {"temperatures": [0, 30, 40, 60],  "spin": 700, "rinses": [1, 2, 3, 4]},
    22: {"temperatures": [0],              "spin": 700, "rinses": [1, 2, 3, 4]},
    23: {"temperatures": [80],             "spin": 700, "rinses": [2]},
    29: {"temperatures": [80],             "spin": 700, "rinses": [1, 2, 3, 4]},
    31: {"temperatures": [0, 30, 40],      "spin": 600, "rinses": [1, 2, 3, 4]},
    36: {"temperatures": [0, 30, 40],      "spin": 700, "rinses": [1, 2, 3, 4]},
    37: {"temperatures": [0, 30, 40, 60],  "spin": 700, "rinses": [1, 2, 3, 4]},
    38: {"temperatures": [0, 30, 40],      "spin": 400, "rinses": [1, 2, 3, 4]},
    39: {"temperatures": [80],             "spin": 700, "rinses": [1, 2, 3, 4]},
    40: {"temperatures": [0, 30, 40, 60],  "spin": 700, "rinses": [1, 2, 3, 4]},
}

MODE_MAP = {
    0: "Golden Wash",
    16: "Antibacterial",
    4: "Spin",
    13: "Underwear",
    22: "Rinse + Spin",
    23: "Drum Clean",
    29: "Boil Wash",
    31: "Delicate",
    36: "New Clothes",
    37: "Socks",
    38: "Bra",
    39: "Towel Boil Wash",
    40: "Gloves",
}

app = Flask(__name__)

def require_device():
    if DEVICE is None:
        raise RuntimeError("Washer device is not initialized. Open the startup diagnostics page.")

def read_all():
    require_device()
    params = [{"siid": s, "piid": p} for s, p in PROPS.values()]
    with READ_LOCK:
        raw = DEVICE.send("get_properties", params)

    id_to_key = {(s, p): k for k, (s, p) in PROPS.items()}
    result = {}
    errors = {}

    for item in raw:
        key = id_to_key.get((item.get("siid"), item.get("piid")))
        if not key:
            continue
        if item.get("code", 0) == 0:
            result[key] = item.get("value")
        else:
            result[key] = None
            errors[key] = f"MIoT error {item.get('code')}"

    for key in PROPS:
        result.setdefault(key, None)

    result["power_text"] = "On" if result["power"] is True else "Off" if result["power"] is False else "Unknown"
    result["status_text"] = STATUS_MAP.get(result["status"], f"Code {result['status']}")
    result["mode_text"] = MODE_MAP.get(result["mode"], f"Program code {result['mode']}")
    result["fault_text"] = "No fault" if result["fault"] == 0 else f"Fault code {result['fault']}"
    result["locked_text"] = "Yes" if result["locked"] is True else "No" if result["locked"] is False else "Unknown"
    result["errors"] = errors
    return result

def set_property_direct(siid, piid, value):
    require_device()
    # Use direct MIoT set_properties so numeric zero remains a valid value.
    params = [{"siid": siid, "piid": piid, "value": value}]
    with READ_LOCK:
        reply = DEVICE.send("set_properties", params)

    if not isinstance(reply, list) or not reply:
        raise RuntimeError(f"Unexpected MIoT reply: {reply!r}")

    item = reply[0]
    if item.get("code", 0) != 0:
        raise RuntimeError(f"MIoT error {item.get('code')}")
    return item

def call_action_direct(siid, aiid, params=None):
    require_device()
    with READ_LOCK:
        return DEVICE.call_action_by(siid, aiid, params or [])




def _now_local():
    return datetime.now().astimezone()

def _parse_iso(value):
    return datetime.fromisoformat(value) if value else None

def _save_schedule_locked():
    if SCHEDULE_STATE is None:
        try:
            SCHEDULE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return
    tmp = SCHEDULE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(SCHEDULE_STATE, f, indent=2)
    tmp.replace(SCHEDULE_PATH)

def load_schedule():
    global SCHEDULE_STATE
    with SCHEDULE_LOCK:
        try:
            if SCHEDULE_PATH.exists():
                with SCHEDULE_PATH.open("r", encoding="utf-8") as f:
                    SCHEDULE_STATE = json.load(f)
            else:
                SCHEDULE_STATE = None
        except Exception as exc:
            log_event("SCHEDULE", f"Could not load schedule: {exc}")
            SCHEDULE_STATE = None

def get_schedule_public():
    with SCHEDULE_LOCK:
        if not SCHEDULE_STATE:
            return None
        s = dict(SCHEDULE_STATE)
        s.pop("config", None)
        return s

def cancel_schedule(reason="Cancelled"):
    global SCHEDULE_STATE
    with SCHEDULE_LOCK:
        if SCHEDULE_STATE:
            log_event("SCHEDULE", reason)
        SCHEDULE_STATE = None
        _save_schedule_locked()

def interrupt_active_schedule(reason):
    """Mark an already-started scheduled cycle as deliberately interrupted.

    Terminal interrupted schedules do not block creation of a new schedule.
    """
    global SCHEDULE_STATE
    with SCHEDULE_LOCK:
        if not SCHEDULE_STATE or SCHEDULE_STATE.get("status") not in ("started", "running"):
            return False
        now = _now_local().isoformat(timespec="seconds")
        SCHEDULE_STATE["status"] = "interrupted"
        SCHEDULE_STATE["last_error"] = str(reason)
        SCHEDULE_STATE["interrupted_at"] = now
        SCHEDULE_STATE["updated_at"] = now
        _save_schedule_locked()
    log_event("SCHEDULE INTERRUPTED", reason)
    return True

def _next_clock_time(hhmm, now=None):
    now = now or _now_local()
    try:
        hh, mm = [int(x) for x in hhmm.split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except Exception:
        raise ValueError("Time must be HH:MM")
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target

def create_server_schedule(mode, hhmm):
    global SCHEDULE_STATE

    state = read_all()
    if state.get("power") is not True:
        raise RuntimeError("Washer must be powered on before scheduling")
    if int(state.get("fault") or 0) != 0:
        raise RuntimeError(f"Washer has fault {state.get('fault')}")
    if int(state.get("status") or 0) not in (0, 1, 17):
        raise RuntimeError("Washer must be idle before scheduling")

    duration = int(state.get("left_time") or 0)
    if duration <= 0:
        raise RuntimeError("Washer did not provide a valid program duration")

    now = _now_local()
    if mode == "start":
        start_at = _next_clock_time(hhmm, now)
        finish_at = start_at + timedelta(minutes=duration)
    elif mode == "finish":
        finish_at = _next_clock_time(hhmm, now)
        start_at = finish_at - timedelta(minutes=duration)
        # If today's requested finish time is too close, automatically use tomorrow.
        if start_at <= now:
            finish_at += timedelta(days=1)
            start_at = finish_at - timedelta(minutes=duration)
    else:
        raise ValueError("Schedule mode must be 'start' or 'finish'")

    cap = PROGRAM_CAPABILITIES.get(int(state["mode"]))
    if not cap:
        raise RuntimeError("Unknown program capabilities")

    record = {
        "status": "pending",
        "mode": mode,
        "requested_time": hhmm,
        "created_at": now.isoformat(timespec="seconds"),
        "start_at": start_at.isoformat(timespec="seconds"),
        "finish_at": finish_at.isoformat(timespec="seconds"),
        "expected_duration": duration,
        "program_name": MODE_MAP.get(state["mode"], str(state["mode"])),
        "config": {
            "program": int(state["mode"]),
            "temperature": int(state["temperature"]),
            "spin": int(state["spin"]),
            "rinses": int(state["rinses"]),
        },
        "last_error": "",
    }

    with SCHEDULE_LOCK:
        SCHEDULE_STATE = record
        _save_schedule_locked()

    log_event(
        "SCHEDULE",
        f"{mode.upper()} {hhmm} · start {start_at.strftime('%H:%M')} · "
        f"finish ~{finish_at.strftime('%H:%M')}"
    )
    return get_schedule_public()

def _mark_schedule(status, error="", **fields):
    global SCHEDULE_STATE
    with SCHEDULE_LOCK:
        if not SCHEDULE_STATE:
            return
        SCHEDULE_STATE["status"] = status
        SCHEDULE_STATE["last_error"] = error
        SCHEDULE_STATE.update(fields)
        SCHEDULE_STATE["updated_at"] = _now_local().isoformat(timespec="seconds")
        _save_schedule_locked()

def _apply_scheduled_config(config):
    program = int(config["program"])
    cap = PROGRAM_CAPABILITIES[program]

    set_property_direct(2, 3, program)
    time.sleep(0.8)

    if len(cap["temperatures"]) > 1:
        set_property_direct(2, 6, int(config["temperature"]))
    if len(cap["rinses"]) > 1:
        set_property_direct(2, 9, int(config["rinses"]))

    time.sleep(0.5)

def _ensure_power_on_for_schedule(timeout=8.0):
    """Ensure the washer is awake before restoring the scheduled configuration."""
    state = read_all()
    if state.get("power") is True:
        return state

    set_property_direct(2, 1, True)
    log_event("SCHEDULE POWER ON", "Waking washer before scheduled start")

    deadline = time.monotonic() + timeout
    last_state = state
    while time.monotonic() < deadline:
        time.sleep(0.5)
        last_state = read_all()
        if last_state.get("power") is True:
            # Give the controller a short moment to finish waking before writing settings.
            time.sleep(0.5)
            return last_state

    raise RuntimeError("Washer did not power on for scheduled start")

def execute_due_schedule():
    with SCHEDULE_LOCK:
        if not SCHEDULE_STATE or SCHEDULE_STATE.get("status") != "pending":
            return
        record = json.loads(json.dumps(SCHEDULE_STATE))

    now = _now_local()
    start_at = _parse_iso(record["start_at"])
    if not start_at or now < start_at:
        return

    late_seconds = (now - start_at).total_seconds()
    if late_seconds > SCHEDULE_MISSED_GRACE_SECONDS:
        msg = f"Start time missed by {int(late_seconds)} seconds"
        _mark_schedule("missed", msg)
        log_event("SCHEDULE MISSED", msg)
        return

    # Mark starting first to prevent a second scheduler iteration.
    _mark_schedule("starting")

    try:
        # The washer can auto-power-off while a server-side schedule is waiting.
        # Wake it first, then restore the exact saved settings before Start.
        state = _ensure_power_on_for_schedule()
        if int(state.get("fault") or 0) != 0:
            raise RuntimeError(f"Washer fault {state.get('fault')}")
        if int(state.get("status") or 0) not in (0, 1, 17):
            raise RuntimeError(f"Washer is not idle (status {state.get('status')})")

        _apply_scheduled_config(record["config"])
        call_action_direct(2, 1)
        _mark_schedule(
            "started",
            started_at=_now_local().isoformat(timespec="seconds"),
            run_observed=False,
        )
        log_event("SCHEDULE START", record.get("program_name", "Program"))
    except Exception as exc:
        _mark_schedule("failed", str(exc))
        log_event("SCHEDULE FAILED", str(exc))

def monitor_active_schedule():
    """Track a scheduled cycle from Start through confirmed washer completion."""
    global SCHEDULE_LAST_MONITOR_AT

    now_mono = time.monotonic()
    if now_mono - SCHEDULE_LAST_MONITOR_AT < SCHEDULE_MONITOR_INTERVAL_SECONDS:
        return
    SCHEDULE_LAST_MONITOR_AT = now_mono

    with SCHEDULE_LOCK:
        if not SCHEDULE_STATE or SCHEDULE_STATE.get("status") not in ("started", "running"):
            return
        record = json.loads(json.dumps(SCHEDULE_STATE))

    try:
        state = read_all()
    except Exception as exc:
        # A transient read failure must not lose the schedule lifecycle.
        log_event("SCHEDULE MONITOR", f"Status read failed: {exc}")
        return

    status = int(state.get("status") or 0)
    fault = int(state.get("fault") or 0)

    if fault != 0 or status == 27:
        msg = f"Washer fault {fault or status} during scheduled program"
        _mark_schedule("failed", msg)
        log_event("SCHEDULE FAILED", msg)
        return

    # Confirm that the washer actually entered a cycle before accepting FINISHED.
    # This prevents an old idle/finished state from being mistaken for completion
    # immediately after the Start action was sent.
    if status in (7, 9, 11, 25, 26):
        if record.get("status") != "running" or not record.get("run_observed"):
            observed_at = _now_local().isoformat(timespec="seconds")
            _mark_schedule(
                "running",
                run_observed=True,
                run_observed_at=record.get("run_observed_at") or observed_at,
            )
            log_event("SCHEDULE RUNNING", state_name(status, True))
        return

    if status == 17 and record.get("run_observed"):
        actual_finish = _now_local()
        planned_finish = _parse_iso(record.get("finish_at"))
        detail = f"Actual {actual_finish.strftime('%H:%M')}"
        if planned_finish:
            delta_minutes = int(round((actual_finish - planned_finish).total_seconds() / 60.0))
            if delta_minutes == 0:
                detail += " · on time"
            elif delta_minutes > 0:
                detail += f" · {delta_minutes} min late"
            else:
                detail += f" · {abs(delta_minutes)} min early"
        _mark_schedule(
            "finished",
            actual_finish_at=actual_finish.isoformat(timespec="seconds"),
        )
        log_event("SCHEDULE FINISHED", detail)

def scheduler_loop():
    while not SCHEDULER_STOP.wait(1.0):
        try:
            execute_due_schedule()
            monitor_active_schedule()
        except Exception as exc:
            log_event("SCHEDULER ERROR", str(exc))

def start_scheduler():
    global SCHEDULER_THREAD
    load_schedule()
    if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
        return
    SCHEDULER_THREAD = threading.Thread(
        target=scheduler_loop,
        name="viomi-scheduler",
        daemon=True,
    )
    SCHEDULER_THREAD.start()

def valid_ipv4(value):
    try:
        socket.inet_aton(value)
        return value.count(".") == 3
    except Exception:
        return False

def check_udp_handshake(ip, timeout=2.0):
    """Basic Xiaomi/MIoT UDP 54321 handshake; does not require the token."""
    packet = bytes.fromhex("21310020" + "ff" * 28)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(packet, (ip, 54321))
        data, addr = s.recvfrom(1024)
        return len(data) >= 32 and addr[0] == ip
    finally:
        s.close()


def uptime_text():
    seconds = max(0, int(time.time() - PROCESS_STARTED_AT))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

def state_name(status, power):
    if not power:
        return "OFF"
    return {
        0: "READY",
        1: "READY",
        4: "DELAY",
        7: "WASHING",
        9: "RINSING",
        11: "SPINNING",
        17: "FINISHED",
        25: "WEIGHING",
        26: "PAUSED",
        27: "FAULT",
    }.get(int(status), f"STATUS {status}")

def observe_status(status_data):
    global LAST_OBSERVED_STATE, LAST_CONNECTIVITY
    fault = int(status_data.get("fault") or 0)
    current = "DOOR OPEN" if fault == 3 else state_name(
        status_data.get("status", 0), bool(status_data.get("power"))
    )
    if LAST_CONNECTIVITY is False:
        log_event("CONNECTIVITY", "OFFLINE → ONLINE")
    LAST_CONNECTIVITY = True
    if LAST_OBSERVED_STATE is None:
        LAST_OBSERVED_STATE = current
    elif current != LAST_OBSERVED_STATE:
        log_event("STATE", f"{LAST_OBSERVED_STATE} → {current}")
        LAST_OBSERVED_STATE = current

def observe_offline():
    global LAST_CONNECTIVITY
    if LAST_CONNECTIVITY is not False:
        if LAST_CONNECTIVITY is True:
            log_event("CONNECTIVITY", "ONLINE → OFFLINE")
        else:
            log_event("CONNECTIVITY", "OFFLINE")
    LAST_CONNECTIVITY = False

def run_startup_checks():
    global ACTUAL_MODEL, ACTUAL_FIRMWARE, LAST_DIAGNOSTICS
    # Re-read config every time the diagnostics page is opened/rechecked.
    initialize_device()

    checks = []

    def add(name, ok, detail, severity="critical"):
        checks.append({
            "name": name,
            "ok": bool(ok),
            "detail": str(detail),
            "severity": severity,
        })

    # Runtime
    import sys
    py_ok = sys.version_info >= (3, 10)
    add("Python runtime", py_ok, f"Python {sys.version.split()[0]}")

    add(
        "python-miio",
        MIIO_IMPORT_ERROR is None,
        "MIoT library loaded" if MIIO_IMPORT_ERROR is None else MIIO_IMPORT_ERROR
    )

    # Configuration
    add(
        "Configuration file",
        CONFIG_ERROR is None and CONFIG_PATH.exists(),
        CONFIG_ERROR or str(CONFIG_PATH)
    )

    ip_ok = bool(WASHER_IP and valid_ipv4(WASHER_IP))
    add("Washer IP", ip_ok, WASHER_IP or "Missing")

    token_ok = bool(
        WASHER_TOKEN
        and len(WASHER_TOKEN) == 32
        and all(c in "0123456789abcdefABCDEF" for c in WASHER_TOKEN)
    )
    add(
        "MIoT token",
        token_ok,
        "32-character token configured" if token_ok else "Missing or invalid token"
    )

    # Local PC network
    pc_ip = local_ip()
    pc_ip_ok = pc_ip != "127.0.0.1"
    detail = pc_ip
    if EXPECTED_PC_IP:
        matches = pc_ip == EXPECTED_PC_IP
        add(
            "Windows PC IP",
            pc_ip_ok and matches,
            f"{pc_ip} (expected {EXPECTED_PC_IP})",
            "warning" if pc_ip_ok else "critical"
        )
    else:
        add("Windows PC network", pc_ip_ok, pc_ip)

    # PWA assets: warnings only, controller works without them.
    for filename, label in [
        ("viomi_icon_180.png", "iPhone icon"),
        ("viomi_icon_192.png", "PWA 192px icon"),
        ("viomi_icon_512.png", "PWA 512px icon"),
    ]:
        exists = Path(__file__).with_name(filename).exists()
        add(label, exists, filename if exists else f"{filename} missing", "warning")

    # Washer reachability
    if ip_ok:
        try:
            udp_ok, udp_ms = timed("UDP handshake", check_udp_handshake, WASHER_IP)
            add(
                "Washer network",
                udp_ok,
                (f"UDP 54321 response from {WASHER_IP} · {udp_ms} ms"
                 if udp_ok else f"No UDP response · {udp_ms} ms")
            )
        except Exception as exc:
            add("Washer network", False, f"No response: {exc}")
    else:
        add("Washer network", False, "Cannot test without a valid washer IP")

    # Authenticated MIoT read/model check
    if DEVICE is not None and token_ok:
        try:
            def _get_info():
                with READ_LOCK:
                    return DEVICE.info()
            info, info_ms = timed("Device info", _get_info)
            model = getattr(info, "model", None)
            fw = getattr(info, "firmware_version", None) or getattr(info, "firmware", None)
            ACTUAL_MODEL = model
            ACTUAL_FIRMWARE = fw
            model_ok = model == EXPECTED_MODEL
            detail = f"{model or 'Unknown model'} · {info_ms} ms"
            if fw:
                detail = f"{model or 'Unknown model'} · firmware {fw} · {info_ms} ms"
            add("Washer identity", model_ok, detail)

            # One actual property transaction confirms token + MIoT protocol.
            status, read_ms = timed("MIoT read", read_all)
            add(
                "MIoT communication",
                True,
                f"Authenticated read OK · {status.get('power_text')} · {status.get('status_text')} · {read_ms} ms"
            )
        except Exception as exc:
            add("MIoT communication", False, str(exc))
    else:
        add("MIoT communication", False, "Not tested because token/library is unavailable")

    # Collapse the three PWA icon checks into one compact diagnostics row.
    icon_names = {"iPhone icon", "PWA 192px icon", "PWA 512px icon"}
    icon_checks = [c for c in checks if c["name"] in icon_names]
    if len(icon_checks) == 3:
        checks = [c for c in checks if c["name"] not in icon_names]
        icons_ok = all(c["ok"] for c in icon_checks)
        missing = [c["name"] for c in icon_checks if not c["ok"]]
        checks.insert(6, {
            "name": "App icons",
            "ok": icons_ok,
            "detail": "180px · 192px · 512px" if icons_ok else "Missing: " + ", ".join(missing),
            "severity": "warning",
        })

    critical_failures = [c for c in checks if not c["ok"] and c["severity"] == "critical"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
    result = {
        "checks": checks,
        "ok": not critical_failures,
        "critical_count": len(critical_failures),
        "warning_count": len(warnings),
        "pc_ip": pc_ip,
    }
    LAST_DIAGNOSTICS = result
    return result

STARTUP_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#f4f7fb">
<title>VIOMI Startup Check</title>
<style>
:root {
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --blue:#0f6ee8;
  --blue-2:#2b7bec;
  --blue-soft:#eaf3ff;
  --ink:#12263d;
  --muted:#68798e;
  --bg:#f4f7fb;
  --surface:#ffffff;
  --line:#dbe4ef;
  --green:#28a865;
  --green-soft:#e9f7ef;
  --amber:#b77b00;
  --amber-soft:#fff6dc;
  --red:#c94242;
  --red-soft:#fff0f0;
  --shadow:0 4px 15px rgba(35,58,86,.075);
}
* { box-sizing:border-box; }
body {
  margin:0;
  background:var(--bg);
  color:var(--ink);
  padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom);
}
.wrap { max-width:720px; margin:0 auto; padding:18px 18px 20px; }
.diag-header { display:flex; align-items:center; gap:13px; margin-bottom:16px; }
.diag-app-icon {
  width:52px; height:52px; border-radius:15px; background:#fff; border:1px solid var(--line);
  box-shadow:var(--shadow); display:flex; align-items:center; justify-content:center; overflow:hidden; flex:0 0 auto;
}
.diag-app-icon img { width:42px; height:42px; object-fit:contain; border-radius:10px; }
.diag-copy { min-width:0; }
h1 { margin:0; font-size:25px; line-height:1.06; letter-spacing:-.025em; }
.diag-sub { margin-top:4px; color:var(--muted); font-size:14px; }
.summary {
  margin:0 0 14px; padding:15px 17px; border-radius:16px; text-align:left;
  font-weight:800; font-size:16px; box-shadow:var(--shadow); border:1px solid transparent;
}
.summary.ok { color:#17663d; background:var(--green-soft); border-color:#c9ead8; }
.summary.warn { color:#795400; background:var(--amber-soft); border-color:#f1dfa5; }
.summary.bad { color:#9f3030; background:var(--red-soft); border-color:#f0c8c8; }
.section-title { font-size:14px; font-weight:800; color:var(--ink); margin:17px 2px 8px; }
.checks { display:grid; gap:8px; }
.check {
  display:grid; grid-template-columns:34px minmax(0,1fr); gap:11px; align-items:center;
  background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:11px 13px; box-shadow:var(--shadow);
}
.icon {
  width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:16px; font-weight:800;
}
.ok-row .icon { background:var(--green-soft); color:var(--green); }
.warn-row .icon { background:var(--amber-soft); color:var(--amber); }
.bad-row .icon { background:var(--red-soft); color:var(--red); }
.name { font-size:13px; line-height:1.15; font-weight:800; }
.detail { color:var(--muted); font-size:11px; margin-top:3px; line-height:1.25; overflow-wrap:anywhere; }
.meta {
  display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px;
}
.meta-card {
  background:var(--surface); border:1px solid var(--line); border-radius:13px; padding:10px 11px; box-shadow:var(--shadow);
}
.meta-label { color:var(--muted); font-size:10px; margin-bottom:4px; }
.meta-value { font-size:12px; font-weight:750; overflow-wrap:anywhere; line-height:1.2; }
.log {
  background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:4px 12px;
  box-shadow:var(--shadow); max-height:145px; overflow:auto;
}
.log-row { font-size:10.5px; line-height:1.3; padding:7px 0; border-bottom:1px solid #edf1f6; }
.log-row:last-child { border-bottom:0; }
.actions {
  display:grid; grid-template-columns:.9fr .9fr 1.2fr; gap:9px; margin-top:14px;
  position:sticky; bottom:calc(env(safe-area-inset-bottom) + 4px); padding-top:8px;
  background:linear-gradient(to bottom,rgba(244,247,251,0),var(--bg) 28%);
}
button, a.btn {
  border:0; border-radius:14px; min-height:48px; padding:12px 10px; font-size:14px; font-weight:800;
  text-decoration:none; display:flex; align-items:center; justify-content:center; box-sizing:border-box;
}
.primary { background:linear-gradient(180deg,var(--blue-2),var(--blue)); color:#fff; box-shadow:0 3px 8px rgba(15,110,232,.2); }
.secondary { background:#fff; color:#41546a; border:1px solid #cfd9e5 !important; box-shadow:var(--shadow); }
button:disabled { opacity:.48; }
.note { color:var(--muted); font-size:10px; text-align:center; line-height:1.3; margin-top:7px; }
@media (max-width:520px) {
  .wrap { padding:12px 10px 14px; }
  .diag-app-icon { width:46px; height:46px; border-radius:13px; }
  .diag-app-icon img { width:37px; height:37px; }
  h1 { font-size:21px; }
  .diag-sub { font-size:12px; }
  .summary { padding:12px 13px; font-size:14px; border-radius:13px; }
  .check { padding:9px 10px; grid-template-columns:30px minmax(0,1fr); gap:8px; border-radius:12px; }
  .icon { width:28px; height:28px; font-size:14px; }
  .name { font-size:12px; }
  .detail { font-size:9.5px; }
  .meta { grid-template-columns:1fr 1fr; gap:6px; }
  .actions { gap:6px; }
  button, a.btn { min-height:44px; font-size:12px; border-radius:12px; }
}
</style>
{% if auto_continue %}
<script>
setTimeout(() => { window.location.replace("/app"); }, 3000);
</script>
{% endif %}
</head>
<body>
<div class="wrap">
  <div class="diag-header">
    <div class="diag-app-icon"><img src="/apple-touch-icon.png" alt=""></div>
    <div class="diag-copy">
      <h1>VIOMI Washing Machine</h1>
      <div class="diag-sub">Startup diagnostics</div>
    </div>
  </div>

  <div class="summary {{ summary_class }}">{{ summary_text }}</div>

  <div class="section-title">System checks</div>
  <div class="checks">
  {% for c in checks %}
    <div class="check {{ 'ok-row' if c.ok else ('warn-row' if c.severity == 'warning' else 'bad-row') }}">
      <div class="icon">{{ "✓" if c.ok else ("!" if c.severity == "warning" else "×") }}</div>
      <div>
        <div class="name">{{ c.name }}</div>
        <div class="detail">{{ c.detail }}</div>
      </div>
    </div>
  {% endfor %}
  </div>

  <div class="section-title">Controller details</div>
  <div class="meta">
    <div class="meta-card"><div class="meta-label">Version</div><div class="meta-value">{{ controller_version }}</div></div>
    <div class="meta-card"><div class="meta-label">Uptime</div><div class="meta-value">{{ uptime }}</div></div>
    <div class="meta-card"><div class="meta-label">Washer</div><div class="meta-value">{{ washer_ip }}</div></div>
    <div class="meta-card"><div class="meta-label">PC</div><div class="meta-value">{{ pc_ip }}</div></div>
    <div class="meta-card"><div class="meta-label">Model</div><div class="meta-value">{{ actual_model or "Unknown" }}</div></div>
    <div class="meta-card"><div class="meta-label">Firmware</div><div class="meta-value">{{ actual_firmware or "Unknown" }}</div></div>
  </div>

  <div class="section-title">Recent events</div>
  <div class="log">
    {% if events %}
      {% for e in events %}
      <div class="log-row">{{ e.time }} · <b>{{ e.event }}</b>{% if e.detail %} · {{ e.detail }}{% endif %}{% if e.duration_ms is defined %} · {{ e.duration_ms }} ms{% endif %}</div>
      {% endfor %}
    {% else %}
      <div class="log-row">No events recorded yet.</div>
    {% endif %}
  </div>

  <div class="actions">
    <a class="btn secondary" href="/">Recheck</a>
    <a class="btn secondary" href="/diagnostics/export">Export</a>
    {% if can_continue %}
    <a class="btn primary" href="/app">Open Controller</a>
    {% else %}
    <button class="primary" disabled>Fix issues first</button>
    {% endif %}
  </div>

  {% if auto_continue %}
  <div class="note">All critical checks passed. Opening controller…</div>
  {% elif warning_count and can_continue %}
  <div class="note">Critical checks passed; warnings do not prevent operation.</div>
  {% else %}
  <div class="note">The controller will remain here until critical issues are resolved.</div>
  {% endif %}
</div>
</body>
</html>
"""

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="VIOMI Washer">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#f4f7fb">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="manifest" href="/manifest.webmanifest">
<title>VIOMI Washing Machine</title>
<style>
:root {
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --blue:#0f6ee8;
  --blue-hi:#2d7df0;
  --blue-soft:#eaf3ff;
  --ink:#10243b;
  --muted:#66778d;
  --surface:#ffffff;
  --bg:#f4f7fb;
  --line:#dbe4ef;
  --danger:#df5757;
  --danger-dark:#c43e3e;
  --shadow:0 4px 15px rgba(35,58,86,.075);
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--bg); color:var(--ink);
  padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom);
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:720px; margin:0 auto; padding:18px 18px 20px; }
.header-row { display:flex; align-items:center; gap:13px; margin-bottom:17px; }
.app-mark {
  width:54px; height:54px; border-radius:15px; background:#fff; border:1px solid var(--line);
  box-shadow:var(--shadow); display:flex; align-items:center; justify-content:center; overflow:hidden; flex:0 0 auto;
}
.app-mark img { width:43px; height:43px; border-radius:10px; object-fit:contain; }
.header-copy { min-width:0; }
h1 { font-size:27px; margin:0; line-height:1.04; letter-spacing:-.03em; color:var(--ink); }
.sub { color:var(--muted); margin-top:5px; font-size:15px; }
.local-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#34b879; margin-left:5px; vertical-align:1px; }
.status-banner {
  width:100%; text-align:center; font-size:29px; line-height:1; font-weight:850; letter-spacing:.04em;
  padding:22px 12px; margin:0 0 16px; border-radius:18px; background:#e9eef5; color:var(--ink);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.8);
}
.status-banner::before { content:"⏻"; font-weight:500; margin-right:14px; letter-spacing:0; }
.status-banner.scheduled {
  display:block;
  padding:10px 14px 11px;
  line-height:1.08;
}
.status-banner.scheduled::before { content:none; }
.scheduled-label {
  display:flex;
  align-items:center;
  justify-content:center;
  gap:7px;
  font-size:12px;
  font-weight:850;
  letter-spacing:.08em;
  color:#315a84;
  margin-bottom:5px;
}
.scheduled-label::before { content:"◷"; font-size:14px; letter-spacing:0; }
.scheduled-times {
  display:flex;
  align-items:center;
  justify-content:center;
  gap:18px;
  font-size:16px;
  font-weight:850;
  letter-spacing:.01em;
  color:var(--ink);
  font-variant-numeric:tabular-nums;
}
.scheduled-time { white-space:nowrap; }
.scheduled-time span {
  color:#667a91;
  font-size:11px;
  font-weight:750;
  margin-right:5px;
  text-transform:uppercase;
  letter-spacing:.04em;
}
.status-banner.active { background:#17283c; color:#fff; }
.status-banner.paused { background:#eef1f5; color:#405267; border:1px solid #cbd5df; }
.status-banner.finished { background:#e9eef5; color:var(--ink); }
.status-banner.fault { background:#c94343; color:#fff; }
.status-banner.door-warning { background:#fff0bf; color:#5f4700; border:1px solid #d8b84c; }
.status-banner.offline { background:#65768b; color:#fff; }
.metrics { display:grid; grid-template-columns:1fr 1fr; gap:11px; }
.metric-card {
  min-height:104px; background:var(--surface); border:1px solid var(--line); border-radius:16px;
  padding:16px 18px; box-shadow:var(--shadow); display:grid; grid-template-columns:44px minmax(0,1fr); gap:12px; align-items:center;
}
.metric-icon {
  font-size:31px; line-height:1; color:#5f7793; text-align:center; font-weight:400;
}
.metric-card.accent .metric-icon, .metric-card.accent .value { color:var(--blue); }
.metric-copy { min-width:0; }
.label { font-size:15px; color:#4f6680; margin-bottom:6px; line-height:1.05; }
.value { font-size:25px; font-weight:800; line-height:1.03; letter-spacing:-.015em; overflow-wrap:anywhere; }
.compact-status {
  margin-top:11px; background:var(--surface); border:1px solid var(--line); border-radius:15px; min-height:66px;
  padding:14px 18px; box-shadow:var(--shadow); display:flex; justify-content:space-between; gap:16px; align-items:center;
  font-size:15px;
}
.compact-status-item { display:flex; align-items:center; gap:9px; }
.status-mini-icon { font-size:20px; color:#607994; }
.label-inline { color:#4f6680; }
.controls { margin-top:15px; display:grid; gap:12px; }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.action-row { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
.card {
  background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:15px 17px; box-shadow:var(--shadow);
}
.program-row { display:grid; grid-template-columns:minmax(0,1fr); gap:6px; }
.compact-control .label { margin-bottom:9px; }
button, select {
  width:100%; min-height:58px; border-radius:14px; padding:15px 17px; font-size:18px; font-weight:700; box-sizing:border-box;
  font-family:inherit;
}
button { border:0; background:linear-gradient(180deg,var(--blue-hi),var(--blue)); color:#fff; box-shadow:0 3px 8px rgba(15,110,232,.18); }
button:active:not(:disabled) { transform:translateY(1px); }
button.danger { background:linear-gradient(180deg,#eb6868,var(--danger)); }
button.secondary { background:#69778a; }
button:disabled, select:disabled { opacity:.45; box-shadow:none; }
select {
  appearance:auto; border:1px solid #ccd7e4; background:#fff; color:var(--ink); box-shadow:none; font-weight:700;
}
.btn-icon { display:inline-block; margin-right:10px; }
.pause-icon { display:inline-block; margin-right:10px; letter-spacing:0; }
#powerOnBtn, #powerOffBtn { font-size:20px; min-height:62px; }
#setBtn { background:var(--blue-soft); color:var(--blue); border:1px solid #b8d5ff; box-shadow:none; }
#startBtn { background:linear-gradient(180deg,#5a99ef,#3d82e5); }
#pauseBtn { background:#d9dee6; color:#506176; box-shadow:none; }
#pauseBtn:not(:disabled) { background:#eef1f5; color:var(--ink); border:1px solid #aeb9c6; }
.schedule-card {
  padding:18px 18px 17px; overflow:hidden;
}
.schedule-title { font-size:20px; font-weight:850; color:var(--blue); margin:0 0 17px 1px; display:flex; align-items:center; gap:10px; }
.schedule-title::before { content:"▣"; font-size:19px; }
.schedule-controls {
  display:grid; grid-template-columns:minmax(180px,1.4fr) 105px 12px 105px; gap:10px; align-items:end;
}
.schedule-field { min-width:0; }
.schedule-field-label { font-size:13px; color:#4f6680; margin:0 0 7px 4px; line-height:1; }
#scheduleMode { min-width:165px; }
.schedule-clock-select { width:105px; min-width:105px; max-width:105px; text-align:center; font-variant-numeric:tabular-nums; }
.schedule-colon { align-self:end; text-align:center; font-size:24px; font-weight:850; line-height:58px; }
#scheduleBtn {
  margin:22px 0 0; min-height:62px; display:flex; align-items:center; justify-content:center; gap:10px; font-size:20px;
}
.schedule-btn-icon { font-size:20px; }
.schedule-summary { display:none; grid-template-columns:minmax(0,1fr) 105px; gap:10px; align-items:center; }
.schedule-text { font-size:14px; line-height:1.35; font-weight:700; }
#scheduleCancelBtn { margin:0; min-height:52px; }
.footer-row { display:flex; align-items:center; gap:10px; margin-top:15px; min-height:44px; }
#msg { flex:1; color:var(--muted); font-size:12px; line-height:1.25; }
#msg::before { content:"◷"; margin-right:7px; color:#607994; }
.diagnostics-link, .refresh-mini {
  width:44px; min-width:44px; height:44px; min-height:44px; padding:0; border-radius:50%; display:flex; align-items:center; justify-content:center;
  text-decoration:none; box-shadow:var(--shadow); font-size:19px;
}
.diagnostics-link { color:#52677f; background:#fff; border:1px solid #cdd7e2; }
.refresh-mini { background:#40546b; color:#fff; border:0; }
@media (max-width:560px) {
  .wrap { padding:12px 10px 14px; }
  .header-row { margin-bottom:12px; }
  .app-mark { width:48px; height:48px; border-radius:13px; }
  .app-mark img { width:39px; height:39px; }
  h1 { font-size:22px; }
  .sub { font-size:12px; margin-top:3px; }
  .status-banner { font-size:22px; padding:16px 10px; margin-bottom:9px; border-radius:14px; }
  .status-banner::before { margin-right:9px; }
  .metrics { gap:7px; }
  .metric-card { min-height:76px; padding:10px 11px; border-radius:13px; grid-template-columns:29px minmax(0,1fr); gap:7px; }
  .metric-icon { font-size:22px; }
  .label { font-size:11px; margin-bottom:3px; }
  .value { font-size:18px; }
  .compact-status { margin-top:7px; padding:10px 11px; min-height:48px; border-radius:12px; font-size:12px; }
  .status-mini-icon { font-size:16px; }
  .controls { margin-top:8px; gap:7px; }
  .row2,.action-row { gap:7px; }
  .card { padding:10px 11px; border-radius:13px; }
  button,select { min-height:50px; padding:12px 13px; font-size:16px; border-radius:12px; }
  #powerOnBtn,#powerOffBtn { min-height:52px; font-size:17px; }
  .btn-icon,.pause-icon { margin-right:7px; }
  .schedule-card { padding:12px 11px 11px; border-top-width:3px; }
  .schedule-title { font-size:16px; margin-bottom:12px; gap:7px; }
  .schedule-title::before { font-size:15px; }
  .schedule-controls { grid-template-columns:minmax(125px,1.3fr) 78px 8px 78px; gap:6px; }
  .schedule-field-label { font-size:10px; margin:0 0 5px 2px; }
  .schedule-clock-select { width:78px; min-width:78px; max-width:78px; padding-left:8px; padding-right:20px; }
  .schedule-colon { line-height:50px; font-size:18px; }
  #scheduleBtn { margin-top:18px; min-height:52px; font-size:17px; }
  .footer-row { margin-top:8px; }
  #msg { font-size:9.5px; }
  .diagnostics-link,.refresh-mini { width:38px; min-width:38px; height:38px; min-height:38px; font-size:16px; }
}
@media (max-width:560px) and (max-height:960px) {
  .wrap { padding:6px 10px 7px; }
  .header-row { gap:9px; margin-bottom:6px; }
  .app-mark { width:38px; height:38px; border-radius:11px; }
  .app-mark img { width:31px; height:31px; border-radius:8px; }
  h1 { font-size:20px; line-height:1; }
  .sub { font-size:10px; margin-top:2px; }
  .local-dot { width:6px; height:6px; margin-left:4px; }

  .status-banner { font-size:19px; padding:10px 8px; margin-bottom:5px; border-radius:12px; }
  .status-banner::before { margin-right:7px; }
  .status-banner.scheduled { padding:7px 9px 8px; }
  .scheduled-label { font-size:9px; margin-bottom:3px; gap:5px; }
  .scheduled-label::before { font-size:11px; }
  .scheduled-times { gap:13px; font-size:13px; }
  .scheduled-time span { font-size:8px; margin-right:3px; }

  .metrics { gap:5px; }
  .metric-card {
    min-height:54px; padding:6px 9px; border-radius:11px;
    grid-template-columns:23px minmax(0,1fr); gap:6px;
  }
  .metric-icon { font-size:18px; }
  .label { font-size:9px; margin-bottom:1px; }
  .value { font-size:16px; line-height:1; }

  .compact-status {
    margin-top:5px; padding:6px 9px; min-height:34px; border-radius:10px;
    font-size:10px;
  }
  .compact-status-item { gap:5px; }
  .status-mini-icon { font-size:13px; }

  .controls { margin-top:5px; gap:5px; }
  .row2,.action-row { gap:5px; }
  .card { padding:6px 9px; border-radius:11px; }
  .program-row { gap:3px; }
  .compact-control .label { margin-bottom:4px; }

  button,select {
    min-height:42px; padding:8px 10px; font-size:15px; border-radius:10px;
  }
  #powerOnBtn,#powerOffBtn { min-height:43px; font-size:15px; }
  .btn-icon,.pause-icon { margin-right:6px; }

  .schedule-card { padding:7px 9px 8px; border-top-width:3px; }
  .schedule-title { font-size:14px; margin:0 0 6px; gap:5px; }
  .schedule-title::before { font-size:13px; }
  .schedule-controls { grid-template-columns:minmax(118px,1.3fr) 67px 6px 67px; gap:5px; }
  .schedule-field-label { font-size:8.5px; margin:0 0 3px 1px; }
  #scheduleMode { min-width:118px; }
  .schedule-clock-select {
    width:67px; min-width:67px; max-width:67px; padding:7px 18px 7px 7px;
  }
  .schedule-colon { line-height:42px; font-size:16px; }
  #scheduleBtn { margin-top:8px; min-height:43px; font-size:15px; gap:7px; }
  .schedule-btn-icon { font-size:16px; }
  .schedule-summary { grid-template-columns:minmax(0,1fr) 82px; gap:6px; }
  .schedule-text { font-size:10px; line-height:1.2; }
  #scheduleCancelBtn { min-height:38px; }

  .footer-row { margin-top:5px; min-height:34px; gap:6px; }
  #msg { font-size:8px; line-height:1.1; }
  #msg::before { margin-right:4px; }
  .diagnostics-link,.refresh-mini {
    width:32px; min-width:32px; height:32px; min-height:32px; font-size:14px;
  }
}
@media (min-width:561px) and (max-height:1050px) {
  .wrap { max-width:760px; padding:8px 14px 8px; }
  .header-row { gap:10px; margin-bottom:7px; }
  .app-mark { width:40px; height:40px; border-radius:11px; }
  .app-mark img { width:33px; height:33px; border-radius:8px; }
  h1 { font-size:21px; line-height:1; }
  .sub { font-size:10px; margin-top:2px; }
  .local-dot { width:6px; height:6px; }

  .status-banner { font-size:20px; padding:10px 8px; margin-bottom:6px; border-radius:12px; }
  .status-banner::before { margin-right:8px; }

  .metrics { gap:6px; }
  .metric-card {
    min-height:55px; padding:6px 10px; border-radius:11px;
    grid-template-columns:24px minmax(0,1fr); gap:7px;
  }
  .metric-icon { font-size:18px; }
  .label { font-size:9px; margin-bottom:1px; }
  .value { font-size:16px; line-height:1; }

  .compact-status {
    margin-top:6px; min-height:35px; padding:6px 10px; border-radius:10px; font-size:10px;
  }
  .compact-status-item { gap:5px; }
  .status-mini-icon { font-size:13px; }

  .controls { margin-top:6px; gap:6px; }
  .row2,.action-row { gap:6px; }
  .card { padding:7px 10px; border-radius:11px; }
  .program-row { gap:3px; }
  .compact-control .label { margin-bottom:4px; }

  button,select { min-height:42px; padding:8px 11px; font-size:15px; border-radius:10px; }
  #powerOnBtn,#powerOffBtn { min-height:44px; font-size:15px; }
  .btn-icon,.pause-icon { margin-right:6px; }

  .schedule-card { padding:8px 10px 9px; border-top-width:3px; }
  .schedule-title { font-size:14px; margin:0 0 7px; gap:5px; }
  .schedule-title::before { font-size:13px; }
  .schedule-controls { grid-template-columns:minmax(180px,1.4fr) 78px 8px 78px; gap:6px; }
  .schedule-field-label { font-size:9px; margin:0 0 3px 2px; }
  #scheduleMode { min-width:180px; }
  .schedule-clock-select { width:78px; min-width:78px; max-width:78px; padding:7px 20px 7px 8px; }
  .schedule-colon { line-height:42px; font-size:17px; }
  #scheduleBtn { margin-top:9px; min-height:44px; font-size:15px; gap:7px; }
  .schedule-btn-icon { font-size:16px; }
  .schedule-summary { grid-template-columns:minmax(0,1fr) 90px; gap:7px; }
  .schedule-text { font-size:10px; line-height:1.2; }
  #scheduleCancelBtn { min-height:38px; }

  .footer-row { margin-top:5px; min-height:34px; gap:7px; }
  #msg { font-size:8.5px; line-height:1.1; }
  #msg::before { margin-right:4px; }
  .diagnostics-link,.refresh-mini { width:32px; min-width:32px; height:32px; min-height:32px; font-size:14px; }
}
@media (display-mode:standalone) {
  body { overscroll-behavior-y:none; }
  .wrap { padding-top:6px; }
}

/* V57: cleaner schedule card and aligned interrupted-schedule controls */
.schedule-card { border-top:0 !important; }
.schedule-actions { margin-top:10px; }
.schedule-actions .schedule-btn,
#scheduleBtn { width:100%; margin:0 !important; }
.schedule-interrupted,
.schedule-history,
.schedule-result { align-items:center; }
.schedule-interrupted .clear-btn,
.schedule-history .clear-btn,
.schedule-result .clear-btn,
#clearScheduleBtn {
  position:static !important;
  float:none !important;
  margin:0 0 0 10px !important;
  flex:0 0 auto;
  align-self:center;
}
</style>
</head>
<body>
<div class="wrap">
  <div class="header-row">
    <div class="app-mark"><img src="/apple-touch-icon.png" alt=""></div>
    <div class="header-copy">
      <h1>VIOMI Washing Machine</h1>
      <div class="sub">Local control<span class="local-dot"></span></div>
    </div>
  </div>

  <div id="statusBanner" class="status-banner">CONNECTING</div>

  <div class="metrics">
    <div class="metric-card">
      <div class="metric-icon">⏻</div>
      <div class="metric-copy"><div class="label">Power</div><div class="value" id="power">—</div></div>
    </div>
    <div class="metric-card accent">
      <div class="metric-icon">◎</div>
      <div class="metric-copy"><div class="label">Program</div><div class="value" id="mode">—</div></div>
    </div>
    <div class="metric-card">
      <div class="metric-icon">◷</div>
      <div class="metric-copy"><div class="label">Remaining</div><div class="value" id="left">—</div></div>
    </div>
    <div class="metric-card accent">
      <div class="metric-icon">°</div>
      <div class="metric-copy"><div class="label">Temperature</div><div class="value" id="temp">—</div></div>
    </div>
    <div class="metric-card accent">
      <div class="metric-icon">↻</div>
      <div class="metric-copy"><div class="label">Spin speed</div><div class="value" id="spin">—</div></div>
    </div>
    <div class="metric-card accent">
      <div class="metric-icon">◇</div>
      <div class="metric-copy"><div class="label">Rinse cycles</div><div class="value" id="rinses">—</div></div>
    </div>
  </div>

  <div class="compact-status">
    <span class="compact-status-item"><span class="status-mini-icon">◇</span><span><span class="label-inline">Fault:</span> <span id="fault">—</span></span></span>
    <span class="compact-status-item"><span class="status-mini-icon">▢</span><span><span class="label-inline">Lock:</span> <span id="locked">—</span></span></span>
  </div>

  <div class="controls">
    <div class="row2">
      <button id="powerOnBtn" onclick="post('/api/power/on')"><span class="btn-icon">⏻</span>Power On</button>
      <button id="powerOffBtn" class="danger" onclick="post('/api/power/off')"><span class="btn-icon">⏻</span>Power Off</button>
    </div>

    <div class="card">
      <div class="label">Select program</div>
      <div class="program-row">
        <select id="program">
          <option value="0">Golden Wash</option>
          <option value="16">Antibacterial</option>
          <option value="4">Spin</option>
          <option value="13">Underwear</option>
          <option value="22">Rinse + Spin</option>
          <option value="23">Drum Clean</option>
          <option value="29">Boil Wash</option>
          <option value="31">Delicate</option>
          <option value="36">New Clothes</option>
          <option value="37">Socks</option>
          <option value="38">Bra</option>
          <option value="39">Towel Boil Wash</option>
          <option value="40">Gloves</option>
        </select>
      </div>
    </div>

    <div class="row2">
      <div class="card compact-control">
        <div class="label">Temperature</div>
        <select id="temperature"></select>
      </div>
      <div class="card compact-control">
        <div class="label">Rinse cycles</div>
        <select id="rinseSelect"></select>
      </div>
    </div>

    <div class="action-row">
      <button id="setBtn" onclick="applySettings()"><span class="btn-icon">⚙</span>SET</button>
      <button id="startBtn" onclick="post('/api/start')"><span class="btn-icon">▶</span>Start</button>
      <button id="pauseBtn" class="secondary" onclick="post('/api/pause')"><span class="pause-icon">II</span>Pause</button>
    </div>

    <div class="card schedule-card">
      <div class="schedule-title">Schedule</div>
      <div id="scheduleEditor">
        <div class="schedule-controls">
          <div class="schedule-field">
            <div class="schedule-field-label">Schedule mode</div>
            <select id="scheduleMode">
              <option value="start">Start at</option>
              <option value="finish">Finish at</option>
            </select>
          </div>
          <div class="schedule-field">
            <div class="schedule-field-label">Hour</div>
            <select id="scheduleHour" class="schedule-clock-select" aria-label="Hour">
              <option value="00">00</option><option value="01">01</option><option value="02">02</option><option value="03">03</option>
              <option value="04">04</option><option value="05">05</option><option value="06">06</option><option value="07">07</option>
              <option value="08">08</option><option value="09">09</option><option value="10">10</option><option value="11">11</option>
              <option value="12">12</option><option value="13">13</option><option value="14">14</option><option value="15">15</option>
              <option value="16">16</option><option value="17">17</option><option value="18">18</option><option value="19">19</option>
              <option value="20">20</option><option value="21">21</option><option value="22">22</option><option value="23">23</option>
            </select>
          </div>
          <div class="schedule-colon">:</div>
          <div class="schedule-field">
            <div class="schedule-field-label">Minute</div>
            <select id="scheduleMinute" class="schedule-clock-select" aria-label="Minute">
              <option value="00">00</option><option value="05">05</option><option value="10">10</option><option value="15">15</option>
              <option value="20">20</option><option value="25">25</option><option value="30">30</option><option value="35">35</option>
              <option value="40">40</option><option value="45">45</option><option value="50">50</option><option value="55">55</option>
            </select>
          </div>
        </div>
        <button id="scheduleBtn" class="schedule-action" onclick="createSchedule()"><span class="schedule-btn-icon">◷</span><span>Schedule</span></button>
      </div>
      <div id="scheduleSummary" class="schedule-summary">
        <div id="scheduleText" class="schedule-text"></div>
        <button id="scheduleCancelBtn" class="secondary" onclick="cancelSchedule()">Cancel</button>
      </div>
    </div>
  </div>

  <div class="footer-row">
    <div id="msg">Reading washer status…</div>
    <a class="diagnostics-link" href="/?stay=1" title="Startup diagnostics" aria-label="Startup diagnostics">⚙</a>
    <button class="refresh-mini secondary" onclick="refreshNow()" aria-label="Refresh">↻</button>
  </div>
</div>

<script>
let busy = false;
let validationPending = false;
let uiEpoch = 0;
let lastGoodStatus = null;
let isOffline = false;
let lastSeenAt = null;
let commandPending = false;
let userEditingProgram = false;
let userEditingTemperature = false;
let userEditingRinses = false;

// Every POST must carry this header; the server rejects POSTs without it.
const POST_OPTIONS = {method:"POST", headers:{"X-Viomi-Request":"1"}};

const PROGRAM_CAPABILITIES = {
  0:{temperatures:[40],spin:700,rinses:[2]},
  16:{temperatures:[60],spin:700,rinses:[1,2,3,4]},
  4:{temperatures:[0],spin:700,rinses:[0]},
  13:{temperatures:[0,30,40,60],spin:700,rinses:[1,2,3,4]},
  22:{temperatures:[0],spin:700,rinses:[1,2,3,4]},
  23:{temperatures:[80],spin:700,rinses:[2]},
  29:{temperatures:[80],spin:700,rinses:[1,2,3,4]},
  31:{temperatures:[0,30,40],spin:600,rinses:[1,2,3,4]},
  36:{temperatures:[0,30,40],spin:700,rinses:[1,2,3,4]},
  37:{temperatures:[0,30,40,60],spin:700,rinses:[1,2,3,4]},
  38:{temperatures:[0,30,40],spin:400,rinses:[1,2,3,4]},
  39:{temperatures:[80],spin:700,rinses:[1,2,3,4]},
  40:{temperatures:[0,30,40,60],spin:700,rinses:[1,2,3,4]}
};

function fillSelect(el, values, current, formatter) {
  el.innerHTML = "";
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = String(v);
    opt.textContent = formatter(v);
    el.appendChild(opt);
  }
  if (values.includes(Number(current))) el.value = String(current);
}

function updateCapabilityControls(program, temperature, rinses) {
  const cap = PROGRAM_CAPABILITIES[Number(program)];
  if (!cap) return;

  const t = document.getElementById("temperature");
  const r = document.getElementById("rinseSelect");

  fillSelect(t, cap.temperatures, temperature,
    v => v === 0 ? "Cold" : `${v} °C`);
  fillSelect(r, cap.rinses, rinses,
    v => v === 0 ? "None" : String(v));

  const tempFixed = cap.temperatures.length === 1;
  const rinseFixed = cap.rinses.length === 1;
  t.disabled = tempFixed;
  r.disabled = rinseFixed;
}

document.addEventListener("DOMContentLoaded", () => {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 10);
  const rounded = Math.ceil(now.getMinutes() / 5) * 5;
  if (rounded >= 60) {
    now.setHours(now.getHours() + 1);
    now.setMinutes(0);
  } else {
    now.setMinutes(rounded);
  }
  const h = document.getElementById("scheduleHour");
  const m = document.getElementById("scheduleMinute");
  if (h) h.value = String(now.getHours()).padStart(2, "0");
  if (m) m.value = String(now.getMinutes()).padStart(2, "0");
  const programEl = document.getElementById("program");
  const tempEl = document.getElementById("temperature");
  const rinseEl = document.getElementById("rinseSelect");

  programEl.addEventListener("change", () => {
    userEditingProgram = true;
    const cap = PROGRAM_CAPABILITIES[Number(programEl.value)];
    if (cap) {
      updateCapabilityControls(programEl.value, cap.temperatures[0], cap.rinses[0]);
    }
  });
  tempEl.addEventListener("change", () => userEditingTemperature = true);
  rinseEl.addEventListener("change", () => userEditingRinses = true);
});

async function refreshNow(force=false) {
  if ((busy || validationPending) && !force) return;

  const requestEpoch = uiEpoch;
  const msg = document.getElementById("msg");

  try {
    const r = await fetch("/api/status", {cache:"no-store"});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Status request failed");

    // A SET may have happened while this request was in flight.
    // Never allow that older response to overwrite the optimistic UI.
    if (!force && (validationPending || requestEpoch !== uiEpoch)) {
      return;
    }

    renderStatusData(d);
    setOfflineState(false);
    msg.textContent = "Last update: " + new Date().toLocaleTimeString();
  } catch(e) {
    if (!force && (validationPending || requestEpoch !== uiEpoch)) {
      return;
    }

    setOfflineState(true);
    const when = new Date().toLocaleTimeString();
    msg.textContent = "Offline — retrying automatically (" + when + ")";
  }
}

async function post(url, body=null) {
  if (busy || commandPending || validationPending) return;
  busy = true;
  setCommandPending(true);
  const msg = document.getElementById("msg");
  msg.textContent = "Sending command…";
  try {
    const options = {method:"POST", headers:{...POST_OPTIONS.headers, "Content-Type":"application/json"}};
    if (body !== null) options.body = JSON.stringify(body);
    const r = await fetch(url, options);
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || "Command failed");
    msg.textContent = "Command accepted.";
    if (url === "/api/start") {
      try {
        const sr = await fetch("/api/start-check", {cache:"no-store"});
        const sd = await sr.json();
        if (sr.ok && !sd.error) {
          uiEpoch++;
          renderStatusData(sd);
          if (Number(sd.fault) === 3) {
            msg.textContent = "Close the door, then press Start.";
          }
        }
      } catch (_) {
        // The normal refresh loop remains the fallback.
      }
    }
  } catch(e) {
    msg.textContent = "Error: " + e.message;
  } finally {
    busy = false;
    setTimeout(async () => {
      await refreshNow(true);
      setCommandPending(false);
    }, 700);
  }
}

function captureDisplayedState() {
  return {
    programText: document.getElementById("mode").textContent,
    temperatureText: document.getElementById("temp").textContent,
    spinText: document.getElementById("spin").textContent,
    rinsesText: document.getElementById("rinses").textContent,
    programValue: document.getElementById("program").value,
    temperatureValue: document.getElementById("temperature").value,
    rinsesValue: document.getElementById("rinseSelect").value
  };
}

function restoreDisplayedState(s) {
  document.getElementById("mode").textContent = s.programText;
  document.getElementById("temp").textContent = s.temperatureText;
  document.getElementById("spin").textContent = s.spinText;
  document.getElementById("rinses").textContent = s.rinsesText;
  document.getElementById("program").value = s.programValue;
  updateCapabilityControls(
    Number(s.programValue),
    Number(s.temperatureValue),
    Number(s.rinsesValue)
  );
}

function showOptimisticSettings(program, temperature, rinses) {
  const cap = PROGRAM_CAPABILITIES[program];
  const programSelect = document.getElementById("program");
  const programName = programSelect.options[programSelect.selectedIndex].text;

  document.getElementById("mode").textContent = programName;
  document.getElementById("temp").textContent =
    temperature === 0 ? "Cold" : temperature + " °C";
  document.getElementById("spin").textContent = cap.spin + " rpm";
  document.getElementById("rinses").textContent =
    rinses === 0 ? "None" : String(rinses);
}


async function validateRequestedSettings(program, temperature, rinses, timeoutMs=10000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;

  while (Date.now() < deadline) {
    try {
      const r = await fetch("/api/status", {cache:"no-store"});
      const d = await r.json();
      if (r.ok) {
        last = d;
        const cap = PROGRAM_CAPABILITIES[program];

        const programOk = Number(d.mode) === program;
        const tempOk = Number(d.temperature) === temperature;
        const rinseOk = Number(d.rinses) === rinses;
        const spinOk = Number(d.spin) === Number(cap.spin);

        if (programOk && tempOk && rinseOk && spinOk) {
          return {ok:true, data:d};
        }
      }
    } catch (e) {
      // Keep polling until timeout; transient read errors are not an update failure.
    }

    await new Promise(resolve => setTimeout(resolve, 500));
  }

  return {ok:false, data:last};
}





function setCommandPending(pending) {
  commandPending = pending;
  const ids = [
    "powerOnBtn", "powerOffBtn", "setBtn", "startBtn", "pauseBtn",
    "scheduleBtn", "scheduleCancelBtn", "program", "temperature", "rinseSelect",
    "scheduleMode", "scheduleHour", "scheduleMinute"
  ];
  if (pending) {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) el.disabled = true;
    }
  } else if (!isOffline && lastGoodStatus) {
    updateActionStates(lastGoodStatus);
  }
}

function formatAgo(ms) {
  if (ms < 60000) return "just now";
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return mins + " min ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + " h ago";
  const days = Math.floor(hrs / 24);
  return days + " d ago";
}

function updateOfflineBannerAge() {
  if (!isOffline) return;
  const banner = document.getElementById("statusBanner");
  if (!lastSeenAt) {
    banner.textContent = "OFFLINE";
    return;
  }
  banner.textContent = "OFFLINE · LAST SEEN " + formatAgo(Date.now() - lastSeenAt).toUpperCase();
}

function displayStateForStatus(status, power) {
  if (!power) return {text:"OFF", cls:""};
  switch (Number(status)) {
    case 0:
    case 1:
      return {text:"READY", cls:""};
    case 4:
      return {text:"DELAY", cls:""};
    case 7:
      return {text:"WASHING", cls:"active"};
    case 9:
      return {text:"RINSING", cls:"active"};
    case 11:
      return {text:"SPINNING", cls:"active"};
    case 17:
      return {text:"FINISHED", cls:"finished"};
    case 25:
      return {text:"WEIGHING", cls:"active"};
    case 26:
      return {text:"PAUSED", cls:"paused"};
    case 27:
      return {text:"FAULT", cls:"fault"};
    default:
      return {text:"STATUS " + status, cls:""};
  }
}

function renderStatusBanner(status, power, leftTime=null, fault=0) {
  const banner = document.getElementById("statusBanner");
  if (Number(fault) === 3) {
    banner.textContent = "CLOSE DOOR";
    banner.className = "status-banner door-warning";
    return;
  }
  const s = displayStateForStatus(status, power);
  let text = s.text;
  if ([7,9,11,25,26].includes(Number(status)) && leftTime != null) {
    text += " · " + leftTime + " MIN";
  }
  banner.textContent = text;
  banner.className = "status-banner" + (s.cls ? " " + s.cls : "");
}

function setOfflineState(offline) {
  isOffline = offline;

  const ids = [
    "powerOnBtn", "powerOffBtn", "setBtn", "startBtn", "pauseBtn",
    "program", "temperature", "rinseSelect"
  ];

  if (offline) {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) el.disabled = true;
    }
    const banner = document.getElementById("statusBanner");
    banner.className = "status-banner offline";
    updateOfflineBannerAge();
  } else if (lastGoodStatus) {
    updateActionStates(lastGoodStatus);
  }
}

function updateActionStates(d) {
  const status = Number(d.status);
  const power = d.power === true;

  // Confirmed W1 states:
  // 0 off/standby, 1 standby, 7 washing, 9 rinsing,
  // 11 spinning, 17 finished, 25 weighing, 26 paused, 27 fault.
  const active = [7, 9, 11, 25].includes(status);
  const paused = status === 26;
  const doorOpen = Number(d.fault) === 3;
  const faulted = (status === 27 || Number(d.fault) !== 0) && !doorOpen;
  const configurable = power && !doorOpen && [0, 1, 17, 26].includes(status);
  const startAllowed = power && (doorOpen || [0, 1, 17, 26].includes(status));

  const setBtn = document.getElementById("setBtn");
  const startBtn = document.getElementById("startBtn");
  const pauseBtn = document.getElementById("pauseBtn");
  const powerOnBtn = document.getElementById("powerOnBtn");
  const powerOffBtn = document.getElementById("powerOffBtn");
  const program = document.getElementById("program");
  const temperature = document.getElementById("temperature");
  const rinses = document.getElementById("rinseSelect");
  const scheduleBtn = document.getElementById("scheduleBtn");
  const scheduleCancelBtn = document.getElementById("scheduleCancelBtn");
  const scheduleMode = document.getElementById("scheduleMode");
  const scheduleHour = document.getElementById("scheduleHour");
  const scheduleMinute = document.getElementById("scheduleMinute");
  const hasPendingSchedule = d.schedule && ["pending","starting","started","running"].includes(d.schedule.status);

  if (startBtn) startBtn.textContent = paused ? "Resume" : "Start";

  if (setBtn) setBtn.disabled = commandPending || !configurable || active || faulted;
  if (startBtn) startBtn.disabled = commandPending || !startAllowed || active || faulted;
  if (pauseBtn) pauseBtn.disabled = commandPending || !active;
  if (powerOnBtn) powerOnBtn.disabled = commandPending || power;
  if (powerOffBtn) powerOffBtn.disabled = commandPending || !power || (active && !doorOpen);
  if (scheduleBtn) scheduleBtn.disabled = commandPending || !configurable || active || faulted || hasPendingSchedule;
  if (scheduleMode) scheduleMode.disabled = commandPending || hasPendingSchedule;
  if (scheduleHour) scheduleHour.disabled = commandPending || hasPendingSchedule;
  if (scheduleMinute) scheduleMinute.disabled = commandPending || hasPendingSchedule;
  if (scheduleCancelBtn) scheduleCancelBtn.disabled = commandPending;

  // Do not allow configuration changes while a cycle is actively running.
  if (program) program.disabled = !configurable;
  if (temperature) {
    const variable = PROGRAM_CAPABILITIES[Number(program?.value)]?.temperatures.length > 1;
    temperature.disabled = !configurable || !variable;
  }
  if (rinses) {
    const variable = PROGRAM_CAPABILITIES[Number(program?.value)]?.rinses.length > 1;
    rinses.disabled = !configurable || !variable;
  }
}


function formatScheduleClock(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return hh + ":" + mm;
}

function renderSchedule(schedule) {
  const editor = document.getElementById("scheduleEditor");
  const summary = document.getElementById("scheduleSummary");
  const text = document.getElementById("scheduleText");
  const actionBtn = document.getElementById("scheduleCancelBtn");

  if (!schedule || schedule.status === "cancelled") {
    editor.style.display = "grid";
    summary.style.display = "none";
    if (actionBtn) {
      actionBtn.style.display = "";
      actionBtn.disabled = false;
      actionBtn.textContent = "Cancel";
    }
    return;
  }

  if (schedule.status === "interrupted") {
    editor.style.display = "grid";
    summary.style.display = "grid";
    summary.style.gridTemplateColumns = "minmax(0,1fr) 82px";
    text.textContent = "Previous schedule interrupted" + (schedule.last_error ? " · " + schedule.last_error : "");
    if (actionBtn) {
      actionBtn.style.display = "";
      actionBtn.disabled = false;
      actionBtn.textContent = "Clear";
    }
    return;
  }

  editor.style.display = "none";
  summary.style.display = "grid";

  const start = formatScheduleClock(schedule.start_at);
  const finish = formatScheduleClock(schedule.finish_at);
  const actualFinish = formatScheduleClock(schedule.actual_finish_at);

  if (actionBtn) {
    actionBtn.style.display = "";
    actionBtn.disabled = false;
    actionBtn.textContent = "Cancel";
  }

  if (schedule.status === "pending") {
    summary.style.gridTemplateColumns = "minmax(0,1fr) 82px";
    text.textContent = "Starts " + start + " · finishes ~" + finish;
  } else if (schedule.status === "starting") {
    text.textContent = "Starting scheduled program…";
  } else if (schedule.status === "started") {
    text.textContent = "Start sent · waiting for washer";
    if (actionBtn) actionBtn.style.display = "none";
    summary.style.gridTemplateColumns = "1fr";
  } else if (schedule.status === "running") {
    text.textContent = "Running · planned finish ~" + finish;
    if (actionBtn) actionBtn.style.display = "none";
    summary.style.gridTemplateColumns = "1fr";
  } else if (schedule.status === "finished") {
    text.textContent = "Finished · planned ~" + finish + " · actual " + actualFinish;
    if (actionBtn) {
      actionBtn.textContent = "Clear";
      actionBtn.style.display = "";
    }
    summary.style.gridTemplateColumns = "minmax(0,1fr) 82px";
  } else if (schedule.status === "missed") {
    text.textContent = "MISSED SCHEDULE · " + (schedule.last_error || "");
    if (actionBtn) actionBtn.textContent = "Clear";
  } else if (schedule.status === "failed") {
    text.textContent = "SCHEDULE FAILED · " + (schedule.last_error || "");
    if (actionBtn) actionBtn.textContent = "Clear";
  } else if (schedule.status === "interrupted") {
    text.textContent = "SCHEDULE INTERRUPTED · " + (schedule.last_error || "");
    if (actionBtn) actionBtn.textContent = "Clear";
  } else {
    text.textContent = schedule.status.toUpperCase();
  }
}

async function createSchedule() {
  if (busy || commandPending || validationPending) return;

  const mode = document.getElementById("scheduleMode").value;
  const hour = document.getElementById("scheduleHour").value;
  const minute = document.getElementById("scheduleMinute").value;
  const timeValue = hour + ":" + minute;
  const msg = document.getElementById("msg");

  busy = true;
  setCommandPending(true);
  try {
    const r = await fetch("/api/schedule", {
      method:"POST",
      headers:{...POST_OPTIONS.headers, "Content-Type":"application/json"},
      body:JSON.stringify({mode:mode, time:timeValue})
    });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || "Could not create schedule");
    renderSchedule(d.schedule);
    msg.textContent = mode === "finish"
      ? "Finish-time schedule created."
      : "Start-time schedule created.";
    await refreshNow(true);
  } catch (e) {
    msg.textContent = "Schedule failed: " + e.message;
  } finally {
    busy = false;
    setCommandPending(false);
  }
}

async function cancelSchedule() {
  if (busy || commandPending || validationPending) return;
  busy = true;
  setCommandPending(true);
  try {
    const r = await fetch("/api/schedule/cancel", POST_OPTIONS);
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || "Could not cancel schedule");
    renderSchedule(null);
    document.getElementById("msg").textContent = "Schedule cancelled.";
    await refreshNow(true);
  } catch (e) {
    document.getElementById("msg").textContent = "Cancel failed: " + e.message;
  } finally {
    busy = false;
    setCommandPending(false);
  }
}

function renderStatusData(d) {
  lastGoodStatus = d;
  isOffline = false;
  lastSeenAt = Date.now();
  document.getElementById("power").textContent = d.power_text;
  renderStatusBanner(d.status, d.power === true, d.left_time, d.fault);
  document.getElementById("mode").textContent = d.mode_text;
  document.getElementById("left").textContent = d.left_time == null ? "—" : d.left_time + " min";
  document.getElementById("temp").textContent = d.temperature == null ? "—" : (d.temperature === 0 ? "Cold" : d.temperature + " °C");
  document.getElementById("spin").textContent = d.spin == null ? "—" : d.spin + " rpm";
  document.getElementById("rinses").textContent = d.rinses == null ? "—" : (d.rinses === 0 ? "None" : d.rinses);
  document.getElementById("fault").textContent = d.fault_text;
  document.getElementById("locked").textContent = d.locked_text;
  renderSchedule(d.schedule || null);

  if (d.schedule && d.schedule.status === "pending" && [0,1,17].includes(Number(d.status))) {
    const banner = document.getElementById("statusBanner");
    banner.innerHTML =
      '<div class="scheduled-label">SCHEDULED</div>' +
      '<div class="scheduled-times">' +
        '<div class="scheduled-time"><span>Start</span>' + formatScheduleClock(d.schedule.start_at) + '</div>' +
        '<div class="scheduled-time"><span>Finish</span>~' + formatScheduleClock(d.schedule.finish_at) + '</div>' +
      '</div>';
    banner.className = "status-banner scheduled";
  }

  updateActionStates(d);

  if (Number(d.fault) === 3) {
    document.getElementById("msg").textContent = "Close the door, then press Start.";
  }

  if (d.mode != null && !userEditingProgram) {
    document.getElementById("program").value = String(d.mode);
    if (!userEditingTemperature && !userEditingRinses) {
      updateCapabilityControls(d.mode, d.temperature, d.rinses);
    }
  }
}

async function applySettings() {
  const program = Number(document.getElementById("program").value);
  const temperature = Number(document.getElementById("temperature").value);
  const rinses = Number(document.getElementById("rinseSelect").value);
  const cap = PROGRAM_CAPABILITIES[program];

  if (!cap || !cap.temperatures.includes(temperature) || !cap.rinses.includes(rinses)) {
    document.getElementById("msg").textContent = "Invalid settings for this program.";
    return;
  }

  const previous = captureDisplayedState();

  userEditingProgram = false;
  userEditingTemperature = false;
  userEditingRinses = false;

  // Invalidate any status request that may already be in flight, then freeze
  // normal refreshes BEFORE showing the optimistic values.
  uiEpoch++;
  validationPending = true;
  setCommandPending(true);
  const setBtn = document.getElementById("setBtn");
  const oldSetText = setBtn.textContent;
  setBtn.disabled = true;
  setBtn.textContent = "...";
  showOptimisticSettings(program, temperature, rinses);
  document.getElementById("msg").textContent = "Applying settings...";

  try {
    busy = true;

    // Program first: selecting it reloads the washer's default profile.
    let r = await fetch("/api/program/" + program, POST_OPTIONS);
    let j = await r.json();
    if (!r.ok || j.ok === false) throw new Error(j.error || "Program setting failed");

    await new Promise(resolve => setTimeout(resolve, 800));

    if (cap.temperatures.length > 1) {
      r = await fetch("/api/temperature/" + temperature, POST_OPTIONS);
      j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || "Temperature setting failed");
    }

    if (cap.rinses.length > 1) {
      r = await fetch("/api/rinses/" + rinses, POST_OPTIONS);
      j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || "Rinse setting failed");
    }

    busy = false;
    document.getElementById("msg").textContent = "Validating settings...";

    // Do NOT let the normal refresh loop replace the optimistic values.
    // Poll silently until the washer reports the requested values.
    const validation = await validateRequestedSettings(program, temperature, rinses, 10000);

    if (!validation.ok) {
      throw new Error("Washer did not confirm the requested settings");
    }

    // Now that the washer has confirmed them, invalidate any older reads
    // and render the confirmed status once.
    uiEpoch++;
    renderStatusData(validation.data);
    setBtn.textContent = "✓ SET";
    document.getElementById("msg").textContent = "Settings applied.";
    await new Promise(resolve => setTimeout(resolve, 500));
    setBtn.textContent = oldSetText;

  } catch (e) {
    busy = false;
    uiEpoch++;
    restoreDisplayedState(previous);
    setBtn.textContent = "! FAILED";
    document.getElementById("msg").textContent = "Update failed: " + e.message;
    await new Promise(resolve => setTimeout(resolve, 800));
    setBtn.textContent = oldSetText;
  } finally {
    validationPending = false;
    setCommandPending(false);
    if (!isOffline && lastGoodStatus) updateActionStates(lastGoodStatus);
  }
}

async function loop() {
  await refreshNow();
  setTimeout(loop, 5000);
}
setInterval(updateOfflineBannerAge, 60000);
loop();
</script>
</body>
</html>
"""


def _request_hostname():
    host = (request.host or "").lower()
    if host.startswith("["):
        return host[1:host.find("]")]
    return host.rsplit(":", 1)[0]

def _host_allowed(hostname):
    # Reject DNS-rebinding names: only IP literals, this PC's own names and
    # explicitly configured names may address the controller.
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    own = socket.gethostname().lower()
    allowed = {"localhost", own, own + ".local"}
    allowed.update(str(h).lower() for h in (CONFIG.get("allowed_hosts") or []))
    return hostname in allowed

@app.before_request
def reject_foreign_requests():
    hostname = _request_hostname()
    if not _host_allowed(hostname):
        log_event("BLOCKED", f"Host {hostname} · {request.path}")
        return jsonify({"ok": False, "error": "Host not allowed"}), 403

    if request.method != "POST":
        return None

    # A custom header cannot be sent cross-site without a CORS preflight,
    # which this server never approves; the Origin check is a second line.
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc.lower() != (request.host or "").lower():
        log_event("BLOCKED", f"Origin {origin} · {request.path}")
        return jsonify({"ok": False, "error": "Cross-origin request rejected"}), 403
    if request.headers.get(REQUEST_MARKER_HEADER) != "1":
        log_event("BLOCKED", f"Missing {REQUEST_MARKER_HEADER} · {request.path}")
        return jsonify({"ok": False, "error": "Request not sent by the controller page"}), 403
    return None

@app.after_request
def disable_browser_cache(response):
    # The controller is local and frequently updated; never let iOS reuse stale HTML/JS.
    if response.mimetype in ("text/html", "application/json", "application/manifest+json"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_file(Path(__file__).with_name("viomi_icon_180.png"), mimetype="image/png")

@app.route("/icon-192.png")
def icon_192():
    return send_file(Path(__file__).with_name("viomi_icon_192.png"), mimetype="image/png")

@app.route("/icon-512.png")
def icon_512():
    return send_file(Path(__file__).with_name("viomi_icon_512.png"), mimetype="image/png")

@app.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "VIOMI Washing Machine",
        "short_name": "VIOMI Washer",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#111111",
        "theme_color": "#111111",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")

@app.route("/diagnostics/export")
def diagnostics_export():
    result = LAST_DIAGNOSTICS or run_startup_checks()
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "controller_version": CONTROLLER_VERSION,
        "controller_uptime": uptime_text(),
        "washer_ip": WASHER_IP,
        "pc_ip": result.get("pc_ip"),
        "expected_model": EXPECTED_MODEL,
        "actual_model": ACTUAL_MODEL,
        "firmware": ACTUAL_FIRMWARE,
        "timings_ms": dict(TIMINGS),
        "checks": result.get("checks", []),
        "recent_events": list(EVENT_LOG),
        "schedule": get_schedule_public(),
    }
    # Deliberately excludes the MIoT token.
    body = json.dumps(report, indent=2, ensure_ascii=False)
    response = Response(body, mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="viomi_diagnostics.json"'
    return response

@app.route("/app")
def controller():
    return render_template_string(PAGE)

@app.route("/")
def startup():
    started = time.perf_counter()
    result = run_startup_checks()
    diag_ms = int((time.perf_counter() - started) * 1000)
    log_event(
        "DIAGNOSTICS",
        "OK" if result["ok"] else f"{result['critical_count']} issue(s)",
        diag_ms
    )
    manual_diagnostics = request.args.get("stay") == "1"

    if result["ok"] and result["warning_count"] == 0:
        summary_text = "All systems ready"
        summary_class = "ok"
        auto_continue = not manual_diagnostics
    elif result["ok"]:
        summary_text = f"Ready with {result['warning_count']} warning(s)"
        summary_class = "warn"
        auto_continue = False
    else:
        summary_text = f"{result['critical_count']} startup issue(s) found"
        summary_class = "bad"
        auto_continue = False

    return render_template_string(
        STARTUP_PAGE,
        checks=result["checks"],
        can_continue=result["ok"],
        warning_count=result["warning_count"],
        summary_text=summary_text,
        summary_class=summary_class,
        auto_continue=auto_continue,
        controller_version=CONTROLLER_VERSION,
        washer_ip=WASHER_IP or "—",
        pc_ip=result["pc_ip"],
        expected_model=EXPECTED_MODEL,
        actual_model=ACTUAL_MODEL,
        actual_firmware=ACTUAL_FIRMWARE,
        uptime=uptime_text(),
        events=list(EVENT_LOG)[:5],
    )

@app.route("/api/start-check")
def api_start_check():
    """Poll briefly after Start so an open-door fault is shown promptly."""
    deadline = time.monotonic() + 3.0
    last = None
    while time.monotonic() < deadline:
        try:
            last = read_all()
            observe_status(last)
            fault = int(last.get("fault") or 0)
            status = int(last.get("status") or 0)
            if fault != 0 or status in (7, 9, 11, 25, 26):
                return jsonify(last)
        except Exception:
            pass
        time.sleep(0.35)
    if last is not None:
        return jsonify(last)
    return jsonify({"error": "No status response after Start"}), 503

@app.route("/api/status")
def api_status():
    try:
        data = read_all()
        observe_status(data)
        data["schedule"] = get_schedule_public()
        return jsonify(data)
    except Exception as e:
        observe_offline()
        return jsonify({"error": str(e), "diagnostics": "/"}), 503

@app.route("/api/power/on", methods=["POST"])
def api_power_on():
    try:
        set_property_direct(2, 1, True)
        log_event("POWER ON")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/power/off", methods=["POST"])
def api_power_off():
    try:
        schedule = get_schedule_public()
        set_property_direct(2, 1, False)
        if schedule and schedule.get("status") in ("pending", "starting"):
            cancel_schedule("Cancelled by Power Off")
        elif schedule and schedule.get("status") in ("started", "running"):
            interrupt_active_schedule("Interrupted by Power Off")
        log_event("POWER OFF")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/program/<int:value>", methods=["POST"])
def api_program(value):
    try:
        if value not in MODE_MAP:
            return jsonify({"ok": False, "error": f"Unsupported program code: {value}"}), 400

        set_property_direct(2, 3, value)
        interrupt_active_schedule("Interrupted by manual SET/program change")
        return jsonify({"ok": True, "value": value, "program": MODE_MAP[value]})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/temperature/<int:value>", methods=["POST"])
def api_temperature(value):
    try:
        if value not in TEMPERATURE_VALUES:
            return jsonify({"ok": False, "error": f"Unsupported temperature: {value}"}), 400
        set_property_direct(2, 6, value)
        interrupt_active_schedule("Interrupted by manual SET/temperature change")
        return jsonify({"ok": True, "value": value})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/spin/<int:value>", methods=["POST"])
def api_spin(value):
    try:
        if value not in SPIN_VALUES:
            return jsonify({"ok": False, "error": f"Unsupported spin speed: {value}"}), 400
        set_property_direct(2, 7, value)
        interrupt_active_schedule("Interrupted by manual SET/spin change")
        return jsonify({"ok": True, "value": value})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/rinses/<int:value>", methods=["POST"])
def api_rinses(value):
    try:
        if value not in RINSE_VALUES:
            return jsonify({"ok": False, "error": f"Unsupported rinse count: {value}"}), 400
        set_property_direct(2, 9, value)
        interrupt_active_schedule("Interrupted by manual SET/rinse change")
        return jsonify({"ok": True, "value": value})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/schedule", methods=["POST"])
def api_schedule_create():
    try:
        payload = request.get_json(silent=True) or {}
        mode = str(payload.get("mode") or "").strip().lower()
        hhmm = str(payload.get("time") or "").strip()
        schedule = create_server_schedule(mode, hhmm)
        return jsonify({"ok": True, "schedule": schedule})
    except Exception as e:
        log_event("SCHEDULE FAILED", str(e))
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/schedule/cancel", methods=["POST"])
def api_schedule_cancel():
    cancel_schedule("Cancelled by user")
    return jsonify({"ok": True})

@app.route("/api/schedule")
def api_schedule_status():
    return jsonify({"ok": True, "schedule": get_schedule_public()})


@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        if get_schedule_public() and get_schedule_public().get("status") in ("pending", "starting"):
            cancel_schedule("Cancelled by manual Start")
        call_action_direct(2, 1)
        log_event("START / RESUME")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/pause", methods=["POST"])
def api_pause():
    try:
        call_action_direct(2, 2)
        log_event("PAUSE")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("COMMAND FAILED", f"{request.path} · {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    start_scheduler()
    ip = local_ip()
    print()
    print("VIOMI local web interface")
    print("Open on this PC: http://127.0.0.1:8080  (startup diagnostics)")
    print(f"Open on your iPhone: http://{ip}:8080  (startup diagnostics)")
    print("Keep this window open while using the web interface.")
    print()
    app.run(host="0.0.0.0", port=8080, debug=False)
