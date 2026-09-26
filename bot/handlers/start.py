"""Entry points and the always-available commands."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import keyboards, texts
from bot.config import Settings
from core.quota import Mode
from core.quota import check as check_quota
from db.models import User

router = Router(name="start")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    # Two keyboards, two jobs: the persistent one makes sure reopening the bot
    # is never a blank chat, the inline one is the menu itself.
    await message.answer(texts.WELCOME_BACK, reply_markup=keyboards.begin())
    await message.answer(texts.START, reply_markup=keyboards.modes())


@router.message(F.text == texts.BEGIN)
async def begin(message: Message, state: FSMContext) -> None:
    """The persistent button.

    No state filter, and this router is included first, so pressing it while
    the bot is waiting for a genre shows the menu instead of recording «✨
    Начать» as the genre.
    """
    await state.clear()
    await message.answer(texts.START, reply_markup=keyboards.modes())


@router.message(Command("help"))
@router.callback_query(F.data == "nav:help")
async def help_command(event: Message | CallbackQuery) -> None:
    target = event if isinstance(event, Message) else event.message
    if isinstance(target, Message):
        await target.answer(texts.HELP)
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(Command("methodology"))
async def methodology(message: Message, settings: Settings) -> None:
    await message.answer(texts.methodology(settings.methodology_url))


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CANCELLED)


@router.message(Command("formula"))
async def formula(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CHOOSE_CHANGE_TYPE, reply_markup=keyboards.change_types())


@router.message(Command("limits"))
async def limits(
    message: Message,
    user: User,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """What is left today. Read-only — checking must never consume anything."""
    async with sessions() as session:
        merged = await session.merge(user)
        by_formula = await check_quota(session, merged, Mode.FORMULA, settings)
        by_situation = await check_quota(session, merged, Mode.EXPECTATION, settings)
        # Rolled back: check() creates today's usage row as a side effect, and a
        # status command has no business writing anything.
        await session.rollback()

    await message.answer(
        texts.limits(
            free_formula=by_formula.free_left,
            free_expectation=by_situation.free_left,
            paid=merged.paid_units,
        )
    )
