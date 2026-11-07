"""From a change in this clone to live on the boat in about a minute: the tests for what changed, the commits, push, pull in
C:\\Drifter, restart only what needs it, verify.

    py -3.12 tools/ship.py check                         # only the tests for what changed (nothing is committed)
    py -3.12 tools/ship.py change "Summary" [--body ..]  # tests, commit (code and docs apart), changelog line, push, deploy
    py -3.12 tools/ship.py release 1.2.0                 # Unreleased -> 1.2.0, VERSION/README, commit, tag, push, deploy
    py -3.12 tools/ship.py deploy                        # pull in C:\\Drifter, restart what changed, verify
    add --dry-run to see the plan without doing it

Tests: only the suites and browser tests the changed files can affect (tests/run_all.py <suite ...>, `npx playwright test
-g ...` for a page module, everything for the shared parts); GitHub CI still runs everything after the push. MasterVolt
runs `quick`; the suites run side by side (tests/run_all.py). Each test run that passed is remembered with the content
of the changed files it covered (.git/ship-green.json, local only, never committed) and is not run again while that is
unchanged, so after a failure only the failed part and what the fix touches run again. Restarts: none for web/ (the gateway reads the files per request and sw.js carries a fingerprint of them),
the gateway for drifter.py, a module for its own code; a change that needs the service restarted (drifterd, supervisor,
common/proc.py) or new environments (pyproject.toml, uv.lock) is never done here: it is printed as the step left to do.
The privacy hook runs on every commit; nothing here passes --no-verify. Small changes collect under "## Unreleased" in
CHANGELOG.md; `release` turns them into a version.
"""
from __future__ import annotations

import argparse, datetime, hashlib, json, re, shutil, ssl, subprocess, sys, textwrap, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = Path(r"C:\Drifter")
CLAUDE = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
ALL = {"gateway", "supervisor", "common", "privacy-scan", "proc", "drifterd", "verify-live", "watchdog", "backup", "ship",
       "energy", "anchor", "guard", "guard-api", "washer", "enginelog"}
COMMON_USERS = {"common", "gateway", "proc", "drifterd", "supervisor", "watchdog", "anchor", "guard", "guard-api", "washer", "enginelog"}
SUITE_RULES = [   # (path or prefix, suites of tests/run_all.py)
    ("drifter.py", {"gateway", "watchdog", "backup"}), ("supervisor.py", {"supervisor", "drifterd"}), ("drifterd.py", {"drifterd"}),
    ("common/", COMMON_USERS), ("modules.json", {"gateway", "drifterd", "supervisor", "backup"}),
    ("tools/privacy_scan.py", {"privacy-scan"}), ("tools/verify_live.py", {"verify-live"}), ("tools/backup.py", {"backup", "gateway"}),
    ("tools/ship.py", {"ship"}), ("web/sw.js", {"gateway"}),
    ("modules/energy/", {"energy"}), ("modules/anchor/", {"anchor"}), ("modules/guard/", {"guard", "guard-api"}),
    ("modules/washer/", {"washer"}), ("modules/enginelog/", {"enginelog"}), ("pyproject.toml", ALL), ("uv.lock", ALL)]
PAGES = {"energy": "overview|energy-|Engine ECU", "anchor": "overview|anchor at", "guard": "overview|guard at", "washer": "overview|washer at", "enginelog": "overview|enginelog|Engine log"}
UI_ALL = ("tests/ui/", "tools/mock_upstreams.py", "tools/config.mock.json", "playwright.config.ts", "package.json", "package-lock.json")
ORDER = ("energy", "anchor", "guard", "washer", "enginelog", "gateway")          # the gateway last: it answers the restart requests
GREEN = ROOT / ".git" / "ship-green.json"     # the files of the last green test run and their content (local only)
VERIFY_WAIT = 45                               # s the live checks wait for what is still starting after a restart


