"""Tests for the formula module.

The matrix test below is the single most important test in the project: the
paradox rule is computed rather than looked up, so it has to be checked against
the author's own generation matrix, cell by cell, for all 192 formulas.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from core.formula import (
    ARTIFICIAL_CAUSES,
    CAUSES,
    CHANGE_KINDS,
    CHANGE_TYPES,
    NATURAL_CAUSES,
    Formula,
    FormulaError,
    ParadoxVerdict,
    all_formulas,
    classify_paradox,
    foreign_causes,
    normalise,
)

FIXTURE = Path(__file__).parent / "fixtures" / "matrix.csv"


def load_matrix() -> dict[str, bool]:
    """The generation matrix as transcribed from the source image."""
    rows: dict[str, bool] = {}
    with FIXTURE.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            for code, has_paradox in csv.reader([line]):
                if code == "formula":
                    continue
                rows[code] = has_paradox == "true"
    return rows


# --------------------------------------------------------------------------- #
# The matrix
# --------------------------------------------------------------------------- #


def test_fixture_covers_the_whole_code_space() -> None:
    matrix = load_matrix()
    assert len(matrix) == 192
    assert set(matrix) == {f.code for f in all_formulas()}


@pytest.mark.parametrize("formula", all_formulas(), ids=lambda f: f.code)
def test_paradox_rule_matches_the_generation_matrix(formula: Formula) -> None:
    """Every cell of the matrix must agree with the computed verdict."""
    expected = load_matrix()[formula.code]
    assert formula.paradox.has_any is expected, (
        f"{formula.code}: matrix says has_paradox={expected}, rule says {formula.paradox.value}"
    )


def test_matrix_has_exactly_four_paradox_free_formulas_per_row() -> None:
    matrix = load_matrix()
    for change_type in CHANGE_TYPES:
        for kind in CHANGE_KINDS:
            row = [v for k, v in matrix.items() if k.startswith(f"{change_type}{kind}-")]
            assert len(row) == 16
            assert row.count(False) == 4


# --------------------------------------------------------------------------- #
# The rule itself
# --------------------------------------------------------------------------- #


def test_foreign_causes_are_the_opposite_kind() -> None:
    assert foreign_causes("е") == ARTIFICIAL_CAUSES
    assert foreign_causes("и") == NATURAL_CAUSES
    assert set(CAUSES) == NATURAL_CAUSES | ARTIFICIAL_CAUSES
    assert not NATURAL_CAUSES & ARTIFICIAL_CAUSES


@pytest.mark.parametrize(
    ("kind", "c1", "c2", "expected"),
    [
        # Natural: Ф and М are at home, Д and К are foreign.
        ("е", "Ф", "М", ParadoxVerdict.NONE),
        ("е", "Ф", "Д", ParadoxVerdict.PARADOX_2),
        ("е", "Д", "М", ParadoxVerdict.PARADOX_1),
        ("е", "Д", "К", ParadoxVerdict.BOTH),
        ("е", "К", "К", ParadoxVerdict.BOTH),
        ("е", "Ф", "Ф", ParadoxVerdict.NONE),
        # Artificial: mirrored.
        ("и", "Д", "К", ParadoxVerdict.NONE),
        ("и", "Д", "Ф", ParadoxVerdict.PARADOX_2),
        ("и", "Ф", "К", ParadoxVerdict.PARADOX_1),
        ("и", "Ф", "М", ParadoxVerdict.BOTH),
        ("и", "М", "М", ParadoxVerdict.BOTH),
        ("и", "Д", "Д", ParadoxVerdict.NONE),
    ],
)
def test_classify_paradox_worked_examples(
    kind: str, c1: str, c2: str, expected: ParadoxVerdict
) -> None:
    assert classify_paradox(kind, c1, c2) == expected


def test_the_two_kinds_are_mirror_images() -> None:
    """Keeping the shift and swapping the kind inverts the verdict completely.

    Every cause that was at home becomes foreign, so NONE becomes BOTH and each
    paradox becomes the other one: ``е-ФД`` carries paradox №2 (the Revelation
    introduces an agent into a natural process), while ``и-ФД`` carries paradox
    №1 (an artificial process is presented through a bare form).
    """
    mirror = {
        ParadoxVerdict.NONE: ParadoxVerdict.BOTH,
        ParadoxVerdict.BOTH: ParadoxVerdict.NONE,
        ParadoxVerdict.PARADOX_1: ParadoxVerdict.PARADOX_2,
        ParadoxVerdict.PARADOX_2: ParadoxVerdict.PARADOX_1,
    }
    for c1 in CAUSES:
        for c2 in CAUSES:
            natural = classify_paradox("е", c1, c2)
            artificial = classify_paradox("и", c1, c2)
            assert artificial == mirror[natural], f"{c1}{c2}"


def test_classify_paradox_rejects_unknown_kind() -> None:
    with pytest.raises(FormulaError):
        classify_paradox("x", "Ф", "М")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["1е-ФД", "1е.ФД", "1еФД", " 1е-ФД ", "1е - ФД"])
def test_parse_accepts_every_separator(raw: str) -> None:
    assert Formula.parse(raw).code == "1е-ФД"


def test_parse_folds_latin_homoglyphs() -> None:
    """A user on a Latin layout types M, K and e that look right but are not."""
    assert Formula.parse("1e-ФД").code == "1е-ФД"  # Latin "e" in the kind
    assert Formula.parse("6и-KМ").code == "6и-КМ"  # Latin "K" in the cause
    assert Formula.parse("2е-MД").code == "2е-МД"  # Latin "M" in the cause
    assert normalise("1e-KM") == "1е-КМ"  # all three at once


@pytest.mark.parametrize(
    "raw",
    ["", "1е", "7е-ФД", "0и-ФД", "1х-ФД", "1е-ФX", "1е-ФДК", "твист", "1е-фд"],
)
def test_parse_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(FormulaError):
        Formula.parse(raw)


@pytest.mark.parametrize("formula", all_formulas(), ids=lambda f: f.code)
def test_parse_round_trips_every_formula(formula: Formula) -> None:
    assert Formula.parse(formula.code) == formula


def test_direct_construction_validates() -> None:
    with pytest.raises(FormulaError):
        Formula(change_type=9, change_kind="е", cause_1="Ф", cause_2="М")
    with pytest.raises(FormulaError):
        Formula(change_type=1, change_kind="x", cause_1="Ф", cause_2="М")
    with pytest.raises(FormulaError):
        Formula(change_type=1, change_kind="е", cause_1="Ф", cause_2="Z")


# --------------------------------------------------------------------------- #
# Rendering and helpers
# --------------------------------------------------------------------------- #


def test_accessors() -> None:
    formula = Formula.parse("6и-КМ")
    assert formula.group == "6и"
    assert formula.shift == "КМ"
    assert str(formula) == "6и-КМ"
    assert not formula.is_content_shift
    assert Formula.parse("6и-КК").is_content_shift


def test_describe_reads_as_russian() -> None:
    text = Formula.parse("6и-ФК").describe()
    assert "искусственное" in text
    assert "Исчезновение" in text
    assert "Формальная" in text
    assert "Конечная" in text


def test_all_formulas_is_the_full_space_without_duplicates() -> None:
    formulas = all_formulas()
    assert len(formulas) == 192
    assert len({f.code for f in formulas}) == 192
    assert sum(f.is_content_shift for f in formulas) == 48


def test_content_shift_count_matches_the_methodology_arithmetic() -> None:
    """144 archetypes + 48 content shifts = 192; the methodology counts 40 of the
    48 because Growth and Decline are not split in v1.0 (docs/SPEC.md §3.7)."""
    formulas = all_formulas()
    archetypes = [f for f in formulas if not f.is_content_shift]
    assert len(archetypes) == 144
