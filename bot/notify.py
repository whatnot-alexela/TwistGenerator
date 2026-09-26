"""Telling the owner when something breaks.

The user is shown "Автор уведомлён" — so the author has to actually be. A
failure nobody sees is the expensive kind: the bot keeps refusing generations
while the only person who can fix it reads nothing but a log file on a server
he does not log into.

Notification is best effort by design. If Telegram refuses the message, that
must not turn one failure into two: the user has already been answered by the
time this runs.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot

logger = logging.getLogger(__name__)

#: Telegram rejects anything longer, and a traceback can be much longer.
MAX_DETAIL = 3000


async def tell_owner(bot: Bot, owner_id: int, what: str, detail: str = "") -> None:
    body = f"⚠️ <b>{html.escape(what)}</b>"
    if detail:
        body += f"\n\n<code>{html.escape(detail[:MAX_DETAIL])}</code>"
    try:
        await bot.send_message(owner_id, body)
    except Exception:  # noqa: BLE001 — a failed warning must not mask the failure
        logger.exception("could not warn the owner about: %s", what)
