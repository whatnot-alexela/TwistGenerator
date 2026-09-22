"""Ratings and comments.

Re-rating is allowed and every change is appended to history: how a verdict
moved is itself research data for the methodology.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import keyboards, texts
from bot.fsm.states import Feedback
from db.models import Generation, Rating, RatingHistory

router = Router(name="rating")

MAX_COMMENT = 500


@router.callback_query(F.data.startswith("rate:"))
async def rate(
    query: CallbackQuery, sessions: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    _, raw_id, raw_score = str(query.data).split(":")
    generation_id, score = int(raw_id), int(raw_score)

    async with sessions() as session:
        generation = await session.get(Generation, generation_id)
        if generation is None or generation.user_id != user_id:
            await query.answer()
            return

        rating = await session.scalar(select(Rating).where(Rating.generation_id == generation_id))
        if rating is None:
            rating = Rating(generation_id=generation_id, score=score)
            session.add(rating)
        else:
            rating.score = score
        session.add(RatingHistory(generation_id=generation_id, score=score))
        await session.commit()

    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(
            reply_markup=keyboards.rating(generation_id, current=score)
        )
    await query.answer(texts.RATED)


@router.callback_query(F.data.startswith("comment:"))
async def ask_comment(query: CallbackQuery, state: FSMContext) -> None:
    generation_id = int(str(query.data).split(":")[1])
    await state.set_state(Feedback.awaiting_comment)
    await state.update_data(comment_for=generation_id)
    if isinstance(query.message, Message):
        await query.message.answer(texts.ASK_COMMENT)
    await query.answer()


@router.message(Feedback.awaiting_comment)
async def store_comment(
    message: Message,
    state: FSMContext,
    sessions: async_sessionmaker[AsyncSession],
    user_id: int,
) -> None:
    data = await state.get_data()
    generation_id = data.get("comment_for")
    comment = (message.text or "").strip()

    if len(comment) > MAX_COMMENT:
        await message.answer(texts.TOO_LONG.format(length=len(comment), limit=MAX_COMMENT))
        return

    async with sessions() as session:
        generation = await session.get(Generation, generation_id)
        if generation is None or generation.user_id != user_id:
            await state.clear()
            return

        rating = await session.scalar(select(Rating).where(Rating.generation_id == generation_id))
        if rating is None:
            # A comment without a score is still worth keeping; the neutral 3
            # marks it as unrated rather than inventing an opinion.
            rating = Rating(generation_id=generation_id, score=3, comment=comment)
            session.add(rating)
        else:
            rating.comment = comment
        session.add(RatingHistory(generation_id=generation_id, score=rating.score, comment=comment))
        await session.commit()

    await state.clear()
    await message.answer(texts.COMMENT_SAVED)
