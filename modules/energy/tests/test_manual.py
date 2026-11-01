"""The manual: the served HTML is built from MANUAL.md, and what the manual names (tools, tests, API routes, files) exists."""

import re
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from mastervolt.app import create_app
from mastervolt.config import PATHS, Paths
from mastervolt.runtime import Services
from tools import build_manual


def main():
    assert build_manual.main(["--check"]) == 0, "docs/manual.html is out of date: run py -m tools.build_manual"
    manual = (PATHS.docs / "MANUAL.md").read_text(encoding="utf-8")
    print("docs/manual.html is built from the current MANUAL.md: OK")

    # every command the manual tells the reader to run exists
    for module in sorted(set(re.findall(r"py -m (tools|tests)\.(\w+)", manual))):
        assert (
            PATHS.base / module[0] / f"{module[1]}.py"
        ).is_file(), f"the manual mentions py -m {module[0]}.{module[1]}, which does not exist"
    assert (PATHS.base / "mastervolt" / "reports" / "battery_health.py").is_file()
    for name in (
        "start_mastervolt_server.cmd",
        "run.ps1",
        "setup_local_https.ps1",
        "control_maps.json",
        "mastershunt_config_maps.json",
        "requirements.txt",
    ):
        assert (PATHS.base / name).is_file(), f"the manual mentions {name}"
    for doc in (
        "docs/hardware-notes.md",
        "docs/local-https.md",
        "docs/VERIFIED_FIELD_MAP.txt",
        "tools/find_masterbus_usb.ps1",
        "tools/install_autostart.ps1",
        "tools/ecu_capture_session.ps1",
    ):
        assert (PATHS.base / doc).is_file(), f"the manual mentions {doc}"
    print("Every tool, test, script and document the manual names exists: OK")

    # every API route the manual lists is a real route
    folder = Path(tempfile.mkdtemp())
    for name in ("control_maps.json", "mastershunt_config_maps.json"):
        shutil.copy(PATHS.base / name, folder / name)
    shutil.copytree(PATHS.static, folder / "static", ignore=shutil.ignore_patterns("products"))
    shutil.copytree(PATHS.docs, folder / "docs", ignore=shutil.ignore_patterns("archive", "device-schemas"))
    client = TestClient(create_app(Services(Paths(folder))))
    paths = set(client.get("/openapi.json").json()["paths"])
    listed = set(re.findall(r"\| `(?:GET|POST)(?:`/`(?:GET|POST))? (/api/[a-z\-]+(?:/[a-z\-]+)*)", manual))
    missing = sorted(
        route for route in listed if route not in paths and not any(path.startswith(route + "/") or path == route for path in paths)
    )
    assert not missing, f"the manual lists routes that do not exist: {missing}"
    print(f"{len(listed)} API routes named in the manual all exist: OK")

    page = client.get("/manual")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and "Mastervolt Energy - Manual" in page.text
    assert (
        'id="back"' in page.text and "Back to the app" in page.text
    ), "the manual needs a way back to the app (the iPhone app has no back button)"
    assert 'href="/manual"' in (PATHS.static / "index.html").read_text(encoding="utf-8"), "the Settings page must link to the manual"
    index = (PATHS.static / "index.html").read_text(encoding="utf-8")
    assert 'id="manualBtn"' in index and 'onclick="openManual()"' in index, "the Reports tab must have the Manual button"
    assert "function openManual()" in (PATHS.static / "js" / "reports.js").read_text(encoding="utf-8")
    print("GET /manual serves the manual; the Settings page links to it and the Reports tab has a Manual button: OK")


if __name__ == "__main__":
    main()
