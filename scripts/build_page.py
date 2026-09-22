#!/usr/bin/env python3
"""Build the public methodology page from the imported methodology.

    python scripts/build_page.py

Writes a single self-contained `docs/methodology.html` — no server side, no
assets, nothing to install. Upload it to kiloslov.ru and point
`METHODOLOGY_URL` at it.

Generated from `methodology/` rather than written by hand, so the page cannot
drift from what the bot actually uses: add an appendix, re-run the importer,
re-run this, and the page has it too.

The corrections in `methodology/corrections.yaml` apply here as well — readers
get the repaired text. The redactions do not: those remove the author's own
asides from the *prompt*, and his book is his to publish in full.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.catalog import Catalog  # noqa: E402
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES, Formula, all_formulas  # noqa: E402
from core.prompt.builder import CORE_MANIFEST, PromptBuilder, strip_front_matter  # noqa: E402

TITLE = "Генератор сюжетных твистов по Аристотелю"
SUBTITLE = "188 формул · методика Саши Мара"
BOT_URL = "https://t.me/twist_generator"

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfaf8;
  --fg: #1c1b19;
  --muted: #6b6560;
  --rule: #e3ded7;
  --accent: #8a5a2b;
  --card: #ffffff;
  --mark-none: #9a9490;
  --mark-p1: #2f6f9f;
  --mark-p2: #8a4f9f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #171614;
    --fg: #e8e4de;
    --muted: #9a938b;
    --rule: #2f2d2a;
    --accent: #d09a5e;
    --card: #1f1e1b;
    --mark-none: #6b6560;
    --mark-p1: #6aa8d8;
    --mark-p2: #b98dd0;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 17px/1.65 Georgia, "Times New Roman", serif;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 44rem; margin: 0 auto; padding: 3rem 16px 6rem; }
header { border-bottom: 2px solid var(--rule); padding-bottom: 2rem; margin-bottom: 2.5rem; }
h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 .4rem; font-weight: 600; }
.sub { color: var(--muted); font-size: 1rem; margin: 0; }
h2 {
  font-size: 1.4rem; margin: 3rem 0 1rem; font-weight: 600;
  padding-top: 1.5rem; border-top: 1px solid var(--rule);
}
h3 { font-size: 1.1rem; margin: 2rem 0 .6rem; font-weight: 600; }
p { margin: 0 0 1rem; }
a { color: var(--accent); }
code, .code {
  font: 0.92em/1.4 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  background: var(--card); border: 1px solid var(--rule);
  border-radius: 4px; padding: .1em .35em;
}
nav { background: var(--card); border: 1px solid var(--rule);
  border-radius: 8px; padding: 1.2rem 1.5rem; }
nav ol { margin: 0; padding-left: 1.2rem; }
nav li { margin: .25rem 0; }
nav li.part { list-style: none; margin-left: -1.2rem; margin-top: .9rem;
  color: var(--muted); font-size: .9rem; }
table { border-collapse: collapse; width: 100%; margin: 1.5rem 0; font-size: .92rem; }
th, td { border: 1px solid var(--rule); padding: .5rem .6rem;
  text-align: left; vertical-align: top; }
th { background: var(--card); font-weight: 600; }
.matrix { font: .8rem/1.3 ui-monospace, Menlo, monospace; }
.matrix td, .matrix th { padding: .3rem .25rem; text-align: center; }
.m-none { color: var(--mark-none); }
.m-p1 { color: var(--mark-p1); font-weight: 600; }
.m-p2 { color: var(--mark-p2); font-weight: 600; }
.m-both { color: var(--accent); font-weight: 700; }
.legend { font-size: .9rem; color: var(--muted); }
.legend span { margin-right: 1.2rem; white-space: nowrap; }
.formula { border: 1px solid var(--rule); border-radius: 8px;
  padding: 1rem 1.2rem; margin: 1rem 0; background: var(--card); }
.formula h4 { margin: 0 0 .5rem; font-size: 1.05rem; font-family: ui-monospace, Menlo, monospace; }
.formula .label { color: var(--muted); font-size: .85rem;
  text-transform: uppercase; letter-spacing: .04em; }
.ref { border-left: 3px solid var(--rule); padding-left: 1rem;
  margin-top: .8rem; font-size: .95rem; }
.cta { background: var(--card); border: 1px solid var(--rule); border-radius: 8px;
  padding: 1.5rem; margin: 3rem 0; text-align: center; }
.cta a { font-size: 1.1rem; font-weight: 600; }
footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
  color: var(--muted); font-size: .9rem; }
@media (max-width: 40rem) {
  body { font-size: 16px; }
  .wrap { padding-top: 2rem; }
  h1 { font-size: 1.6rem; }
  .matrix { font-size: .68rem; }
  .matrix td, .matrix th { padding: .2rem .1rem; }
}
"""


