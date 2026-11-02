"""The gateway's watchdog (drifter.Watchdog): a push message when a system has been down (not running, or not answering
its health check) for 5 minutes, one when it is back, never twice, and nothing for a module on hold or after "Switch
all systems off". A fake supervisor and a fake clock; nothing is sent."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import drifter  # noqa: E402

UP = {"state": "running", "health": {"ok": True}, "held": False}


class FakeSup:
    def __init__(self): self.mods = {n: dict(UP) for n in ("energy", "anchor", "guard", "washer")}; self.shutdown = None; self.error = None
    def snapshot(self): return {"modules": self.mods, "shutdown": self.shutdown, **({"error": self.error} if self.error else {})}


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.sup, self.t, self.sent = FakeSup(), [1_800_000_000.0], []
        self.dog = drifter.Watchdog(self.sup, Path(tempfile.mkdtemp()) / "pushover.json", clock=lambda: self.t[0],
                                    send=lambda title, msg, prio: self.sent.append((title, msg, prio)))

    def at(self, minutes): self.t[0] = 1_800_000_000.0 + minutes * 60; self.dog.check()

    def test_down_for_five_minutes_then_back(self):
        self.sup.mods["energy"] = {"state": "failed", "held": False}
        self.at(0); self.at(4); self.assertEqual(self.sent, [])                  # a restart takes less than 5 minutes
        self.at(5); self.at(6)
        self.assertEqual(len(self.sent), 1); title, msg, prio = self.sent[0]
        self.assertEqual((title, prio), ("Drifter: Energy down", 1)); self.assertIn("Float protection", msg)
        self.sup.mods["energy"] = dict(UP); self.at(12)
        self.assertEqual(self.sent[-1][:1], ("Drifter: Energy back",)); self.assertIn("down 12 min", self.sent[-1][1])
        self.at(20); self.assertEqual(len(self.sent), 2)

    def test_not_answering_counts_and_guard_is_normal_priority(self):
        self.sup.mods["guard"] = {"state": "running", "health": {"ok": False}, "held": False}
        self.at(0); self.at(5)
        self.assertEqual(self.sent[0][0], "Drifter: BoatGuard down"); self.assertIn("not answering", self.sent[0][1]); self.assertEqual(self.sent[0][2], 0)

    def test_quiet_on_hold_switched_off_or_without_drifterd(self):
        self.sup.mods["washer"] = {"state": "held", "held": True}; self.at(0); self.at(10)
        self.sup.mods["anchor"] = {"state": "down", "held": False}; self.sup.shutdown = {"state": "running"}; self.at(11); self.at(30)
        self.sup.shutdown = None; self.sup.error = "drifterd not reachable"; self.at(31); self.at(40)
        self.assertEqual(self.sent, [])

    def test_keys(self):
        self.assertIsNone(self.dog.keys()); self.assertFalse(self.dog.status()["configured"])
        with self.assertRaises(ValueError): self.dog.test()
        self.dog.key_file.write_text(json.dumps({"token": "a" * 30, "user": "b" * 30}))  # privacy: ok
        self.assertTrue(self.dog.status()["configured"])


if __name__ == "__main__":
    unittest.main()
