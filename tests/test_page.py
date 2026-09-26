"""Tests for the public methodology page.

The page is generated, so the thing worth testing is that it cannot drift from
the methodology the bot uses: the matrix comes from the rule, every catalogued
formula gets a card, and the importer's breadcrumb noise does not reach a
reader.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from core.catalog import Catalog
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES, Formula, all_formulas

ROOT = Path(__file__).resolve().parent.parent
MARKS = {"none": "·", "paradox_1": "1", "paradox_2": "2", "both": "⁑"}


def load_builder() -> ModuleType:
    """Load scripts/build_page.py, which is a script rather than a package."""
    spec = importlib.util.spec_from_file_location("build_page", ROOT / "scripts" / "build_page.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_builder()


@pytest.fixture(scope="module")
def page() -> str:
    return str(builder.build(ROOT / "methodology"))


def test_the_matrix_agrees_with_the_rule(page: str) -> None:
    table = re.search(r'<table class="matrix">(.*?)</table>', page, re.S)
    assert table
    rows = re.findall(r"<tr>(.*?)</tr>", table.group(1), re.S)
    shifts = [f"{a}{b}" for a in CAUSES for b in CAUSES]

    assert len(rows) == len(CHANGE_TYPES) * len(CHANGE_KINDS) + 1
    body = iter(rows[1:])
    for change_type in CHANGE_TYPES:
        for kind in CHANGE_KINDS:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", next(body))
            assert len(cells) == len(shifts)
            for shift, cell in zip(shifts, cells, strict=True):
                formula = Formula(change_type, kind, shift[0], shift[1])
                assert cell == MARKS[formula.paradox.value], formula.code


def test_every_catalogued_formula_has_a_card(page: str) -> None:
    catalog = Catalog.load(ROOT / "methodology" / "examples")
    catalogued = [formula for formula in all_formulas() if formula in catalog]
    assert len(catalogued) == 24  # 1е and 6и, the two finished appendices
    for formula in catalogued:
        assert f"<h4>{formula.code}</h4>" in page


def test_a_formula_without_references_says_so_rather_than_inventing_one(page: str) -> None:
    catalog = Catalog.load(ROOT / "methodology" / "examples")
    assert catalog.unreferenced()  # the ten the author has not placed yet
    assert page.count("Реализаций в кино и литературе пока не найдено.") == len(
        catalog.unreferenced()
    )


def test_the_part_breadcrumb_is_lifted_out_of_the_body(page: str) -> None:
    """The FB2 repeats the part name under every heading; a reader sees it once."""
    assert "<p>[Часть" not in page
    assert '<li class="part">Часть 1' in page


def test_a_block_of_several_sections_drops_every_breadcrumb() -> None:
    part, body = builder.split_part("[Часть 3. Матрица]\n\nтекст\n\n[Часть 3. Матрица]\n\nещё")
    assert part == "Часть 3. Матрица"
    assert "[" not in body


def test_nothing_reaches_the_page_as_raw_markdown(page: str) -> None:
    text = re.sub(r"<[^>]+>", "", page)
    assert "**" not in text
    assert "|---" not in text


def test_markup_in_the_source_cannot_inject_html() -> None:
    rendered = builder.markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_the_committed_page_is_current(page: str) -> None:
    """CI's staleness check, as a test: re-run scripts/build_page.py and commit."""
    committed = ROOT / "docs" / "methodology.html"
    assert committed.read_text(encoding="utf-8") == page