def markdown_to_html(text: str) -> str:
    """Enough Markdown for what the importer and the hand-written tables use."""
    out: list[str] = []
    in_table = False
    for line in text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # the separator row
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            row = "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False

        if not stripped:
            continue
        if stripped.startswith("### "):
            out.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h3>{inline(stripped[3:])}</h3>")
        elif stripped.startswith("# "):
            out.append(f"<h2>{inline(stripped[2:])}</h2>")
        elif stripped.startswith("- "):
            out.append(f"<p>— {inline(stripped[2:])}</p>")
        else:
            out.append(f"<p>{inline(stripped)}</p>")

    if in_table:
        out.append("</table>")
    return "\n".join(out)


def inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


#: The FB2 repeats the part name under every section heading, sometimes with a
#: stray bracket. On the page the part becomes a heading of its own, so the
#: line is lifted out rather than printed twice.
BREADCRUMB = re.compile(r"^\[(.+?)\]\[?$")


def split_part(body: str) -> tuple[str | None, str]:
    part: str | None = None
    kept: list[str] = []
    for line in body.split("\n"):
        found = BREADCRUMB.match(line.strip())
        if found:
            # A block can concatenate several source sections, each repeating
            # the line; the first one names the part, the rest are dropped too.
            part = part or found.group(1).strip()
            continue
        kept.append(line)
    return part, "\n".join(kept)


def matrix_table() -> str:
    """The generation matrix, rendered from the rule rather than transcribed."""
    shifts = [f"{a}{b}" for a in CAUSES for b in CAUSES]
    head = "".join(f"<th>{shift}</th>" for shift in shifts)
    rows = [f"<tr><th></th>{head}</tr>"]

    for change_type in CHANGE_TYPES:
        for kind in CHANGE_KINDS:
            cells = []
            for shift in shifts:
                formula = Formula(
                    change_type=change_type,
                    change_kind=kind,
                    cause_1=shift[0],
                    cause_2=shift[1],
                )
                verdict = formula.paradox
                css, mark = {
                    "none": ("m-none", "·"),
                    "paradox_1": ("m-p1", "1"),
                    "paradox_2": ("m-p2", "2"),
                    "both": ("m-both", "⁑"),
                }[verdict.value]
                cells.append(f'<td class="{css}">{mark}</td>')
            rows.append(f"<tr><th>{change_type}{kind}</th>{''.join(cells)}</tr>")

    return f'<table class="matrix">{"".join(rows)}</table>'


def examples_section(catalog: Catalog) -> str:
    parts: list[str] = []
    for formula in all_formulas():
        entry = catalog.get(formula)
        if entry is None:
            continue
        block = [
            '<div class="formula">',
            f"<h4>{formula.code}</h4>",
            f'<p class="label">{html.escape(formula.describe())}</p>',
        ]
        for example in entry.examples:
            block.append(f"<p><strong>Ожидание.</strong> {html.escape(example.expectation)}</p>")
            block.append(f"<p><strong>Откровение.</strong> {html.escape(example.revelation)}</p>")
        for reference in entry.references:
            block.append('<div class="ref">')
            block.append(f"<p><strong>{html.escape(reference.label)}</strong></p>")
            block.append(f"<p>{html.escape(reference.analysis)}</p>")
            if reference.note:
                block.append(f"<p><em>{html.escape(reference.note)}</em></p>")
            block.append("</div>")
        if not entry.references:
            block.append('<p class="legend">Реализаций в кино и литературе пока не найдено.</p>')
        block.append("</div>")
        parts.append("\n".join(block))
    return "\n".join(parts)


