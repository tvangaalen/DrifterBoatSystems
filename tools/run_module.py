"""Runs one module from its active location (modules.json + locations.json) without a window and waits for it.

For scheduled tasks and start_all.ps1:  pyw tools\\run_module.py <module>
Sets DRIFTER_DATA in the Drifter location, so the module keeps its runtime files in <data>\\<module>. Output goes to
<data folder>\\logs\\<module>.console.log. Exit code = the module's, so a task can restart it.

The runner puts itself in a Windows job object that kills everything in it when the runner ends. The server (and the
launchers it starts) inherit the job, so stopping the scheduled task, or killing the runner, also stops the server.
Without it a task's server outlived "Stop-ScheduledTask" and, running in session 0, could then not be stopped by the
user at all.
"""
import ctypes, os, subprocess, sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modules  # noqa: E402

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JobObjectExtendedLimitInformation = 0x2000, 9


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def join_kill_on_close_job():
    """Put this process in a new kill-on-close job; children started afterwards inherit it. Returns the handle (keep it
    open for the life of the process) or None when Windows refuses (then the old behaviour applies)."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE; k.GetCurrentProcess.restype = wintypes.HANDLE
    job = k.CreateJobObjectW(None, None)
    if not job: return None
    info = _Extended(); info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(wintypes.HANDLE(job), JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)): return None
    if not k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k.GetCurrentProcess())): return None
    return job


CREATE_SUSPENDED = 0x4


def start_in_job(job, cmd, **kw):
    """Start cmd suspended, put it in `job`, then let it run. Task Scheduler's own job lets children break away silently,
    so inheriting our job is not enough under a task (BoatGuard outlived Stop-ScheduledTask that way); assigning the child
    explicitly before it runs puts it, and everything it starts (the venv launcher starts the real python), in our job."""
    p = subprocess.Popen(cmd, creationflags=kw.pop("creationflags", 0) | (CREATE_SUSPENDED if job else 0), **kw)
    if job:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(p._handle))): print("job assignment failed", file=sys.stderr)
        ctypes.WinDLL("ntdll").NtResumeProcess(wintypes.HANDLE(int(p._handle)))
    return p


def main(name):
    m = modules.resolve(name)
    logs = Path(m["data"]) / "logs"; logs.mkdir(parents=True, exist_ok=True)
    job = join_kill_on_close_job()
    with open(logs / f"{m['name']}.console.log", "a", encoding="utf-8") as out:
        out.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} start {m['location']}: {' '.join(m['command'])} in {m['folder']}"
                  f"{'' if job else ' (no job object: the server may outlive this runner)'}\n"); out.flush()
        cmd = m["command"][:]; exe = Path(m["folder"]) / cmd[0]
        if exe.exists(): cmd[0] = str(exe)              # .venv\Scripts\python.exe relative to the module folder
        p = start_in_job(job, cmd, cwd=m["folder"], env={**os.environ, **m["env"]}, stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        return p.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
