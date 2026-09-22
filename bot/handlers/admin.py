"""Owner-only commands.

Unknown users get the same silence an unrecognised command gets: replying
"you are not the owner" tells a stranger the command exists.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import texts
from core.export import build_workbook, collect_stats, parse_window
from core.quota import local_today
from db.models import User

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_owner(user: User | None) -> bool:
    return bool(user and user.is_owner)


@router.message(Command("stats"))
async def stats(message: Message, user: User, sessions: async_sessionmaker[AsyncSession]) -> None:
    if not _is_owner(user):
        return

    async with sessions() as session:
        figures = await collect_stats(session, local_today())
    await message.answer(texts.stats(figures))


@router.message(Command("export"))
async def export(
    message: Message,
    user: User,
    command: CommandObject,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    if not _is_owner(user):
        return

    try:
        window = parse_window((command.args or "").split())
    except ValueError as error:
        await message.answer(texts.EXPORT_BAD_DATES.format(error=error))
        return

    async with sessions() as session:
        report = await build_workbook(session, local_today(), window)

    if not report.rows.get("generations"):
        await message.answer(texts.EXPORT_EMPTY)
        return

    await message.answer_document(
        BufferedInputFile(report.data, filename=report.filename),
        caption=texts.export_caption(report.rows),
    )
    logger.info("export sent to owner: %s", report.rows)
