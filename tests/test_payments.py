"""Tests for Telegram Stars payments.

Two mistakes cost real money and both are tested from the failing side:
crediting a replayed delivery twice, which the owner pays for, and taking
money while crediting nothing, which the user pays for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import keyboards, texts
from bot.config import Settings
from bot.handlers.payments import PAYLOAD_PREFIX, pack_by_id
from db.models import Payment, User
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
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite://")
    await create_all(engine)
    yield make_session_factory(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def user(sessions: async_sessionmaker[AsyncSession]) -> User:
    async with sessions() as session:
        person = User(telegram_id=42, username="buyer")
        session.add(person)
        await session.commit()
        return person


async def apply_payment(
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    charge_id: str,
    units: int = 10,
    stars: int = 260,
) -> tuple[bool, int]:
    """The crediting transaction, as the handler runs it."""
    async with sessions() as session:
        session.add(
            Payment(
                user_id=user.id,
                pack_id="small",
                stars=stars,
                units=units,
                telegram_payment_charge_id=charge_id,
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            async with sessions() as reader:
                fresh = await reader.get(User, user.id)
                return False, fresh.paid_units if fresh else 0
        account = await session.get(User, user.id)
        assert account is not None
        account.paid_units += units
        await session.commit()
        return True, account.paid_units


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


async def test_a_payment_credits_once(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    credited, balance = await apply_payment(sessions, user, "charge-1")
    assert credited is True
    assert balance == 10


async def test_a_replayed_delivery_credits_nothing(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    """Telegram retries what it did not see acknowledged. Crediting twice is
    free generations the owner pays for."""
    await apply_payment(sessions, user, "charge-1")
    credited, balance = await apply_payment(sessions, user, "charge-1")

    assert credited is False
    assert balance == 10  # unchanged

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Payment)) == 1


async def test_two_genuine_payments_both_credit(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    await apply_payment(sessions, user, "charge-1")
    credited, balance = await apply_payment(sessions, user, "charge-2")

    assert credited is True
    assert balance == 20


async def test_the_payment_row_records_what_was_charged(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    await apply_payment(sessions, user, "charge-1", units=30, stars=700)

    async with sessions() as session:
        payment = await session.scalar(select(Payment))
        assert payment is not None
        assert payment.stars == 700
        assert payment.units == 30
        assert payment.pack_id == "small"


# --------------------------------------------------------------------------- #
# Packs
# --------------------------------------------------------------------------- #


def test_a_pack_is_found_by_its_id() -> None:
    assert pack_by_id(settings(), "small") == ("small", 10, 260)
    assert pack_by_id(settings(), "enormous") is None


def test_the_payload_identifies_the_pack_rather_than_the_amount() -> None:
    """Trusting the amount would credit wrongly the moment a price changes."""
    payload = f"{PAYLOAD_PREFIX}medium"
    assert payload.removeprefix(PAYLOAD_PREFIX) == "medium"
    assert pack_by_id(settings(), "medium") == ("medium", 30, 700)


def test_every_pack_has_a_button() -> None:
    config = settings()
    markup = keyboards.packs(config.packs)
    actions = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert actions == {f"pack:{name}" for name, _, _ in config.packs}


def test_the_buttons_state_both_numbers() -> None:
    labels = [b.text for row in keyboards.packs(settings().packs).inline_keyboard for b in row]
    assert "10 генераций — 260 ⭐" in labels


# --------------------------------------------------------------------------- #
# What the user is told
# --------------------------------------------------------------------------- #


def test_the_offer_states_the_refund_policy() -> None:
    """Declared up front, not discovered afterwards."""
    text = texts.buy(settings().packs, balance=0)
    assert "возврат не предусмотрен" in text


def test_the_offer_explains_the_two_unit_prices() -> None:
    text = texts.buy(settings().packs, balance=0)
    assert "1 единица" in text
    assert "2" in text


def test_the_offer_says_free_limits_come_first() -> None:
    assert "Бесплатные лимиты" in texts.buy(settings().packs, balance=0)


def test_the_balance_is_shown_when_there_is_one() -> None:
    assert "5 единиц" in texts.buy(settings().packs, balance=5)
    assert "единиц." not in texts.buy(settings().packs, balance=0).split("Сейчас")[0][-20:]


def test_the_receipt_names_the_new_balance() -> None:
    """A bare thank-you hides a wrong number; a stated balance gets corrected."""
    assert "12" in texts.payment_thanks(10, 12)


def test_a_replayed_receipt_does_not_claim_a_credit() -> None:
    text = texts.payment_thanks(0, 10)
    assert "уже был зачислен" in text
    assert "Зачислено" not in text


def test_the_pack_description_says_units_do_not_expire() -> None:
    assert "не сгорают" in texts.pack_description(10)


def test_buy_is_advertised() -> None:
    from bot.main import COMMANDS

    assert "buy" in {command.command for command in COMMANDS}


@pytest.mark.parametrize("units", [10, 30, 100])
def test_pack_titles_are_readable(units: int) -> None:
    assert str(units) in texts.pack_title(units)
