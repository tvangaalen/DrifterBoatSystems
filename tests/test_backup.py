"""tools/backup.py and drifterd's nightly start: only the listed key files go into a back-up (a missing one is noted, the
others still saved), the 7-daily/4-weekly retention and the schedule. Temporary folders only."""
import json, sys, tempfile, unittest, zipfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import backup as B  # noqa: E402

KEYS = ["anchor/pushover.json", "anchor/nfl.json", "guard/pushover.json", "guard/ezviz_token.json", "washer/viomi_config.json"]


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.data, self.dest = self.tmp / "data", self.tmp / "dest"
        for f in KEYS[:-1] + ["anchor/anchor_state.json", "energy/data/history.sqlite3"]:
            (self.data / f).parent.mkdir(parents=True, exist_ok=True); (self.data / f).write_text("{}")

    def test_only_the_key_files(self):
        z = zipfile.ZipFile(B.make(self.data, KEYS, self.dest, datetime(2026, 11, 2, 3, 30)))
        self.assertEqual(set(z.namelist()), set(KEYS[:-1]) | {"manifest.json"})    # no positions, track or history
        m = json.loads(z.read("manifest.json"))
        self.assertEqual(m["created"], "2026-11-02T03:30:00")
        self.assertIn("error", m["files"][-1])                                         # the missing washer file is noted
        self.assertEqual(Path(z.filename).name, "drifter-20261102-0330.zip")

    def test_the_configured_list_is_the_key_files(self):
        self.assertEqual([f.replace("\\", "/") for f in B.config()["files"]], KEYS)

    def test_retention(self):
        self.dest.mkdir()
        now = datetime(2026, 11, 2, 3, 30)
        for d in range(60):                                     # one a night for 60 nights, two on the newest day
            (self.dest / (now - timedelta(days=d)).strftime(B.NAME)).write_bytes(b"z")
        (self.dest / now.replace(hour=12).strftime(B.NAME)).write_bytes(b"z"); (self.dest / "drifter-x.zip").write_bytes(b"other")
        B.prune(self.dest, 7, 4, now)
        kept = [t for t, _ in B.backups(self.dest)]
        self.assertEqual(len(kept), 11)                          # 7 days + 4 weeks
        self.assertEqual(kept[-1], now.replace(hour=12))         # the newest one of a day wins
        self.assertEqual(len({t.date() for t in kept}), 11)
        self.assertTrue((self.dest / "drifter-x.zip").exists())  # not ours: left alone

    def test_schedule(self):
        self.assertEqual(B.next_run("03:30", datetime(2026, 11, 2, 1, 0)), datetime(2026, 11, 2, 3, 30))
        self.assertEqual(B.next_run("03:30", datetime(2026, 11, 2, 3, 30)), datetime(2026, 11, 3, 3, 30))

    def test_drifterd_starts_it_once_a_night(self):
        import drifterd as D
        clock = [datetime(2026, 11, 2, 3, 29)]; started = []; done = [False]
        class P:
            returncode = 0
            def poll(self): return 0 if done[0] else None
        b = D.Backup(self.data, start=lambda: started.append(1) or P(), now=lambda: clock[0])
        b.tick(); self.assertEqual(started, [])
        clock[0] = datetime(2026, 11, 2, 3, 31); b.tick(); b.tick(); self.assertEqual(started, [1])   # never two at once
        done[0] = True; b.tick(); self.assertIsNone(b.failed)
        clock[0] = datetime(2026, 11, 2, 22, 0); b.tick(); self.assertEqual(started, [1])
        clock[0] = datetime(2026, 11, 3, 3, 30); b.tick(); self.assertEqual(started, [1, 1])


if __name__ == "__main__":
    unittest.main()
