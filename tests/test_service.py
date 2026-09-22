"""Tests for the generation service.

The service exists to keep one promise: a user pays for a twist only when a
twist arrives. Most of what follows checks that promise from the failing side.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession as Session

from bot.config import Settings
from core.catalog import Catalog
from core.claude import ClaudeClient, ClaudeError, Outcome
from core.formula import Formula
from core.prompt.builder import PromptBuilder
from core.prompt.slice import UserInput
from core.quota import Mode, Verdict, local_today, spend
from core.service import GenerationService, QuotaExceeded
from db.models import ApiCall, Generation, User
from db.session import create_all, make_engine, make_session_factory

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@dataclass
class StubUsage:
    input_tokens: int = 20_000
    output_tokens: int = 4_000
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class StubBlock:
    type: str = "text"
    text: str = "Ожидание. Откровение. Почему это работает по формуле."


@dataclass
class StubMessage:
    content: list[StubBlock] = field(default_factory=lambda: [StubBlock()])
    stop_reason: str | None = "end_turn"
    usage: StubUsage = field(default_factory=StubUsage)
    model: str = "claude-opus-5"
    stop_details: None = None


class StubStream:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def __aenter__(self) -> StubStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_final_message(self) -> Any:
        return self._result


@dataclass
class StubMessages:
    script: list[Any] = field(default_factory=lambda: [StubMessage()])
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def stream(self, **kwargs: Any) -> StubStream:
        self.calls.append(kwargs)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return StubStream(item)


def settings(**overrides: object) -> Settings:
    base = {
        "bot_token": "t",
        "anthropic_api_key": "k",
        "owner_telegram_id": 1,
        "database_url": "sqlite+aiosqlite://",
        "methodology_url": "https://example.org",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    instance = make_engine("sqlite+aiosqlite://")
    await create_all(instance)
    yield instance
    await instance.dispose()


@pytest_asyncio.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker[Session]:
    return make_session_factory(engine)


@pytest_asyncio.fixture
async def user_id(sessions: async_sessionmaker[Session]) -> int:
    async with sessions() as session:
        person = User(telegram_id=555, username="reader")
        session.add(person)
        await session.commit()
        return person.id


def build_service(
    sessions: async_sessionmaker[Session],
    messages: StubMessages | None = None,
    **config: object,
) -> GenerationService:
    async def no_sleep(_: float) -> None:
        return None

    return GenerationService(
        settings=settings(**config),
        catalog=Catalog.load(),
        builder=PromptBuilder(),
        claude=ClaudeClient(messages=messages or StubMessages(), sleep=no_sleep),
        sessions=sessions,
    )


async def count(sessions: async_sessionmaker[Session], model: Any) -> int:
    async with sessions() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


async def test_a_generation_is_stored_with_everything_needed_to_reproduce_it(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions)
    result = await service.generate(user_id, Formula.parse("6и-ФК"), seed=7)

    async with sessions() as session:
        stored = await session.get(Generation, result.generation_id)
        assert stored is not None
        assert stored.formula == "6и-ФК"
        assert stored.paradox_1 is True
        assert stored.paradox_2 is False
        assert stored.catalogued is True
        assert stored.had_reference is True
        assert stored.example_seed == 7
        assert stored.profile == "full"
        assert stored.block_b  # the exact slice that was sent
        assert stored.was_free is True
        assert stored.units_charged == 1


async def test_the_api_call_is_recorded_against_the_generation(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions)
    result = await service.generate(user_id, Formula.parse("1е-ФД"))

    async with sessions() as session:
        call = await session.scalar(
            select(ApiCall).where(ApiCall.generation_id == result.generation_id)
        )
        assert call is not None
        assert call.purpose == "generation"
        assert call.input_tokens == 20_000
        assert call.output_tokens == 4_000
        assert call.cost_usd > 0
        assert call.error is None


async def test_the_cost_lands_in_the_ledger(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions)
    result = await service.generate(user_id, Formula.parse("1е-ФД"))

    async with sessions() as session:
        assert await spend(session, local_today()) == result.completion.cost_usd


async def test_user_input_reaches_both_the_prompt_and_the_record(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    messages = StubMessages()
    service = build_service(sessions, messages)
    result = await service.generate(
        user_id,
        Formula.parse("1е-ФД"),
        user_input=UserInput(genre="нуар", characters="детектив"),
    )

    assert "Жанр: нуар" in messages.calls[0]["messages"][0]["content"]
    async with sessions() as session:
        stored = await session.get(Generation, result.generation_id)
        assert stored is not None
        assert stored.genre == "нуар"
        assert stored.characters == "детектив"


async def test_an_uncatalogued_formula_is_marked_as_such(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions)
    result = await service.generate(user_id, Formula.parse("3и-МК"))

    async with sessions() as session:
        stored = await session.get(Generation, result.generation_id)
        assert stored is not None
        assert stored.catalogued is False
        assert stored.had_reference is False


# --------------------------------------------------------------------------- #
# Refusal before any money is spent
# --------------------------------------------------------------------------- #


async def test_the_quota_is_checked_before_the_api_is_called(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    messages = StubMessages()
    service = build_service(sessions, messages, free_formula_gens_per_day=0)

    with pytest.raises(QuotaExceeded) as caught:
        await service.generate(user_id, Formula.parse("1е-ФД"))

    assert caught.value.decision.verdict is Verdict.DENIED_DAILY_LIMIT
    assert messages.calls == []  # nothing was sent, nothing was billed
    assert await count(sessions, ApiCall) == 0


async def test_nothing_is_stored_when_the_quota_refuses(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions, free_formula_gens_per_day=0)
    with pytest.raises(QuotaExceeded):
        await service.generate(user_id, Formula.parse("1е-ФД"))
    assert await count(sessions, Generation) == 0


# --------------------------------------------------------------------------- #
# Failure after money has been spent
# --------------------------------------------------------------------------- #


async def test_a_refusal_costs_the_owner_but_not_the_user(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    refused = StubMessage(stop_reason="refusal")
    service = build_service(sessions, StubMessages(script=[refused]))

    with pytest.raises(ClaudeError) as caught:
        await service.generate(user_id, Formula.parse("1е-ФД"))
    assert caught.value.outcome is Outcome.REFUSED

    async with sessions() as session:
        # Billed, so it is in the ledger and in api_calls...
        assert await spend(session, local_today()) > 0
        call = await session.scalar(select(ApiCall))
        assert call is not None
        assert call.error is not None
        assert call.generation_id is None
        # ...but no twist was stored and no allowance was consumed.
        assert await session.scalar(select(func.count()).select_from(Generation)) == 0
        user = await session.get(User, user_id)
        assert user is not None


async def test_the_allowance_survives_a_failure(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    service = build_service(sessions, StubMessages(script=[StubMessage(stop_reason="refusal")]))
    for _ in range(3):
        with pytest.raises(ClaudeError):
            await service.generate(user_id, Formula.parse("1е-ФД"))

    # Three failures later, all three free generations are still available.
    working = build_service(sessions)
    result = await working.generate(user_id, Formula.parse("1е-ФД"))
    assert result.decision.verdict is Verdict.FREE
    assert result.decision.free_left == 2


async def test_paid_units_survive_a_failure(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.paid_units = 5
        await session.commit()

    service = build_service(
        sessions,
        StubMessages(script=[StubMessage(stop_reason="refusal")]),
        free_formula_gens_per_day=0,
    )
    with pytest.raises(ClaudeError):
        await service.generate(user_id, Formula.parse("1е-ФД"))

    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.paid_units == 5


async def test_a_network_failure_is_recorded_with_no_cost(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    class APIConnectionError(Exception):
        pass

    service = build_service(sessions, StubMessages(script=[APIConnectionError("down")]))
    with pytest.raises(ClaudeError):
        await service.generate(user_id, Formula.parse("1е-ФД"))

    async with sessions() as session:
        call = await session.scalar(select(ApiCall))
        assert call is not None
        assert call.cost_usd == Decimal("0")
        assert "unavailable" in (call.error or "")
        assert await spend(session, local_today()) == Decimal("0")


# --------------------------------------------------------------------------- #
# Charging
# --------------------------------------------------------------------------- #


async def test_a_paid_generation_decrements_units_and_not_the_allowance(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.paid_units = 2
        await session.commit()

    service = build_service(sessions, free_formula_gens_per_day=0)
    result = await service.generate(user_id, Formula.parse("1е-ФД"))

    assert result.decision.verdict is Verdict.PAID
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.paid_units == 1
        assert await spend(session, local_today()) == Decimal("0")
        assert await spend(session, local_today(), free=False) > 0


async def test_expectation_mode_charges_two_units(
    sessions: async_sessionmaker[Session], user_id: int
) -> None:
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.paid_units = 3
        await session.commit()

    service = build_service(sessions, free_expectation_gens_per_day=0)
    result = await service.generate(
        user_id,
        Formula.parse("1е-ФД"),
        mode=Mode.EXPECTATION,
        user_input=UserInput(situation="Деревня пустеет."),
    )

    assert result.decision.units == 2
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.paid_units == 1
        stored = await session.get(Generation, result.generation_id)
        assert stored is not None
        assert stored.mode == "expectation"
        assert stored.user_expectation == "Деревня пустеет."


async def test_an_unknown_user_is_an_error_not_a_silent_generation(
    sessions: async_sessionmaker[Session],
) -> None:
    service = build_service(sessions)
    with pytest.raises(LookupError, match="no user"):
        await service.generate(9999, Formula.parse("1е-ФД"))
