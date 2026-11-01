"""Build docs/manual.html from docs/MANUAL.md (the page the app serves at /manual).

    py -m tools.build_manual            # write docs/manual.html
    py -m tools.build_manual --check    # exit 1 when docs/manual.html is out of date

A small Markdown renderer with exactly what the manual uses - headings, paragraphs, bold/italic/code/links, bullet and numbered
lists (with indented continuation, including code blocks), tables, block quotes, fenced code - so the manual needs no
third-party package and is readable offline on the boat.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "MANUAL.md"
TARGET = ROOT / "docs" / "manual.html"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#fff;--fg:#17212b;--muted:#5b6b7a;--line:#d7dee5;--code:#f1f4f7;--accent:#00666b;--quote:#eef7f7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b141b;--fg:#dbe5ec;--muted:#8fa3b3;--line:#233443;--code:#13222d;--accent:#4fd1d5;--quote:#10252b}}}}
html{{scroll-behavior:smooth}}
.back{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:.6rem;padding:.55rem 1rem;padding-top:max(.55rem,env(safe-area-inset-top));background:var(--bg);border-bottom:1px solid var(--line)}}
.back a{{display:inline-block;padding:.5rem .9rem;border:1px solid var(--accent);border-radius:8px;font-weight:700;text-decoration:none}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}}
.wrap{{max-width:60rem;margin:0 auto;padding:1rem 1rem 4rem}}
nav.toc{{border:1px solid var(--line);border-radius:10px;padding:.6rem 1rem;margin:1rem 0 2rem;background:var(--code)}}
nav.toc ul{{margin:.3rem 0;padding-left:0;list-style:none;columns:2 16rem}}
nav.toc a{{text-decoration:none}}
h1{{font-size:1.9rem;margin:.6rem 0}}
h2{{font-size:1.45rem;margin:2.4rem 0 .6rem;padding-top:.6rem;border-top:1px solid var(--line)}}
h3{{font-size:1.15rem;margin:1.6rem 0 .4rem}}
a{{color:var(--accent)}}
code{{background:var(--code);padding:.1em .35em;border-radius:5px;font:0.9em ui-monospace,SFMono-Regular,Consolas,monospace}}
pre{{background:var(--code);padding:.8rem 1rem;border-radius:8px;overflow:auto;line-height:1.35}}
pre code{{background:none;padding:0}}
blockquote{{margin:1rem 0;padding:.5rem 1rem;border-left:4px solid var(--accent);background:var(--quote);border-radius:0 8px 8px 0}}
.table{{overflow-x:auto;margin:1rem 0}}
table{{border-collapse:collapse;width:100%;font-size:.95rem}}
th,td{{border:1px solid var(--line);padding:.35rem .6rem;text-align:left;vertical-align:top}}
th{{background:var(--code)}}
hr{{border:0;border-top:1px solid var(--line);margin:2rem 0}}
li{{margin:.2rem 0}}
</style>
</head>
<body>
<div class="back"><a id="back" href="/">&larr; Back to the app</a></div>
<script>
// In the installed phone app this page opens inside the app window, which has no browser back button: this one returns to the
// app. A pop-up window (desktop) is simply closed; otherwise go back in the history, or to the app's start page.
document.getElementById('back').addEventListener('click', function (event) {{
  event.preventDefault();
  if (window.opener) {{ window.close(); return; }}
  if (history.length > 1) {{ history.back(); return; }}
  location.href = '/';
}});
</script>
<div class="wrap">
{toc}
{body}
</div></body>
</html>
"""


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[^a-z0-9]+", "-", html.unescape(text).lower()).strip("-")


def inline(text: str) -> str:
    """Escape, then apply code, bold, italic and links (code spans are protected from the rest)."""
    spans: list[str] = []

    def keep(match):
        spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def split_row(line: str) -> list[str]:
    cells, current, escaped = [], "", False
    for char in line.strip().strip("|") if line.strip().startswith("|") else line.strip():
        if escaped:
            current += "|" if char == "|" else "\\" + char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += char
    cells.append(current.strip())
    return cells


LIST_ITEM = re.compile(r"^(\s*)([*-]|\d+\.)\s+(.*)$")


def render(lines: list[str], headings: list[tuple[int, str, str]] | None = None) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            language, code = line[3:].strip(), []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre><code class="language-{language}">{html.escape(chr(10).join(code))}</code></pre>')
        elif re.match(r"^#{1,6} ", line):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            if headings is not None and level in (2,):
                headings.append((level, text, slug(text)))
            out.append(f'<h{level} id="{slug(text)}">{inline(text)}</h{level}>')
            i += 1
        elif re.match(r"^---+$", line.strip()):
            out.append("<hr>")
            i += 1
        elif line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].lstrip())
                i += 1
            out.append(f"<blockquote>{render(quote)}</blockquote>")
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1]):
            header = split_row(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            head = "".join(f"<th>{inline(cell)}</th>" for cell in header)
            body = "".join("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in rows)
            out.append(f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        elif LIST_ITEM.match(line):
            ordered = LIST_ITEM.match(line).group(2)[0].isdigit()
            items = []
            while i < len(lines) and (LIST_ITEM.match(lines[i]) or (items and (lines[i].startswith("  ") or not lines[i].strip()))):
                match = LIST_ITEM.match(lines[i])
                if match and not match.group(1):
                    items.append([match.group(3)])
                elif items:
                    items[-1].append(lines[i][2:] if lines[i].startswith("  ") else lines[i])
                i += 1
            rendered = []
            for item in items:
                while item and not item[-1].strip():
                    item.pop()
                inner = render(item)
                if inner.startswith("<p>") and inner.count("<p>") == 1 and inner.endswith("</p>"):
                    inner = inner[3:-4]
                rendered.append(f"<li>{inner}</li>")
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(rendered)}</{tag}>")
        else:
            paragraph = []
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"^(#{1,6} |```|---+$|>|\s*\|)", lines[i])
                and not LIST_ITEM.match(lines[i])
            ):
                paragraph.append(lines[i].strip())
                i += 1
            if not paragraph:  # a line that matched nothing above: never loop on it
                paragraph.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


def build(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    title = re.sub(r"^#\s+", "", lines[0]).strip()
    headings: list[tuple[int, str, str]] = []
    body = render(lines, headings)
    toc = (
        '<nav class="toc"><strong>Contents</strong><ul>'
        + "".join(f'<li><a href="#{anchor}">{inline(text)}</a></li>' for _, text, anchor in headings)
        + "</ul></nav>"
    )
    # the table of contents goes below the title and the introduction, before the first chapter
    first = body.index("<h2 ")
    return PAGE.format(title=html.escape(title), toc="", body=body[:first] + toc + "\n" + body[first:])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when docs/manual.html is out of date")
    args = parser.parse_args(argv)
    page = build(SOURCE.read_text(encoding="utf-8"))
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != page:
            print("docs/manual.html is out of date: run py -m tools.build_manual", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(page, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET.relative_to(ROOT)} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
