"""Code shared by the Drifter gateway and the module servers (stdlib only).

- `net`: which addresses a server may bind to, DNS-rebinding and same-origin checks.
- `web`: HTTPS context and the quiet threading server of the stdlib servers.
- `logs`: one log format (24-hour clock), optional rotating log file.
- `timefmt`: 24-hour clock texts.
- `pushover`: posting to the Pushover API; queueing and retries stay in each module.
- `issue_cert.ps1`: a server certificate from the existing Mastervolt Local CA (never creates a CA).

A module imports it after putting the repository root on `sys.path` (two folders up from `modules/<name>`).
MasterVolt (energy) does not use it: it owns the CA and has its own launcher and package.
"""