# ------------------------------------------------------------------------------------------------- plans (pure, tested)
def test_plan(files: list[str]) -> dict:
    """What to run for these changed files: run_all suites, browser tests (None, "all" or a -g pattern), type check, ruff."""
    suites: set[str] = set(); ui: set[str] = set(); ui_all = False; ruff: set[str] = set()
    for f in files:
        for prefix, s in SUITE_RULES:
            if f == prefix or (prefix.endswith("/") and f.startswith(prefix)): suites |= s
        m = re.fullmatch(r"tests/test_(\w+)\.py", f)
        if m: suites.add(m.group(1).replace("_", "-"))
        if f.endswith(".py"): ruff.add("modules/energy" if f.startswith("modules/energy/") else ".")
        if f.startswith(UI_ALL): ui_all = True
        elif f.startswith("web/"):
            page = re.fullmatch(r"web/(energy|anchor|guard|washer|enginelog)\.js", f)
            if page: ui.add(PAGES[page.group(1)])
            else: ui_all = True
    pattern = "all" if ui_all else "|".join(sorted(ui)) or None
    typecheck = pattern is not None and any(f.startswith("web/") and f.endswith((".js", ".ts", ".json")) or f.startswith(UI_ALL) for f in files)
    return {"suites": sorted(suites & ALL), "ui": pattern, "typecheck": typecheck, "ruff": sorted(ruff)}


def units(plan: dict) -> set[str]:
    """The separate test runs of a plan: each suite, "browser", "typecheck", "ruff:<folder>"."""
    return set(plan["suites"]) | {f"ruff:{d}" for d in plan["ruff"]} | ({"typecheck"} if plan["typecheck"] else set()) | ({"browser"} if plan["ui"] else set())


def units_needed(files: list[str], prints: dict, green: dict, head: str) -> set[str]:
    """The test runs the changed files still need. A run is skipped when it passed before on the same commit with exactly
    the same content of every changed file it covers (and no other): fixing one file after a run only reruns that
    file's part. A file back to its committed version counts as a change of the files that run covered."""
    per_file = {f: units(test_plan([f])) for f in files}
    need = set()
    for u in units(test_plan(files)):
        covered = {f: prints.get(f) for f in files if u in per_file[f]}
        if green.get(u) != {"head": head, "files": covered}: need.add(u)
    return need


def restart_plan(files: list[str]) -> tuple[list[str], list[str]]:
    """(modules to restart through the gateway, in ORDER; steps left to the user) for the files a pull brought in."""
    want: set[str] = set(); todo: list[str] = []
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if f in ("drifterd.py", "supervisor.py", "common/proc.py"):
            todo.append(f"{f} changed: the service needs a restart (restarts every module): Restart-Service Drifter")
        elif f in ("pyproject.toml", "uv.lock"):
            todo.append(f"{f} changed: rebuild the environments (py -3.12 tools\\sync_envs.py --into .venv-next <module>), then restart")
        elif f in ("drifter.py", "modules.json", "tools/backup.py"): want.add("gateway")
        elif f == "common/service.py": want |= {"anchor", "guard", "washer", "enginelog"}
        elif f.startswith("common/"): want |= {"gateway", "anchor", "guard", "washer", "enginelog"}
        elif m := re.match(r"modules/(energy|anchor|guard|washer|enginelog)/", f):
            if not (f.endswith(".md") or "/docs/" in f or "/tests/" in f or name.startswith("test_")): want.add(m.group(1))
    return [m for m in ORDER if m in want], list(dict.fromkeys(todo))


def add_unreleased(text: str, summary: str) -> str:
    """CHANGELOG.md with `summary` as the last line under "## Unreleased" (made at the top when missing)."""
    line = textwrap.fill(summary, 120, initial_indent="- ", subsequent_indent="  ") + "\n"
    if "\n## Unreleased\n" not in text:
        head, rest = text.split("\n## ", 1)
        text = f"{head}\n## Unreleased\n\n## {rest}"
    start = text.index("\n## Unreleased\n") + len("\n## Unreleased\n")
    end = text.find("\n## ", start); end = len(text) if end < 0 else end
    block = text[start:end].strip("\n")
    return text[:start] + "\n" + (block + "\n" if block else "") + line + text[end:]


