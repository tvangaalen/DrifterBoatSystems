"""Builds web/manual.html, the user manual the app opens (System → Manual), from docs/MANUAL.md.

    py -3.12 tools/build_manual.py            write web/manual.html
    py -3.12 tools/build_manual.py --check    exit 1 when web/manual.html is out of date (tests/test_manual.py)

The Markdown renderer is MasterVolt's (modules/energy/tools/build_manual.py: headings, paragraphs, lists, tables, code,
quotes; no packages); the page uses the app's stylesheet and theme, and its "‹ Drifter" button returns to the app (a
home-screen app has no back button).
"""
from __future__ import annotations

import argparse, html, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE, TARGET = ROOT / "docs" / "MANUAL.md", ROOT / "web" / "manual.html"
_spec = importlib.util.spec_from_file_location("mv_build_manual", ROOT / "modules" / "energy" / "tools" / "build_manual.py")
MD = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(MD)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="format-detection" content="telephone=no">
<title>{title}</title>
<link rel="icon" href="icons/icon.svg" type="image/svg+xml">
<script>
try {{ const t = localStorage.getItem("drifter-theme"); if (t && t !== "auto") document.documentElement.dataset.theme = t; }} catch (e) {{}}
</script>
<link rel="stylesheet" href="app.css">
<style>
  body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
  .mhead{{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:10px;padding:calc(10px + env(safe-area-inset-top)) 16px 10px;background:var(--bg);border-bottom:1px solid var(--line)}}
  .mhead b{{font-size:18px}}
  .wrap{{max-width:56rem;margin:0 auto;padding:8px 16px calc(48px + env(safe-area-inset-bottom))}}
  .wrap a{{color:var(--accent)}}
  nav.toc{{border:1px solid var(--line);border-radius:12px;padding:8px 16px;margin:16px 0 24px;background:var(--card)}}
  nav.toc ul{{margin:4px 0;padding-left:0;list-style:none;columns:2 16rem}}
  nav.toc a{{text-decoration:none}}
  h1{{font-size:1.7rem;margin:12px 0}}
  h2{{font-size:1.35rem;margin:36px 0 8px;padding-top:12px;border-top:1px solid var(--line)}}
  h3{{font-size:1.1rem;margin:24px 0 6px}}
  code{{background:var(--card2);padding:.1em .35em;border-radius:5px;font:.9em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
  pre{{background:var(--card2);padding:12px 16px;border-radius:10px;overflow:auto;line-height:1.35}}
  pre code{{background:none;padding:0}}
  blockquote{{margin:16px 0;padding:8px 16px;border-left:4px solid var(--warn);background:var(--warnbg);border-radius:0 10px 10px 0}}
  .table{{overflow-x:auto;margin:16px 0}}
  table{{border-collapse:collapse;width:100%;font-size:.95rem}}
  th,td{{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}}
  th{{background:var(--card2)}}
  hr{{border:0;border-top:1px solid var(--line);margin:32px 0}}
  li{{margin:3px 0}}
</style>
</head>
<body>
<div class="mhead"><button class="btn sec sm" type="button" id="back">‹ Drifter</button><b>Manual</b></div>
<div class="wrap">
{body}
</div>
<script>
document.getElementById("back").onclick = () => {{ if (window.opener && !window.opener.closed) window.close(); setTimeout(() => {{ location.href = "./#system"; }}, 300); }};
</script>
</body>
</html>
"""


def build(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    title = lines[0].lstrip("# ").strip()
    headings: list = []
    body = MD.render(lines, headings)
    toc = '<nav class="toc"><strong>Contents</strong><ul>' + "".join(f'<li><a href="#{a}">{MD.inline(t)}</a></li>' for _, t, a in headings) + "</ul></nav>"
    first = body.index("<h2 ")                       # the contents go after the title and the introduction
    return PAGE.format(title=html.escape(title), body=body[:first] + toc + "\n" + body[first:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when web/manual.html is out of date")
    a = ap.parse_args(argv)
    page = build(SOURCE.read_text(encoding="utf-8"))
    if a.check:
        ok = TARGET.exists() and TARGET.read_text(encoding="utf-8") == page
        if not ok: print("web/manual.html is out of date: run py -3.12 tools/build_manual.py", file=sys.stderr)
        return 0 if ok else 1
    TARGET.write_text(page, encoding="utf-8", newline="\n"); print(f"Wrote {TARGET.relative_to(ROOT)} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
