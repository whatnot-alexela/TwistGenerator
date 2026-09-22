"""Tests for the bot layer: texts, keyboards, and the single-flight lock.

The handlers themselves are thin — they translate service outcomes into
messages — so what is tested here is that every outcome *has* a message, and
that the lock which stops a double-tap costing the owner two generations
actually holds.
"""

from __future__ import annotations

import asyncio

import pytest

from bot import keyboards, texts
from bot.handlers.mode_formula import FAILURES, FIELDS, REFUSALS
from bot.main import COMMANDS
from bot.middlewares.single_flight import SingleFlight
from core.analysis import Analysis, Compatibility, Reading
from core.analysis import Verdict as AnalysisVerdict
from core.catalog import Catalog
from core.claude import Outcome
from core.formula import CAUSES, CHANGE_TYPES, Formula, ParadoxVerdict, all_formulas
from core.quota import Verdict


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load()


# --------------------------------------------------------------------------- #
# Every outcome has something to say
# --------------------------------------------------------------------------- #


def test_every_refusal_has_a_message() -> None:
    """A new verdict must not reach a user as a blank message."""
    denied = {verdict for verdict in Verdict if not verdict.allowed}
    assert set(REFUSALS) == denied
    assert all(REFUSALS[verdict].strip() for verdict in denied)


def test_every_failure_has_a_message() -> None:
    failures = {outcome for outcome in Outcome if outcome is not Outcome.OK}
    assert set(FAILURES) == failures
    assert all(FAILURES[outcome].strip() for outcome in failures)


def test_only_an_unavailable_service_invites_a_retry() -> None:
    assert "через минуту" in FAILURES[Outcome.UNAVAILABLE]
    assert "через минуту" not in FAILURES[Outcome.REFUSED]


def test_every_failure_says_the_generation_was_not_charged() -> None:
    """Otherwise the user assumes they lost one and stops trusting the count."""
    for outcome, message in FAILURES.items():
        assert "не списана" in message, outcome


def test_every_paradox_verdict_has_card_text_and_a_button_hint() -> None:
    for verdict in ParadoxVerdict:
        assert texts.PARADOX_CARD[verdict].strip()
        assert texts.PARADOX_HINT[verdict].strip()


# --------------------------------------------------------------------------- #
# The formula card tells the truth about coverage
# --------------------------------------------------------------------------- #


def card(code: str, catalog: Catalog, seed: int = 1) -> str:
    formula = Formula.parse(code)
    return texts.formula_card(formula, catalog.build_slice(formula, seed=seed))


def test_a_fully_covered_formula_shows_example_and_reference(catalog: Catalog) -> None:
    text = card("1е-ФД", catalog)
    assert "Пример из методики" in text
    assert "Шоу Трумана" in text or "Граф Монте-Кристо" in text
    assert texts.UNRESEARCHED not in text


def test_an_unreferenced_formula_gets_the_celebration(catalog: Catalog) -> None:
    text = card("1е-ФМ", catalog)
    assert "малоисследованный твист" in text
    assert "Пример из методики" in text


def test_an_uncatalogued_formula_says_the_appendix_is_unwritten(catalog: Catalog) -> None:
    text = card("3и-МК", catalog)
    assert "ещё не написано" in text
    assert "Пример из методики" not in text
    assert "малоисследованный твист" not in text


def test_the_card_names_the_paradox(catalog: Catalog) -> None:
    assert "Парадокс №1" in card("6и-ФК", catalog)
    assert "Парадокса нет" in card("1е-ФМ", catalog)
    assert "Оба парадокса" in card("1е-ДК", catalog)


def test_the_card_renders_for_every_formula(catalog: Catalog) -> None:
    """Including the 168 with nothing catalogued."""
    for formula in all_formulas():
        text = texts.formula_card(formula, catalog.build_slice(formula, seed=1))
        assert formula.code in text
        assert len(text) > 100


# --------------------------------------------------------------------------- #
# Keyboards
# --------------------------------------------------------------------------- #


