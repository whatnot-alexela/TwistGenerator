"""Inline keyboards.

Callback data is parsed back into a formula, so it carries the real letters
rather than indices — a callback that survives a redeploy is worth the extra
few bytes, and `ft:1е` is legible in a log.
"""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from core.analysis import Analysis, Reading
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES, classify_paradox


def begin() -> ReplyKeyboardMarkup:
    """The one row that stays at the bottom of the chat.

    Kept to a single short button on purpose: a reply keyboard takes screen
    space away from the conversation for as long as it is there.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.BEGIN)]],
        resize_keyboard=True,
        is_persistent=True,
    )


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
    for letter in CAUSES:
        builder.button(
            text=texts.cause_label(letter),
            callback_data=f"c1:{change_type}:{change_kind}:{letter}",
        )
    builder.button(text="← Назад", callback_data=f"nav:kinds:{change_type}")
    # One per row: the gloss makes the labels too long to pair up on a phone.
    builder.adjust(1)
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


# --------------------------------------------------------------------------- #
# Mode 2 — from a described situation
# --------------------------------------------------------------------------- #


def readings(options: Sequence[Reading]) -> InlineKeyboardMarkup:
    """The one or two readings the analysis proposed, plus the manual way out."""
    builder = InlineKeyboardBuilder()
    for index, reading in enumerate(options, start=1):
        builder.button(
            text=f"Вариант {index}: {reading.prefix}",
            callback_data=f"read:{reading.change_type}:{reading.change_kind}:{reading.cause_1}",
        )
    builder.button(text="Выбрать самому", callback_data="man:types")
    builder.button(text="Переписать ситуацию", callback_data="sit:again")
    builder.adjust(1)
    return builder.as_markup()


def manual_types(analysis: Analysis) -> InlineKeyboardMarkup:
    """Every change type, marked with the best verdict available under it.

    A branch is never shown as ✅ when nothing inside it is.
    """
    builder = InlineKeyboardBuilder()
    for number, name in CHANGE_TYPES.items():
        marker = analysis.best_for_type(number).marker
        builder.button(text=f"{marker} {number} · {name}", callback_data=f"mt:{number}")
    builder.button(text="← Назад к вариантам", callback_data="man:back")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def manual_kinds(analysis: Analysis, change_type: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for kind, name in CHANGE_KINDS.items():
        marker = analysis.best_for_kind(change_type, kind).marker
        builder.button(
            text=f"{marker} {kind} · {name.capitalize()}",
            callback_data=f"mk:{change_type}:{kind}",
        )
    builder.button(text="← Назад", callback_data="man:types")
    builder.adjust(1)
    return builder.as_markup()


def manual_causes(analysis: Analysis, change_type: int, change_kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for letter in CAUSES:
        marker = analysis.verdict(change_type, change_kind, letter).verdict.marker
        builder.button(
            text=f"{marker} {texts.cause_label(letter)}",
            callback_data=f"mc:{change_type}:{change_kind}:{letter}",
        )
    builder.button(text="← Назад", callback_data=f"mk:back:{change_type}")
    builder.adjust(1)
    return builder.as_markup()


def contradiction(change_type: int, change_kind: str, cause_1: str) -> InlineKeyboardMarkup:
    """Three ways forward. The third is the one that teaches something."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Выбрать другой код", callback_data="man:types")
    builder.button(text="Переписать Ожидание", callback_data="sit:again")
    builder.button(
        text="Сгенерировать всё равно",
        callback_data=f"force:{change_type}:{change_kind}:{cause_1}",
    )
    builder.adjust(1)
    return builder.as_markup()


def conditional(change_type: int, change_kind: str, cause_1: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Принять допущение",
        callback_data=f"accept:{change_type}:{change_kind}:{cause_1}",
    )
    builder.button(text="← Выбрать другое", callback_data="man:types")
    builder.adjust(1)
    return builder.as_markup()


def situation_cause_2(change_type: int, change_kind: str, cause_1: str) -> InlineKeyboardMarkup:
    """The Revelation cause. Unconstrained — only the paradox changes."""
    builder = InlineKeyboardBuilder()
    for letter, name in CAUSES.items():
        verdict = classify_paradox(change_kind, cause_1, letter)
        builder.button(
            text=f"{letter} · {name} — {texts.PARADOX_HINT[verdict]}",
            callback_data=f"sc2:{change_type}:{change_kind}:{cause_1}:{letter}",
        )
    builder.adjust(1)
    return builder.as_markup()


def packs(available: Sequence[tuple[str, int, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for pack_id, units, stars in available:
        builder.button(text=f"{units} генераций — {stars} ⭐", callback_data=f"pack:{pack_id}")
    builder.adjust(1)
    return builder.as_markup()
