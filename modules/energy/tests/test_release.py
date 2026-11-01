"""Release consistency: the version lives in `mastervolt/__init__.py` and everything else must agree with it.

CLAUDE.md used to say "bump the version in three places"; this test makes forgetting one impossible. It also checks that the
service worker pre-caches exactly the files index.html loads, and that every front-end script parses on its own.
"""

import re
import shutil
import subprocess

from mastervolt import __version__
from mastervolt.config import PATHS

STATIC = PATHS.static


def main():
    version = __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    worker = (STATIC / "service-worker.js").read_text(encoding="utf-8")
    assert (
        f"const CACHE = 'mastervolt-v{version}-shell';" in worker
    ), "service-worker.js CACHE must carry the version (it is what refreshes the installed PWA)"
    shell = set(re.findall(r"'(/[^']*)'", worker.split("const SHELL = [")[1].split("];")[0]))

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'<script src="([^"]+)"', index) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', index)
    assert assets, "index.html loads no scripts or stylesheet"
    for asset in assets:
        assert (PATHS.base / asset.lstrip("/")).is_file(), f"index.html loads {asset}, which does not exist"
        assert asset in shell, f"service-worker.js does not pre-cache {asset}"
    assert {"/", "/manifest.webmanifest"} <= shell
    assert not [
        name for name in STATIC.glob("js/*.js") if f"/static/js/{name.name}" not in assets
    ], "a script in static/js is not loaded by index.html"
    print(
        f"Version {version}: service worker cache name and its {len(shell)} pre-cached files agree with index.html ({len(assets)} assets): OK"
    )

    readme = (PATHS.base / "README.md").read_text(encoding="utf-8")
    assert f"Mastervolt Energy v{version}" in readme.splitlines()[2], "README.md must state the current version in its first paragraph"
    changelog = (PATHS.base / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^### (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    assert newest == version, f"CHANGELOG.md's newest entry is {newest}, the version is {version}"
    manual = (PATHS.base / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    assert f"version {version}" in manual.lower().replace("**", ""), "docs/MANUAL.md must state the version it describes"
    print("README, CHANGELOG and the manual state the current version: OK")

    node = shutil.which("node")
    if node:
        for script in sorted(STATIC.glob("js/*.js")):
            result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
            assert result.returncode == 0, f"{script.name} does not parse:\n{result.stderr}"
        print(f"Every front-end script parses on its own ({len(list(STATIC.glob('js/*.js')))} files, node --check): OK")
    else:
        print("node not installed: front-end syntax check skipped")


if __name__ == "__main__":
    main()
