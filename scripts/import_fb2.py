#!/usr/bin/env python3
"""Turn the methodology's FB2 source into the data the bot runs on.

Idempotent. Run it whenever the author adds an appendix; commit the result.

    python scripts/import_fb2.py methodology/source/twist_generator_v1.fb2

Outputs, all under ``methodology/``:

* ``core/*.md``      — the prompt core blocks (see docs/SPEC.md §4.2)
* ``examples/*.yaml`` — the example catalogue, one file per change code
* ``images/*.jpg``    — the embedded reference tables, for manual transcription

Two things are never overwritten: ``tables/*.md``, which is hand-transcribed
from the images, and any core block whose front matter says ``frozen: true``,
which is hand-condensed. Both are reported as skipped instead.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.formula import (  # noqa: E402
    CAUSES,
    CHANGE_KINDS,
    CHANGE_TYPES,
    Formula,
    FormulaError,
)

FB2_NS: Final[str] = "{http://www.gribuser.ru/xml/fictionbook/2.0}"

#: Section title -> core block filename. Titles are matched by prefix, after
#: whitespace normalisation, because the source numbers them inconsistently.
CORE_SECTIONS: Final[dict[str, str]] = {
    "Часть 1. Философский инструментарий": "a02_six_arenas.md",
    "2. Четыре причины": "a03_four_causes.md",
    "3. Двигатель изменений": "a04_triad.md",
    "4. Естественные и искусственные изменения": "a05_natural_artificial.md",
    "Часть 2. Анатомия сюжетного твиста": "a06_expectation_revelation.md",
    "6. Структура и содержание формулы твиста": "a07_formula_structure.md",
    "8. Парадокс №1": "a08_paradox_rules.part1.md",
    "9. Парадокс №2": "a08_paradox_rules.part2.md",
    "11. Формулы с совмещенными парадоксами": "a08_paradox_rules.part3.md",
    "10. Различие в механике твистов": "a09_paradox_mechanics.md",
    "Приложение 6": "b01_appendix6.md",
    "Приложение 7": "b02_appendix7.md",
}

#: Sections deliberately left out of the prompt. Recorded so the coverage report
#: can show that they were seen and skipped on purpose, not missed.
EXCLUDED_SECTIONS: Final[dict[str, str]] = {
    "От автора": "author's preface, not methodology",
    "Как читать эту книгу": "reading guide, not methodology",
    "Введение": "motivational introduction",
    "Часть 3. Матрица генерации твистов. 7.": "superseded by the computed rule",
    "Заключение": "closing remarks",
    "Фильм «Я — Легенда»": "removed by the author: the twist has a paradox the breakdown omits",
}

#: Appendix section title -> output filename stem.
EXAMPLE_SECTIONS: Final[dict[str, str]] = {
    "1.1. Естественное изменение Места": "1e",
    "6.2. Искусственное изменение Исчезновение": "6i",
}

#: Matched against the raw paragraph, so Latin homoglyphs are spelled out here
#: rather than normalised away — ``normalise`` also strips spaces, which would
#: destroy the example text that follows the code.
_FORMULA_LEAD = re.compile(
    r"^([1-6][еиeu][.\-][ФМДКKMe]{2})\s*(?:вар\.?\s*\d+)?\s*:\s*(.*)$",
    re.DOTALL,
)
_EXPECTATION = re.compile(r"Ожидание\s*:\s*(.*?)(?=Откровение\s*:|$)", re.DOTALL)
_REVELATION = re.compile(r"Откровение\s*:\s*(.*)$", re.DOTALL)
_REFERENCE = re.compile(r"^(Фильм|Книга)\s*:\s*(.*)$", re.DOTALL)
_NOTE = re.compile(r"(Примечание\s*:.*)$", re.DOTALL)
_TITLE_YEAR = re.compile(r"^[«\"“”']?(?P<title>[^»\"“”']+)[»\"“”']?\s*\((?P<meta>[^)]*)\)")
_YEAR = re.compile(r"(1[5-9]\d{2}|20\d{2})")


def squash(text: str) -> str:
    """Collapse whitespace and normalise the unicode the source is littered with."""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Correction:
    """A repair to damage in the source: see methodology/corrections.yaml."""

    find: str
    replace: str
    reason: str
    applied: int = 0


def load_corrections(path: Path) -> list[Correction]:
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    corrections: list[Correction] = []
    for index, item in enumerate(document):
        for key in ("find", "replace", "reason"):
            if key not in item:
                raise SystemExit(f"{path.name}[{index}]: missing required key {key!r}")
        corrections.append(
            Correction(find=item["find"], replace=item["replace"], reason=item["reason"])
        )
    return corrections


def apply_corrections(text: str, corrections: list[Correction]) -> str:
    """Repair one paragraph, counting how often each correction fires."""
    for correction in corrections:
        hits = text.count(correction.find)
        if hits:
            correction.applied += hits
            text = text.replace(correction.find, correction.replace)
    return text


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


@dataclass
class Example:
    expectation: str
    revelation: str


@dataclass
class Reference:
    kind: str  # "film" | "book"
    title: str
    #: Whatever the source puts in the parenthetical beside the title, minus the
    #: year. For books that is the author; for films it is sometimes the
    #: director and sometimes the original title. The source is not consistent,
    #: so this is kept verbatim and never labelled "author".
    credit: str | None
    year: int | None
    analysis: str
    note: str | None


@dataclass
class CatalogueEntry:
    code: str
    examples: list[Example] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)


def read_sections(
    source: Path, corrections: list[Correction] | None = None
) -> tuple[list[Section], dict[str, bytes]]:
    """Return the book's sections in order, plus its embedded images.

    Corrections are applied here, to every paragraph as it is extracted, so that
    everything written downstream — prompt blocks and the example catalogue
    alike — is already repaired.
    """
    corrections = corrections or []
    raw = source.read_text(encoding="utf-8-sig")

    images: dict[str, bytes] = {}
    for match in re.finditer(
        r'<binary content-type="[^"]+" id="([^"]+)">(.*?)</binary>', raw, re.DOTALL
    ):
        images[match.group(1)] = base64.b64decode(re.sub(r"\s", "", match.group(2)))

    body_only = re.sub(r"<binary.*?</binary>", "", raw, flags=re.DOTALL)
    root = ElementTree.fromstring(body_only)

    sections: list[Section] = []
    for node in root.iter(f"{FB2_NS}section"):
        title_node = node.find(f"{FB2_NS}title")
        if title_node is None:
            continue
        title = squash("".join(title_node.itertext()))
        section = Section(title=title)
        for paragraph in node.iter(f"{FB2_NS}p"):
            # A <p> inside the title element is the title itself, not content.
            if paragraph in list(title_node.iter(f"{FB2_NS}p")):
                continue
            text = apply_corrections(squash("".join(paragraph.itertext())), corrections)
            if text:
                section.paragraphs.append(text)
        sections.append(section)
    return sections, images


def parse_reference(kind_word: str, body: str) -> Reference:
    """Split a ``Фильм: "X" (Y, 1998): …`` line into its parts."""
    note_match = _NOTE.search(body)
    note = squash(note_match.group(1)) if note_match else None
    if note_match:
        body = body[: note_match.start()]

    analysis = squash(body)
    title, credit, year = analysis[:120], None, None
    meta_match = _TITLE_YEAR.match(analysis)
    if meta_match:
        title = squash(meta_match.group("title"))
        meta = meta_match.group("meta")
        year_match = _YEAR.search(meta)
        if year_match:
            year = int(year_match.group(1))
            meta = _YEAR.sub("", meta)
        credit = squash(meta.strip(" ,")) or None

    return Reference(
        kind="film" if kind_word == "Фильм" else "book",
        title=title,
        credit=credit,
        year=year,
        analysis=analysis,
        note=note,
    )


def parse_catalogue(section: Section) -> list[CatalogueEntry]:
    """Read one example appendix into catalogue entries, in source order."""
    entries: dict[str, CatalogueEntry] = {}
    order: list[str] = []
    current: CatalogueEntry | None = None

    for paragraph in section.paragraphs:
        lead = _FORMULA_LEAD.match(paragraph)
        if lead:
            try:
                code = Formula.parse(lead.group(1)).code
            except FormulaError:
                continue
            if code not in entries:
                entries[code] = CatalogueEntry(code=code)
                order.append(code)
            current = entries[code]
            _absorb_example(current, lead.group(2))
            continue

        if current is None:
            continue

        reference = _REFERENCE.match(paragraph)
        if reference:
            current.references.append(parse_reference(reference.group(1), reference.group(2)))
            continue

        if paragraph.startswith("Ожидание"):
            _absorb_example(current, paragraph)

    return [entries[code] for code in order]


def _absorb_example(entry: CatalogueEntry, body: str) -> None:
    expectation = _EXPECTATION.search(body)
    revelation = _REVELATION.search(body)
    if expectation and revelation:
        entry.examples.append(
            Example(
                expectation=squash(expectation.group(1)),
                revelation=squash(revelation.group(1)),
            )
        )


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def is_frozen(path: Path) -> bool:
    if not path.exists():
        return False
    head = path.read_text(encoding="utf-8")[:200]
    return bool(re.search(r"^frozen:\s*true\s*$", head, re.MULTILINE))


def write_core_block(out_dir: Path, filename: str, section: Section) -> str:
    path = out_dir / filename
    if is_frozen(path):
        return "skipped (frozen)"
    body = "\n\n".join(section.paragraphs)
    path.write_text(
        f"---\nsource_section: {section.title}\nfrozen: false\n---\n\n"
        f"# {section.title}\n\n{body}\n",
        encoding="utf-8",
    )
    return "written"


def yaml_scalar(value: str) -> str:
    """Quote a scalar for YAML without pulling in a serialiser's line wrapping."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_catalogue(
    out_dir: Path, stem: str, section: Section, entries: list[CatalogueEntry]
) -> None:
    group = stem.replace("i", "и").replace("e", "е")
    change_type = int(group[0])
    change_kind = group[1]

    lines = [
        f"# Generated by scripts/import_fb2.py from: {section.title}",
        "# Hand edits will be overwritten on the next import.",
        f"group: {yaml_scalar(group)}",
        f"change_type: {change_type}",
        f"change_kind: {yaml_scalar(change_kind)}",
        f"source_section: {yaml_scalar(section.title)}",
        "formulas:",
    ]
    for entry in entries:
        lines.append(f"  - code: {yaml_scalar(entry.code)}")
        if entry.examples:
            lines.append("    examples:")
            for example in entry.examples:
                lines.append(f"      - expectation: {yaml_scalar(example.expectation)}")
                lines.append(f"        revelation: {yaml_scalar(example.revelation)}")
        if entry.references:
            lines.append("    references:")
            for reference in entry.references:
                lines.append(f"      - kind: {yaml_scalar(reference.kind)}")
                lines.append(f"        title: {yaml_scalar(reference.title)}")
                credit = yaml_scalar(reference.credit) if reference.credit else "null"
                lines.append(f"        credit: {credit}")
                lines.append(f"        year: {reference.year if reference.year else 'null'}")
                lines.append(f"        analysis: {yaml_scalar(reference.analysis)}")
                note = yaml_scalar(reference.note) if reference.note else "null"
                lines.append(f"        note: {note}")

    (out_dir / f"{stem}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def matches(title: str, prefixes: dict[str, str]) -> str | None:
    for prefix, value in prefixes.items():
        if title.startswith(prefix):
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the FB2 file")
    parser.add_argument("--out", type=Path, default=Path("methodology"))
    args = parser.parse_args()

    corrections = load_corrections(args.out / "corrections.yaml")
    sections, images = read_sections(args.source, corrections)
    for directory in ("core", "examples", "images"):
        (args.out / directory).mkdir(parents=True, exist_ok=True)

    report: list[str] = []
    catalogues: dict[str, list[CatalogueEntry]] = {}
    unknown: list[str] = []

    for section in sections:
        if filename := matches(section.title, CORE_SECTIONS):
            status = write_core_block(args.out / "core", filename, section)
            report.append(f"  core     {filename:<36} {status}")
        elif stem := matches(section.title, EXAMPLE_SECTIONS):
            entries = parse_catalogue(section)
            catalogues[stem] = entries
            write_catalogue(args.out / "examples", stem, section, entries)
            report.append(f"  examples {stem + '.yaml':<36} {len(entries)} formulas")
        elif reason := matches(section.title, EXCLUDED_SECTIONS):
            report.append(f"  excluded {section.title[:36]:<36} {reason}")
        elif section.paragraphs:
            unknown.append(section.title)

    for name, data in images.items():
        (args.out / "images" / name).write_bytes(data)

    # ---- coverage report -------------------------------------------------- #
    print(f"Source: {args.source}")
    print(f"Sections: {len(sections)}   Images: {len(images)}\n")

    misfired = [c for c in corrections if c.applied != 1]
    if misfired:
        print("Corrections that did not apply exactly once:")
        for correction in misfired:
            print(f"  {correction.applied}x  {correction.find[:70]}")
        raise SystemExit(
            "\nEvery correction must match exactly once. A correction that no longer\n"
            "fires has silently stopped repairing the source; one that fires twice is\n"
            "not specific enough. Fix methodology/corrections.yaml."
        )
    print(f"Corrections applied: {len(corrections)}\n")
    print("\n".join(report))

    if unknown:
        print("\nUnrecognised sections (add them to CORE_SECTIONS, EXAMPLE_SECTIONS")
        print("or EXCLUDED_SECTIONS in this script):")
        for title in unknown:
            print(f"  ? {title[:88]}")

    total: Counter[str] = Counter()
    print("\nCatalogue coverage")
    print(f"  {'formula':<10} {'examples':>8} {'refs':>5}")
    for entries in catalogues.values():
        for entry in entries:
            refs = len(entry.references)
            total["formulas"] += 1
            total["examples"] += len(entry.examples)
            total["references"] += refs
            total["films"] += sum(r.kind == "film" for r in entry.references)
            total["books"] += sum(r.kind == "book" for r in entry.references)
            if refs == 0:
                total["unreferenced"] += 1
            marker = "" if refs else "   <- малоисследованный твист"
            print(f"  {entry.code:<10} {len(entry.examples):>8} {refs:>5}{marker}")

    catalogued = {entry.code for entries in catalogues.values() for entry in entries}
    space = len(CHANGE_TYPES) * len(CHANGE_KINDS) * len(CAUSES) ** 2
    print(
        f"\n  catalogued {total['formulas']} of {space} formulas"
        f"   examples {total['examples']}"
        f"   references {total['references']}"
        f" ({total['films']} films, {total['books']} books)"
        f"\n  with an example but no reference: {total['unreferenced']}"
        f"\n  uncatalogued: {space - len(catalogued)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
