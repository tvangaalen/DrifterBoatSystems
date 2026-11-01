# v0.15.2 — Windows/iPhone disconnect log fix

When the iPhone Safari/PWA is closed, iOS can terminate an open HTTP socket
immediately. On Windows, Python's Proactor event loop may log:

```text
ConnectionResetError: [WinError 10054]
An existing connection was forcibly closed by the remote host
```

This is a normal client disconnect, not a MasterBus failure.

v0.15.2 installs a narrow asyncio exception handler that suppresses only
`ConnectionResetError` cases matching WinError/errno `10054`.

All other asyncio exceptions still go through the normal Uvicorn/Python error
handler.

## Start

```powershell
cd C:\temp\mastervoltproject;
py -m uvicorn app:app --host 0.0.0.0 --port 8000
```
