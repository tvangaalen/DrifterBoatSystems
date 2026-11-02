"""tools/backup.py ("Backup keys and tokens"): exactly the listed key files are copied, in the data folder's layout,
replacing the previous copy; a missing one is reported and the others are still copied. Temporary folders only."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import backup as B  # noqa: E402

KEYS = ["anchor/pushover.json", "anchor/nfl.json", "guard/pushover.json", "guard/ezviz_token.json", "washer/viomi_config.json",
        "gateway/pushover.json"]


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.data, self.dest = self.tmp / "data", self.tmp / "dest"
        for f in KEYS[:-1] + ["anchor/anchor_state.json", "energy/data/history.sqlite3"]:
            (self.data / f).parent.mkdir(parents=True, exist_ok=True); (self.data / f).write_text(f"key of {f}")

    def test_copies_only_the_key_files(self):
        r = B.copy_keys(self.data, KEYS, self.dest)
        self.assertEqual(r["copied"], KEYS[:-1]); self.assertEqual([m["file"] for m in r["missing"]], ["gateway/pushover.json"])
        copied = sorted(p.relative_to(self.dest).as_posix() for p in self.dest.rglob("*") if p.is_file())
        self.assertEqual(copied, sorted(KEYS[:-1]))                       # no positions, track or history; no .part left
        self.assertEqual((self.dest / "guard/ezviz_token.json").read_text(), "key of guard/ezviz_token.json")
        self.assertIsNotNone(B.last_copy(self.dest, KEYS))

    def test_replaces_the_previous_copy(self):
        B.copy_keys(self.data, KEYS, self.dest); (self.data / "anchor/nfl.json").write_text("new key")
        B.copy_keys(self.data, KEYS, self.dest)
        self.assertEqual((self.dest / "anchor/nfl.json").read_text(), "new key")

    def test_nothing_copied_yet(self):
        self.assertIsNone(B.last_copy(self.dest, KEYS))

    def test_the_configured_list_is_the_key_files(self):
        self.assertEqual([f.replace("\\", "/") for f in B.config()["files"]], KEYS)


if __name__ == "__main__":
    unittest.main()
