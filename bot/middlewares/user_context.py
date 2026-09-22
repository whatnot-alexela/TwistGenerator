"""Resolve the Telegram user into a database row, once per update.

Handlers get a ``User`` rather than a telegram id, so none of them has to
remember to create the row first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import User


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, sessions: async_sessionmaker[AsyncSession], owner_id: int) -> None:
        self.sessions = sessions
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        if telegram_user is None:
            return await handler(event, data)

        async with self.sessions() as session:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id))
            if user is None:
                user = User(
                    telegram_id=telegram_user.id,
                    username=telegram_user.username,
                    first_name=telegram_user.first_name,
                    language_code=telegram_user.language_code,
                    is_owner=telegram_user.id == self.owner_id,
                )
                session.add(user)
            else:
                user.username = telegram_user.username
                user.first_name = telegram_user.first_name
                # Ownership can be granted after the row already exists.
                user.is_owner = user.is_owner or telegram_user.id == self.owner_id
            await session.commit()
            data["user"] = user
            data["user_id"] = user.id
            data["is_owner"] = user.is_owner

        return await handler(event, data)
