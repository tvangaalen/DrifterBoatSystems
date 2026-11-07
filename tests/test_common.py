"""common/ tests: LAN-only binding, DNS rebinding, same origin, 24-hour clock, logging, Pushover posting (fake
urlopen, nothing is sent) and the certificate script's refusal without the CA (it must never create one)."""
import io, logging, subprocess, sys, tempfile, time, unittest, urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import logs, net, pushover, timefmt  # noqa: E402


class NetTest(unittest.TestCase):
    def test_lan_only(self):
        for ok in ("127.0.0.1", "::1", "192.168.1.166", "10.0.0.2", "172.16.5.1"): self.assertTrue(net.is_lan(ok), ok)
        for bad in ("0.0.0.0", "::", "8.8.8.8", "169.254.1.1", "172.32.0.1", "boat.lan", ""): self.assertFalse(net.is_lan(bad), bad)
        self.assertEqual(net.check_bind(" 192.168.1.166 "), "192.168.1.166")
        with self.assertRaisesRegex(SystemExit, "VIOMI_BIND 0.0.0.0"): net.check_bind("0.0.0.0", "VIOMI_BIND")

    def test_host_allowed(self):
        self.assertTrue(net.host_allowed("192.168.1.166:8100")); self.assertTrue(net.host_allowed("LOCALHOST"))
        self.assertTrue(net.host_allowed("[::1]:8100")); self.assertTrue(net.host_allowed("boat.lan:80", ["Boat.lan"]))
        self.assertFalse(net.host_allowed("evil.example")); self.assertFalse(net.host_allowed("")); self.assertFalse(net.host_allowed(None))
        self.assertEqual(net.request_host("[fe80::1]:8100"), "fe80::1")

    def test_same_origin(self):
        self.assertTrue(net.same_origin(None, "127.0.0.1:8100")); self.assertTrue(net.same_origin("https://127.0.0.1:8100", "127.0.0.1:8100"))
        self.assertFalse(net.same_origin("http://evil.example", "127.0.0.1:8100")); self.assertFalse(net.same_origin("https://127.0.0.1:8101", "127.0.0.1:8100"))


class TimeAndLogTest(unittest.TestCase):
    def test_24_hour_clock(self):
        t = time.mktime((2026, 11, 2, 15, 4, 5, 0, 0, -1))
        self.assertEqual((timefmt.hm(t), timefmt.hms(t), timefmt.stamp(t)), ("15:04", "15:04:05", "2026-11-02 15:04:05"))

    def test_rotating_file(self):
        with tempfile.TemporaryDirectory() as d:
            lg = logging.getLogger("test-common"); lg.propagate = False
            with mock.patch.object(sys, "stderr", None): logs.setup(lg, Path(d) / "logs" / "x.log", max_bytes=200, keep=2)   # pythonw
            self.assertEqual(len(lg.handlers), 1)
            for i in range(30): lg.info("line %d with some text", i)
            for h in list(lg.handlers): h.close(); lg.removeHandler(h)
            files = sorted(p.name for p in (Path(d) / "logs").iterdir())
            self.assertEqual(files, ["x.log", "x.log.1", "x.log.2"])
            self.assertRegex((Path(d) / "logs" / "x.log").read_text(encoding="utf-8"), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO line")


class PushoverTest(unittest.TestCase):
    def test_post_and_errors(self):
        seen = []
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        def ok(req, timeout): seen.append((req.full_url, req.data, req.get_header("User-agent"))); return Resp(b'{"status":1,"receipt":"R"}')
        with mock.patch("urllib.request.urlopen", ok):
            self.assertEqual(pushover.post("messages.json", {"token": "t", "user": "u", "title": "a b"}, "Test/1"), {"status": 1, "receipt": "R"})
        self.assertEqual(seen, [("https://api.pushover.net/1/messages.json", b"token=t&user=u&title=a+b", "Test/1")])

        def refused(req, timeout): raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"errors":["user key is invalid"]}'))
        with mock.patch("urllib.request.urlopen", refused), self.assertRaises(pushover.PushoverError) as e: pushover.post("messages.json", {}, "T")
        self.assertEqual((e.exception.code, e.exception.detail), (400, "user key is invalid")); self.assertIn("HTTP 400", str(e.exception))

        def down(req, timeout): raise OSError("no route")
        with mock.patch("urllib.request.urlopen", down), self.assertRaises(OSError): pushover.post("messages.json", {}, "T")
        self.assertTrue(pushover.KEY_RE.match("a" * 30)); self.assertFalse(pushover.KEY_RE.match("a" * 29))


class SharedKeysTest(unittest.TestCase):
    """The shared Pushover keys (System page) and the priority/sound choices; files in a temporary folder only."""
    def test_shared_file_only_inside_drifter_data(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict("os.environ", {"DRIFTER_DATA": d}):
                self.assertEqual(pushover.shared_file(Path(d) / "anchor"), Path(d) / "pushover.json")
                self.assertIsNone(pushover.shared_file(Path(d) / "x" / "anchor"))          # a scratch folder: never the real keys
            with mock.patch.dict("os.environ", {"DRIFTER_DATA": ""}): self.assertIsNone(pushover.shared_file(Path(d) / "anchor"))

    def test_keys_in_both_layouts_and_masked(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a.json"), Path(d, "b.json")
            b.write_text('{"token": "%s", "user": "%s"}' % ("t" * 30, "u" * 30))  # privacy: ok
            self.assertEqual(pushover.find_keys(a, b), ({"token": "t" * 30, "user": "u" * 30}, b))
            with self.assertRaises(ValueError): pushover.write_keys(a, "short", None)
            r = pushover.write_keys(a, "x" * 30, "")  # privacy: ok
            self.assertEqual((r["app_token"], r["configured"]), ("…xxxx", False)); self.assertIsNone(pushover.read_keys(a))
            pushover.write_keys(a, None, "y" * 30)  # privacy: ok
            self.assertEqual(pushover.find_keys(a, b)[1], a); self.assertNotIn("x" * 30, str(pushover.masked(a)))

    def test_clean_prefs(self):
        d = {"a": {"priority": 0, "sound": ""}, "b": {"priority": 1, "sound": ""}}
        self.assertEqual(pushover.clean_prefs({"a": {"sound": "bike"}}, d, {"b": {"priority": -1}}),
                         {"a": {"priority": 0, "sound": "bike"}, "b": {"priority": -1, "sound": ""}})
        self.assertEqual(pushover.clean_prefs({"b": {"priority": 2}}, d, emergency=("b",))["b"]["priority"], 2)
        for bad in ({"a": {"priority": 2}}, {"a": {"priority": 1.5}}, {"a": {"sound": "boom"}}, {"c": {}}, {"a": 1}, []):
            with self.assertRaises(ValueError): pushover.clean_prefs(bad, d)


class CertScriptTest(unittest.TestCase):
    def test_refuses_without_the_ca_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            ca, out = Path(d) / "ca", Path(d) / "out"; ca.mkdir()
            r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "common" / "issue_cert.ps1"),
                                "-Name", "t", "-Cn", "T", "-OutDir", str(out), "-CaDir", str(ca)], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(r.returncode, 0); self.assertIn("Mastervolt Local CA not found", r.stdout + r.stderr)
            self.assertEqual(list(ca.iterdir()), []); self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
