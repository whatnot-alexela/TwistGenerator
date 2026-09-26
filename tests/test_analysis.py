"""Tests for reading a situation into the left half of a formula.

Two things here cost the user something real if they go wrong: a malformed
answer that the bot presents as a confident reading, and a "conditional"
verdict with no condition attached — the user would be agreeing to a premise
nobody can show them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from core.analysis import (
    LEFT_HALF_SIZE,
    SCHEMA,
    Analysis,
    AnalysisError,
    Compatibility,
    Reading,
    Verdict,
    analyse,
    parse_analysis,
)
from core.claude import ClaudeError, Outcome
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def full_map(default: str = "contradiction", **overrides: str) -> list[dict[str, Any]]:
    """A complete 48-entry map, with named cells overridden."""
    rows = []
    for change_type in CHANGE_TYPES:
        for kind in CHANGE_KINDS:
            for cause in CAUSES:
                key = f"{change_type}{kind}-{cause}"
                verdict = overrides.get(key.replace("-", "_"), default)
                row: dict[str, Any] = {
                    "change_type": change_type,
                    "change_kind": kind,
                    "cause_1": cause,
                    "verdict": verdict,
                }
                if verdict == "conditional":
                    row["condition"] = "если считать реку живым существом"
                rows.append(row)
    return rows


def payload(**overrides: Any) -> str:
    document: dict[str, Any] = {
        "classifiable": True,
        "top_readings": [
            {
                "change_type": 1,
                "change_kind": "е",
                "cause_1": "Ф",
                "justification": "текст описывает природный процесс",
            }
        ],
        "compatibility": full_map(**{"1е_Ф": "ok"}),
    }
    document.update(overrides)
    return json.dumps(document, ensure_ascii=False)


@dataclass
class StubUsage:
    input_tokens: int = 18_000
    output_tokens: int = 900
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class StubBlock:
    type: str = "text"
    text: str = ""


@dataclass
class StubMessage:
    content: list[StubBlock]
    stop_reason: str | None = "end_turn"
    usage: StubUsage = field(default_factory=StubUsage)


@dataclass
class StubMessages:
    result: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_a_complete_answer_parses() -> None:
    classifiable, readings, compatibility, missing = parse_analysis(payload())

    assert classifiable is True
    assert len(compatibility) == LEFT_HALF_SIZE
    assert readings[0].prefix == "1е-Ф"
    assert compatibility["1е-Ф"].verdict is Verdict.OK
    assert missing == ()


def test_an_incomplete_map_is_rejected() -> None:
    """A map with holes would show ❌ on options nobody judged."""
    with pytest.raises(AnalysisError, match="карта совместимости неполная"):
        parse_analysis(payload(compatibility=full_map()[:10]))


def test_a_conditional_without_its_condition_becomes_a_contradiction() -> None:
    """The user cannot agree to a premise the bot cannot show them."""
    rows = full_map()
    rows[0] = {**rows[0], "verdict": "conditional"}  # no condition field
    parsed = parse_analysis(payload(compatibility=rows))[2]

    key = f"{rows[0]['change_type']}{rows[0]['change_kind']}-{rows[0]['cause_1']}"
    assert parsed[key].verdict is Verdict.CONTRADICTION
    assert parsed[key].condition is None


def test_a_conditional_with_its_condition_survives() -> None:
    parsed = parse_analysis(payload(compatibility=full_map(**{"1е_Ф": "conditional"})))[2]
    assert parsed["1е-Ф"].verdict is Verdict.CONDITIONAL
    assert parsed["1е-Ф"].condition


def test_an_unclassifiable_answer_needs_no_map() -> None:
    classifiable, readings, compatibility, missing = parse_analysis(
        json.dumps(
            {
                "classifiable": False,
                "missing_information": ["кто действует", "что именно меняется"],
                "top_readings": [],
                "compatibility": [],
            },
            ensure_ascii=False,
        )
    )
    assert classifiable is False
    assert readings == ()
    assert compatibility == {}
    assert "кто действует" in missing


def test_classifiable_without_a_reading_is_rejected() -> None:
    with pytest.raises(AnalysisError, match="нет ни одного прочтения"):
        parse_analysis(payload(top_readings=[]))


def test_broken_json_is_rejected() -> None:
    with pytest.raises(AnalysisError, match="не разобрался как JSON"):
        parse_analysis("{не json")


def test_a_reading_missing_a_field_is_rejected() -> None:
    with pytest.raises(AnalysisError, match="прочтение без обязательного поля"):
        parse_analysis(payload(top_readings=[{"change_type": 1, "change_kind": "е"}]))


def test_a_verdict_with_an_unknown_value_is_rejected() -> None:
    rows = full_map()
    rows[0] = {**rows[0], "verdict": "возможно"}
    with pytest.raises(AnalysisError, match="вердикт без обязательного поля"):
        parse_analysis(payload(compatibility=rows))


# --------------------------------------------------------------------------- #
# Rolling verdicts up to the parent buttons
# --------------------------------------------------------------------------- #


def analysis_from(**overrides: str) -> Analysis:
    _, readings, compatibility, _ = parse_analysis(payload(compatibility=full_map(**overrides)))
    return Analysis(True, readings, compatibility)


def test_a_branch_is_never_greener_than_what_is_inside_it() -> None:
    analysis = analysis_from(**{"1е_Ф": "ok"})
    assert analysis.best_for_type(1) is Verdict.OK
    assert analysis.best_for_type(2) is Verdict.CONTRADICTION
    assert analysis.best_for_kind(1, "е") is Verdict.OK
    assert analysis.best_for_kind(1, "и") is Verdict.CONTRADICTION


def test_a_conditional_child_shows_as_conditional_above() -> None:
    analysis = analysis_from(**{"3и_М": "conditional"})
    assert analysis.best_for_type(3) is Verdict.CONDITIONAL
    assert analysis.best_for_kind(3, "и") is Verdict.CONDITIONAL


def test_an_unknown_cell_reads_as_a_contradiction() -> None:
    """Never invite a choice nobody judged."""
    assert Analysis(True, (), {}).verdict(1, "е", "Ф").verdict is Verdict.CONTRADICTION


def test_markers_are_distinct() -> None:
    assert len({verdict.marker for verdict in Verdict}) == 3


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


async def test_the_request_asks_for_structured_output_at_low_effort() -> None:
    messages = StubMessages(StubMessage(content=[StubBlock(text=payload())]))
    await analyse(messages, "ЯДРО", "Деревня пустеет.", effort="low")

    sent = messages.calls[0]
    assert sent["output_config"]["effort"] == "low"
    # The API takes a wrapper around the schema. Sending the schema bare was a
    # live 400 — "output_config.format.type: Input should be 'json_schema'" —
    # and no stub could have caught it, so it is pinned here.
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["format"]["schema"]["required"] == [
        "classifiable",
        "top_readings",
        "compatibility",
    ]
    assert sent["thinking"] == {"type": "adaptive"}
    assert "ЯДРО" in sent["system"][0]["text"]
    assert sent["messages"][0]["content"] == "Деревня пустеет."


async def test_the_result_carries_its_cost() -> None:
    messages = StubMessages(StubMessage(content=[StubBlock(text=payload())]))
    analysis = await analyse(messages, "ЯДРО", "Деревня пустеет.")

    assert analysis.classifiable
    assert analysis.usage.input_tokens == 18_000
    assert analysis.cost_usd > 0


async def test_a_refusal_is_reported_as_one() -> None:
    messages = StubMessages(StubMessage(content=[StubBlock(text="")], stop_reason="refusal"))
    with pytest.raises(ClaudeError) as caught:
        await analyse(messages, "ЯДРО", "что-то")
    assert caught.value.outcome is Outcome.REFUSED


async def test_a_rate_limit_is_marked_retryable() -> None:
    class RateLimitError(Exception):
        pass

    with pytest.raises(ClaudeError) as caught:
        await analyse(StubMessages(RateLimitError("429")), "ЯДРО", "что-то")
    assert caught.value.outcome is Outcome.UNAVAILABLE


async def test_a_bad_request_is_ours_to_fix() -> None:
    class BadRequestError(Exception):
        status_code = 400

    with pytest.raises(ClaudeError) as caught:
        await analyse(StubMessages(BadRequestError("schema")), "ЯДРО", "что-то")
    assert caught.value.outcome is Outcome.BROKEN


async def test_a_malformed_answer_surfaces_rather_than_being_guessed_at() -> None:
    messages = StubMessages(StubMessage(content=[StubBlock(text="не json")]))
    with pytest.raises(AnalysisError):
        await analyse(messages, "ЯДРО", "что-то")


# --------------------------------------------------------------------------- #
# Small pieces
# --------------------------------------------------------------------------- #


def test_the_reading_prefix_leaves_the_revelation_open() -> None:
    reading = Reading(6, "и", "Ф", "обоснование")
    assert reading.prefix == "6и-Ф"
    assert "Исчезновение" in reading.describe()
    assert "искусственное" in reading.describe()


def test_compatibility_defaults_to_no_condition() -> None:
    assert Compatibility(Verdict.OK).condition is None


def test_the_left_half_is_forty_eight_options() -> None:
    assert LEFT_HALF_SIZE == 48
    assert len(full_map()) == 48


# --------------------------------------------------------------------------- #
# The schema the API will accept
# --------------------------------------------------------------------------- #

#: Structured outputs take a subset of JSON Schema. Two keywords this schema
#: once used are rejected outright — `maxItems` ("For 'array' type, property
#: 'maxItems' is not supported") and, with it, `minItems`; `minimum`, `maximum`
#: and `maxLength` are not worth the next 400 either. Nothing here replaces
#: them: the 48-entry completeness check lives in `parse_analysis`, and the
#: bounds live in the instruction text.
ALLOWED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "description",
}


def walk(node: Any, path: str = "SCHEMA") -> list[str]:
    found: list[str] = []
    if not isinstance(node, dict):
        return found
    for key, value in node.items():
        if key not in ALLOWED_KEYWORDS:
            found.append(f"{path}.{key}")
        if key == "properties" and isinstance(value, dict):
            found += [item for name, sub in value.items() for item in walk(sub, f"{path}.{name}")]
        elif key == "items":
            found += walk(value, f"{path}[]")
    return found


def test_the_schema_uses_only_keywords_the_api_accepts() -> None:
    assert walk(SCHEMA) == []


def test_completeness_is_enforced_by_the_parser_rather_than_the_schema() -> None:
    """The schema can no longer pin the map to 48 entries — this must."""
    with pytest.raises(AnalysisError, match="карта совместимости неполная"):
        parse_analysis(payload(compatibility=full_map()[:47]))
