"""The user manual: web/manual.html is built from docs/MANUAL.md (tools/build_manual.py), the System page links to it, and
the manual names no file or tool that does not exist."""
import re, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ManualTest(unittest.TestCase):
    def test_built_from_the_source(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_manual.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_linked_from_the_system_page_and_cached(self):
        self.assertIn('href="manual.html"', (ROOT / "web" / "core" / "app.js").read_text(encoding="utf-8"))
        self.assertIn('"manual.html"', (ROOT / "web" / "sw.js").read_text(encoding="utf-8"))
        page = (ROOT / "web" / "manual.html").read_text(encoding="utf-8")
        self.assertIn('id="back"', page); self.assertIn('href="app.css"', page)

    def test_no_am_pm(self):
        text = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\b\d{1,2}:\d{2}\s?(AM|PM)\b")
        for doc in re.findall(r"\]\(([^)#:]+\.md)\)", text):
            self.assertTrue((ROOT / "docs" / doc).exists(), doc)


if __name__ == "__main__":
    unittest.main()
