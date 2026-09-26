"""Telegram Stars payments.

Crediting has to be idempotent. Telegram retries a delivery it did not see
acknowledged, and a replayed `successful_payment` that credits twice is free
generations the owner pays for. The charge id is unique in the database, so the
second attempt hits the constraint and credits nothing.

The inverse mistake is worse: taking money and crediting nothing. So the credit
is written in the same transaction as the payment record, and the user is told
their new balance rather than a bare thank-you — if the number is wrong they
will say so immediately.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import keyboards, texts
from bot.config import Settings
from db.models import Payment, User

logger = logging.getLogger(__name__)
router = Router(name="payments")

#: Telegram requires this to be non-empty and under 128 bytes. It comes back
#: on the invoice and on the payment, so the pack is identified by it rather
#: than by trusting the amount.
PAYLOAD_PREFIX = "pack:"


def pack_by_id(settings: Settings, pack_id: str) -> tuple[str, int, int] | None:
    for name, units, stars in settings.packs:
        if name == pack_id:
            return name, units, stars
    return None


@router.message(Command("buy"))
async def buy(message: Message, settings: Settings, user: User) -> None:
    await message.answer(
        texts.buy(settings.packs, user.paid_units),
        reply_markup=keyboards.packs(settings.packs),
    )


@router.callback_query(F.data.startswith("pack:"))
async def send_invoice(query: CallbackQuery, settings: Settings) -> None:
    pack_id = str(query.data).split(":", 1)[1]
    pack = pack_by_id(settings, pack_id)
    if pack is None or not isinstance(query.message, Message):
        await query.answer()
        return

    name, units, stars = pack
    await query.message.answer_invoice(
        title=texts.pack_title(units),
        description=texts.pack_description(units),
        payload=f"{PAYLOAD_PREFIX}{name}",
        currency="XTR",
        prices=[LabeledPrice(label=texts.pack_title(units), amount=stars)],
        # Stars take no provider token; a real one here would be a bug.
        provider_token="",
    )
    await query.answer()


@router.pre_checkout_query()
async def confirm(query: PreCheckoutQuery, settings: Settings) -> None:
    """Approve, unless the payload names a pack we no longer sell.

    Declining here is the only safe moment: after this, Telegram has taken the
    money and the bot owes the units.
    """
    pack_id = query.invoice_payload.removeprefix(PAYLOAD_PREFIX)
    if pack_by_id(settings, pack_id) is None:
        logger.warning("declining checkout for unknown pack %r", pack_id)
        await query.answer(ok=False, error_message=texts.PACK_GONE)
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def credit(
    message: Message, settings: Settings, user: User, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = message.successful_payment
    if payment is None:
        return

    pack_id = payment.invoice_payload.removeprefix(PAYLOAD_PREFIX)
    pack = pack_by_id(settings, pack_id)
    if pack is None:
        # Paid for a pack that has since been removed. The money is taken, so
        # credit what the invoice actually charged rather than refusing.
        logger.error("paid for unknown pack %r; crediting by amount", pack_id)
        units = max(payment.total_amount // 26, 1)
    else:
        units = pack[1]

    async with sessions() as session:
        session.add(
            Payment(
                user_id=user.id,
                pack_id=pack_id,
                stars=payment.total_amount,
                units=units,
                telegram_payment_charge_id=payment.telegram_payment_charge_id,
            )
        )
        try:
            # Flush first: the unique charge id is what makes this idempotent,
            # and it has to be tested before anything is credited.
            await session.flush()
        except IntegrityError:
            await session.rollback()
            logger.info("ignoring a replayed payment %s", payment.telegram_payment_charge_id)
            async with sessions() as reader:
                fresh = await reader.get(User, user.id)
                balance = fresh.paid_units if fresh else 0
            await message.answer(texts.payment_thanks(0, balance))
            return

        # Read the row inside this transaction rather than trusting the User
        # instance the middleware handed over: that one is a snapshot, and
        # merging its stale balance would wipe out an earlier purchase.
        account = await session.get(User, user.id)
        if account is None:
            await session.rollback()
            logger.error("paid user %s vanished before crediting", user.id)
            await message.answer(texts.ERROR_GENERIC)
            return
        account.paid_units += units
        await session.commit()
        balance = account.paid_units

    logger.info("credited %d units to user %s for %d stars", units, user.id, payment.total_amount)
    await message.answer(texts.payment_thanks(units, balance))
