"""Who may generate, and on whose money.

Three gates, in order: the emergency stop, then the user's free allowance for
today, then their paid balance. A request that passes none of them is refused
with a reason the bot can explain rather than a bare "no".

Two rules hold throughout, both from docs/SPEC.md §7:

* nothing is charged until a generation has actually succeeded — a refusal or a
  timeout costs the owner money but never costs the user a unit;
* the daily and monthly caps apply to **free** spend only. A paid generation was
  funded by whoever bought it, so capping it would be refusing money already
  taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from db.models import BudgetLedger, DailyUsage, User

#: The owner's local day. Quotas reset at midnight Moscow time, not UTC, so a
#: user's "three a day" matches the day they are living in.
LOCAL_OFFSET: Final[timedelta] = timedelta(hours=3)


class Mode(Enum):
    FORMULA = "formula"
    EXPECTATION = "expectation"

    @property
    def units(self) -> int:
        """Accounting units, docs/SPEC.md §7.1."""
        return 1 if self is Mode.FORMULA else 2


class Verdict(Enum):
    FREE = "free"
    PAID = "paid"
    DENIED_BLOCKED = "denied_blocked"
    DENIED_DAILY_LIMIT = "denied_daily_limit"
    DENIED_BUDGET = "denied_budget"
    DENIED_EMERGENCY = "denied_emergency"

    @property
    def allowed(self) -> bool:
        return self in (Verdict.FREE, Verdict.PAID)


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    units: int
    #: How many free generations of this mode the user has left afterwards.
    free_left: int = 0
    paid_left: int = 0

    @property
    def allowed(self) -> bool:
        return self.verdict.allowed

    @property
    def was_free(self) -> bool:
        return self.verdict is Verdict.FREE


def local_today(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return (now.astimezone(UTC) + LOCAL_OFFSET).date()


def month_start(day: date) -> date:
    return day.replace(day=1)


async def _usage_row(session: AsyncSession, user_id: int, day: date) -> DailyUsage:
    row = await session.scalar(
        select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.usage_date == day)
    )
    if row is None:
        row = DailyUsage(user_id=user_id, usage_date=day)
        session.add(row)
        await session.flush()
    return row


async def _ledger_row(session: AsyncSession, day: date) -> BudgetLedger:
    row = await session.scalar(select(BudgetLedger).where(BudgetLedger.period_date == day))
    if row is None:
        row = BudgetLedger(period_date=day)
        session.add(row)
        await session.flush()
    return row


async def spend(session: AsyncSession, day: date, free: bool = True) -> Decimal:
    """Recorded spend for one day."""
    row = await session.scalar(select(BudgetLedger).where(BudgetLedger.period_date == day))
    if row is None:
        return Decimal("0")
    return row.free_spend_usd if free else row.paid_spend_usd


async def month_spend(session: AsyncSession, day: date) -> tuple[Decimal, Decimal]:
    """``(free, paid)`` spend so far in the calendar month containing ``day``."""
    rows = (
        await session.scalars(
            select(BudgetLedger).where(
                BudgetLedger.period_date >= month_start(day),
                BudgetLedger.period_date <= day,
            )
        )
    ).all()
    free = sum((row.free_spend_usd for row in rows), Decimal("0"))
    paid = sum((row.paid_spend_usd for row in rows), Decimal("0"))
    return free, paid


async def check(
    session: AsyncSession,
    user: User,
    mode: Mode,
    settings: Settings,
    now: datetime | None = None,
) -> Decision:
    """Decide whether this generation may run, and on whose money."""
    units = mode.units
    day = local_today(now)

    if user.is_blocked:
        return Decision(Verdict.DENIED_BLOCKED, units)

    free_month, paid_month = await month_spend(session, day)
    if free_month + paid_month >= settings.emergency_stop_usd:
        # Covers paid traffic too: past this line something is wrong, and the
        # right response is to stop rather than to keep billing.
        return Decision(Verdict.DENIED_EMERGENCY, units)

    limit = (
        settings.free_formula_gens_per_day
        if mode is Mode.FORMULA
        else settings.free_expectation_gens_per_day
    )
    usage = await _usage_row(session, user.id, day)
    used = usage.formula_gens if mode is Mode.FORMULA else usage.expectation_gens
    free_left = max(limit - used, 0)

    budget_is_open = (
        await spend(session, day) < settings.daily_free_budget_usd
        and free_month < settings.monthly_free_budget_usd
    )

    # The owner tests the bot constantly; his own use should not eat the public
    # allowance. The emergency stop above still applies to him.
    if user.is_owner:
        return Decision(Verdict.FREE, units, free_left=free_left, paid_left=user.paid_units)

    if free_left > 0 and budget_is_open:
        return Decision(Verdict.FREE, units, free_left=free_left - 1, paid_left=user.paid_units)

    if user.paid_units >= units:
        return Decision(Verdict.PAID, units, free_left=free_left, paid_left=user.paid_units - units)

    if free_left > 0 and not budget_is_open:
        # The user has allowance left; the bot as a whole has run out of money.
        return Decision(Verdict.DENIED_BUDGET, units, free_left=free_left)

    return Decision(Verdict.DENIED_DAILY_LIMIT, units, paid_left=user.paid_units)


async def charge(
    session: AsyncSession,
    user: User,
    mode: Mode,
    decision: Decision,
    cost: Decimal,
    now: datetime | None = None,
) -> None:
    """Record a *successful* generation against quota and ledger.

    Never call this for a failed generation. The cost of a failure still belongs
    in ``api_calls`` — it was billed — but it must not consume the user's
    allowance or their paid units.
    """
    if not decision.allowed:
        raise ValueError(f"cannot charge a refused generation: {decision.verdict}")

    day = local_today(now)
    ledger = await _ledger_row(session, day)

    if decision.was_free:
        usage = await _usage_row(session, user.id, day)
        if mode is Mode.FORMULA:
            usage.formula_gens += 1
        else:
            usage.expectation_gens += 1
        ledger.free_spend_usd += cost
    else:
        user.paid_units -= decision.units
        ledger.paid_spend_usd += cost


async def record_failure(
    session: AsyncSession,
    cost: Decimal,
    was_free: bool,
    now: datetime | None = None,
) -> None:
    """Put the cost of a failed call in the ledger without charging anyone.

    A refusal or a truncated response is billed by the API, so leaving it out
    would make the caps read low and let real spend run past them.
    """
    if cost <= 0:
        return
    ledger = await _ledger_row(session, local_today(now))
    if was_free:
        ledger.free_spend_usd += cost
    else:
        ledger.paid_spend_usd += cost
