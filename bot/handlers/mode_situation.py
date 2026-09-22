"""Mode 2 — the user describes a situation and the bot reads it into a formula.

The shape of this dialog follows from one fact about the methodology: the left
half of a formula is determined by the Expectation text, while the Revelation
cause is free. So the bot proposes readings rather than asking, and when the
user overrides it, every button carries the verdict for that choice.

Choosing a contradiction is never silently refused and never silently obeyed.
The rule being violated is quoted, and one of the three ways out rewrites the
Expectation to fit — showing the user exactly what had to change. That is the
path that teaches the methodology rather than merely enforcing it.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.fsm.states import Situation
from bot.handlers.mode_formula import FAILURES, REFUSALS
from bot.middlewares.single_flight import SingleFlight
from core.analysis import Analysis, Compatibility, Reading, Verdict
from core.claude import ClaudeError
from core.formula import Formula
from core.prompt.slice import MAX_SITUATION, UserInput
from core.quota import Mode
from core.service import GenerationService, QuotaExceeded

logger = logging.getLogger(__name__)
router = Router(name="mode_situation")


# --------------------------------------------------------------------------- #
# Describing the situation
# --------------------------------------------------------------------------- #


@router.callback_query(F.data == "mode:situation")
@router.callback_query(F.data == "sit:again")
async def ask_situation(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Situation.describing)
    if isinstance(query.message, Message):
        await query.message.answer(texts.ASK_SITUATION)
    await query.answer()


@router.message(Command("situation"))
async def situation_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Situation.describing)
    await message.answer(texts.ASK_SITUATION)


@router.message(Situation.describing)
async def analyse(
    message: Message,
    state: FSMContext,
    service: GenerationService,
    user_id: int,
    single_flight: SingleFlight,
) -> None:
    situation = (message.text or "").strip()
    if len(situation) > MAX_SITUATION:
        await message.answer(texts.TOO_LONG.format(length=len(situation), limit=MAX_SITUATION))
        return

    async with single_flight.hold(user_id) as acquired:
        if not acquired:
            await message.answer(texts.ALREADY_RUNNING)
            return

        notice = await message.answer(texts.ANALYSING)
        try:
            analysis = await service.analyse_situation(user_id, situation)
        except QuotaExceeded as refused:
            await notice.edit_text(REFUSALS[refused.decision.verdict])
            return
        except ClaudeError as failure:
            await notice.edit_text(FAILURES[failure.outcome])
            return
        except Exception:
            logger.exception("analysis blew up for user %s", user_id)
            await notice.edit_text(texts.ERROR_GENERIC)
            return

    await notice.delete()
    await state.update_data(situation=situation, analysis=_pack(analysis))

    if not analysis.classifiable:
        # The classifier working, not failing: say what is missing rather than
        # guessing a formula the text does not support.
        missing = (
            "\n".join(f"• {item}" for item in analysis.missing_information) or "• подробностей"
        )
        await state.set_state(Situation.describing)
        await message.answer(texts.UNCLASSIFIABLE.format(missing=missing))
        return

    await state.set_state(Situation.readings)
    await message.answer(
        f"{texts.READINGS_INTRO}\n\n{texts.readings_block(analysis.readings)}",
        reply_markup=keyboards.readings(analysis.readings),
    )


# --------------------------------------------------------------------------- #
# Picking the left half
# --------------------------------------------------------------------------- #


@router.callback_query(F.data.startswith("read:"))
async def accept_reading(query: CallbackQuery, state: FSMContext) -> None:
    _, change_type, change_kind, cause_1 = str(query.data).split(":")
    await _offer_cause_2(query, state, int(change_type), change_kind, cause_1)


@router.callback_query(F.data == "man:types")
@router.callback_query(F.data == "man:back")
async def manual_types(query: CallbackQuery, state: FSMContext) -> None:
    analysis = await _analysis(state)
    if analysis is None:
        await query.answer()
        return
    await state.set_state(Situation.manual_type)
    if isinstance(query.message, Message):
        await query.message.answer(
            texts.MANUAL_INTRO, reply_markup=keyboards.manual_types(analysis)
        )
    await query.answer()


@router.callback_query(F.data.startswith("mt:"))
@router.callback_query(F.data.startswith("mk:back:"))
async def manual_kinds(query: CallbackQuery, state: FSMContext) -> None:
    analysis = await _analysis(state)
    if analysis is None:
        await query.answer()
        return
    change_type = int(str(query.data).split(":")[-1])
    await state.set_state(Situation.manual_kind)
    if isinstance(query.message, Message):
        await query.message.edit_text(
            texts.CHOOSE_CHANGE_KIND,
            reply_markup=keyboards.manual_kinds(analysis, change_type),
        )
    await query.answer()


@router.callback_query(F.data.startswith("mk:"))
async def manual_causes(query: CallbackQuery, state: FSMContext) -> None:
    analysis = await _analysis(state)
    if analysis is None:
        await query.answer()
        return
    _, change_type, change_kind = str(query.data).split(":")
    await state.set_state(Situation.manual_cause)
    if isinstance(query.message, Message):
        await query.message.edit_text(
            texts.CHOOSE_CAUSE_1,
            reply_markup=keyboards.manual_causes(analysis, int(change_type), change_kind),
        )
    await query.answer()


@router.callback_query(F.data.startswith("mc:"))
async def manual_chosen(query: CallbackQuery, state: FSMContext) -> None:
    """The override. What happens next depends on the verdict, and a
    contradiction is neither refused nor silently obeyed."""
    analysis = await _analysis(state)
    if analysis is None:
        await query.answer()
        return

    _, raw_type, change_kind, cause_1 = str(query.data).split(":")
    change_type = int(raw_type)
    verdict: Compatibility = analysis.verdict(change_type, change_kind, cause_1)

    if verdict.verdict is Verdict.OK:
        await _offer_cause_2(query, state, change_type, change_kind, cause_1)
        return

    if not isinstance(query.message, Message):
        await query.answer()
        return

    if verdict.verdict is Verdict.CONDITIONAL:
        await query.message.answer(
            texts.CONDITIONAL.format(condition=verdict.condition),
            reply_markup=keyboards.conditional(change_type, change_kind, cause_1),
        )
    else:
        await query.message.answer(
            texts.CONTRADICTION.format(
                explanation=texts.contradiction_note(change_type, change_kind, cause_1)
            ),
            reply_markup=keyboards.contradiction(change_type, change_kind, cause_1),
        )
    await query.answer()


@router.callback_query(F.data.startswith("accept:"))
async def accept_condition(query: CallbackQuery, state: FSMContext) -> None:
    analysis = await _analysis(state)
    _, raw_type, change_kind, cause_1 = str(query.data).split(":")
    change_type = int(raw_type)
    condition = analysis.verdict(change_type, change_kind, cause_1).condition if analysis else None
    await state.update_data(condition=condition, adapt=False)
    await _offer_cause_2(query, state, change_type, change_kind, cause_1)


@router.callback_query(F.data.startswith("force:"))
async def force_contradiction(query: CallbackQuery, state: FSMContext) -> None:
    """A formula cannot be forced onto a text, but the text can be adjusted."""
    _, raw_type, change_kind, cause_1 = str(query.data).split(":")
    await state.update_data(condition=None, adapt=True)
    await _offer_cause_2(query, state, int(raw_type), change_kind, cause_1)


# --------------------------------------------------------------------------- #
# The Revelation, and generating
# --------------------------------------------------------------------------- #


async def _offer_cause_2(
    query: CallbackQuery, state: FSMContext, change_type: int, change_kind: str, cause_1: str
) -> None:
    await state.set_state(Situation.cause_2)
    await state.update_data(change_type=change_type, change_kind=change_kind, cause_1=cause_1)
    if isinstance(query.message, Message):
        await query.message.answer(
            texts.CHOOSE_SITUATION_CAUSE_2,
            reply_markup=keyboards.situation_cause_2(change_type, change_kind, cause_1),
        )
    await query.answer()


@router.callback_query(F.data.startswith("sc2:"))
async def generate(
    query: CallbackQuery,
    state: FSMContext,
    service: GenerationService,
    user_id: int,
    single_flight: SingleFlight,
) -> None:
    _, raw_type, change_kind, cause_1, cause_2 = str(query.data).split(":")
    formula = Formula(
        change_type=int(raw_type),
        change_kind=change_kind,
        cause_1=cause_1,
        cause_2=cause_2,
    )
    data = await state.get_data()
    situation = data.get("situation")
    if not situation or not isinstance(query.message, Message):
        await query.answer()
        return

    async with single_flight.hold(user_id) as acquired:
        if not acquired:
            await query.answer(texts.ALREADY_RUNNING, show_alert=True)
            return

        await query.answer()
        notice = await query.message.answer(texts.GENERATING)
        try:
            result = await service.generate(
                user_id=user_id,
                formula=formula,
                mode=Mode.EXPECTATION,
                user_input=UserInput(
                    genre=data.get("genre"),
                    characters=data.get("characters"),
                    situation=situation,
                    condition=data.get("condition"),
                ),
                adapt_expectation=bool(data.get("adapt")),
            )
        except QuotaExceeded as refused:
            await notice.edit_text(REFUSALS[refused.decision.verdict])
            return
        except ClaudeError as failure:
            await notice.edit_text(FAILURES[failure.outcome])
            return
        except Exception:
            logger.exception("situation generation blew up for user %s", user_id)
            await notice.edit_text(texts.ERROR_GENERIC)
            return

    await notice.delete()
    body = result.text
    if data.get("adapt"):
        body += texts.adapted_notice(situation)
    await query.message.answer(body)
    await query.message.answer(texts.RATE, reply_markup=keyboards.rating(result.generation_id))


# --------------------------------------------------------------------------- #
# Keeping the analysis in the dialog
# --------------------------------------------------------------------------- #


def _pack(analysis: Analysis) -> dict[str, Any]:
    """Store the map in FSM state so every later press is answered offline."""
    return {
        "classifiable": analysis.classifiable,
        "readings": [
            [r.change_type, r.change_kind, r.cause_1, r.justification] for r in analysis.readings
        ],
        "compatibility": {
            key: [item.verdict.value, item.condition]
            for key, item in analysis.compatibility.items()
        },
    }


def _unpack(raw: dict[str, Any]) -> Analysis:
    readings = tuple(
        Reading(int(item[0]), str(item[1]), str(item[2]), str(item[3]))
        for item in raw.get("readings") or []
    )
    compatibility = {
        str(key): Compatibility(Verdict(value[0]), value[1])
        for key, value in (raw.get("compatibility") or {}).items()
    }
    return Analysis(
        classifiable=bool(raw.get("classifiable")),
        readings=readings,
        compatibility=compatibility,
    )


async def _analysis(state: FSMContext) -> Analysis | None:
    raw = (await state.get_data()).get("analysis")
    return _unpack(raw) if isinstance(raw, dict) else None
