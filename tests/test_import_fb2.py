"""Tests for the FB2 import pipeline.

The pipeline runs by hand and its output is committed, so these tests guard the
two things that would silently corrupt that output: the frozen-block protection
and the paragraph parser.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_importer() -> ModuleType:
    """Load scripts/import_fb2.py, which is a script rather than a package."""
    spec = importlib.util.spec_from_file_location("import_fb2", ROOT / "scripts" / "import_fb2.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules, so register first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fb2 = load_importer()


# --------------------------------------------------------------------------- #
# Frozen blocks
# --------------------------------------------------------------------------- #


def test_frozen_block_is_not_overwritten(tmp_path: Path) -> None:
    """A11 is hand-condensed from 2650 tokens to 600; an import must not undo that."""
    path = tmp_path / "a11.md"
    original = "---\nfrozen: true\n---\n\nhand-condensed prose\n"
    path.write_text(original, encoding="utf-8")

    section = fb2.Section(title="10. Различие в механике твистов", paragraphs=["raw source"])
    status = fb2.write_core_block(tmp_path, "a11.md", section)

    assert status == "skipped (frozen)"
    assert path.read_text(encoding="utf-8") == original


def test_unfrozen_block_is_regenerated(tmp_path: Path) -> None:
    path = tmp_path / "a02.md"
    path.write_text("---\nfrozen: false\n---\n\nstale\n", encoding="utf-8")

    section = fb2.Section(title="Часть 1", paragraphs=["fresh"])
    assert fb2.write_core_block(tmp_path, "a02.md", section) == "written"
    assert "fresh" in path.read_text(encoding="utf-8")


def test_missing_block_is_created(tmp_path: Path) -> None:
    section = fb2.Section(title="Часть 1", paragraphs=["text"])
    assert fb2.write_core_block(tmp_path, "new.md", section) == "written"
    assert (tmp_path / "new.md").exists()


# --------------------------------------------------------------------------- #
# Paragraph parsing
# --------------------------------------------------------------------------- #


def test_example_keeps_its_spaces() -> None:
    """Regression: normalising the whole paragraph stripped every space."""
    section = fb2.Section(
        title="1.1",
        paragraphs=[
            "1е.ФД: Ожидание: стая животных мигрирует (Форма). Откровение: их гонит хищник."
        ],
    )
    entry = fb2.parse_catalogue(section)[0]
    assert entry.code == "1е-ФД"
    assert entry.examples[0].expectation == "стая животных мигрирует (Форма)."
    assert entry.examples[0].revelation == "их гонит хищник."


def test_variants_accumulate_under_one_formula() -> None:
    section = fb2.Section(
        title="1.1",
        paragraphs=[
            "1е.КФ вар.1: Ожидание: первое (Цель). Откровение: первое (Форма).",
            "Ожидание: второе (Цель). Откровение: второе (Форма).",
        ],
    )
    entries = fb2.parse_catalogue(section)
    assert len(entries) == 1
    assert len(entries[0].examples) == 2


def test_both_separators_are_accepted() -> None:
    section = fb2.Section(
        title="1.1",
        paragraphs=[
            "1е.ФД: Ожидание: а (Форма). Откровение: б (Действующая).",
            "1е-ФК: Ожидание: в (Форма). Откровение: г (Цель).",
        ],
    )
    assert [entry.code for entry in fb2.parse_catalogue(section)] == ["1е-ФД", "1е-ФК"]


def test_reference_is_attached_to_the_preceding_formula() -> None:
    section = fb2.Section(
        title="1.1",
        paragraphs=[
            "1е.ФД: Ожидание: а (Форма). Откровение: б (Действующая).",
            'Книга: "Граф Монте-Кристо" (Александр Дюма, 1844). Дантес считает...',
        ],
    )
    entry = fb2.parse_catalogue(section)[0]
    assert len(entry.references) == 1
    reference = entry.references[0]
    assert reference.kind == "book"
    assert reference.title == "Граф Монте-Кристо"
    assert reference.credit == "Александр Дюма"
    assert reference.year == 1844


def test_film_parenthetical_is_kept_as_credit_not_author() -> None:
    """For films the source often puts the original title there, not a director."""
    reference = fb2.parse_reference("Фильм", '"Шоу Трумана" (The Truman Show, 1998). Ожидание: ...')
    assert reference.kind == "film"
    assert reference.title == "Шоу Трумана"
    assert reference.credit == "The Truman Show"
    assert reference.year == 1998


def test_note_is_split_off_from_the_analysis() -> None:
    reference = fb2.parse_reference(
        "Книга",
        '"Десять негритят" (Агата Кристи, 1939). Разбор. Примечание: Парадокс №1 реализован.',
    )
    assert reference.note == "Примечание: Парадокс №1 реализован."
    assert "Примечание" not in reference.analysis


def test_paragraph_before_any_formula_is_ignored() -> None:
    section = fb2.Section(title="1.1", paragraphs=["Вводный абзац без формулы."])
    assert fb2.parse_catalogue(section) == []


def test_malformed_formula_code_is_skipped_not_fatal() -> None:
    section = fb2.Section(
        title="1.1",
        paragraphs=[
            "9я.ЯЯ: Ожидание: а. Откровение: б.",
            "1е.ФД: Ожидание: а (Форма). Откровение: б (Действующая).",
        ],
    )
    assert [entry.code for entry in fb2.parse_catalogue(section)] == ["1е-ФД"]


# --------------------------------------------------------------------------- #
# Section routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("2. Четыре причины: «Почему» происходит в истории", "a03_four_causes.md"),
        ("Приложение 6. Твисты с парадоксом", "b05_appendix6.source.md"),
        ("Никому не известный раздел", None),
    ],
)
def test_core_section_routing(title: str, expected: str | None) -> None:
    assert fb2.matches(title, fb2.CORE_SECTIONS) == expected


def test_excluded_sections_are_recognised_on_purpose() -> None:
    """Skipped sections must be listed, not silently dropped as unrecognised."""
    assert fb2.matches("От автора", fb2.EXCLUDED_SECTIONS) is not None
    assert fb2.matches("3. Двигатель изменений: триада", fb2.EXCLUDED_SECTIONS) is not None


def test_real_source_parses_into_the_committed_numbers() -> None:
    """End-to-end against the real book: the figures quoted in docs/SPEC.md §3.3."""
    sections, images = fb2.read_sections(ROOT / "methodology" / "source" / "twist_generator_v1.fb2")
    assert len(images) == 7

    catalogued = 0
    examples = 0
    references = 0
    for section in sections:
        if fb2.matches(section.title, fb2.EXAMPLE_SECTIONS):
            entries = fb2.parse_catalogue(section)
            catalogued += len(entries)
            examples += sum(len(entry.examples) for entry in entries)
            references += sum(len(entry.references) for entry in entries)

    assert (catalogued, examples, references) == (24, 29, 20)
