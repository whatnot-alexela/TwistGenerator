"""Tests for the example catalogue loader.

Most of these run against the real, committed catalogue, so they double as a
regression test on the import pipeline's output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.catalog import Catalog, CatalogError, Coverage
from core.formula import Formula

REAL_CATALOG = Path(__file__).resolve().parent.parent / "methodology" / "examples"

#: Transcribed from the coverage report of scripts/import_fb2.py and verified by
#: hand against the methodology's appendices.
UNREFERENCED = {
    "1е-ФМ",
    "1е-МФ",
    "1е-МД",
    "1е-ДМ",
    "1е-ДК",
    "1е-КФ",
    "1е-КМ",
    "1е-КД",
    "6и-ФМ",
    "6и-МФ",
}


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load(REAL_CATALOG)


# --------------------------------------------------------------------------- #
# The committed catalogue
# --------------------------------------------------------------------------- #


def test_the_two_finished_appendices_are_present(catalog: Catalog) -> None:
    assert catalog.groups() == {"1е", "6и"}
    assert len(catalog) == 24


def test_every_catalogued_formula_has_at_least_one_example(catalog: Catalog) -> None:
    for code in ("1е-ФД", "6и-КД"):
        entry = catalog.get(code)
        assert entry is not None
        assert entry.examples


def test_unreferenced_formulas_match_the_methodology(catalog: Catalog) -> None:
    assert set(catalog.unreferenced()) == UNREFERENCED


def test_example_text_survived_the_import(catalog: Catalog) -> None:
    """Regression: an early import stripped every space out of the example text."""
    entry = catalog.get("1е-ФД")
    assert entry is not None
    example = entry.examples[0]
    assert example.expectation.startswith("стая животных мигрирует")
    assert " " in example.revelation


def test_reference_metadata_survived_the_import(catalog: Catalog) -> None:
    entry = catalog.get("1е-ФД")
    assert entry is not None
    titles = {reference.title for reference in entry.references}
    assert "Шоу Трумана" in titles
    assert "Граф Монте-Кристо" in titles
    monte_cristo = next(r for r in entry.references if r.title == "Граф Монте-Кристо")
    assert monte_cristo.kind == "book"
    assert monte_cristo.year == 1844
    assert monte_cristo.credit == "Александр Дюма"


def test_reference_label_is_ready_for_the_card(catalog: Catalog) -> None:
    entry = catalog.get("1е-ФД")
    assert entry is not None
    labels = {reference.label for reference in entry.references}
    assert "Книга «Граф Монте-Кристо» (Александр Дюма, 1844)" in labels


# --------------------------------------------------------------------------- #
# The three coverage states
# --------------------------------------------------------------------------- #


def test_full_coverage(catalog: Catalog) -> None:
    assert catalog.coverage("1е-ФД") is Coverage.FULL


def test_unreferenced_coverage(catalog: Catalog) -> None:
    """These are the ones that earn «Ура, вы нашли малоисследованный твист»."""
    assert catalog.coverage("1е-ФМ") is Coverage.UNREFERENCED


@pytest.mark.parametrize("code", ["2е-ФД", "1е-ФФ", "6и-ДД", "4и-КМ"])
def test_uncatalogued_coverage(catalog: Catalog, code: str) -> None:
    """Groups whose appendix is not written yet, and the content shifts."""
    assert catalog.coverage(code) is Coverage.UNCATALOGUED
    assert code not in catalog


def test_content_shifts_of_finished_groups_are_still_uncatalogued(catalog: Catalog) -> None:
    for shift in ("ФФ", "ММ", "ДД", "КК"):
        assert catalog.coverage(f"1е-{shift}") is Coverage.UNCATALOGUED
        assert catalog.coverage(f"6и-{shift}") is Coverage.UNCATALOGUED


# --------------------------------------------------------------------------- #
# Slice selection
# --------------------------------------------------------------------------- #


def test_slice_is_reproducible_from_its_seed(catalog: Catalog) -> None:
    formula = Formula.parse("6и-КД")
    first = catalog.build_slice(formula, seed=12345)
    second = catalog.build_slice(formula, seed=first.seed)
    assert first == second


def test_slice_varies_across_seeds_when_there_is_something_to_vary(
    catalog: Catalog,
) -> None:
    formula = Formula.parse("1е-КФ")  # three example variants
    chosen = {catalog.build_slice(formula, seed=seed).example for seed in range(40)}
    assert len(chosen) > 1


def test_slice_for_an_uncatalogued_formula_is_empty_but_valid(catalog: Catalog) -> None:
    result = catalog.build_slice(Formula.parse("3и-МК"))
    assert result.coverage is Coverage.UNCATALOGUED
    assert result.example is None
    assert result.reference is None
    assert result.seed is not None


def test_slice_for_an_unreferenced_formula_has_an_example_only(catalog: Catalog) -> None:
    result = catalog.build_slice(Formula.parse("1е-ФМ"), seed=1)
    assert result.coverage is Coverage.UNREFERENCED
    assert result.example is not None
    assert result.reference is None


def test_slice_without_a_seed_still_records_one(catalog: Catalog) -> None:
    result = catalog.build_slice(Formula.parse("1е-ФД"))
    replayed = catalog.build_slice(Formula.parse("1е-ФД"), seed=result.seed)
    assert replayed.example == result.example
    assert replayed.reference == result.reference


# --------------------------------------------------------------------------- #
# Malformed input is fatal
# --------------------------------------------------------------------------- #


def write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "bad.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_missing_directory_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        Catalog.load(tmp_path / "nowhere")


def test_invalid_yaml_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="invalid YAML"):
        Catalog.load(write(tmp_path, "formulas: [\n"))


def test_unknown_formula_code_is_fatal(tmp_path: Path) -> None:
    body = 'group: "1е"\nchange_type: 1\nchange_kind: "е"\nformulas:\n  - code: "9я-ЯЯ"\n'
    with pytest.raises(CatalogError, match="not a twist formula"):
        Catalog.load(write(tmp_path, body))


def test_formula_in_the_wrong_group_is_fatal(tmp_path: Path) -> None:
    body = 'group: "1е"\nchange_type: 1\nchange_kind: "е"\nformulas:\n  - code: "6и-ФД"\n'
    with pytest.raises(CatalogError, match="does not belong to group"):
        Catalog.load(write(tmp_path, body))


def test_missing_required_key_is_fatal(tmp_path: Path) -> None:
    body = 'group: "1е"\nchange_type: 1\nchange_kind: "е"\n'
    with pytest.raises(CatalogError, match="missing required key 'formulas'"):
        Catalog.load(write(tmp_path, body))


def test_example_without_a_revelation_is_fatal(tmp_path: Path) -> None:
    body = (
        'group: "1е"\nchange_type: 1\nchange_kind: "е"\nformulas:\n'
        '  - code: "1е-ФД"\n    examples:\n      - expectation: "нечто"\n'
    )
    with pytest.raises(CatalogError, match="missing required key 'revelation'"):
        Catalog.load(write(tmp_path, body))


def test_duplicate_formula_across_files_is_fatal(tmp_path: Path) -> None:
    body = 'group: "1е"\nchange_type: 1\nchange_kind: "е"\nformulas:\n  - code: "1е-ФД"\n'
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(CatalogError, match="duplicate formula"):
        Catalog.load(tmp_path)


# --------------------------------------------------------------------------- #
# Source damage repaired at import (methodology/corrections.yaml)
# --------------------------------------------------------------------------- #


def test_damaged_words_are_repaired_in_the_catalogue(catalog: Catalog) -> None:
    """The FB2 source has words with a dropped letter or a missing space. Users
    read this text in the formula card, so it must arrive repaired."""
    entry = catalog.get("6и-ФК")
    assert entry is not None
    example = " ".join(e.expectation + e.revelation for e in entry.examples)
    assert "изменения общественных" in example
    assert "корпорации" in example
    assert "измененияобщественных" not in example
    assert "корпор ции" not in example


def test_no_damaged_word_survives_anywhere(catalog: Catalog) -> None:
    for code in ("1е-ФД", "6и-ФД", "6и-ФК"):
        entry = catalog.get(code)
        assert entry is not None
        blob = " ".join(
            [e.expectation + e.revelation for e in entry.examples]
            + [r.analysis + (r.note or "") for r in entry.references]
        )
        for damage in ("Кажд ерть", "имитироватьрезонансный", "корпор ции"):
            assert damage not in blob, f"{code}: {damage}"
