"""Processes for drifterd (Windows): every server runs in its own kill-on-close job object, so stopping it (or drifterd
ending) also ends everything it started (cmd, the venv launcher, the real Python). A server started before drifterd
(adopted) is stopped through the process listening on its port and the launchers above it. Stdlib (ctypes) only."""
from __future__ import annotations

import ctypes, os, subprocess
from ctypes import wintypes
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_SUSPENDED, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JobObjectExtendedLimitInformation = 0x4, 0x2000, 9
LAUNCHERS = ("cmd.exe", "py.exe", "pyw.exe", "python.exe", "pythonw.exe")   # walked up from a listener when stopping an adopted server


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _k():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE; k.GetCurrentProcess.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE; k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    return k


def new_job():
    """A kill-on-close job object handle, or None when Windows refuses."""
    k = _k(); job = k.CreateJobObjectW(None, None)
    if not job: return None
    info = _Extended(); info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(wintypes.HANDLE(job), JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)): return None
    return job


def join_job(job) -> bool:
    """Put this process in `job` (children started afterwards inherit it)."""
    return bool(_k().AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(_k().GetCurrentProcess())))


def start_in_job(job, cmd, **kw) -> subprocess.Popen:
    """Start cmd suspended, put it in `job`, then let it run. Assigning before it runs puts everything it starts (the venv
    launcher starts the real python) in the job too; an inherited job is not enough under Task Scheduler or a service."""
    p = subprocess.Popen(cmd, creationflags=kw.pop("creationflags", 0) | (CREATE_SUSPENDED if job else 0), **kw)
    if job:
        k = _k()
        if not k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(p._handle))):
            p.kill(); raise OSError(f"could not put {cmd[0]} in its job object (error {ctypes.get_last_error()})")
        ctypes.WinDLL("ntdll").NtResumeProcess(wintypes.HANDLE(int(p._handle)))
    return p


def job_pids(job) -> list[int]:
    """The process ids in the job (JobObjectBasicProcessIdList)."""
    class _List(ctypes.Structure):
        _fields_ = [("Assigned", wintypes.DWORD), ("InList", wintypes.DWORD), ("Ids", ctypes.c_size_t * 256)]
    lst = _List()
    if not _k().QueryInformationJobObject(wintypes.HANDLE(job), 3, ctypes.byref(lst), ctypes.sizeof(lst), None): return []
    return [int(lst.Ids[i]) for i in range(lst.InList)]


def end_job(job, wait: float = 10) -> None:
    """Ends every process in the job, waits (up to `wait` s) until each is gone, then closes the job. Waiting on the
    direct child is not enough: the venv launcher's real python can still hold the console log for a moment."""
    k = _k(); handles = []
    for pid in job_pids(job):
        h = k.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE
        if h: handles.append(h)
    try:
        k.TerminateJobObject(wintypes.HANDLE(job), 1)
        for h in handles: k.WaitForSingleObject(wintypes.HANDLE(h), int(wait * 1000))
    finally:
        for h in handles: k.CloseHandle(wintypes.HANDLE(h))
        k.CloseHandle(wintypes.HANDLE(job))


def rotate(log: Path, limit: int = 5_000_000) -> None:
    """Keep a console log bounded: at a start, the previous file over `limit` bytes moves to .log.1."""
    try:
        if log.stat().st_size > limit: os.replace(log, log.with_suffix(".log.1"))
    except OSError: pass


# ---- adopted servers (not started by this drifterd)
def listener_pid(port: int) -> int | None:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[0] == "TCP" and p[3] == "LISTENING" and p[1].rsplit(":", 1)[-1] == str(port): return int(p[4])
    return None


class _PE(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32), ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


def processes() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, exe name) of every process (Toolhelp snapshot)."""
    k = _k(); snap = k.CreateToolhelp32Snapshot(2, 0); e = _PE(); e.dwSize = ctypes.sizeof(_PE); out = {}
    try:
        ok = k.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok: out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower()); ok = k.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally: k.CloseHandle(wintypes.HANDLE(snap))
    return out


def ancestors(pid: int, procs: dict) -> set[int]:
    out = set()
    while pid and pid in procs and pid not in out: out.add(pid); pid = procs[pid][0]
    return out


def chain(pid: int, procs: dict | None = None) -> list[int]:
    """The process and the launchers directly above it (cmd, py/pyw, venv python), as stop_module.ps1 did; never this
    process or one above it (drifterd itself is a python.exe)."""
    procs = procs if procs is not None else processes(); out = []; mine = ancestors(os.getpid(), procs)
    while pid and pid in procs and pid not in out and pid not in mine:
        if out and procs[pid][1] not in LAUNCHERS: break
        out.append(pid); pid = procs[pid][0]
    return out


def kill(pid: int) -> bool:
    k = _k(); h = k.OpenProcess(0x0001, False, pid)        # PROCESS_TERMINATE
    if not h: return False
    try: return bool(k.TerminateProcess(wintypes.HANDLE(h), 1))
    finally: k.CloseHandle(wintypes.HANDLE(h))