def cut_release(text: str, version: str, day: str) -> tuple[str, str]:
    """(CHANGELOG.md with Unreleased turned into "### version — day" under its "## X.Y", the release notes)."""
    m = re.search(r"\n## Unreleased\n(.*?)(?=\n## |\Z)", text, re.S)
    notes = m.group(1).strip("\n") if m else ""
    if not notes: raise SystemExit("nothing under ## Unreleased in CHANGELOG.md: nothing to release")
    text = text[:m.start()] + text[m.end():]
    minor = ".".join(version.split(".")[:2]); entry = f"### {version} — {day}\n\n{notes}\n\n"
    if f"\n## {minor}\n" in text:
        i = text.index(f"\n## {minor}\n") + len(f"\n## {minor}\n\n")
        return text[:i] + entry + text[i:], notes
    head, rest = text.split("\n## ", 1)
    return f"{head}\n## {minor}\n\n{entry}## {rest}", notes


# ------------------------------------------------------------------------------------------------- doing it
def run(cmd, cwd=ROOT, check=True, quiet=False) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    if check and r.returncode:
        print(out[-4000:]); raise SystemExit(f"failed: {' '.join(map(str, cmd))}")
    if not quiet and out: print(textwrap.indent(out, "    "))
    return out


def git(*args, cwd=ROOT, check=True) -> str:
    return run(["git", *args], cwd=cwd, check=check, quiet=True)


def changed() -> list[str]:
    out = []
    st = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    for ln in st.stdout.splitlines():
        p = ln[3:].split(" -> ")[-1].strip().strip('"')
        out.append(p)
    return out


def step(title: str, cmd, cwd=ROOT, hint: str = "", keep_going: bool = False) -> str:
    """Runs one step and prints its tail; a failure stops ship.py (keep_going: the caller decides). Returns the output."""
    t0 = time.monotonic(); print(f"- {title}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = (r.stdout + r.stderr).strip().splitlines()
    tail = "\n".join(lines[-12:] if r.returncode else [ln for ln in lines if re.search(r"\d+ (passed|failed|flaky)", ln)] or lines[-2:])
    if keep_going: tail = "\n".join(lines[-40:])
    print(textwrap.indent(tail, "    ") + f"\n    ({time.monotonic() - t0:.0f} s)")
    if r.returncode and not keep_going: raise SystemExit(f"{title}: failed" + (f"\n{hint}" if hint else ""))
    return r.stdout + r.stderr


def py() -> str:
    v = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(v) if v.exists() else sys.executable


def fingerprints(files: list[str]) -> dict:
    out = {}
    for f in files:
        p = ROOT / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "deleted"
    return out


def check(files: list[str], dry: bool) -> None:
    prints, head = fingerprints(files), git("rev-parse", "HEAD")
    try: green = json.loads(GREEN.read_text(encoding="utf-8"))
    except (OSError, ValueError): green = {}
    need = units_needed(files, prints, green, head); full = test_plan(files)
    skip = sorted(units(full) - need)
    p = {"suites": [x for x in full["suites"] if x in need], "ruff": [d for d in full["ruff"] if f"ruff:{d}" in need],
         "typecheck": "typecheck" in need, "ui": full["ui"] if "browser" in need else None}
    print(f"tests for {len(files)} changed file(s): suites {', '.join(p['suites']) or '-'}; browser {p['ui'] or '-'}"
          f"; type check {'yes' if p['typecheck'] else 'no'}; ruff {', '.join(p['ruff']) or '-'}"
          + (f"\n  passed before with exactly these files, not run again: {', '.join(skip)}" if skip else ""))
    if dry: return
    per_file = {f: units(test_plan([f])) for f in files}

    def passed(*done: str) -> None:              # remembered at once, so a later failure keeps what passed
        for u in done: green[u] = {"head": head, "files": {f: prints.get(f) for f in files if u in per_file[f]}}
        GREEN.write_text(json.dumps(green), encoding="utf-8")

    for d in p["ruff"]: step(f"ruff {d}", ["py", "-3.12", "-m", "ruff", "check", "--no-cache", d]); passed(f"ruff:{d}")   # the cache once hid an error CI found
    if p["typecheck"]: step("type check", [shutil.which("npm") or "npm", "run", "typecheck"]); passed("typecheck")
    if p["suites"]:
        out = step("python tests", [py(), "tests/run_all.py", "quick", *p["suites"]], keep_going=True)
        ok = [m.group(1) for m in re.finditer(r"^ok\s+(\S+)", out, re.M) if m.group(1) in p["suites"]]
        passed(*ok)
        if len(ok) < len(p["suites"]): raise SystemExit("python tests: failed")
    if p["ui"]:
        step("browser tests", [shutil.which("npx") or "npx", "playwright", "test", *([] if p["ui"] == "all" else ["-g", p["ui"]])],
             hint="a snapshot that changed on purpose: npx playwright test -g <test> --update-snapshots, read the diff, run again")
        passed("browser")


def message(summary: str, body: str | None, claude: bool) -> str:
    return summary + (f"\n\n{body.strip()}" if body else "") + (f"\n\n{CLAUDE}" if claude else "")


def is_doc(f: str) -> bool:
    return f.endswith(".md") or f.startswith("docs/")


def edit(path: Path, fn) -> None:
    """Change a text file through fn(str) -> str, keeping its line endings."""
    raw = path.read_bytes(); crlf = b"\r\n" in raw
    s = fn(raw.decode("utf-8").replace("\r\n", "\n"))
    path.write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))


