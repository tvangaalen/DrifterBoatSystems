from flask import Flask, jsonify, request, Response
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
CONTROLLER_VERSION = "3.8-v59"
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

def diagnostics_summary(result):
    if result["ok"] and result["warning_count"] == 0:
        return "All systems ready", "ok"
    if result["ok"]:
        return f"Ready with {result['warning_count']} warning(s)", "warn"
    return f"{result['critical_count']} startup issue(s) found", "bad"

@app.route("/api/diagnostics")
def api_diagnostics():
    """Startup checks and controller details for the Drifter app. ?recheck=1 runs the checks again (re-reads the
    config and re-creates the device, as the old diagnostics page did); otherwise the last result is returned."""
    if request.args.get("recheck") == "1" or LAST_DIAGNOSTICS is None:
        started = time.perf_counter()
        result = run_startup_checks()
        log_event("DIAGNOSTICS", "OK" if result["ok"] else f"{result['critical_count']} issue(s)", int((time.perf_counter() - started) * 1000))
    else:
        result = LAST_DIAGNOSTICS
    summary, summary_class = diagnostics_summary(result)
    return jsonify({
        **result, "summary": summary, "summary_class": summary_class,
        "controller_version": CONTROLLER_VERSION, "uptime": uptime_text(), "washer_ip": WASHER_IP or None,
        "expected_model": EXPECTED_MODEL, "model": ACTUAL_MODEL, "firmware": ACTUAL_FIRMWARE, "timings_ms": dict(TIMINGS),
    })

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

def bind_address():
    """Only the Drifter gateway on this PC talks to the controller, so it listens on localhost. VIOMI_BIND may name
    another loopback or private (RFC 1918) address; never a public interface or all interfaces."""
    addr = (os.environ.get("VIOMI_BIND") or "127.0.0.1").strip()
    ip = ipaddress.ip_address(addr)
    if not (ip.is_loopback or (ip.is_private and not ip.is_unspecified and not ip.is_link_local)):
        raise SystemExit(f"VIOMI_BIND {addr}: only localhost or a private LAN address is allowed")
    return addr

if __name__ == "__main__":
    host = bind_address()
    start_scheduler()
    print()
    print(f"VIOMI controller {CONTROLLER_VERSION} API on http://{host}:8080 (used by the Drifter app)")
    print("Keep this process running for scheduled programs.")
    print()
    app.run(host=host, port=8080, debug=False)
