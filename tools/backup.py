"""Back-up and restore of the keys and tokens and the engine log (maintenance, fuel fills, engine alarms), the files that
cannot be made again without the services or the user: the Pushover keys, the noforeignland.com keys, the EZVIZ session,
the washer's token (backup.keys in modules.json) and enginelog\\log.json (backup.maintenance). Never MasterVolt's history
database, the track, the anchor state or logs (the user's choice: a back-up stays small).

Each back-up is a folder <dest>\\drifter-backup-YYYYMMDD-HHMMSS with the files in the data folder's layout and a
manifest.json (when, why, which files). The newest `keep` back-ups are kept, older ones of that name are removed; nothing
else in <dest> is touched. The folder, a daily time and how many to keep are set on the System page
(<data>\\gateway\\backup.json); the live gateway runs the daily one (Backups.start) and the buttons Back up now / Restore.
A restore first backs up the current files ("before restore"), so it can be undone, then puts the chosen files back.
Restarting the modules that read them is the caller's (the gateway, through drifterd).

    py -3.12 tools/backup.py                 back up now
    py -3.12 tools/backup.py list            the back-ups, newest first
    py -3.12 tools/backup.py restore NAME    put them back (then restart the modules it names)

Stdlib only. Restoring by hand: docs/RUNBOOK.md.
"""
from __future__ import annotations

import json, logging, os, re, shutil, sys, threading, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import modules as M  # noqa: E402

log = logging.getLogger("drifter.backup")
NAME = re.compile(r"drifter-backup-\d{8}-\d{6}")
DEFAULTS = {"dest": r"C:\DrifterBackups", "daily": True, "at": "03:00", "keep": 30}
KEEP = (1, 365)
WHAT = ("all", "keys", "maintenance")
RESTART = ("anchor", "guard", "washer", "enginelog")   # modules that read these files only at start


def config() -> dict:
    b = M.spec().get("backup", {})
    return {"dest": Path(os.path.expandvars(b.get("dest", DEFAULTS["dest"]))), "keys": list(b.get("keys", [])),
            "maintenance": list(b.get("maintenance", []))}


def _rel(p: str) -> str: return p.replace("\\", "/")