def change(a) -> None:
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main": raise SystemExit("not on main")
    files = changed()
    if not files: raise SystemExit("nothing changed")
    if not a.no_test: check(files, a.dry_run)
    files = changed()
    code, docs = [f for f in files if not is_doc(f)], [f for f in files if is_doc(f)]
    print(f"commit: {len(code)} code file(s), {len(docs)} doc file(s) + the changelog line")
    if a.dry_run: return deploy(a, dry=True, extra=files)
    if code:
        git("add", "--", *code); print(git("diff", "--cached", "--stat"))
        run(["git", "commit", "-q", "-m", message(a.summary, a.body, a.claude)])
    if not a.no_changelog: edit(ROOT / "CHANGELOG.md", lambda s: add_unreleased(s, a.summary)); docs = sorted(set(docs) | {"CHANGELOG.md"})
    if docs:
        git("add", "--", *docs)
        run(["git", "commit", "-q", "-m", message(("Docs: " if code else "") + a.summary, None if code else a.body, a.claude)])
    print(git("log", "--oneline", "-3"))
    if a.no_push: return print("not pushed (--no-push)")
    git("push", "-q", "origin", "main"); print("pushed")
    deploy(a)


def release(a) -> None:
    v = a.version
    if not re.fullmatch(r"\d+\.\d+\.\d+", v): raise SystemExit("version: X.Y.Z")
    cur = re.search(r'^VERSION = "([\d.]+)"', (ROOT / "drifter.py").read_text(encoding="utf-8"), re.M).group(1)
    if tuple(map(int, v.split("."))) <= tuple(map(int, cur.split("."))): raise SystemExit(f"{v} is not after {cur}")
    if changed(): raise SystemExit("uncommitted changes: ship them first (ship.py change)")
    day = datetime.date.today().isoformat()
    log, notes = cut_release((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").replace("\r\n", "\n"), v, day)
    print(f"Drifter {cur} -> {v}\n{notes}")
    if a.dry_run: return
    edit(ROOT / "CHANGELOG.md", lambda s: cut_release(s, v, day)[0])
    edit(ROOT / "drifter.py", lambda s: s.replace(f'VERSION = "{cur}"', f'VERSION = "{v}"', 1))
    edit(ROOT / "README.md", lambda s: s.replace(f"Version {cur} ·", f"Version {v} ·", 1))
    step("python tests", [py(), "tests/run_all.py", "gateway"])
    git("add", "drifter.py", "README.md", "CHANGELOG.md")
    run(["git", "commit", "-q", "-m", message(f"Drifter {v}", notes, a.claude)])
    git("tag", f"v{v}"); git("push", "-q", "origin", "main", f"v{v}"); print(f"pushed with tag v{v}")
    deploy(a)


def gateway(cfg: dict):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # LAN, own CA
    base = f"https://{cfg['bind']}:{cfg['port']}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Drifter-Request": "1"} if body is not None else {})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r: return json.loads(r.read() or b"{}")
    return call


