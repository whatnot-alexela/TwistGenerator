"""The database, as described in docs/SPEC.md §8.

PostgreSQL in production, SQLite in the tests, so the column types here are the
portable SQLAlchemy ones rather than Postgres spellings. Two choices are worth
knowing about:

* money is ``Numeric``, never a float — a month of summed generations on a
  float drifts, and these numbers decide when free generation stops;
* every timestamp is timezone-aware and stored in UTC, while the daily quota
  resets on the owner's local day (see ``core/quota.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


#: SQLite only auto-increments a column declared INTEGER PRIMARY KEY, so a plain
#: BigInteger key works in Postgres and fails in the tests. The variant keeps one
#: schema definition serving both.
BigIntKey = BigInteger().with_variant(Integer, "sqlite")


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))

    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Paid generation units, in the accounting of docs/SPEC.md §7.1.
    paid_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()

    __table_args__ = (CheckConstraint("paid_units >= 0", name="paid_units_non_negative"),)


class Generation(Base):
    """One request that produced twists, with everything needed to reproduce it."""

    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # formula | expectation
    formula: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    change_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(1), nullable=False)
    cause_1: Mapped[str] = mapped_column(String(1), nullable=False)
    cause_2: Mapped[str] = mapped_column(String(1), nullable=False)
    paradox_1: Mapped[bool] = mapped_column(Boolean, nullable=False)
    paradox_2: Mapped[bool] = mapped_column(Boolean, nullable=False)

    #: Whether the methodology had an example, and whether it had a film or book.
    catalogued: Mapped[bool] = mapped_column(Boolean, nullable=False)
    had_reference: Mapped[bool] = mapped_column(Boolean, nullable=False)

    genre: Mapped[str | None] = mapped_column(String(64))
    characters: Mapped[str | None] = mapped_column(String(300))
    setting: Mapped[str | None] = mapped_column(String(100))
    audience: Mapped[str | None] = mapped_column(String(32))

    #: Mode 2: the user's own Expectation, and the rewrite if one was needed.
    user_expectation: Mapped[str | None] = mapped_column(Text)
    adapted_expectation: Mapped[str | None] = mapped_column(Text)
    expectation_adapted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    override_verdict: Mapped[str | None] = mapped_column(String(16))
    override_condition: Mapped[str | None] = mapped_column(Text)

    #: Reproduces which example and reference the slice picked.
    example_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The assembled slice, verbatim. The core is identified by profile alone.
    block_b: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)

    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    effort: Mapped[str] = mapped_column(String(16), nullable=False)

    units_charged: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    was_free: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = _now()

    rating: Mapped[Rating | None] = relationship(
        back_populates="generation", uselist=False, cascade="all, delete-orphan"
    )
    api_calls: Mapped[list[ApiCall]] = relationship(back_populates="generation")

    __table_args__ = (Index("ix_generations_user_created", "user_id", "created_at"),)


class Rating(Base):
    """The user's verdict. One per generation; changes are appended to history."""

    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    generation_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("generations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()

    generation: Mapped[Generation] = relationship(back_populates="rating")

    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 5", name="score_between_1_and_5"),
        Index("ix_ratings_score", "score"),
    )


class RatingHistory(Base):
    """Every rating a generation has ever had, including the ones replaced.

    Re-rating is allowed, and how a verdict moved is itself research data.
    """

    __tablename__ = "rating_history"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    generation_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("generations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="history_score_range"),)


class ApiCall(Base):
    """One call to Claude, successful or not.

    Failures are recorded too: a refusal is billed, and an unrecorded refusal is
    money missing from the ledger.
    """

    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    generation_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("generations.id", ondelete="SET NULL")
    )
    user_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)  # generation | analysis

    model: Mapped[str] = mapped_column(String(64), nullable=False)
    effort: Mapped[str] = mapped_column(String(16), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    #: Free calls count against the budget caps; paid ones are funded already.
    was_free: Mapped[bool] = mapped_column(Boolean, nullable=False)

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = _now()

    generation: Mapped[Generation | None] = relationship(back_populates="api_calls")

    __table_args__ = (Index("ix_api_calls_created", "created_at"),)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pack_id: Mapped[str] = mapped_column(String(16), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Telegram's id for the charge. Unique, so a replayed webhook cannot credit
    #: the same purchase twice.
    telegram_payment_charge_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = _now()


class DailyUsage(Base):
    """Per-user free allowance, one row per user per day."""

    __tablename__ = "daily_usage"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)

    formula_gens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expectation_gens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analyses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_daily_usage"),)


class BudgetLedger(Base):
    """What the bot spent on a given day, free and paid kept apart.

    The caps of §7.3 apply to free spend only: a paid generation was funded by
    the user who bought it.
    """

    __tablename__ = "budget_ledger"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    period_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    free_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), nullable=False
    )
    paid_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), nullable=False
    )
