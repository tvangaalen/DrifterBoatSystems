"""Read-only check, run by install_service.ps1 in the session the boot task will use (session 0, nobody logged on):
can it see the MasterBus USB Link and Bluetooth LE, and start a process the way the supervisor does (Win32_Process
Create)? Opens no device and connects to nothing (the Bluetooth part only listens to advertisements for 4 s), writes
only its result file. Device names and addresses are not recorded.

    py tools\\session0_check.py <result.json>
"""
import asyncio, ctypes, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

MASTERBUS_VID = 0x1A64          # mastervolt/masterbus/usb.py


def session_id(pid=None) -> int:
    sid = ctypes.c_ulong(); ctypes.windll.kernel32.ProcessIdToSessionId(pid or os.getpid(), ctypes.byref(sid)); return sid.value


def main(result: Path):
    out = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "user": os.environ.get("USERNAME"), "session": session_id(), "python": sys.executable}
    try:
        import hid
        devs = hid.enumerate(); out["usb_hid_devices"] = len(devs); out["masterbus_usb"] = any(d.get("vendor_id") == MASTERBUS_VID for d in devs)
    except Exception as e: out["usb_error"] = repr(e)

    async def ble():
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        a = await BluetoothAdapter.get_default_async(); out["bluetooth_adapter"] = a is not None
        if a is None: return
        r = await a.get_radio_async(); out["bluetooth_on"] = bool(r and int(r.state) == 1)
        from bleak import BleakScanner
        out["bluetooth_devices_heard"] = len(await BleakScanner.discover(timeout=4.0))
    try: asyncio.run(ble())
    except Exception as e: out["bluetooth_error"] = repr(e)

    # the supervisor starts modules through Win32_Process Create (start_all.ps1): does that work here, and in which session?
    marker = Path(tempfile.gettempdir()) / f"drifter_s0_{os.getpid()}.txt"; child = marker.with_suffix(".py")
    child.write_text("import ctypes, os, sys\ns = ctypes.c_ulong(); ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(s))\n"
                     "open(sys.argv[1], 'w').write(str(s.value))\n", encoding="utf-8")
    venv = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "pythonw.exe"   # as start_all.ps1 does
    pyw = str(venv) if venv.exists() else shutil.which("pyw") or r"C:\Windows\pyw.exe"
    line = f'"{pyw}" "{child}" "{marker}"'.replace("'", "''")
    ps = f"(Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine = '{line}'}}).ReturnValue"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        out["process_create_result"] = r.stdout.strip() or r.stderr.strip()[-200:]
        for _ in range(30):
            if marker.exists(): time.sleep(0.2); out["process_create_session"] = int(marker.read_text()); marker.unlink(); break
            time.sleep(0.5)
        child.unlink(missing_ok=True)
    except Exception as e: out["process_create_error"] = repr(e)
    out["ok"] = bool(out.get("masterbus_usb") and out.get("bluetooth_on") and "bluetooth_error" not in out and out.get("process_create_session") is not None)
    result.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