def test_every_change_type_is_offered() -> None:
    labels = [b.text for row in keyboards.change_types().inline_keyboard for b in row]
    assert len(labels) == len(CHANGE_TYPES)
    for number, name in CHANGE_TYPES.items():
        assert any(name in label and str(number) in label for label in labels)


def test_the_second_cause_buttons_state_the_resulting_paradox() -> None:
    """The whole point: the user chooses knowing what they are choosing."""
    buttons = [b for row in keyboards.causes_2(1, "е", "Ф").inline_keyboard for b in row]
    labels = {b.text for b in buttons if b.callback_data and b.callback_data.startswith("c2:")}

    assert any(label == "Ф · Формальная — без парадокса" for label in labels)
    assert any(label == "Д · Действующая — Парадокс №2" for label in labels)


def test_the_paradox_hint_matches_the_rule_for_every_combination() -> None:
    for kind in ("е", "и"):
        for cause_1 in CAUSES:
            markup = keyboards.causes_2(1, kind, cause_1)
            for row in markup.inline_keyboard:
                for button in row:
                    if not button.callback_data or not button.callback_data.startswith("c2:"):
                        continue
                    cause_2 = button.callback_data.split(":")[4]
                    formula = Formula(
                        change_type=1, change_kind=kind, cause_1=cause_1, cause_2=cause_2
                    )
                    assert texts.PARADOX_HINT[formula.paradox] in button.text


def test_callback_data_round_trips_into_a_formula() -> None:
    for row in keyboards.causes_2(6, "и", "К").inline_keyboard:
        for button in row:
            if button.callback_data and button.callback_data.startswith("c2:"):
                _, change_type, kind, c1, c2 = button.callback_data.split(":")
                formula = Formula(
                    change_type=int(change_type), change_kind=kind, cause_1=c1, cause_2=c2
                )
                assert formula.group == "6и"
                assert formula.cause_1 == "К"


def test_filled_option_fields_are_ticked() -> None:
    plain = [b.text for row in keyboards.options(False, False, False).inline_keyboard for b in row]
    filled = [b.text for row in keyboards.options(True, False, True).inline_keyboard for b in row]

    assert "Добавить жанр" in plain
    assert "✓ Жанр" in filled
    assert "Добавить персонажей" in filled  # untouched field stays untouched


def test_the_rating_keyboard_marks_the_current_score() -> None:
    unrated = [b.text for row in keyboards.rating(1).inline_keyboard for b in row]
    rated = [b.text for row in keyboards.rating(1, current=4).inline_keyboard for b in row]

    assert "☆4" in unrated
    assert "●4" in rated
    assert "☆5" in rated


def test_every_optional_field_has_a_prompt_and_a_limit() -> None:
    for field, (state, prompt, limit) in FIELDS.items():
        assert state.state, field
        assert prompt.strip(), field
        assert limit > 0, field
        # The prompt must quote the limit, or the user finds out by being told no.
        assert str(limit) in prompt, field


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def test_owner_commands_are_not_advertised() -> None:
    """Listing them invites everyone to try."""
    advertised = {command.command for command in COMMANDS}
    assert "export" not in advertised
    assert "stats" not in advertised


def test_the_advertised_commands_all_have_descriptions() -> None:
    for command in COMMANDS:
        assert command.description.strip()


# --------------------------------------------------------------------------- #
# One generation at a time
# --------------------------------------------------------------------------- #


async def test_a_second_press_is_refused_while_the_first_runs() -> None:
    """Without this, a double-tap bills the owner twice for one user's quota."""
    flight = SingleFlight()
    async with flight.hold(1) as first:
        assert first is True
        async with flight.hold(1) as second:
            assert second is False


async def test_the_lock_is_released_afterwards() -> None:
    flight = SingleFlight()
    async with flight.hold(1):
        pass
    async with flight.hold(1) as again:
        assert again is True


async def test_the_lock_is_released_even_when_the_handler_raises() -> None:
    flight = SingleFlight()
    with pytest.raises(RuntimeError):
        async with flight.hold(1):
            raise RuntimeError("generation blew up")
    async with flight.hold(1) as again:
        assert again is True


async def test_users_do_not_block_each_other() -> None:
    flight = SingleFlight()
    async with flight.hold(1), flight.hold(2) as other:
        assert other is True