def deploy(a, dry: bool = False, extra: list[str] | None = None) -> None:
    old = git("rev-parse", "HEAD", cwd=LIVE)
    if dry:
        if a.command == "deploy": git("fetch", "-q", cwd=LIVE)
        files = git("diff", "--name-only", old, "origin/main" if a.command == "deploy" else "HEAD").splitlines() + (extra or [])
        mods, todo = restart_plan(files)
        return print(f"deploy: restart {', '.join(mods) or 'nothing (web/docs only)'}" + "".join(f"\n  left to do: {t}" for t in todo))
    git("pull", "-q", "--ff-only", cwd=LIVE); new = git("rev-parse", "HEAD", cwd=LIVE)
    if old == new: return print("C:\\Drifter is up to date: nothing to deploy")
    files = git("diff", "--name-only", old, new, cwd=LIVE).splitlines()
    mods, todo = restart_plan(files)
    print(f"C:\\Drifter {old[:7]} -> {new[:7]} ({len(files)} files); restart: {', '.join(mods) or 'nothing'}")
    cfg = json.loads((LIVE / "config.json").read_text(encoding="utf-8")); call = gateway(cfg)
    if a.no_restart and mods: todo.append(f"restart {', '.join(mods)} (--no-restart)"); mods = []
    for m in mods: print(f"  restart {m}: {call('/api/supervisor/restart', {'module': m})}")
    # A short wait: what still starts (the BMS units take ~2 minutes after an energy restart, a washer that is off) is
    # reported as still coming up, not waited for; only a real failure stops here.
    step("verify live", [py(), "tools/verify_live.py", "--wait", str(VERIFY_WAIT if mods else 0), "--pending-ok"])
    sys.path.insert(0, str(LIVE)); import drifter        # the live code's own fingerprint of its web/ files
    live = call("/api/systems")
    want = drifter.web_build(LIVE / "web")
    print(f"live: Drifter {live.get('version')}, web build {live.get('build')}" + ("" if live.get("build") == want else f" (expected {want}!)"))
    for t in todo: print(f"LEFT TO DO: {t}")
    if live.get("build") != want: raise SystemExit("the live web build is not the pulled one")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="only the tests for what changed")
    s = sub.add_parser("change", help="tests, commit, changelog line, push, deploy")
    s.add_argument("summary"); s.add_argument("--body"); s.add_argument("--no-changelog", action="store_true")
    s.add_argument("--no-test", action="store_true"); s.add_argument("--no-push", action="store_true")
    r = sub.add_parser("release", help="Unreleased -> a version, tag, push, deploy"); r.add_argument("version")
    d = sub.add_parser("deploy", help="pull in C:\\Drifter, restart what changed, verify")
    for p in (c, s, r, d): p.add_argument("--dry-run", action="store_true")
    for p in (s, r): p.add_argument("--claude", action="store_true", help="add Claude's Co-Authored-By line")
    for p in (s, r, d): p.add_argument("--no-restart", action="store_true")
    a = ap.parse_args(argv); t0 = time.monotonic()
    sys.stdout.reconfigure(errors="replace")             # test output can hold characters the console cannot show
    if a.command == "check": check(changed(), a.dry_run)
    elif a.command == "change": change(a)
    elif a.command == "release": release(a)
    else: deploy(a, a.dry_run)
    print(f"done in {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
