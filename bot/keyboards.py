"""Inline keyboards.

Callback data is parsed back into a formula, so it carries the real letters
rather than indices — a callback that survives a redeploy is worth the extra
few bytes, and `ft:1е` is legible in a log.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES, classify_paradox


def modes() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Собрать по формуле", callback_data="mode:formula")
    builder.button(text="Начать с описания ситуации", callback_data="mode:situation")
    builder.button(text="Как это работает", callback_data="nav:help")
    builder.adjust(1)
    return builder.as_markup()


def change_types() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for number, name in CHANGE_TYPES.items():
        builder.button(text=f"{number} · {name}", callback_data=f"type:{number}")
    builder.adjust(2)
    return builder.as_markup()


def change_kinds(change_type: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="е · Естественное", callback_data=f"kind:{change_type}:е")
    builder.button(text="и · Искусственное", callback_data=f"kind:{change_type}:и")
    builder.button(text="← Назад", callback_data="nav:types")
    builder.adjust(1)
    return builder.as_markup()


def causes_1(change_type: int, change_kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for letter, name in CAUSES.items():
        builder.button(
            text=f"{letter} · {name}", callback_data=f"c1:{change_type}:{change_kind}:{letter}"
        )
    builder.button(text="← Назад", callback_data=f"nav:kinds:{change_type}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def causes_2(change_type: int, change_kind: str, cause_1: str) -> InlineKeyboardMarkup:
    """Each option is labelled with the paradox it produces.

    Computed locally from the matrix rule, so showing it costs nothing and the
    user chooses knowing what they are choosing.
    """
    builder = InlineKeyboardBuilder()
    for letter, name in CAUSES.items():
        verdict = classify_paradox(change_kind, cause_1, letter)
        builder.button(
            text=f"{letter} · {name} — {texts.PARADOX_HINT[verdict]}",
            callback_data=f"c2:{change_type}:{change_kind}:{cause_1}:{letter}",
        )
    builder.button(text="← Назад", callback_data=f"nav:c1:{change_type}:{change_kind}")
    builder.adjust(1)
    return builder.as_markup()


def options(has_genre: bool, has_characters: bool, has_setting: bool) -> InlineKeyboardMarkup:
    """A filled field shows a tick, so the user can see what they already set."""
    builder = InlineKeyboardBuilder()
    builder.button(text=("✓ Жанр" if has_genre else "Добавить жанр"), callback_data="opt:genre")
    builder.button(
        text=("✓ Персонажи" if has_characters else "Добавить персонажей"),
        callback_data="opt:characters",
    )
    builder.button(
        text=("✓ Сеттинг" if has_setting else "Добавить сеттинг"), callback_data="opt:setting"
    )
    builder.button(text="✨ Сгенерировать", callback_data="opt:generate")
    builder.button(text="← Выбрать другую формулу", callback_data="nav:types")
    builder.adjust(1)
    return builder.as_markup()


def rating(generation_id: int, current: int | None = None) -> InlineKeyboardMarkup:
    """Five stars plus a comment. A given score is marked, so re-rating is
    visibly a change rather than a first vote."""
    builder = InlineKeyboardBuilder()
    for score in range(1, 6):
        mark = "●" if current == score else "☆"
        builder.button(text=f"{mark}{score}", callback_data=f"rate:{generation_id}:{score}")
    builder.adjust(5)

    builder.row(
        InlineKeyboardButton(text="💬 Комментарий", callback_data=f"comment:{generation_id}"),
        InlineKeyboardButton(text="🔁 Ещё вариант", callback_data=f"again:{generation_id}"),
    )
    return builder.as_markup()


def kinds_label(change_kind: str) -> str:
    return CHANGE_KINDS[change_kind]