def _copy(src: Path, dst: Path) -> None:
    """A copy is written next to its target first, so a failed copy never leaves half a file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part"); shutil.copy2(src, tmp); tmp.replace(dst)


class Backups:
    """The back-ups of one data folder. `settings_file` keeps the choices and when the daily one last ran."""

    def __init__(self, data: Path, keys: list[str], maintenance: list[str], settings_file: Path, default_dest: Path | str | None = None,
                 restart=None, clock=time.time):
        self.data, self.keys, self.maint = Path(data), [_rel(k) for k in keys], [_rel(k) for k in maintenance]
        self.file, self.clock, self.restart = Path(settings_file), clock, restart
        self.defaults = {**DEFAULTS, "dest": str(default_dest or DEFAULTS["dest"])}
        self.lock = threading.Lock(); self.busy = None; self._stop = threading.Event()

    @classmethod
    def live(cls, restart=None) -> "Backups":
        c = config()
        return cls(M.DATA, c["keys"], c["maintenance"], M.DATA / "gateway" / "backup.json", c["dest"], restart)

    # settings -----------------------------------------------------------------------------------------------------------
    def _state(self) -> dict:
        try: s = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError): s = {}
        return s if isinstance(s, dict) else {}

    def _save_state(self, s: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True); tmp = self.file.with_name(self.file.name + ".part")
        tmp.write_bytes(json.dumps(s, indent=1).encode()); tmp.replace(self.file)

    def settings(self) -> dict:
        s = self._state(); return {k: s.get(k, v) for k, v in self.defaults.items()}

    def check_dest(self, dest: str) -> Path:
        d = str(dest or "").strip()
        p = Path(d)
        if not d or len(d) > 200 or not (re.match(r"^[A-Za-z]:\\", d) or d.startswith("\\\\")) or ".." in p.parts:
            raise ValueError("Folder: a full path, like C:\\DrifterBackups or \\\\nas\\share\\Drifter")
        for inside, what in ((self.data, "the data folder"), (M.LIVE, "the app's folder")):
            r, i = os.path.normcase(os.path.abspath(d)), os.path.normcase(os.path.abspath(inside))
            if r == i or r.startswith(i.rstrip("\\/") + os.sep): raise ValueError(f"Folder: not inside {what} ({inside})")
        return p

    def set_settings(self, body) -> dict:
        if not isinstance(body, dict): raise ValueError("invalid settings")
        unknown = set(body) - set(DEFAULTS)
        if unknown: raise ValueError(f"unknown setting {sorted(unknown)[0]}")
        new = {**self.settings(), **body}
        dest = self.check_dest(new["dest"])
        if not isinstance(new["daily"], bool): raise ValueError("daily must be true or false")
        if not (isinstance(new["at"], str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", new["at"])): raise ValueError("Time: HH:MM, 24-hour")
        k = new["keep"]
        if isinstance(k, bool) or not isinstance(k, int) or not KEEP[0] <= k <= KEEP[1]: raise ValueError(f"Keep: a whole number from {KEEP[0]} to {KEEP[1]}")
        try: dest.mkdir(parents=True, exist_ok=True)
        except OSError as e: raise ValueError(f"Folder: cannot make or use {dest} ({e.strerror or e})") from None
        s = self._state(); s.update({"dest": str(dest), "daily": new["daily"], "at": new["at"], "keep": k})
        s["slot_done"] = self._slot(self.clock(), new["at"])          # a new time counts from now: no back-up at once
        self._save_state(s); log.info("back-up settings: %s, daily %s at %s, keep %d", dest, new["daily"], new["at"], k)
        return self.settings()

    # back up -------------------------------------------------------------------------------------------------------------
    def files(self, what: str = "all") -> list[str]:
        return (self.keys if what in ("all", "keys") else []) + (self.maint if what in ("all", "maintenance") else [])

    def run(self, reason: str = "by hand") -> dict:
        """One back-up of every file now. A missing file is reported and the others are still copied."""
        with self.lock:
            dest = Path(self.settings()["dest"]); t = self.clock()
            name = "drifter-backup-" + datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S")
            folder = dest / name
            if folder.exists(): raise ValueError("a back-up was made this second; try again")
            copied, missing = [], []
            try: folder.mkdir(parents=True)
            except OSError as e: return self._result(t, reason, name, [], [], f"cannot write to {dest}: {e.strerror or e}")
            for rel in self.files():
                try: _copy(self.data / rel, folder / rel); copied.append(rel)
                except OSError as e: missing.append({"file": rel, "error": f"{type(e).__name__}: {e.strerror or e}"})
            man = {"t": t, "reason": reason, "files": copied, "missing": missing}
            try: (folder / "manifest.json").write_bytes(json.dumps(man, indent=1).encode())
            except OSError as e: return self._result(t, reason, name, copied, missing, f"cannot write to {dest}: {e.strerror or e}")
            removed = self._prune(dest, self.settings()["keep"])
            return self._result(t, reason, name, copied, missing, None if copied else "no file could be copied", removed)

    def _result(self, t, reason, name, copied, missing, error, removed=()) -> dict:
        r = {"t": t, "reason": reason, "name": name, "dest": self.settings()["dest"], "copied": copied, "missing": missing,
             "error": error, "removed": list(removed), "ok": not error and not missing}
        s = self._state(); s["last"] = {k: r[k] for k in ("t", "reason", "name", "ok", "error")} | {"missing": [m["file"] for m in missing]}
        self._save_state(s)
        (log.warning if not r["ok"] else log.info)("back-up %s (%s) to %s: %d of %d files%s%s", name, reason, r["dest"], len(copied),
                                                    len(self.files()), "".join(f"; {m['file']} not copied ({m['error']})" for m in missing),
                                                    f"; {error}" if error else "")
        return r

    def _prune(self, dest: Path, keep: int) -> list[str]:
        old = [b["name"] for b in self.list(dest)][keep:]
        for n in old:
            try: shutil.rmtree(dest / n)
            except OSError as e: log.warning("could not remove old back-up %s: %s", n, e)
        return old

    def list(self, dest: Path | None = None) -> list[dict]:
        """The back-ups in the folder, newest first: name, time, why, the files in it."""
        dest = Path(dest or self.settings()["dest"]); out = []
        try: entries = list(dest.iterdir())
        except OSError: return []
        for d in entries:
            if not (NAME.fullmatch(d.name) and d.is_dir()): continue
            try: man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            files = [f for f in man.get("files", []) if f in self.keys + self.maint and (d / f).is_file()]
            out.append({"name": d.name, "t": man.get("t"), "reason": man.get("reason", ""), "keys": sum(f in self.keys for f in files),
                        "maintenance": sum(f in self.maint for f in files)})
        return sorted(out, key=lambda b: b["name"], reverse=True)

    # restore -------------------------------------------------------------------------------------------------------------
    def restore(self, name: str, what: str = "all") -> dict:
        """Puts the files of back-up `name` back in the data folder (`what`: all, keys or maintenance), after backing up the
        current ones. Only the listed files, only those that differ. Restarts (through `restart`) the modules that read
        a changed file at start; one that refuses (an alarm, a BMS control) is named in `not_restarted`."""
        if what not in WHAT: raise ValueError("what: all, keys or maintenance")
        if not (isinstance(name, str) and NAME.fullmatch(name)): raise ValueError("no such back-up")
        src = Path(self.settings()["dest"]) / name
        if name not in [b["name"] for b in self.list()]: raise ValueError("no such back-up")
        files = [f for f in self.files(what) if (src / f).is_file()]
        if not files: raise ValueError("that back-up has none of these files")
        before = self.run("before restore")
        if before["error"]: raise RuntimeError(f"the current files could not be backed up first: {before['error']}")
        changed, same = [], []
        with self.lock:
            for f in files:
                cur = self.data / f
                if cur.is_file() and cur.read_bytes() == (src / f).read_bytes(): same.append(f); continue
                _copy(src / f, cur); changed.append(f)
        mods = sorted({f.split("/")[0] for f in changed} & set(RESTART))
        restarted, not_restarted = [], []
        for m in mods:
            try:
                if self.restart: self.restart(m)
                restarted.append(m)
            except Exception as e: not_restarted.append({"module": m, "error": str(e)})
        log.info("restored %s (%s): %d changed, %d the same; restarted %s%s; the files before it are in %s", name, what, len(changed),
                 len(same), ", ".join(restarted) or "nothing", "".join(f"; {x['module']} not restarted ({x['error']})" for x in not_restarted), before["name"])
        return {"name": name, "what": what, "restored": changed, "unchanged": same, "restarted": restarted, "not_restarted": not_restarted,
                "before": before["name"]}

    # the daily one -------------------------------------------------------------------------------------------------------
    @staticmethod
    def _slot(t: float, at: str) -> float:
        """The latest daily time `at` (HH:MM, local) at or before `t`."""
        now = datetime.fromtimestamp(t); h, m = map(int, at.split(":"))
        s = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return (s if s <= now else s - timedelta(days=1)).timestamp()

    def due(self) -> float | None:
        """The slot to back up for now, or None. A slot missed while the PC was off is made up once at the next start."""
        s = self.settings()
        if not s["daily"]: return None
        slot = self._slot(self.clock(), s["at"]); done = self._state().get("slot_done")
        if done is None:                                   # the first start with this feature: wait for the first slot
            st = self._state(); st["slot_done"] = slot; self._save_state(st); return None
        return slot if slot > done else None

    def tick(self) -> dict | None:
        slot = self.due()
        if slot is None: return None
        st = self._state(); st["slot_done"] = slot; self._save_state(st)     # one try per slot, also when it fails
        try: return self.run("daily")
        except Exception as e: log.warning("daily back-up failed: %s", e); return None

    def next_run(self) -> float | None:
        s = self.settings()
        if not s["daily"]: return None
        slot = self._slot(self.clock(), s["at"])
        return slot if self.due() else slot + 86400

    def start(self, every: float = 30) -> None:
        def loop():
            while not self._stop.wait(every):
                try: self.tick()
                except Exception as e: log.warning("back-up schedule: %s", e)
        threading.Thread(target=loop, name="backup", daemon=True).start()

    def info(self) -> dict:
        """For the System page."""
        s = self.settings()
        return {**s, "keys": len(self.keys), "maintenance": len(self.maint), "last": self._state().get("last"), "next": self.next_run(),
                "backups": self.list()[:60], "keep_limits": list(KEEP)}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    b = Backups.live()
    if argv[:1] == ["list"]:
        for x in b.list(): print(f"{x['name']}  {x['reason']:<14} {x['keys']} keys, {x['maintenance']} engine log")
        return 0
    if argv[:1] == ["restore"] and len(argv) >= 2:
        r = b.restore(argv[1], argv[2] if len(argv) > 2 else "all")
        print(f"restored {len(r['restored'])} files; the files before it are in {r['before']}")
        mods = sorted({f.split('/')[0] for f in r["restored"]} & set(RESTART))
        if mods: print("restart these on the System page: " + ", ".join(mods))
        return 0
    if argv: sys.exit(__doc__)
    r = b.run("by hand"); print(f"{len(r['copied'])} of {len(b.files())} files copied to {r['dest']}\\{r['name']}")
    for m in r["missing"]: print(f"  not copied: {m['file']} ({m['error']})")
    if r["error"]: print(f"  {r['error']}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
