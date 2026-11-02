"""tools/privacy_scan.py: what it refuses and what it lets through. The suspicious strings are built from pieces so this
file itself passes the scan."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import privacy_scan as P  # noqa: E402


def scan(text, deny=(), file="x.py"): return P.scan([(file, 1, text)], list(deny))


class PrivacyScanTest(unittest.TestCase):
    def test_refused(self):
        for text, what in [("anchor = 12.3" + "45678, 3.4" + "56789", "position"), ("at 12.3" + "45678/3.4" + "56789", "position"),
                           ("mac = 'aa:bb:" + "cc:dd:ee:ff'", "MAC address"), ("token = '" + "Ab3" * 11 + "'", "key or token"),
                           ("-----BEGIN RSA " + "PRIVATE KEY-----", "private key"), ("mail me@" + "someone.net", "e-mail address")]:
            found = scan(text); self.assertEqual(len(found), 1, text); self.assertIn(what, found[0])

    def test_deny_list_entry_is_reported_without_showing_it(self):
        found = scan("camera serial X1" + "2345 here", deny=["x12345"])
        self.assertEqual(len(found), 1); self.assertIn("deny-list entry", found[0]); self.assertNotIn("12345", found[0])

    def test_let_through(self):
        for text in ["LAT, LON = 39.0, 1.5", "dist 1.23456 m, 7.5", "author 1+x@" + "users.noreply.github.com", "sha 0123456789abcdef",
                     "x = 'a' * 30", "Python.3.13_qbz5n2kfra8p0", "made up 12.3" + "45678, 3.4" + "56789  # privacy: ok"]:
            self.assertEqual(scan(text), [], text)
        self.assertEqual(scan("token = '" + "Ab3" * 11 + "'", file="uv.lock"), [])


if __name__ == "__main__":
    unittest.main()
