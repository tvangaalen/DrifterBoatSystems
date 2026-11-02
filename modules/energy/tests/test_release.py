"""Release consistency: the version lives in `mastervolt/__init__.py` and everything else must agree with it.

CLAUDE.md used to say "bump the version in three places"; this test makes forgetting one impossible. Since 3.0 the page is the
Energy module of the Drifter app (`web/energy.js` of Drifter Boat Systems), so there is no service worker or page to check here.
"""

import re

from mastervolt import __version__
from mastervolt.config import PATHS


def main():
    version = __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert not (PATHS.base / "static").exists(), "the classic page (static/) was removed in 3.0: the Drifter app shows Energy"

    readme = (PATHS.base / "README.md").read_text(encoding="utf-8")
    assert f"Mastervolt Energy v{version}" in readme.splitlines()[2], "README.md must state the current version in its first paragraph"
    changelog = (PATHS.base / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^### (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    assert newest == version, f"CHANGELOG.md's newest entry is {newest}, the version is {version}"
    manual = (PATHS.base / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    assert f"version {version}" in manual.lower().replace("**", ""), "docs/MANUAL.md must state the version it describes"
    print(f"Version {version}: README, CHANGELOG and the manual state it: OK")


if __name__ == "__main__":
    main()
