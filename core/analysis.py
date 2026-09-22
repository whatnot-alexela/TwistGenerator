"""Reading a described situation into the left half of a formula.

The freedom in a formula is asymmetric. The **Revelation** cause is free: any of
the four yields a valid twist, only the paradox changes. The **left half** — the
change type, its kind, and the cause perceived in the Expectation — is fixed by
what the user actually wrote, because the methodology's own rule says the kind
of change is read from the Expectation. Putting a cause there that the text does
not support is not an unusual choice; it is a false one.

So one call classifies the text and returns a verdict for **all 48** left-half
options at once. The bot keeps that map in the dialog and answers every
subsequent button press from it, without going back to the API. Marking the
buttons then costs nothing, and a user who overrides the reading can see what
they are overriding.

See docs/SPEC.md §5.4 and §6.2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from core.claude import ClaudeError, Outcome, extract_text
from core.costs import Usage, cost_usd
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES

logger = logging.getLogger(__name__)

#: 6 change types × 2 kinds × 4 first causes.
LEFT_HALF_SIZE: Final[int] = len(CHANGE_TYPES) * len(CHANGE_KINDS) * len(CAUSES)


class Verdict(Enum):
    """How well one left-half reading fits the user's text."""

    OK = "ok"
    CONDITIONAL = "conditional"
    CONTRADICTION = "contradiction"

    @property
    def marker(self) -> str:
        return {"ok": "✅", "conditional": "⚠️", "contradiction": "❌"}[self.value]

    @property
    def rank(self) -> int:
        """For rolling child verdicts up to a parent button."""
        return {"ok": 2, "conditional": 1, "contradiction": 0}[self.value]


@dataclass(frozen=True, slots=True)
class Reading:
    """One way the situation can be read, with the reasoning behind it."""

    change_type: int
    change_kind: str
    cause_1: str
    justification: str

    @property
    def prefix(self) -> str:
        """``1е-Ф`` — the formula with its Revelation still open."""
        return f"{self.change_type}{self.change_kind}-{self.cause_1}"

    def describe(self) -> str:
        return (
            f"{CHANGE_KINDS[self.change_kind]} изменение "
            f"«{CHANGE_TYPES[self.change_type]}», "
            f"в Ожидании — {CAUSES[self.cause_1]} причина"
        )


@dataclass(frozen=True, slots=True)
class Compatibility:
    verdict: Verdict
    #: Required when the verdict is CONDITIONAL: what has to be assumed.
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class Analysis:
    """The whole result of one analysis call."""

    classifiable: bool
    readings: tuple[Reading, ...]
    compatibility: dict[str, Compatibility]
    missing_information: tuple[str, ...] = ()
    usage: Usage = Usage()
    cost_usd: Any = None

    def verdict(self, change_type: int, change_kind: str, cause_1: str) -> Compatibility:
        """The verdict for one left-half option, from the cached map."""
        return self.compatibility.get(
            f"{change_type}{change_kind}-{cause_1}",
            Compatibility(Verdict.CONTRADICTION),
        )

    def best_for_type(self, change_type: int) -> Verdict:
        """The best verdict under a change type, for its button's marker."""
        return self._best(f"{change_type}")

    def best_for_kind(self, change_type: int, change_kind: str) -> Verdict:
        return self._best(f"{change_type}{change_kind}-")

    def _best(self, prefix: str) -> Verdict:
        found = [item.verdict for key, item in self.compatibility.items() if key.startswith(prefix)]
        return max(found, key=lambda verdict: verdict.rank) if found else Verdict.CONTRADICTION


# --------------------------------------------------------------------------- #
# The schema the model must answer in
# --------------------------------------------------------------------------- #

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["classifiable", "top_readings", "compatibility"],
    "properties": {
        "classifiable": {
            "type": "boolean",
            "description": "Достаточно ли в тексте сведений, чтобы отнести его к формуле",
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Только если classifiable=false: чего именно не хватает в тексте",
        },
        "top_readings": {
            "type": "array",
            "minItems": 0,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["change_type", "change_kind", "cause_1", "justification"],
                "properties": {
                    "change_type": {"type": "integer", "minimum": 1, "maximum": 6},
                    "change_kind": {"type": "string", "enum": ["е", "и"]},
                    "cause_1": {"type": "string", "enum": ["Ф", "М", "Д", "К"]},
                    "justification": {"type": "string", "maxLength": 600},
                },
            },
        },
        "compatibility": {
            "type": "array",
            "minItems": LEFT_HALF_SIZE,
            "maxItems": LEFT_HALF_SIZE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["change_type", "change_kind", "cause_1", "verdict"],
                "properties": {
                    "change_type": {"type": "integer", "minimum": 1, "maximum": 6},
                    "change_kind": {"type": "string", "enum": ["е", "и"]},
                    "cause_1": {"type": "string", "enum": ["Ф", "М", "Д", "К"]},
                    "verdict": {"type": "string", "enum": ["ok", "conditional", "contradiction"]},
                    "condition": {"type": "string", "maxLength": 300},
                },
            },
        },
    },
}

