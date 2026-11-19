"""tools/backup.py (System page: back-up and restore): exactly the listed key files and the engine log are copied, into a
dated folder in the data folder's layout; the newest `keep` are kept; the daily one runs once per slot (a missed slot at the
next start); a restore backs up the current files first, puts back only what differs and restarts what reads it.
Temporary folders and a fake clock only."""
import json, sys, tempfile, unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import backup as B  # noqa: E402

KEYS = ["pushover.json", "anchor/pushover.json", "anchor/nfl.json", "guard/pushover.json", "guard/ezviz_token.json", "washer/viomi_config.json",
        "gateway/pushover.json"]
MAINT = ["enginelog/log.json"]


def at(s: str) -> float: return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.data, self.dest = self.tmp / "data", self.tmp / "dest"
        for f in KEYS[:-1] + MAINT + ["anchor/anchor_state.json", "energy/data/history.sqlite3"]:
            (self.data / f).parent.mkdir(parents=True, exist_ok=True); (self.data / f).write_text(f"key of {f}")
        self.t = [at("2026-11-19 10:00:00")]; self.restarted = []
        self.b = B.Backups(self.data, KEYS, MAINT, self.data / "gateway" / "backup.json", self.dest, restart=self.restarted.append,
                           clock=lambda: self.t[0])

    def later(self, s: float): self.t[0] += s

    def test_copies_only_the_keys_and_the_engine_log(self):
        r = self.b.run()
        self.assertEqual(r["name"], "drifter-backup-20261119-100000"); self.assertFalse(r["ok"])
        self.assertEqual(r["copied"], KEYS[:-1] + MAINT); self.assertEqual([m["file"] for m in r["missing"]], ["gateway/pushover.json"])
        folder = self.dest / r["name"]
        copied = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        self.assertEqual(copied, sorted(KEYS[:-1] + MAINT + ["manifest.json"]))      # no history database, state or track; no .part
        self.assertEqual((folder / "enginelog/log.json").read_text(), "key of enginelog/log.json")
        self.assertEqual(self.b.list()[0], {"name": r["name"], "t": self.t[0], "reason": "by hand", "keys": 6, "maintenance": 1})
        self.assertEqual(self.b.info()["last"]["missing"], ["gateway/pushover.json"])

    def test_keeps_the_newest(self):
        self.b.set_settings({"keep": 3}); (self.dest / "other").mkdir()
        names = []
        for _ in range(5): names.append(self.b.run()["name"]); self.later(60)
        self.assertEqual([x["name"] for x in self.b.list()], names[:1:-1])
        self.assertTrue((self.dest / "other").is_dir())                                # nothing else in the folder is touched

    def test_settings(self):
        new = self.tmp / "elsewhere"
        s = self.b.set_settings({"dest": str(new), "daily": True, "at": "04:30", "keep": 10})
        self.assertEqual(s, {"dest": str(new), "daily": True, "at": "04:30", "keep": 10}); self.assertTrue(new.is_dir())
        self.assertEqual(B.Backups(self.data, KEYS, MAINT, self.data / "gateway" / "backup.json").settings()["at"], "04:30")
        for body, msg in [({"dest": "relative\\x"}, "Folder"), ({"dest": str(self.data / "sub")}, "not inside the data folder"),
                          ({"at": "3:00"}, "Time"), ({"at": "24:00"}, "Time"), ({"keep": 0}, "Keep"), ({"keep": True}, "Keep"),
                          ({"daily": "yes"}, "daily"), ({"colour": 1}, "unknown setting")]:
            with self.assertRaises(ValueError, msg=str(body)) as e: self.b.set_settings(body)
            self.assertIn(msg, str(e.exception))

    def test_daily(self):
        self.assertEqual(self.b.settings(), {"dest": str(self.dest), "daily": True, "at": "03:00", "keep": 30})
        self.assertIsNone(self.b.tick())                                               # first start at 10:00: waits for tomorrow 03:00
        self.assertEqual(self.b.next_run(), at("2026-11-20 03:00:00"))
        self.t[0] = at("2026-11-20 02:59:30"); self.assertIsNone(self.b.tick())
        self.t[0] = at("2026-11-20 03:00:10"); self.assertEqual(self.b.tick()["reason"], "daily")
        self.later(30); self.assertIsNone(self.b.tick())                               # once per slot
        self.t[0] = at("2026-11-23 09:15:00")                                          # the PC was off: made up once
        self.assertEqual(self.b.tick()["name"], "drifter-backup-20261123-091500"); self.later(30); self.assertIsNone(self.b.tick())
        self.b.set_settings({"at": "08:00"}); self.later(30); self.assertIsNone(self.b.tick())   # a new time counts from now
        self.b.set_settings({"daily": False}); self.t[0] = at("2026-11-24 09:00:00")
        self.assertIsNone(self.b.tick()); self.assertIsNone(self.b.next_run())
        self.assertEqual(len(self.b.list()), 2)

    def test_a_failed_daily_one_is_not_retried_every_tick(self):
        self.b.tick(); self.b.set_settings({"dest": str(self.tmp / "gone")}); (self.tmp / "gone").rmdir()
        (self.tmp / "gone").write_text("a file, not a folder")
        self.t[0] = at("2026-11-20 03:00:05"); r = self.b.tick()
        self.assertIn("cannot write", r["error"]); self.assertFalse(self.b.info()["last"]["ok"])
        self.later(30); self.assertIsNone(self.b.tick())

    def test_restore(self):
        name = self.b.run()["name"]; self.later(60)
        (self.data / "enginelog/log.json").write_text("lost entries"); (self.data / "guard/ezviz_token.json").write_text("broken")
        r = self.b.restore(name, "maintenance")
        self.assertEqual((r["restored"], r["restarted"]), (["enginelog/log.json"], ["enginelog"]))
        self.assertEqual((self.data / "enginelog/log.json").read_text(), "key of enginelog/log.json")
        self.assertEqual((self.data / "guard/ezviz_token.json").read_text(), "broken")                    # not asked for
        self.assertEqual((self.dest / r["before"] / "enginelog/log.json").read_text(), "lost entries")     # can be undone
        self.assertEqual(self.b.list()[0]["reason"], "before restore")
        self.later(60); self.restarted.clear()
        r = self.b.restore(name)
        self.assertEqual((r["restored"], self.restarted), (["guard/ezviz_token.json"], ["guard"]))
        self.assertIn("enginelog/log.json", r["unchanged"])

    def test_restore_refusals(self):
        name = self.b.run()["name"]; self.later(60)
        for n, w in (("../x", "all"), ("drifter-backup-20990101-000000", "all"), (name, "everything")):
            with self.assertRaises(ValueError): self.b.restore(n, w)

        def refuse(m): raise ValueError("the anchor watch has an alarm")
        self.b.restart = refuse; (self.data / "anchor/nfl.json").write_text("x")
        r = self.b.restore(name, "keys")
        self.assertEqual(r["not_restarted"], [{"module": "anchor", "error": "the anchor watch has an alarm"}])

    def test_manifest_cannot_reach_other_files(self):
        name = self.b.run()["name"]; folder = self.dest / name
        man = json.loads((folder / "manifest.json").read_text()); man["files"].append("../../evil.json")
        (folder / "manifest.json").write_text(json.dumps(man)); self.later(60)
        self.assertEqual(self.b.list()[-1]["keys"], 6)
        self.b.restore(name); self.assertFalse((self.data.parent / "evil.json").exists())

    def test_the_configured_lists(self):
        c = B.config()
        self.assertEqual([f.replace("\\", "/") for f in c["keys"]], KEYS); self.assertEqual([f.replace("\\", "/") for f in c["maintenance"]], MAINT)


if __name__ == "__main__":
    unittest.main()
