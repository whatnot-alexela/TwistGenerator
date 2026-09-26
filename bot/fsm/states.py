"""Dialog states.

Mode 1 walks four choices, then an optional-input stage that the user can loop
through as many times as they like before generating.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Formula(StatesGroup):
    """Mode 1 — formula first."""

    change_type = State()
    change_kind = State()
    cause_1 = State()
    cause_2 = State()
    options = State()

    awaiting_genre = State()
    awaiting_characters = State()
    awaiting_setting = State()


class Situation(StatesGroup):
    """Mode 2 — the user describes a situation first."""

    describing = State()
    readings = State()
    manual_type = State()
    manual_kind = State()
    manual_cause = State()
    cause_2 = State()
    options = State()

    awaiting_genre = State()
    awaiting_characters = State()


class Feedback(StatesGroup):
    awaiting_comment = State()
