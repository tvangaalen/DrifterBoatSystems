"""tools/ship.py: which tests a change needs, what a deploy restarts, and the changelog's Unreleased section (pure functions)."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ship  # noqa: E402

LOG = "# Changelog\n\n## 1.1\n\n### 1.1.0 — 2026-11-03\n\n- The meter.\n\n## 1.0\n\n### 1.0.0 — 2026-11-02\n\n- Base.\n"


class Tests(unittest.TestCase):
    def test_page_module_runs_only_its_browser_tests(self):
        p = ship.test_plan(["web/energy.js"])
        self.assertEqual((p["suites"], p["ui"], p["typecheck"], p["ruff"]), ([], "overview|energy-|Engine ECU", True, []))

    def test_shared_web_runs_every_browser_test(self):
        for f in ("web/app.css", "web/core/app.js", "tests/ui/pages.spec.ts", "tools/mock_upstreams.py"):
            self.assertEqual(ship.test_plan([f])["ui"], "all", f)

    def test_python_suites(self):
        self.assertEqual(ship.test_plan(["drifter.py"])["suites"], ["backup", "gateway", "watchdog"])
        self.assertEqual(ship.test_plan(["modules/guard/guard/core.py"])["suites"], ["guard", "guard-api"])
        self.assertIn("anchor", ship.test_plan(["common/net.py"])["suites"])
        self.assertEqual(ship.test_plan(["tests/test_verify_live.py"])["suites"], ["verify-live"])
        self.assertEqual(ship.test_plan(["modules/energy/mastervolt/soc.py"])["ruff"], ["modules/energy"])
        self.assertEqual(ship.test_plan(["uv.lock"])["suites"], sorted(ship.ALL))

    def test_docs_only_runs_nothing_heavy(self):
        p = ship.test_plan(["README.md", "docs/RUNBOOK.md"])
        self.assertEqual((p["suites"], p["ui"], p["typecheck"]), ([], None, False))
        self.assertEqual(ship.test_plan(["docs/MANUAL.md"])["suites"], ["manual"])

    def test_restarts(self):
        self.assertEqual(ship.restart_plan(["web/energy.js", "web/app.css", "CHANGELOG.md"]), ([], []))
        self.assertEqual(ship.restart_plan(["drifter.py", "modules/energy/mastervolt/soc.py"])[0], ["energy", "gateway"])
        self.assertEqual(ship.restart_plan(["modules/anchor/CHANGELOG.md", "modules/anchor/test_anchor.py"])[0], [])
        self.assertEqual(ship.restart_plan(["common/service.py"])[0], ["anchor", "guard", "washer"])
        mods, todo = ship.restart_plan(["drifterd.py", "uv.lock"])
        self.assertEqual(mods, []); self.assertEqual(len(todo), 2)              # never done by ship.py itself

    def test_unreleased_lines_collect_at_the_top(self):
        t = ship.add_unreleased(LOG, "First change.")
        self.assertTrue(t.startswith("# Changelog\n\n## Unreleased\n\n- First change.\n\n## 1.1\n"), t)
        t = ship.add_unreleased(t, "Second change.")
        self.assertIn("## Unreleased\n\n- First change.\n- Second change.\n\n## 1.1\n", t)

    def test_release_moves_unreleased_under_its_minor(self):
        t = ship.add_unreleased(ship.add_unreleased(LOG, "One."), "Two.")
        out, notes = ship.cut_release(t, "1.1.1", "2026-11-04")
        self.assertEqual(notes, "- One.\n- Two.")
        self.assertTrue(out.startswith("# Changelog\n\n## 1.1\n\n### 1.1.1 — 2026-11-04\n\n- One.\n- Two.\n\n### 1.1.0"), out)
        out, _ = ship.cut_release(t, "1.2.0", "2026-11-04")
        self.assertTrue(out.startswith("# Changelog\n\n## 1.2\n\n### 1.2.0 — 2026-11-04\n\n- One.\n- Two.\n\n## 1.1\n"), out)
        with self.assertRaises(SystemExit): ship.cut_release(LOG, "1.1.1", "2026-11-04")


if __name__ == "__main__":
    unittest.main()
