"""Tests for quota and budget accounting.

This is the module that decides whether the owner spends money, so the tests
lean on the cases that cost him: a failure that charges anyway, a cap that reads
low because failures went unrecorded, a paid generation refused because free
users exhausted the day's budget.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from core.quota import (
    Decision,
    Mode,
    Verdict,
    charge,
    charge_analysis,
    check,
    check_analysis,
    local_today,
    month_spend,
    record_failure,
    spend,
)
from db.models import BudgetLedger, User
from db.session import create_all, make_engine, make_session_factory


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
async def session() -> AsyncIterator[AsyncSession]:
    engine = make_engine("sqlite+aiosqlite://")
    await create_all(engine)
    factory = make_session_factory(engine)
    async with factory() as active:
        yield active
    await engine.dispose()


@pytest_asyncio.fixture
async def user(session: AsyncSession) -> User:
    person = User(telegram_id=100, username="author")
    session.add(person)
    await session.flush()
    return person


async def spend_free(session: AsyncSession, day: object, amount: str) -> None:
    session.add(BudgetLedger(period_date=day, free_spend_usd=Decimal(amount)))
    await session.flush()


# --------------------------------------------------------------------------- #
# The free allowance
# --------------------------------------------------------------------------- #


async def test_a_fresh_user_generates_free(session: AsyncSession, user: User) -> None:
    decision = await check(session, user, Mode.FORMULA, settings())
    assert decision.verdict is Verdict.FREE
    assert decision.units == 1
    assert decision.free_left == 2


async def test_the_allowance_runs_out_after_three(session: AsyncSession, user: User) -> None:
    config = settings()
    for expected_left in (2, 1, 0):
        decision = await check(session, user, Mode.FORMULA, config)
        assert decision.verdict is Verdict.FREE
        assert decision.free_left == expected_left
        await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))

    assert (await check(session, user, Mode.FORMULA, config)).verdict is Verdict.DENIED_DAILY_LIMIT


async def test_the_two_modes_have_separate_allowances(session: AsyncSession, user: User) -> None:
    config = settings()
    for _ in range(3):
        decision = await check(session, user, Mode.FORMULA, config)
        await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))

    assert (await check(session, user, Mode.FORMULA, config)).verdict is Verdict.DENIED_DAILY_LIMIT
    assert (await check(session, user, Mode.EXPECTATION, config)).verdict is Verdict.FREE


async def test_expectation_mode_costs_two_units(session: AsyncSession, user: User) -> None:
    assert (await check(session, user, Mode.EXPECTATION, settings())).units == 2
    assert Mode.FORMULA.units == 1


async def test_the_owner_is_not_limited(session: AsyncSession, user: User) -> None:
    user.is_owner = True
    config = settings()
    for _ in range(10):
        decision = await check(session, user, Mode.FORMULA, config)
        assert decision.verdict is Verdict.FREE
        await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))


async def test_a_blocked_user_is_refused_first(session: AsyncSession, user: User) -> None:
    user.is_blocked = True
    assert (await check(session, user, Mode.FORMULA, settings())).verdict is Verdict.DENIED_BLOCKED


# --------------------------------------------------------------------------- #
# Paid units
# --------------------------------------------------------------------------- #


async def test_paid_units_take_over_when_the_allowance_is_gone(
    session: AsyncSession, user: User
) -> None:
    config = settings()
    for _ in range(3):
        decision = await check(session, user, Mode.FORMULA, config)
        await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))

    user.paid_units = 5
    decision = await check(session, user, Mode.FORMULA, config)
    assert decision.verdict is Verdict.PAID
    assert decision.paid_left == 4

    await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))
    assert user.paid_units == 4


async def test_free_is_preferred_over_paid(session: AsyncSession, user: User) -> None:
    """Spending a bought unit while a free one is available would be theft."""
    user.paid_units = 10
    assert (await check(session, user, Mode.FORMULA, settings())).verdict is Verdict.FREE


async def test_expectation_mode_needs_two_paid_units(session: AsyncSession, user: User) -> None:
    config = settings()
    decision = await check(session, user, Mode.EXPECTATION, config)
    await charge(session, user, Mode.EXPECTATION, decision, Decimal("0.35"))

    user.paid_units = 1
    assert (
        await check(session, user, Mode.EXPECTATION, config)
    ).verdict is Verdict.DENIED_DAILY_LIMIT

    user.paid_units = 2
    decision = await check(session, user, Mode.EXPECTATION, config)
    assert decision.verdict is Verdict.PAID
    await charge(session, user, Mode.EXPECTATION, decision, Decimal("0.35"))
    assert user.paid_units == 0


# --------------------------------------------------------------------------- #
# Budget caps
# --------------------------------------------------------------------------- #


async def test_the_daily_cap_stops_free_generation(session: AsyncSession, user: User) -> None:
    await spend_free(session, local_today(), "4.00")
    decision = await check(session, user, Mode.FORMULA, settings())

    assert decision.verdict is Verdict.DENIED_BUDGET
    # The user still has allowance; it is the bot that ran out of money.
    assert decision.free_left == 3


async def test_a_paid_user_generates_after_the_free_budget_is_gone(
    session: AsyncSession, user: User
) -> None:
    """Their money already covered it; refusing would be taking it for nothing."""
    await spend_free(session, local_today(), "4.00")
    user.paid_units = 3
    assert (await check(session, user, Mode.FORMULA, settings())).verdict is Verdict.PAID


async def test_the_monthly_cap_stops_free_generation(session: AsyncSession, user: User) -> None:
    today = local_today()
    session.add(BudgetLedger(period_date=today.replace(day=1), free_spend_usd=Decimal("100.00")))
    await session.flush()

    verdict = (await check(session, user, Mode.FORMULA, settings())).verdict
    # On the first of the month both caps coincide; either refusal is correct.
    assert verdict is Verdict.DENIED_BUDGET


async def test_the_emergency_stop_covers_paid_traffic_too(
    session: AsyncSession, user: User
) -> None:
    session.add(BudgetLedger(period_date=local_today(), paid_spend_usd=Decimal("250.00")))
    await session.flush()
    user.paid_units = 100

    assert (
        await check(session, user, Mode.FORMULA, settings())
    ).verdict is Verdict.DENIED_EMERGENCY


async def test_the_emergency_stop_applies_to_the_owner(session: AsyncSession, user: User) -> None:
    user.is_owner = True
    session.add(BudgetLedger(period_date=local_today(), free_spend_usd=Decimal("250.00")))
    await session.flush()

    assert (
        await check(session, user, Mode.FORMULA, settings())
    ).verdict is Verdict.DENIED_EMERGENCY


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #


async def test_charging_records_free_spend(session: AsyncSession, user: User) -> None:
    decision = await check(session, user, Mode.FORMULA, settings())
    await charge(session, user, Mode.FORMULA, decision, Decimal("0.2512"))

    assert await spend(session, local_today()) == Decimal("0.2512")
    assert await spend(session, local_today(), free=False) == Decimal("0")


async def test_charging_a_paid_generation_lands_in_the_paid_column(
    session: AsyncSession, user: User
) -> None:
    user.paid_units = 1
    decision = Decision(Verdict.PAID, units=1, paid_left=0)
    await charge(session, user, Mode.FORMULA, decision, Decimal("0.25"))

    assert await spend(session, local_today()) == Decimal("0")
    assert await spend(session, local_today(), free=False) == Decimal("0.25")


async def test_a_failure_is_recorded_without_charging_anyone(
    session: AsyncSession, user: User
) -> None:
    """A refusal is billed by the API. Leaving it out of the ledger would make
    the caps read low and let real spend run past them."""
    await record_failure(session, Decimal("0.08"), was_free=True)

    assert await spend(session, local_today()) == Decimal("0.08")
    assert user.paid_units == 0
    assert (await check(session, user, Mode.FORMULA, settings())).free_left == 2


async def test_a_free_failure_still_counts_toward_the_cap(
    session: AsyncSession, user: User
) -> None:
    for _ in range(50):
        await record_failure(session, Decimal("0.08"), was_free=True)
    assert (await check(session, user, Mode.FORMULA, settings())).verdict is Verdict.DENIED_BUDGET


async def test_a_zero_cost_failure_writes_nothing(session: AsyncSession) -> None:
    await record_failure(session, Decimal("0"), was_free=True)
    assert await spend(session, local_today()) == Decimal("0")


async def test_charging_a_refused_decision_is_a_programming_error(
    session: AsyncSession, user: User
) -> None:
    refused = Decision(Verdict.DENIED_DAILY_LIMIT, units=1)
    with pytest.raises(ValueError, match="cannot charge a refused generation"):
        await charge(session, user, Mode.FORMULA, refused, Decimal("0.25"))


async def test_month_spend_sums_the_days(session: AsyncSession) -> None:
    today = local_today()
    session.add(BudgetLedger(period_date=today.replace(day=1), free_spend_usd=Decimal("10")))
    if today.day > 1:
        session.add(BudgetLedger(period_date=today, free_spend_usd=Decimal("5")))
    await session.flush()

    free, paid = await month_spend(session, today)
    assert free == (Decimal("15") if today.day > 1 else Decimal("10"))
    assert paid == Decimal("0")


# --------------------------------------------------------------------------- #
# The local day
# --------------------------------------------------------------------------- #


def test_the_day_turns_over_at_midnight_moscow_not_utc() -> None:
    """A user in Moscow gets a fresh allowance when their day starts."""
    assert local_today(datetime(2026, 9, 22, 20, 59, tzinfo=UTC)).day == 22
    assert local_today(datetime(2026, 9, 22, 21, 0, tzinfo=UTC)).day == 23


# --------------------------------------------------------------------------- #
# The analysis allowance
# --------------------------------------------------------------------------- #


async def test_analyses_have_their_own_allowance(session: AsyncSession, user: User) -> None:
    config = settings()
    for _ in range(5):
        decision = await check_analysis(session, user, config)
        assert decision.verdict is Verdict.FREE
        await charge_analysis(session, user, Decimal("0.07"))

    assert (await check_analysis(session, user, config)).verdict is Verdict.DENIED_DAILY_LIMIT
    # ...and the generation allowances are untouched by any of it.
    assert (await check(session, user, Mode.FORMULA, config)).verdict is Verdict.FREE


async def test_an_analysis_costs_no_units(session: AsyncSession, user: User) -> None:
    assert (await check_analysis(session, user, settings())).units == 0


async def test_analysis_spend_lands_in_the_ledger(session: AsyncSession, user: User) -> None:
    await charge_analysis(session, user, Decimal("0.0712"))
    assert await spend(session, local_today()) == Decimal("0.0712")


async def test_the_budget_cap_stops_analyses_too(session: AsyncSession, user: User) -> None:
    await spend_free(session, local_today(), "4.00")
    assert (await check_analysis(session, user, settings())).verdict is Verdict.DENIED_BUDGET


async def test_the_owner_analyses_without_limit(session: AsyncSession, user: User) -> None:
    user.is_owner = True
    config = settings()
    for _ in range(12):
        decision = await check_analysis(session, user, config)
        assert decision.verdict is Verdict.FREE
        await charge_analysis(session, user, Decimal("0.07"))


async def test_a_blocked_user_cannot_analyse(session: AsyncSession, user: User) -> None:
    user.is_blocked = True
    assert (await check_analysis(session, user, settings())).verdict is Verdict.DENIED_BLOCKED