def build(methodology: Path) -> str:
    builder = PromptBuilder(methodology_dir=methodology)
    catalog = Catalog.load(methodology / "examples")

    sections: list[tuple[str | None, str, str]] = []
    for spec in CORE_MANIFEST:
        if spec.name in ("a01_role", "a10_output_contract"):
            continue  # instructions to the model, not part of the book
        body = "\n\n".join(
            strip_front_matter((methodology / source).read_text(encoding="utf-8"))
            for source in spec.sources
        )
        part, body = split_part(body)
        first = next(
            (line[2:] for line in body.split("\n") if line.startswith("# ")), spec.name
        ).strip()
        if part and first.startswith(part):
            # The heading carries the part name in front of the chapter title.
            first = first[len(part) :].lstrip(". ")
            body = body.replace(f"# {part}. {first}", f"# {first}", 1)
        sections.append((part, first, markdown_to_html(body)))

    for key, label in (("paradox_1", "Приложение 6"), ("paradox_2", "Приложение 7")):
        block = builder.build_supplement(key)
        sections.append(("Приложения", label, markdown_to_html(block.text)))

    toc_items: list[str] = []
    seen_part: str | None = None
    for index, (part, title, _) in enumerate(sections):
        if part and part != seen_part:
            toc_items.append(f'<li class="part">{html.escape(part)}</li>')
            seen_part = part
        toc_items.append(f'<li><a href="#s{index}">{html.escape(title)}</a></li>')
    toc = "".join(toc_items)

    body = "".join(
        f'<section id="s{index}">{content}</section>'
        for index, (_, _, content) in enumerate(sections)
    )

    causes = "".join(f"<li><b>{letter}</b> — {name}</li>" for letter, name in CAUSES.items())
    types = "".join(f"<li><b>{n}</b> — {name}</li>" for n, name in CHANGE_TYPES.items())

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(TITLE)}</title>
<meta name="description" content="Систематическая методика построения сюжетных
поворотов на основе четырёх причин Аристотеля и шести типов изменения.">
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>{html.escape(TITLE)}</h1>
  <p class="sub">{html.escape(SUBTITLE)}</p>
</header>

<p>Методика превращает придумывание сюжетного поворота из наития в разбираемую
конструкцию. В её основе — аристотелевское учение об изменении и причинности:
шесть типов изменения, два вида, четыре причины. Их сочетания дают
188&nbsp;формул твиста.</p>

<p>Каждая формула описывает механику обмана через модель
<strong>Ожидание&nbsp;→&nbsp;Откровение</strong> и объясняет, какой из двух
парадоксов в ней работает.</p>

<div class="cta">
  <p>Формулы можно не только читать, но и запускать.</p>
  <p><a href="{BOT_URL}">Генератор твистов в Telegram →</a></p>
</div>

<h2>Как читается формула</h2>
<p>Формула выглядит так: <code>1е-ФД</code>.</p>
<table>
<tr><th>Часть</th><th>Что означает</th></tr>
<tr><td><code>1</code></td><td>Тип изменения: <ul>{types}</ul></td></tr>
<tr><td><code>е</code></td><td>Вид изменения: <b>е</b> естественное (судьба,
природа, случай), <b>и</b> искусственное (чья-то воля). Определяется тем, как
ситуация выглядит <em>в Ожидании</em>.</td></tr>
<tr><td><code>Ф</code></td><td>Причина, которую все считают действующей.</td></tr>
<tr><td><code>Д</code></td><td>Причина, которая раскрывается на самом деле.
<ul>{causes}</ul></td></tr>
</table>
<p>Итого <code>1е-ФД</code>: перемещение, которое выглядит естественным; думали,
дело в природе вещей, а оказалось — кто-то действовал.</p>

<h2>Матрица генерации твистов</h2>
<p>Все 192 сочетания и парадокс, который получается в каждом.</p>
{matrix_table()}
<p class="legend">
  <span class="m-none">· без парадокса</span>
  <span class="m-p1">1 Парадокс №1</span>
  <span class="m-p2">2 Парадокс №2</span>
  <span class="m-both">⁑ оба</span>
</p>

<h2>Содержание</h2>
<nav><ol>{toc}</ol></nav>

{body}

<h2>Примеры твистов</h2>
<p>Готовы приложения по двум группам — естественное изменение Места
(<code>1е</code>) и искусственное Исчезновение (<code>6и</code>). Остальные
в работе.</p>
{examples_section(catalog)}

<div class="cta">
  <p><a href="{BOT_URL}">Построить свой твист по любой из 188 формул →</a></p>
</div>

<footer>
  <p>© Саша Мар. Методика «Генератор твистов 1.0».</p>
  <p>Страница собрана из того же текста, на котором работает бот.</p>
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--methodology", type=Path, default=Path("methodology"))
    parser.add_argument("--out", type=Path, default=Path("docs/methodology.html"))
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    page = build(args.methodology)
    args.out.write_text(page, encoding="utf-8")
    print(f"{args.out}  ({len(page):,} bytes)".replace(",", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
