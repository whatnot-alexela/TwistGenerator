"""Tests for warning the owner.

The user is told «Автор уведомлён». These tests exist so that stays true, and
so that a failure to warn never becomes a second failure in front of the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.notify import MAX_DETAIL, tell_owner


@dataclass
class StubBot:
    sent: list[tuple[int, str]] = field(default_factory=list)
    explode: bool = False

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        if self.explode:
            raise RuntimeError("Telegram says no")
        self.sent.append((chat_id, text))


async def test_the_owner_is_told_what_broke() -> None:
    bot = StubBot()
    await tell_owner(bot, 42, "Генерация 6и-ФК не удалась", "BadRequestError: 400")

    ((chat_id, text),) = bot.sent
    assert chat_id == 42
    assert "6и-ФК" in text
    assert "BadRequestError" in text


async def test_a_long_traceback_is_cut_rather_than_rejected() -> None:
    bot = StubBot()
    await tell_owner(bot, 42, "Сбой", "x" * (MAX_DETAIL * 3))

    assert len(bot.sent[0][1]) < MAX_DETAIL + 200


async def test_html_in_the_error_cannot_break_the_message() -> None:
    bot = StubBot()
    await tell_owner(bot, 42, "Сбой", "<b>не разметка</b>")

    assert "&lt;b&gt;" in bot.sent[0][1]


async def test_a_failed_warning_is_swallowed() -> None:
    """The user has already been answered; a second failure helps nobody."""
    await tell_owner(StubBot(explode=True), 42, "Сбой")


async def test_no_detail_means_no_empty_code_block() -> None:
    bot = StubBot()
    await tell_owner(bot, 42, "Сбой")
    assert "<code>" not in bot.sent[0][1]
