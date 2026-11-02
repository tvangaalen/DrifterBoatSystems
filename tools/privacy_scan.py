"""Privacy scan for this public repository: refuses added lines that look like positions, keys, MAC addresses, private
keys or e-mail addresses, or that contain an entry of the local deny list (MMSI, serials, the owner's e-mail, known
anchorages). Runs as the git pre-commit hook (.githooks/pre-commit) and in CI.

    py tools/privacy_scan.py                  staged changes (the pre-commit hook)
    py tools/privacy_scan.py --range A..B     the commits A..B (CI: what a push adds)

The deny list lives outside git: %DRIFTER_DATA%\\privacy_denylist.txt (default C:\\DrifterData), one entry per line,
# for comments; CI has no deny list and checks the patterns only. A line that is fine after all (made-up test data)
can carry the marker `privacy: ok`. Exit code 1 = findings (the commit is stopped), 0 = clean.
"""
from __future__ import annotations

import os, re, subprocess, sys
from pathlib import Path

PATTERNS = [
    ("position", re.compile(r"(?<![\d.])-?\d{1,2}\.\d{5,}\s*[,/ ]\s*-?\d{1,3}\.\d{5,}(?![\d.])")),   # lat, lon with 5+ decimals
    ("key or token", re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{30,}(?![A-Za-z0-9_\-])")),
    ("MAC address", re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("e-mail address", re.compile(r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com|anthropic\.com|example\.(?:com|org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]
SKIP_FILES = re.compile(r"(^|/)(uv\.lock|package-lock\.json)$|^web/vendor/|\.(png|jpg|ico|pdf|sqlite3)$")
MARKER = "privacy: ok"


def denylist() -> list[str]:
    f = Path(os.environ.get("DRIFTER_DATA", "").strip() or r"C:\DrifterData") / "privacy_denylist.txt"
    try: return [x.strip() for x in f.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    except OSError: return []


def added_lines(args: list[str]):
    """(file, line number, text) of every added line in the diff."""
    diff = subprocess.run(["git", "diff", "--unified=0", "--no-color", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    file, n = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "): file = line[6:] if line.startswith("+++ b/") else None; continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line); n = int(m[1]) if m else 0; continue
        if file and line.startswith("+") and not line.startswith("+++"):
            yield file, n, line[1:]; n += 1


def scan(lines, deny) -> list[str]:
    found = []
    for file, n, text in lines:
        if SKIP_FILES.search(file) or MARKER in text: continue
        for what, rx in PATTERNS:
            if rx.search(text): found.append(f"{file}:{n}: {what}: {text.strip()[:120]}")
        for d in deny:
            if d.lower() in text.lower(): found.append(f"{file}:{n}: deny-list entry: (hidden)")
    return found


def main(argv: list[str]) -> int:
    args = ["--cached"] if not argv else [argv[argv.index("--range") + 1]] if "--range" in argv else argv
    found = scan(added_lines(args), denylist())
    if found:
        print("Privacy scan: this repository is public. Remove these, or mark made-up data with 'privacy: ok':", file=sys.stderr)
        for f in found: print("  " + f, file=sys.stderr)
        return 1
    print("Privacy scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
