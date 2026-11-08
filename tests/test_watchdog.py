"""The gateway's watchdog (drifter.Watchdog): a push message when a system has been down (not running, or not answering
its health check) for 5 minutes, one when it is back, never twice, and nothing for a module on hold or after "Switch
all systems off". A fake supervisor and a fake clock; nothing is sent."""
import json, sys, tempfile, unittest, unittest.mock
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
        self.dir = Path(tempfile.mkdtemp())
        self.dog = drifter.Watchdog(self.sup, self.dir / "gateway" / "pushover.json", clock=lambda: self.t[0],
                                    send=lambda title, msg, event: self.sent.append((title, msg, event)), shared=self.dir / "pushover.json")

    def at(self, minutes): self.t[0] = 1_800_000_000.0 + minutes * 60; self.dog.check()

    def test_down_for_five_minutes_then_back(self):
        self.sup.mods["energy"] = {"state": "failed", "held": False}
        self.at(0); self.at(4); self.assertEqual(self.sent, [])                  # a restart takes less than 5 minutes
        self.at(5); self.at(6)
        self.assertEqual(len(self.sent), 1); title, msg, prio = self.sent[0]
        self.assertEqual((title, prio), ("Drifter: Energy down", "down_high")); self.assertIn("Float protection", msg)
        self.sup.mods["energy"] = dict(UP); self.at(12)
        self.assertEqual(self.sent[-1][:1], ("Drifter: Energy back",)); self.assertIn("down 12 min", self.sent[-1][1])
        self.at(20); self.assertEqual(len(self.sent), 2)

    def test_not_answering_counts_and_guard_is_normal_priority(self):
        self.sup.mods["guard"] = {"state": "running", "health": {"ok": False}, "held": False}
        self.at(0); self.at(5)
        self.assertEqual(self.sent[0][0], "Drifter: BoatGuard down"); self.assertIn("not answering", self.sent[0][1]); self.assertEqual(self.sent[0][2], "down")

    def test_quiet_on_hold_switched_off_or_without_drifterd(self):
        self.sup.mods["washer"] = {"state": "held", "held": True}; self.at(0); self.at(10)
        self.sup.mods["anchor"] = {"state": "down", "held": False}; self.sup.shutdown = {"state": "running"}; self.at(11); self.at(30)
        self.sup.shutdown = None; self.sup.error = "drifterd not reachable"; self.at(31); self.at(40)
        self.assertEqual(self.sent, [])

    def test_keys(self):
        self.assertIsNone(self.dog.keys()); self.assertFalse(self.dog.status()["configured"])
        with self.assertRaises(ValueError): self.dog.test()
        self.dog.key_file.parent.mkdir()
        self.dog.key_file.write_text(json.dumps({"token": "a" * 30, "user": "b" * 30}))  # privacy: ok
        self.assertTrue(self.dog.status()["configured"]); self.assertEqual(self.dog.status()["source"], "gateway")
        # the shared keys (System page) win over the older file, are never answered in full
        with self.assertRaises(ValueError): self.dog.set_keys({"app_token": "short", "user_key": ""})
        r = self.dog.set_keys({"app_token": "c" * 30, "user_key": ""})  # privacy: ok
        self.assertEqual((r["app_token"], r["user_key"], r["configured"]), ("…cccc", "", False))
        self.assertEqual(self.dog.status()["source"], "gateway")                       # incomplete: the older keys still count
        self.dog.set_keys({"user_key": "d" * 30})  # privacy: ok
        self.assertEqual(self.dog.keys(), {"token": "c" * 30, "user": "d" * 30}); self.assertEqual(self.dog.status()["source"], "shared")
        self.assertNotIn("c" * 30, json.dumps(self.dog.status()))

    def test_priority_and_sound(self):
        self.assertEqual(self.dog.prefs()["down_high"], {"on": True, "priority": 1, "sound": ""})
        self.dog.set_prefs({"back": {"priority": -1, "sound": "bike"}})
        self.assertEqual(self.dog.prefs()["back"], {"on": True, "priority": -1, "sound": "bike"}); self.assertEqual(self.dog.prefs()["down"]["priority"], 0)
        for bad in ({"back": {"priority": 2}}, {"back": {"sound": "boom"}}, {"other": {}}, {"back": {"priority": True}}):
            with self.assertRaises(ValueError): self.dog.set_prefs(bad)
        posted = []
        self.dog.key_file.parent.mkdir(exist_ok=True); self.dog.key_file.write_text(json.dumps({"token": "a" * 30, "user": "b" * 30}))  # privacy: ok
        with unittest.mock.patch.object(drifter.pushover, "post", lambda path, fields, agent: posted.append(fields)):
            self.dog._post("t", "m", "back")
        self.assertEqual((posted[0]["priority"], posted[0]["sound"]), (-1, "bike"))
        self.dog.set_prefs({"back": {"on": False}}); posted.clear()
        with unittest.mock.patch.object(drifter.pushover, "post", lambda path, fields, agent: posted.append(fields)):
            self.dog._post("t", "m", "back"); self.assertEqual(posted, [])                 # switched off
            self.dog.test(); self.assertEqual(len(posted), 1)                              # the test is sent anyway
            self.dog.test("down_high", "siren", -1)                                        # one alert, with the choices on the page
            self.assertEqual((posted[-1]["priority"], posted[-1]["sound"]), (-1, "siren")); self.assertIn("Energy or anchor watch down", posted[-1]["title"])
            self.dog.test("back"); self.assertEqual(posted[-1]["priority"], -1)            # its saved priority (set above)
        for bad in (("nope", None, None), ("down", "boom", None), ("down", None, 2)):
            with self.assertRaises(ValueError): self.dog.test(*bad)
        with self.assertRaises(ValueError): self.dog.set_prefs({"back": {"on": "no"}})


if __name__ == "__main__":
    unittest.main()
