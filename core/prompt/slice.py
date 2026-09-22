"""Block B — the part of the prompt that changes with the formula.

The core states the rules; the slice says which formula is being generated, what
the methodology already has to say about it, and what the user asked for.

Everything here is Russian: it is prompt text, not code documentation.
See docs/SPEC.md §4.3 and §4.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.catalog import Coverage, Slice
from core.formula import Formula, ParadoxVerdict
from core.prompt.builder import PromptBuilder

#: One sentence per verdict, naming what the writer has to do. The mechanics are
#: already in core block a09 — this only points at the relevant case, so the
#: slice does not repeat the core back at the model.
PARADOX_STATEMENT: Final[dict[ParadoxVerdict, str]] = {
    ParadoxVerdict.NONE: (
        "Парадокса нет: обе причины свои для этого вида изменения. "
        "Твист работает чистой подменой причины, без сдвига вида изменения. "
        "Не добавляй парадокс, которого в формуле нет."
    ),
    ParadoxVerdict.PARADOX_1: (
        "Парадокс №1 — когнитивный диссонанс в Ожидании. Причина, заявленная "
        "в Ожидании, чужая для этого вида изменения, поэтому противоречие "
        "видно ещё до поворота. Сей признаки несоответствия с самого начала: "
        "читатель должен смутно чувствовать, что что-то не сходится, не "
        "понимая, что именно."
    ),
    ParadoxVerdict.PARADOX_2: (
        "Парадокс №2 — онтологический сдвиг в Откровении. В Ожидании всё "
        "согласовано, противоречия нет вовсе; причина, раскрытая в Откровении, "
        "чужая для этого вида изменения, и именно это переворачивает картину. "
        "Держи в Ожидании полную иллюзию согласованности, без единого намёка."
    ),
    ParadoxVerdict.BOTH: (
        "Оба парадокса сразу. В Ожидании изменение одного вида, но "
        "воспринимается как другое; в Откровении оно оказывается тем, чем "
        "казалось, и это переворачивает всё заново. Диссонанс должен быть "
        "различим с самого начала и при этом вести читателя не туда."
    ),
}

#: Which appendix explains this formula's paradoxes. Both, when it carries both.
_SUPPLEMENTS_BY_VERDICT: Final[dict[ParadoxVerdict, tuple[str, ...]]] = {
    ParadoxVerdict.NONE: (),
    ParadoxVerdict.PARADOX_1: ("paradox_1",),
    ParadoxVerdict.PARADOX_2: ("paradox_2",),
    ParadoxVerdict.BOTH: ("paradox_1", "paradox_2"),
}

_NO_EXAMPLE: Final[str] = (
    "Канонических примеров для этой формулы в Методике пока нет: приложение "
    "с примерами для этой группы ещё не написано. Опирайся только на правила, "
    "изложенные выше, и не выдумывай, будто пример существует."
)

MAX_GENRE: Final[int] = 64
MAX_CHARACTERS: Final[int] = 300
MAX_SETTING: Final[int] = 100
MAX_SITUATION: Final[int] = 500


class UserInputError(ValueError):
    """Raised when a field is longer than the bot promised to accept."""


@dataclass(frozen=True, slots=True)
class UserInput:
    """Block C. Every field is optional; empty ones are left out of the prompt
    entirely rather than sent as empty strings."""

    genre: str | None = None
    characters: str | None = None
    setting: str | None = None
    audience: str | None = None
    #: Mode 2 only: the user's own Expectation, passed through verbatim.
    situation: str | None = None
    #: Mode 2 only: set when the user overrode the bot's reading with a
    #: "conditional" choice. Carried as a stated premise of the generation.
    condition: str | None = None

    def __post_init__(self) -> None:
        for name, limit in (
            ("genre", MAX_GENRE),
            ("characters", MAX_CHARACTERS),
            ("setting", MAX_SETTING),
            ("situation", MAX_SITUATION),
        ):
            value = getattr(self, name)
            if value is not None and len(value) > limit:
                raise UserInputError(f"{name}: {len(value)} characters, limit is {limit}")

    @property
    def is_empty(self) -> bool:
        return not any((self.genre, self.characters, self.setting, self.audience, self.situation))

    def render(self) -> str:
        rows = [
            ("Жанр", self.genre),
            ("Персонажи", self.characters),
            ("Сеттинг или эпоха", self.setting),
            ("Целевая аудитория", self.audience),
        ]
        lines = [f"{label}: {value}" for label, value in rows if value]
        if not lines and not self.situation:
            return "Пользователь не задал дополнительных условий — выбери их сам."
        return "\n".join(lines)


def build_slice(
    formula: Formula,
    catalogue: Slice,
    builder: PromptBuilder,
    user_input: UserInput | None = None,
) -> str:
    """Assemble block B and block C into the user message."""
    user_input = user_input or UserInput()
    parts: list[str] = [
        "# Задание",
        "",
        "## Формула",
        "",
        formula.describe() + ".",
        "",
        PARADOX_STATEMENT[formula.paradox],
    ]

    if formula.is_content_shift:
        parts += [
            "",
            "Это твист содержания причины: тип причины в Ожидании и в "
            "Откровении один и тот же, ошибка не в типе, а в содержании. "
            "Персонажи верно угадывают, какого рода причина действует, но "
            "полностью ошибаются в том, что именно это за причина.",
        ]

    parts += ["", "## Что об этой формуле говорит Методика", ""]
    if catalogue.coverage is Coverage.UNCATALOGUED:
        parts.append(_NO_EXAMPLE)
    else:
        if catalogue.example is not None:
            parts += [
                "Канонический пример:",
                "",
                f"Ожидание: {catalogue.example.expectation}",
                f"Откровение: {catalogue.example.revelation}",
            ]
        if catalogue.reference is not None:
            reference = catalogue.reference
            parts += ["", f"Реализация в известном произведении — {reference.label}:", ""]
            parts.append(reference.analysis)
            if reference.note:
                parts.append(reference.note)
        else:
            parts += [
                "",
                "Реализаций этой формулы в кино и литературе Методика не "
                "нашла. Это не повод ослабить требования — наоборот, строй "
                "твист строго по правилам.",
            ]
        parts += [
            "",
            "Пример дан как образец механики, а не как тема. Не пересказывай "
            "его и не бери его материал: место действия, профессии, эпоха и "
            "предметы должны быть другими.",
        ]

    for key in _SUPPLEMENTS_BY_VERDICT[formula.paradox]:
        block = builder.build_supplement(key)
        number = "№1" if key == "paradox_1" else "№2"
        parts += ["", f"## Обоснование Парадокса {number}", "", block.text]

    parts += ["", "## Исходные данные"]
    if user_input.situation:
        parts += [
            "",
            "Пользователь описал свою исходную ситуацию — это его Ожидание. "
            "Сохрани его дословно по смыслу и построй Откровение именно к "
            "нему, а не придумывай собственную ситуацию:",
            "",
            user_input.situation,
        ]
        if user_input.condition:
            parts += [
                "",
                "Формула применима к этой ситуации при одном допущении, "
                "которое следует считать верным: " + user_input.condition,
            ]
    parts += ["", user_input.render()]

    return "\n".join(parts)