INSTRUCTION: Final[str] = """# Задача: прочитать ситуацию как левую половину формулы

Пользователь описал исходную ситуацию — это его Ожидание. Определи, какой
левой половине формулы она соответствует: тип изменения, вид изменения и
причина, которую в этой ситуации считают действующей.

Помни главное правило Методики: **вид изменения определяется по Ожиданию**, то
есть по тому, как ситуация выглядит до поворота, а не по тому, чем она
окажется. Первая причина — та, которую персонажи и читатель считают настоящей
сейчас, а не та, которая раскроется.

Ответь строго по схеме, тремя частями.

1. `classifiable` — хватает ли в тексте сведений. Если из описания непонятно,
что именно меняется, кто действует или воспринимается ли процесс как природный,
поставь `false` и перечисли в `missing_information`, чего не хватает. Не
угадывай.

2. `top_readings` — **два** лучших прочтения, если их два. Ситуация почти
всегда читается двояко, и второе прочтение не менее ценно, чем первое. В
`justification` объясни, чем именно в тексте подтверждается это прочтение, со
ссылкой на правила Методики.

3. `compatibility` — вердикт по **каждому** из 48 сочетаний (6 типов × 2 вида ×
4 первых причины), без пропусков:
   - `ok` — прочтение прямо подтверждается текстом;
   - `conditional` — возможно при допущении; обязательно опиши это допущение
     в поле `condition` одной фразой;
   - `contradiction` — противоречит тексту по правилам Методики.

Будь строг. `ok` только там, где текст действительно это говорит. Если почти
всё выходит `ok`, значит описание слишком расплывчато — поставь
`classifiable: false`."""


class AnalysisError(Exception):
    """The model answered, but not in a form we can use."""


ParsedAnalysis = tuple[bool, tuple[Reading, ...], dict[str, Compatibility], tuple[str, ...]]


def parse_analysis(payload: str) -> ParsedAnalysis:
    """Read the model's JSON, rejecting anything that would mislead the user."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"ответ не разобрался как JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise AnalysisError("ожидался объект в корне ответа")

    classifiable = bool(document.get("classifiable"))
    missing = tuple(str(item) for item in document.get("missing_information") or [])

    readings: list[Reading] = []
    for raw in document.get("top_readings") or []:
        try:
            readings.append(
                Reading(
                    change_type=int(raw["change_type"]),
                    change_kind=str(raw["change_kind"]),
                    cause_1=str(raw["cause_1"]),
                    justification=str(raw["justification"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError(f"прочтение без обязательного поля: {exc}") from exc

    compatibility: dict[str, Compatibility] = {}
    for raw in document.get("compatibility") or []:
        try:
            key = f"{int(raw['change_type'])}{raw['change_kind']}-{raw['cause_1']}"
            verdict = Verdict(str(raw["verdict"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError(f"вердикт без обязательного поля: {exc}") from exc
        condition = raw.get("condition")
        if verdict is Verdict.CONDITIONAL and not condition:
            # Without the condition the bot cannot tell the user what they are
            # agreeing to, so treat it as the stricter verdict rather than
            # inventing a premise.
            verdict = Verdict.CONTRADICTION
            condition = None
        compatibility[key] = Compatibility(verdict, str(condition) if condition else None)

    if classifiable and len(compatibility) != LEFT_HALF_SIZE:
        raise AnalysisError(
            f"карта совместимости неполная: {len(compatibility)} из {LEFT_HALF_SIZE}"
        )
    if classifiable and not readings:
        raise AnalysisError("нет ни одного прочтения при classifiable=true")

    return classifiable, tuple(readings), compatibility, missing


async def analyse(
    messages: Any,
    system: str,
    situation: str,
    model: str = "claude-opus-5",
    effort: str = "low",
    max_tokens: int = 8000,
) -> Analysis:
    """One classification call. Cheap by design: low effort, no prose."""
    try:
        message = await messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": f"{system}\n\n{INSTRUCTION}"}],
            messages=[{"role": "user", "content": situation}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": SCHEMA},
        )
    except Exception as exc:  # noqa: BLE001 — classified by the caller's taxonomy
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        retryable = name in ("RateLimitError", "APIConnectionError", "APITimeoutError") or (
            isinstance(status, int) and status >= 500
        )
        raise ClaudeError(
            Outcome.UNAVAILABLE if retryable else Outcome.BROKEN, f"{name}: {exc}"
        ) from exc

    usage = Usage.from_response(getattr(message, "usage", None))
    if getattr(message, "stop_reason", None) == "refusal":
        raise ClaudeError(Outcome.REFUSED, "model declined to analyse the situation", usage)

    classifiable, readings, compatibility, missing = parse_analysis(extract_text(message))
    return Analysis(
        classifiable=classifiable,
        readings=readings,
        compatibility=compatibility,
        missing_information=missing,
        usage=usage,
        cost_usd=cost_usd(usage, model),
    )