async def test_concurrent_presses_let_exactly_one_through() -> None:
    flight = SingleFlight()
    results: list[bool] = []

    async def press() -> None:
        async with flight.hold(7) as acquired:
            results.append(acquired)
            if acquired:
                await asyncio.sleep(0.01)

    await asyncio.gather(*(press() for _ in range(5)))
    assert results.count(True) == 1


# --------------------------------------------------------------------------- #
# Mode 2 — the compatibility markers
# --------------------------------------------------------------------------- #


def analysis_with(**overrides: str) -> Analysis:
    compatibility = {
        f"{n}{k}-{c}": Compatibility(
            AnalysisVerdict(overrides.get(f"{n}{k}_{c}", "contradiction")),
            "если считать реку живым существом"
            if overrides.get(f"{n}{k}_{c}") == "conditional"
            else None,
        )
        for n in CHANGE_TYPES
        for k in ("е", "и")
        for c in CAUSES
    }
    return Analysis(True, (Reading(1, "е", "Ф", "обоснование"),), compatibility)


def test_manual_type_buttons_carry_the_best_verdict_under_them() -> None:
    analysis = analysis_with(**{"1е_Ф": "ok", "2и_Д": "conditional"})
    labels = {b.text for row in keyboards.manual_types(analysis).inline_keyboard for b in row}
    assert any(label.startswith("✅ 1") for label in labels)
    assert any(label.startswith("⚠️ 2") for label in labels)
    assert any(label.startswith("❌ 3") for label in labels)


def test_a_branch_is_not_marked_greener_than_its_contents() -> None:
    analysis = analysis_with()  # everything contradicts
    labels = [b.text for row in keyboards.manual_types(analysis).inline_keyboard for b in row]
    assert not any("✅" in label for label in labels)


def test_cause_buttons_carry_the_exact_verdict() -> None:
    analysis = analysis_with(**{"1е_Ф": "ok", "1е_М": "conditional"})
    labels = {
        b.text for row in keyboards.manual_causes(analysis, 1, "е").inline_keyboard for b in row
    }
    assert "✅ Ф · Формальная" in labels
    assert "⚠️ М · Материальная" in labels
    assert "❌ Д · Действующая" in labels


def test_the_contradiction_keyboard_offers_all_three_ways_out() -> None:
    actions = {
        b.callback_data for row in keyboards.contradiction(1, "е", "Д").inline_keyboard for b in row
    }
    assert "man:types" in actions  # pick another code
    assert "sit:again" in actions  # rewrite the situation
    assert "force:1:е:Д" in actions  # generate anyway, adapting the text


def test_the_revelation_cause_is_never_constrained() -> None:
    """The left half is fixed by the text; this half is the author's choice."""
    buttons = [b for row in keyboards.situation_cause_2(1, "е", "Ф").inline_keyboard for b in row]
    assert len(buttons) == len(CAUSES)
    assert not any("❌" in b.text or "⚠️" in b.text for b in buttons)
    # Each still states the paradox it produces.
    for button in buttons:
        assert "—" in button.text


def test_readings_keyboard_always_offers_the_manual_route() -> None:
    markup = keyboards.readings([Reading(1, "е", "Ф", "обоснование")])
    actions = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "man:types" in actions
    assert "sit:again" in actions
    assert "read:1:е:Ф" in actions


def test_mode_2_texts_explain_the_markers() -> None:
    assert "✅" in texts.MANUAL_INTRO
    assert "⚠️" in texts.MANUAL_INTRO
    assert "❌" in texts.MANUAL_INTRO


def test_the_contradiction_text_quotes_the_rule_rather_than_refusing() -> None:
    note = texts.contradiction_note(1, "и", "Ф")
    assert "определяется" in note
    assert "нельзя" not in note.lower()


def test_the_adapted_notice_shows_the_original() -> None:
    notice = texts.adapted_notice("Деревня пустеет.")
    assert "Деревня пустеет." in notice
    assert "переписано" in notice


def test_situation_command_is_advertised() -> None:
    assert "situation" in {command.command for command in COMMANDS}
