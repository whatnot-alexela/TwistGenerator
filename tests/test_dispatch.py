"""Tests that run real presses through a real Dispatcher.

Every other test here calls handlers or keyboards directly, which cannot see
the one thing that actually broke in production: aiogram stops at the first
handler whose filters match, so a handler that matched «Сгенерировать» and
returned early swallowed the press. The button blinked and nothing happened —
no error, no log line, nothing to find.

So these tests feed an Update to a Dispatcher and assert on what came out.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TelegramUser

from bot import texts
from bot.fsm.states import Formula as FormulaStates
from bot.handlers import mode_formula, start
from bot.middlewares.single_flight import SingleFlight
from core.claude import Completion
from core.costs import Usage
from core.formula import Formula
from core.quota import Decision, Verdict
from core.service import Result

CHAT_ID = 4242
USER_ID = 7


class RecordingSession(BaseSession):
    """Answers every API call locally and remembers what was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def close(self) -> None:  # pragma: no cover - nothing to close
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        # Mounted to the bot: a reply the handler then deletes or edits has to
        # be able to call the API itself.
        return message("").as_(bot)

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""

    def texts_sent(self) -> list[str]:
        return [str(getattr(call, "text", "")) for call in self.calls if hasattr(call, "text")]


def message(text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime(2026, 1, 1),
        chat=Chat(id=CHAT_ID, type="private"),
        text=text,
    )


def typed(text: str) -> Update:
    return Update(
        update_id=2,
        message=Message(
            message_id=2,
            date=datetime(2026, 1, 1),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=TelegramUser(id=USER_ID, is_bot=False, first_name="Автор"),
            text=text,
        ),
    )


def press(data: str) -> Update:
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="1",
            from_user=TelegramUser(id=USER_ID, is_bot=False, first_name="Автор"),
            chat_instance="1",
            data=data,
            message=message("меню"),
        ),
    )


@dataclass
class StubService:
    calls: list[Formula] = field(default_factory=list)
    catalog: Any = None

    async def generate(self, *, user_id: int, formula: Formula, **kwargs: Any) -> Result:
        self.calls.append(formula)
        return Result(
            generation_id=1,
            text="Твист.",
            formula=formula,
            decision=Decision(Verdict.FREE, units=1, free_left=2),
            completion=Completion(
                text="Твист.",
                model="claude-opus-5",
                effort="high",
                usage=Usage(100, 100, 0, 0),
                cost_usd=Decimal("0.25"),
                latency_ms=1000,
                stop_reason="end_turn",
            ),
        )


@pytest.fixture
def wired() -> Iterator[tuple[Dispatcher, Bot, RecordingSession, StubService]]:
    session = RecordingSession()
    bot = Bot(token="42:TEST", session=session)
    service = StubService()

    dispatcher = Dispatcher()
    dispatcher.workflow_data.update(
        service=service,
        user_id=USER_ID,
        single_flight=SingleFlight(),
        settings=type("S", (), {"owner_telegram_id": 1})(),
    )
    # start first: its handlers must win over the ones waiting for text.
    dispatcher.include_router(start.router)
    dispatcher.include_router(mode_formula.router)
    yield dispatcher, bot, session, service

    # The routers are module-level singletons and refuse to be attached twice,
    # so each test has to hand them back.
    start.router._parent_router = None
    mode_formula.router._parent_router = None


async def set_up_state(dispatcher: Dispatcher, bot: Bot, **data: Any) -> None:
    context = dispatcher.fsm.get_context(bot, chat_id=CHAT_ID, user_id=USER_ID)
    await context.set_state(FormulaStates.options)
    if data:
        await context.update_data(data)


async def test_pressing_generate_reaches_the_generator(wired: Any) -> None:
    """The regression: «Сгенерировать» was eaten by the optional-field handler."""
    dispatcher, bot, _, service = wired
    await set_up_state(dispatcher, bot, formula="6и-ФК", seed=1)

    await dispatcher.feed_update(bot, press(mode_formula.GENERATE))

    assert [formula.code for formula in service.calls] == ["6и-ФК"]


async def test_an_optional_field_still_asks_rather_than_generating(wired: Any) -> None:
    dispatcher, bot, session, service = wired
    await set_up_state(dispatcher, bot, formula="6и-ФК")

    await dispatcher.feed_update(bot, press("opt:genre"))

    assert service.calls == []
    assert texts.ASK_GENRE in session.texts_sent()


async def test_a_stale_button_says_so_instead_of_blinking(wired: Any) -> None:
    """No formula in state — the bot was restarted under the user."""
    dispatcher, bot, session, service = wired
    await set_up_state(dispatcher, bot)  # no formula

    await dispatcher.feed_update(bot, press(mode_formula.GENERATE))

    assert service.calls == []
    assert texts.SESSION_LOST in session.texts_sent()


async def test_the_persistent_button_opens_the_menu_mid_dialog(wired: Any) -> None:
    """Pressing «Начать» while the bot waits for a genre must not become the genre."""
    dispatcher, bot, session, _ = wired
    context = dispatcher.fsm.get_context(bot, chat_id=CHAT_ID, user_id=USER_ID)
    await context.set_state(FormulaStates.awaiting_genre)

    await dispatcher.feed_update(bot, typed(texts.BEGIN))

    assert texts.CHOOSE_MODE in session.texts_sent()
    assert await context.get_state() is None
    assert (await context.get_data()).get("genre") is None
