"""Twist formula parsing, validation and paradox classification.

A formula has the shape ``<N><K>-<C1><C2>`` — for example ``1е-ФД`` or ``6и-КМ``:

* ``N``  — change type, 1..6
* ``K``  — change kind, ``е`` (natural) or ``и`` (artificial)
* ``C1`` — the cause as perceived in the Expectation
* ``C2`` — the cause revealed to be true in the Revelation

All letters are Cyrillic. See docs/SPEC.md §2 and §3.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

# --------------------------------------------------------------------------- #
# Alphabet
# --------------------------------------------------------------------------- #

CHANGE_TYPES: Final[dict[int, str]] = {
    1: "Место",
    2: "Качество",
    3: "Рост",
    4: "Убыль",
    5: "Возникновение",
    6: "Исчезновение",
}

CHANGE_KINDS: Final[dict[str, str]] = {
    "е": "естественное",
    "и": "искусственное",
}

CAUSES: Final[dict[str, str]] = {
    "Ф": "Формальная",
    "М": "Материальная",
    "Д": "Действующая",
    "К": "Конечная",
}

#: Causes proper to a natural change — form and matter.
NATURAL_CAUSES: Final[frozenset[str]] = frozenset({"Ф", "М"})

#: Causes proper to an artificial change — an agent and a goal.
ARTIFICIAL_CAUSES: Final[frozenset[str]] = frozenset({"Д", "К"})

#: Latin letters that look identical to the Cyrillic ones we use. Telegram users
#: type on mixed layouts and the FB2 source is not free of them either, so every
#: inbound string is normalised before parsing.
_HOMOGLYPHS: Final[dict[str, str]] = {
    "M": "М",  # U+004D -> U+041C
    "K": "К",  # U+004B -> U+041A
    "e": "е",  # U+0065 -> U+0435
    "E": "е",
    "Е": "е",  # Cyrillic capital Ye -> lowercase kind letter
    "И": "и",
    "u": "и",
}

_FORMULA_RE: Final[re.Pattern[str]] = re.compile(
    r"^([1-6])([еи])[-.]?([ФМДК])([ФМДК])$",
)


class ParadoxVerdict(Enum):
    """Which of the two paradoxes a formula carries.

    ``PARADOX_1`` is epistemological and synchronic: the dissonance is already
    present in the Expectation. ``PARADOX_2`` is ontological and diachronic: the
    Expectation is coherent and the Revelation redefines it.
    """

    NONE = "none"
    PARADOX_1 = "paradox_1"
    PARADOX_2 = "paradox_2"
    BOTH = "both"

    @property
    def has_paradox_1(self) -> bool:
        return self in (ParadoxVerdict.PARADOX_1, ParadoxVerdict.BOTH)

    @property
    def has_paradox_2(self) -> bool:
        return self in (ParadoxVerdict.PARADOX_2, ParadoxVerdict.BOTH)

    @property
    def has_any(self) -> bool:
        return self is not ParadoxVerdict.NONE


class FormulaError(ValueError):
    """Raised when a string cannot be read as a twist formula."""


def normalise(raw: str) -> str:
    """Strip whitespace and fold Latin homoglyphs onto their Cyrillic twins."""
    text = raw.strip().replace(" ", "")
    return "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)


def foreign_causes(change_kind: str) -> frozenset[str]:
    """The causes that do not belong to a change of this kind.

    A natural change has no external agent and no goal separate from its form,
    so Д and К are foreign to it. An artificial change is driven by a will, so
    a bare Ф or М is foreign to it. Methodology §8, §9.
    """
    if change_kind == "е":
        return ARTIFICIAL_CAUSES
    if change_kind == "и":
        return NATURAL_CAUSES
    raise FormulaError(f"unknown change kind: {change_kind!r}")


def classify_paradox(change_kind: str, cause_1: str, cause_2: str) -> ParadoxVerdict:
    """Classify a formula's paradoxes.

    Paradox №1 fires when the cause perceived in the Expectation is foreign to
    the change's kind; paradox №2 when the cause revealed in the Revelation is.
    Methodology §8, §9, §11; verified against the generation matrix.
    """
    foreign = foreign_causes(change_kind)
    p1 = cause_1 in foreign
    p2 = cause_2 in foreign
    if p1 and p2:
        return ParadoxVerdict.BOTH
    if p1:
        return ParadoxVerdict.PARADOX_1
    if p2:
        return ParadoxVerdict.PARADOX_2
    return ParadoxVerdict.NONE


@dataclass(frozen=True, slots=True)
class Formula:
    """A validated twist formula."""

    change_type: int
    change_kind: str
    cause_1: str
    cause_2: str

    def __post_init__(self) -> None:
        if self.change_type not in CHANGE_TYPES:
            raise FormulaError(f"change type out of range: {self.change_type}")
        if self.change_kind not in CHANGE_KINDS:
            raise FormulaError(f"unknown change kind: {self.change_kind!r}")
        for cause in (self.cause_1, self.cause_2):
            if cause not in CAUSES:
                raise FormulaError(f"unknown cause: {cause!r}")

    # -- construction ------------------------------------------------------- #

    @classmethod
    def parse(cls, raw: str) -> Formula:
        """Parse ``1е-ФД``, ``1е.ФД`` or ``1еФД``, tolerating Latin homoglyphs."""
        match = _FORMULA_RE.match(normalise(raw))
        if match is None:
            raise FormulaError(f"not a twist formula: {raw!r}")
        return cls(
            change_type=int(match.group(1)),
            change_kind=match.group(2),
            cause_1=match.group(3),
            cause_2=match.group(4),
        )

    # -- rendering ---------------------------------------------------------- #

    @property
    def code(self) -> str:
        """Canonical form, hyphen separated: ``1е-ФД``."""
        return f"{self.change_type}{self.change_kind}-{self.cause_1}{self.cause_2}"

    @property
    def group(self) -> str:
        """The change code the formula belongs to: ``1е``."""
        return f"{self.change_type}{self.change_kind}"

    @property
    def shift(self) -> str:
        """The causal shift, without the change code: ``ФД``."""
        return f"{self.cause_1}{self.cause_2}"

    def __str__(self) -> str:
        return self.code

    # -- classification ----------------------------------------------------- #

    @property
    def is_content_shift(self) -> bool:
        """True for ФФ/ММ/ДД/КК — the cause type is right, its content is not."""
        return self.cause_1 == self.cause_2

    @property
    def paradox(self) -> ParadoxVerdict:
        return classify_paradox(self.change_kind, self.cause_1, self.cause_2)

    def describe(self) -> str:
        """One sentence in Russian, for the prompt slice and the formula card."""
        return (
            f"{self.code} — {CHANGE_KINDS[self.change_kind]} изменение "
            f"«{CHANGE_TYPES[self.change_type]}»; "
            f"в Ожидании воспринимается {CAUSES[self.cause_1]} причина, "
            f"в Откровении раскрывается {CAUSES[self.cause_2]}"
        )


def all_formulas() -> list[Formula]:
    """Every formula in the code space: 6 × 2 × 4 × 4 = 192, in matrix order."""
    return [
        Formula(change_type=n, change_kind=k, cause_1=c1, cause_2=c2)
        for n in sorted(CHANGE_TYPES)
        for k in CHANGE_KINDS
        for c1 in CAUSES
        for c2 in CAUSES
    ]
