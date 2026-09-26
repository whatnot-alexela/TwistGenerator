"""Tests for the per-formula slice — block B and block C.

The slice is what makes one generation different from another, so what it must
never do is as important as what it contains: no appendix the formula does not
need, no claim that an example exists when it does not.
"""

from __future__ import annotations

import pytest

from core.catalog import Catalog
from core.formula import Formula
from core.prompt.builder import PromptBuilder
from core.prompt.slice import (
    MAX_CHARACTERS,
    MAX_GENRE,
    MAX_SITUATION,
    UserInput,
    UserInputError,
    build_slice,
)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load()


@pytest.fixture(scope="module")
def builder() -> PromptBuilder:
    return PromptBuilder()


def slice_for(
    code: str,
    catalog: Catalog,
    builder: PromptBuilder,
    user_input: UserInput | None = None,
    seed: int = 1,
) -> str:
    formula = Formula.parse(code)
    return build_slice(formula, catalog.build_slice(formula, seed=seed), builder, user_input)


# --------------------------------------------------------------------------- #
# The formula itself
# --------------------------------------------------------------------------- #


def test_the_formula_is_spelled_out(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("6и-ФК", catalog, builder)
    assert "6и-ФК" in text
    assert "искусственное" in text
    assert "Исчезновение" in text


@pytest.mark.parametrize(
    ("code", "expected", "forbidden"),
    [
        ("1е-ФМ", "Парадокса нет", "Парадокс №1"),
        ("1е-ФД", "Парадокс №2", "Парадокс №1 —"),
        ("1е-ДМ", "Парадокс №1", "Парадокс №2 —"),
        ("1е-ДК", "Оба парадокса", "Парадокса нет"),
    ],
)
def test_the_paradox_statement_matches_the_formula(
    code: str, expected: str, forbidden: str, catalog: Catalog, builder: PromptBuilder
) -> None:
    text = slice_for(code, catalog, builder)
    assert expected in text
    assert forbidden not in text


def test_a_paradox_free_formula_is_told_not_to_invent_one(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    assert "Не добавляй парадокс" in slice_for("1е-ФМ", catalog, builder)


def test_a_content_shift_is_explained(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("1е-ФФ", catalog, builder)
    assert "твист содержания причины" in text
    assert "ошибка не в типе, а в содержании" in text


def test_an_ordinary_shift_gets_no_content_shift_note(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    assert "твист содержания причины" not in slice_for("1е-ФД", catalog, builder)


# --------------------------------------------------------------------------- #
# Appendices ride only when the formula needs them
# --------------------------------------------------------------------------- #


def test_appendix_6_rides_with_paradox_1_only(catalog: Catalog, builder: PromptBuilder) -> None:
    assert "Обоснование Парадокса №1" in slice_for("1е-ДМ", catalog, builder)
    assert "Обоснование Парадокса №2" not in slice_for("1е-ДМ", catalog, builder)


def test_appendix_7_rides_with_paradox_2_only(catalog: Catalog, builder: PromptBuilder) -> None:
    assert "Обоснование Парадокса №2" in slice_for("1е-ФД", catalog, builder)
    assert "Обоснование Парадокса №1" not in slice_for("1е-ФД", catalog, builder)


def test_both_appendices_ride_with_both_paradoxes(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("1е-ДК", catalog, builder)
    assert "Обоснование Парадокса №1" in text
    assert "Обоснование Парадокса №2" in text


def test_no_appendix_rides_without_a_paradox(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("1е-ФМ", catalog, builder)
    assert "Обоснование Парадокса" not in text


def test_leaving_out_the_wrong_appendix_saves_most_of_the_slice(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    """Appendix 7 alone is 8 800 tokens; sending it to every formula would
    dominate the bill."""
    without = len(slice_for("1е-ФМ", catalog, builder))
    with_both = len(slice_for("1е-ДК", catalog, builder))
    assert with_both > without * 5


# --------------------------------------------------------------------------- #
# What the methodology has, and what it does not
# --------------------------------------------------------------------------- #


def test_a_catalogued_formula_carries_its_example(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("1е-ФД", catalog, builder, seed=1)
    assert "Канонический пример" in text
    assert "Ожидание:" in text
    assert "Откровение:" in text


def test_a_referenced_formula_names_the_work(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("1е-ФД", catalog, builder, seed=1)
    assert "Реализация в известном произведении" in text
    assert "Шоу Трумана" in text or "Граф Монте-Кристо" in text


def test_an_unreferenced_formula_says_so_without_inventing_a_film(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    text = slice_for("1е-ФМ", catalog, builder)
    assert "Реализаций этой формулы в кино и литературе Методика не нашла" in text
    assert "Реализация в известном произведении" not in text


def test_an_uncatalogued_formula_admits_it(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for("3и-МК", catalog, builder)
    assert "Канонических примеров для этой формулы в Методике пока нет" in text
    assert "не выдумывай, будто пример существует" in text
    assert "Канонический пример" not in text


def test_the_example_is_framed_as_mechanics_not_as_a_theme(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    """Otherwise the model rewrites the example instead of using the formula."""
    text = slice_for("1е-ФД", catalog, builder)
    assert "Не пересказывай" in text
    assert "должны быть другими" in text


def test_the_slice_is_reproducible_from_a_seed(catalog: Catalog, builder: PromptBuilder) -> None:
    assert slice_for("1е-КФ", catalog, builder, seed=42) == slice_for(
        "1е-КФ", catalog, builder, seed=42
    )


# --------------------------------------------------------------------------- #
# User input
# --------------------------------------------------------------------------- #


def test_user_fields_reach_the_prompt(catalog: Catalog, builder: PromptBuilder) -> None:
    text = slice_for(
        "1е-ФД",
        catalog,
        builder,
        UserInput(genre="нуар", characters="детектив и вдова", setting="Марсель, 1920-е"),
    )
    assert "Жанр: нуар" in text
    assert "Персонажи: детектив и вдова" in text
    assert "Сеттинг или эпоха: Марсель, 1920-е" in text


def test_empty_fields_are_left_out_rather_than_sent_blank(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    text = slice_for("1е-ФД", catalog, builder, UserInput(genre="нуар"))
    assert "Жанр: нуар" in text
    assert "Персонажи:" not in text
    assert "Сеттинг" not in text


def test_no_input_at_all_says_so_plainly(catalog: Catalog, builder: PromptBuilder) -> None:
    assert "не задал дополнительных условий" in slice_for("1е-ФД", catalog, builder)


def test_a_user_situation_is_passed_through_and_protected(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    situation = "Деревня пустеет: молодёжь уезжает в город каждый год."
    text = slice_for("1е-ФД", catalog, builder, UserInput(situation=situation))
    assert situation in text
    assert "это его Ожидание" in text
    assert "не придумывай собственную ситуацию" in text


def test_a_conditional_override_is_stated_as_a_premise(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    text = slice_for(
        "1е-ФД",
        catalog,
        builder,
        UserInput(situation="Река обмелела.", condition="если считать реку живым существом"),
    )
    assert "при одном допущении" in text
    assert "если считать реку живым существом" in text


def test_a_condition_without_a_situation_is_not_shown(
    catalog: Catalog, builder: PromptBuilder
) -> None:
    text = slice_for("1е-ФД", catalog, builder, UserInput(condition="допущение"))
    assert "допущение" not in text


@pytest.mark.parametrize(
    ("field", "limit"),
    [("genre", MAX_GENRE), ("characters", MAX_CHARACTERS), ("situation", MAX_SITUATION)],
)
def test_over_length_input_is_rejected_not_truncated(field: str, limit: int) -> None:
    with pytest.raises(UserInputError, match=field):
        UserInput(**{field: "я" * (limit + 1)})


def test_input_at_exactly_the_limit_is_accepted() -> None:
    assert UserInput(genre="ж" * MAX_GENRE).genre is not None


def test_is_empty_ignores_the_condition_field() -> None:
    assert UserInput().is_empty
    assert UserInput(condition="допущение").is_empty
    assert not UserInput(genre="нуар").is_empty
