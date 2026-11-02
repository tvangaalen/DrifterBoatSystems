"""Back-ups of the keys on the boat PC that git does not hold and that cannot be made again without the services
themselves: the Pushover keys (anchor watch, BoatGuard), the noforeignland.com keys, the EZVIZ session and the washer's
token. Only these files (backup.files in modules.json; the user's choice of 2026-11-02): no positions, track or history.

    py -3.12 tools/backup.py run      make one now, then keep 7 daily and 4 weekly ones (drifterd runs this every night)
    py -3.12 tools/backup.py list     the back-ups there are

One zip per back-up, drifter-YYYYMMDD-HHMM.zip, in backup.dest of modules.json (C:\\DrifterBackups), with a manifest.json
of the files and their sizes. A file that is missing is noted in the manifest and the log; the others are still saved.
Stdlib only, on the plain python.org Python. Restoring: docs/RUNBOOK.md.
"""
from __future__ import annotations

import argparse, json, logging, os, sys, time, zipfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from common import logs  # noqa: E402
import modules as M  # noqa: E402

log = logging.getLogger("drifter.backup")
NAME = "drifter-%Y%m%d-%H%M.zip"


def config() -> dict:
    b = M.spec().get("backup", {})
    return {"at": b.get("at", "03:30"), "dest": Path(os.path.expandvars(b.get("dest", r"C:\DrifterBackups"))),
            "daily": int(b.get("daily", 7)), "weekly": int(b.get("weekly", 4)), "files": list(b.get("files", []))}


def make(data: Path, files: list[str], dest: Path, now: datetime | None = None) -> Path:
    """Zips `files` (relative to the data folder) into a new back-up in `dest`."""
    now = now or datetime.now(); dest.mkdir(parents=True, exist_ok=True)
    target = dest / now.strftime(NAME); part = target.with_suffix(".zip.part"); manifest = []
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            f = data / rel
            try: z.write(f, rel); manifest.append({"file": rel, "bytes": f.stat().st_size})
            except OSError as e: log.warning("backup: %s missing: %s", rel, e); manifest.append({"file": rel, "error": str(e)})
        z.writestr("manifest.json", json.dumps({"created": now.isoformat(timespec="seconds"), "data": str(data), "files": manifest}, indent=1))
    part.replace(target)
    log.info("backup: %s, %d of %d files", target.name, sum("bytes" in m for m in manifest), len(files))
    return target


def backups(dest: Path) -> list[tuple[datetime, Path]]:
    out = []
    for f in dest.glob("drifter-*.zip"):
        try: out.append((datetime.strptime(f.name, NAME), f))
        except ValueError: pass
    return sorted(out)


def prune(dest: Path, daily: int = 7, weekly: int = 4, now: datetime | None = None) -> list[Path]:
    """Keeps the newest back-up of each of the last `daily` days and of each of the last `weekly` ISO weeks before them;
    removes the others and stale .part files. Never removes the newest back-up."""
    now = now or datetime.now(); found = backups(dest); keep: set[Path] = set()
    if found: keep.add(found[-1][1])
    days, weeks = {}, {}
    for t, f in found: days[t.date()] = f; weeks[t.isocalendar()[:2]] = f         # newest of each day / week wins
    for d in sorted(days, reverse=True)[:daily]: keep.add(days[d])
    first_day = min((d for d in sorted(days, reverse=True)[:daily]), default=now.date())
    older = [w for w in sorted(weeks, reverse=True) if datetime.fromisocalendar(w[0], w[1], 7).date() < first_day]
    for w in older[:weekly]: keep.add(weeks[w])
    gone = [f for _, f in found if f not in keep]
    for f in gone: f.unlink(); log.info("backup: removed %s", f.name)
    for p in dest.glob("*.zip.part"):
        if time.time() - p.stat().st_mtime > 6 * 3600: p.unlink()
    return gone


def next_run(at: str, now: datetime) -> datetime:
    h, m = (int(x) for x in at.split(":")); t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["run", "list"])
    ap.add_argument("--dest", help="back-up folder (default: backup.dest in modules.json)")
    a = ap.parse_args(argv); cfg = config(); dest = Path(a.dest) if a.dest else cfg["dest"]
    if a.command == "list":
        for t, f in backups(dest): print(f"{t:%Y-%m-%d %H:%M}  {f.stat().st_size:8} bytes  {f}")
        return 0
    logs.setup(log, M.DATA / "logs" / "backup.log")
    try: make(M.DATA, cfg["files"], dest); prune(dest, cfg["daily"], cfg["weekly"])
    except Exception:
        log.exception("backup failed"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
