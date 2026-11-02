"""Copies the keys and tokens that cannot be made again without the services themselves to C:\\DrifterBackups: the
Pushover keys (anchor watch, BoatGuard), the noforeignland.com keys, the EZVIZ session and the washer's token
(backup.files in modules.json). Only on request: the button "Backup keys and tokens" on the System page (through the
gateway), or by hand. Nothing runs on a schedule, and no positions, track or history are copied (the user's choice).

    py -3.12 tools/backup.py          copy them now

Each file goes to <dest>\\<module>\\<file>, the same layout as C:\\DrifterData, replacing the previous copy. A missing file
is reported and the others are still copied. Stdlib only. Restoring: docs/RUNBOOK.md.
"""
from __future__ import annotations

import os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import modules as M  # noqa: E402


def config() -> dict:
    b = M.spec().get("backup", {})
    return {"dest": Path(os.path.expandvars(b.get("dest", r"C:\DrifterBackups"))), "files": list(b.get("files", []))}


def copy_keys(data: Path, files: list[str], dest: Path) -> dict:
    """Copies each of `files` (relative to `data`) to the same place under `dest`; a copy is written next to its target
    first, so a failed copy never leaves half a key file. Returns what was copied and what was missing."""
    copied, missing = [], []
    for rel in files:
        src, dst = Path(data) / rel, Path(dest) / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part"); shutil.copy2(src, tmp); tmp.replace(dst)
            copied.append(rel.replace("\\", "/"))
        except OSError as e:
            missing.append({"file": rel.replace("\\", "/"), "error": f"{type(e).__name__}: {e.strerror or e}"})
    return {"dest": str(dest), "copied": copied, "missing": missing, "t": time.time()}


def last_copy(dest: Path, files: list[str]) -> float | None:
    """When the copies were made (the newest copy's time), or None when there are none."""
    times = [(Path(dest) / rel).stat().st_mtime for rel in files if (Path(dest) / rel).is_file()]
    return max(times) if times else None


def main() -> int:
    cfg = config(); r = copy_keys(M.DATA, cfg["files"], cfg["dest"])
    print(f"{len(r['copied'])} of {len(cfg['files'])} files copied to {r['dest']}")
    for m in r["missing"]: print(f"  not copied: {m['file']} ({m['error']})")
    return 1 if r["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
