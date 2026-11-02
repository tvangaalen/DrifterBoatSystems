"""tools/verify_live.py: the module checks on payloads shaped like the live ones (made-up values), and the retry rule."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import verify_live as V  # noqa: E402

BATS = {"BATTERY 1": {}, "BATTERY 2": {}, "BATTERY 3": {}}


class Checks(unittest.TestCase):
    def failed(self, results): return [t for ok, t in results if not ok]

    def test_energy(self):
        good = V.check_energy({"connected_count": 3, "batteries": BATS, "ble_available": True, "control_status": {"busy": False}},
                              {"high_soc_float_policy": {"float_latched": False}})
        self.assertEqual(self.failed(good), [])
        bad = V.check_energy({"connected_count": 1, "batteries": BATS, "ble_available": True, "control_status": {"busy": True}},
                             {"high_soc_float_policy": {"float_latched": True}})
        self.assertEqual(self.failed(bad), ["BMS units connected: 1/3", "no BMS control busy", "Float not latched"])
        self.assertTrue(self.failed(V.check_energy({}, {})))          # no answer is a failure, not a pass

    def test_anchor(self):
        state = {"core": {"connected": True}, "nmea": {"on": True, "port": 10110, "error": None}, "push": {"configured": True},
                 "alive": {"configured": True}, "alarms": []}
        self.assertEqual(self.failed(V.check_anchor(state)), [])
        state.update(core={"connected": False, "last_error": "timeout"}, alarms=[{"text": "Anchor drag"}])
        self.assertEqual(self.failed(V.check_anchor(state)), ["Orca Core connected: timeout", "ALARM: Anchor drag"])

    def test_guard_and_washer(self):
        self.assertEqual(self.failed(V.check_guard({"router_ok": True, "camera": {"online": True, "battery": 90}})), [])
        self.assertEqual(self.failed(V.check_guard({"router_ok": False, "camera": {}})), ["router reachable", "camera online (battery None%)"])
        self.assertEqual(self.failed(V.check_washer({"power_text": "Off", "status_text": "Standby"})), [])
        self.assertTrue(self.failed(V.check_washer({})))

    def test_retry_only_for_checks_that_can_come_right(self):
        retried = V.retryable
        self.assertTrue(retried("BMS units connected: 0/3") and retried("Orca Core connected: timeout"))
        self.assertTrue(retried("/health: no answer (HTTP 0)") and retried("supervisor: starting, health None") and retried("gateway reaches it: None"))
        self.assertFalse(retried("Float not latched") or retried("ALARM: Anchor drag") or retried("refused without token (HTTP 200)"))
        self.assertTrue(retried("refused without token (HTTP 0)"))


if __name__ == "__main__":
    unittest.main()
