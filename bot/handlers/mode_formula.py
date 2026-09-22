"""Mode 1 — the user assembles a formula, then generates from it.

The four choices are a plain walk; the interesting parts are the formula card,
which has to tell the truth about what the methodology does and does not have,
and generation, which must translate every way the service can fail into
something the user can act on.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.fsm.states import Formula as FormulaStates
from bot.middlewares.single_flight import SingleFlight
from core.claude import ClaudeError, Outcome
from core.formula import Formula
from core.prompt.slice import (
    MAX_CHARACTERS,
    MAX_GENRE,
    MAX_SETTING,
    UserInput,
)
from core.quota import Mode, Verdict
from core.service import GenerationService, QuotaExceeded

logger = logging.getLogger(__name__)
router = Router(name="mode_formula")

#: Which refusal gets which explanation. Every verdict is covered, so a new one
#: cannot slip through as a blank message.
REFUSALS = {
    Verdict.DENIED_DAILY_LIMIT: texts.DENIED_DAILY_LIMIT,
    Verdict.DENIED_BUDGET: texts.DENIED_BUDGET,
    Verdict.DENIED_EMERGENCY: texts.DENIED_EMERGENCY,
    Verdict.DENIED_BLOCKED: texts.DENIED_BLOCKED,
}

#: Which failure gets which apology. Only UNAVAILABLE invites a retry.
FAILURES = {
    Outcome.UNAVAILABLE: texts.ERROR_UNAVAILABLE,
    Outcome.REFUSED: texts.ERROR_REFUSED,
    Outcome.TRUNCATED: texts.ERROR_GENERIC,
    Outcome.BROKEN: texts.ERROR_GENERIC,
}

FIELDS = {
    "genre": (FormulaStates.awaiting_genre, texts.ASK_GENRE, MAX_GENRE),
    "characters": (FormulaStates.awaiting_characters, texts.ASK_CHARACTERS, MAX_CHARACTERS),
    "setting": (FormulaStates.awaiting_setting, texts.ASK_SETTING, MAX_SETTING),
}


# --------------------------------------------------------------------------- #
# Building the formula
# --------------------------------------------------------------------------- #


@router.callback_query(F.data == "mode:formula")
@router.callback_query(F.data == "nav:types")
async def choose_change_type(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FormulaStates.change_type)
    await state.update_data(genre=None, characters=None, setting=None)
    await _edit(query, texts.CHOOSE_CHANGE_TYPE, keyboards.change_types())


@router.callback_query(F.data.startswith("type:"))
async def choose_change_kind(query: CallbackQuery, state: FSMContext) -> None:
    change_type = int(_arg(query, 1))
    await state.set_state(FormulaStates.change_kind)
    await _edit(query, texts.CHOOSE_CHANGE_KIND, keyboards.change_kinds(change_type))


@router.callback_query(F.data.startswith("nav:kinds:"))
async def back_to_kinds(query: CallbackQuery, state: FSMContext) -> None:
    change_type = int(_arg(query, 2))
    await state.set_state(FormulaStates.change_kind)
    await _edit(query, texts.CHOOSE_CHANGE_KIND, keyboards.change_kinds(change_type))


@router.callback_query(F.data.startswith("kind:"))
@router.callback_query(F.data.startswith("nav:c1:"))
async def choose_cause_1(query: CallbackQuery, state: FSMContext) -> None:
    offset = 2 if str(query.data).startswith("nav:") else 1
    change_type = int(_arg(query, offset))
    change_kind = _arg(query, offset + 1)
    await state.set_state(FormulaStates.cause_1)
    await _edit(query, texts.CHOOSE_CAUSE_1, keyboards.causes_1(change_type, change_kind))


@router.callback_query(F.data.startswith("c1:"))
async def choose_cause_2(query: CallbackQuery, state: FSMContext) -> None:
    change_type, change_kind, cause_1 = int(_arg(query, 1)), _arg(query, 2), _arg(query, 3)
    await state.set_state(FormulaStates.cause_2)
    await _edit(query, texts.CHOOSE_CAUSE_2, keyboards.causes_2(change_type, change_kind, cause_1))


@router.callback_query(F.data.startswith("c2:"))
async def show_card(query: CallbackQuery, state: FSMContext, service: GenerationService) -> None:
    formula = Formula(
        change_type=int(_arg(query, 1)),
        change_kind=_arg(query, 2),
        cause_1=_arg(query, 3),
        cause_2=_arg(query, 4),
    )
    catalogue = service.catalog.build_slice(formula)

    await state.set_state(FormulaStates.options)
    await state.update_data(formula=formula.code, seed=catalogue.seed)

    if query.message is not None and isinstance(query.message, Message):
        await query.message.answer(texts.formula_card(formula, catalogue))
        await query.message.answer(
            texts.OPTIONS, reply_markup=keyboards.options(False, False, False)
        )
    await query.answer()


# --------------------------------------------------------------------------- #
# Optional input
# --------------------------------------------------------------------------- #


@router.callback_query(F.data.startswith("opt:"), FormulaStates.options)
async def optional_field(query: CallbackQuery, state: FSMContext) -> None:
    field = _arg(query, 1)
    if field == "generate":
        return  # handled by generate() below

    target, prompt, _ = FIELDS[field]
    await state.set_state(target)
    if query.message is not None and isinstance(query.message, Message):
        await query.message.answer(prompt)
    await query.answer()


@router.message(FormulaStates.awaiting_genre)
@router.message(FormulaStates.awaiting_characters)
@router.message(FormulaStates.awaiting_setting)
async def store_field(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    field = next(name for name, (st, _, _) in FIELDS.items() if st.state == current)
    _, _, limit = FIELDS[field]

    value = (message.text or "").strip()
    if len(value) > limit:
        # Rejected rather than truncated: silently cutting a user's sentence in
        # half and generating from the stump is worse than asking again.
        await message.answer(texts.TOO_LONG.format(length=len(value), limit=limit))
        return

    await state.update_data({field: value})
    await state.set_state(FormulaStates.options)
    data = await state.get_data()
    await message.answer(
        texts.OPTIONS,
        reply_markup=keyboards.options(
            bool(data.get("genre")), bool(data.get("characters")), bool(data.get("setting"))
        ),
    )


# --------------------------------------------------------------------------- #
# Generating
# --------------------------------------------------------------------------- #


@router.callback_query(F.data == "opt:generate")
async def generate(
    query: CallbackQuery,
    state: FSMContext,
    service: GenerationService,
    user_id: int,
    single_flight: SingleFlight,
) -> None:
    data = await state.get_data()
    code = data.get("formula")
    if not code or query.message is None or not isinstance(query.message, Message):
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
                formula=Formula.parse(code),
                mode=Mode.FORMULA,
                user_input=UserInput(
                    genre=data.get("genre"),
                    characters=data.get("characters"),
                    setting=data.get("setting"),
                ),
                seed=data.get("seed"),
            )
        except QuotaExceeded as refused:
            await notice.edit_text(REFUSALS[refused.decision.verdict])
            return
        except ClaudeError as failure:
            await notice.edit_text(FAILURES[failure.outcome])
            return
        except Exception:
            logger.exception("generation blew up for user %s", user_id)
            await notice.edit_text(texts.ERROR_GENERIC)
            return

    await notice.delete()
    await query.message.answer(result.text)
    await query.message.answer(texts.RATE, reply_markup=keyboards.rating(result.generation_id))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _arg(query: CallbackQuery, index: int) -> str:
    return str(query.data).split(":")[index]


async def _edit(query: CallbackQuery, text: str, markup: object) -> None:
    if query.message is not None and isinstance(query.message, Message):
        await query.message.edit_text(text, reply_markup=markup)  # type: ignore[arg-type]
    await query.answer()
