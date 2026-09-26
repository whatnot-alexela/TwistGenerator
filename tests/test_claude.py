"""Tests for the Anthropic wrapper and cost accounting.

No network: the client is driven through a stub that plays back whatever
response or exception a test needs. The point of these tests is the failure
taxonomy — a generation that fails must never be charged for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from core.claude import (
    ClaudeClient,
    ClaudeError,
    Outcome,
    extract_text,
)
from core.costs import PRICING, UnknownModelError, Usage, cost_usd, format_usd

# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@dataclass
class StubUsage:
    input_tokens: int = 1000
    output_tokens: int = 500
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class StubBlock:
    type: str
    text: str = ""


@dataclass
class StubDetails:
    category: str | None = None


@dataclass
class StubMessage:
    content: list[StubBlock]
    stop_reason: str | None = "end_turn"
    usage: StubUsage = field(default_factory=StubUsage)
    model: str = "claude-opus-5"
    stop_details: StubDetails | None = None


def message(text: str = "Твист.", **kwargs: Any) -> StubMessage:
    return StubMessage(content=[StubBlock("text", text)], **kwargs)


class StubStream:
    def __init__(self, result: StubMessage) -> None:
        self._result = result

    async def __aenter__(self) -> StubStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_final_message(self) -> StubMessage:
        return self._result


@dataclass
class StubMessages:
    """Plays back a script of responses and exceptions, one per call."""

    script: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def stream(self, **kwargs: Any) -> StubStream:
        """Synchronous, exactly like the SDK's.

        It was `async def` here, and that hid a TypeError that only appeared
        against the live API: the real stream() returns the context manager
        rather than a coroutine.
        """
        self.calls.append(kwargs)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return StubStream(item)


class RateLimitError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class BadRequestError(Exception):
    status_code = 400


class InternalServerError(Exception):
    status_code = 503


def client(*script: Any, **kwargs: Any) -> tuple[ClaudeClient, StubMessages]:
    messages = StubMessages(script=list(script))
    slept: list[float] = []

    async def no_sleep(delay: float) -> None:
        slept.append(delay)

    instance = ClaudeClient(messages=messages, sleep=no_sleep, **kwargs)
    instance.slept = slept  # type: ignore[attr-defined]
    return instance, messages


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


async def test_generate_returns_the_text_and_the_bill() -> None:
    claude, _ = client(message("Ожидание. Откровение."))
    result = await claude.generate("СИСТЕМА", "СРЕЗ")

    assert result.text == "Ожидание. Откровение."
    assert result.model == "claude-opus-5"
    assert result.usage.input_tokens == 1000
    assert result.cost_usd == cost_usd(Usage(1000, 500), "claude-opus-5")
    assert result.latency_ms >= 0


async def test_request_shape_matches_what_opus_5_requires() -> None:
    claude, messages = client(message())
    await claude.generate("СИСТЕМА", "СРЕЗ")
    sent = messages.calls[0]

    assert sent["model"] == "claude-opus-5"
    # budget_tokens is rejected on Opus 5 — adaptive thinking is the only mode.
    assert sent["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in sent["thinking"]
    # effort lives inside output_config, not at the top level.
    assert sent["output_config"]["effort"] == "high"
    assert "effort" not in sent
    assert sent["fallbacks"] == "default"
    assert sent["system"][0]["text"] == "СИСТЕМА"
    assert sent["messages"] == [{"role": "user", "content": "СРЕЗ"}]


async def test_caching_is_off_unless_asked_for() -> None:
    claude, messages = client(message())
    await claude.generate("СИСТЕМА", "СРЕЗ")
    assert "cache_control" not in messages.calls[0]["system"][0]

    claude, messages = client(message(), cache_system_prompt=True)
    await claude.generate("СИСТЕМА", "СРЕЗ")
    assert messages.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_thinking_blocks_are_not_part_of_the_answer() -> None:
    reply = StubMessage(content=[StubBlock("thinking", "рассуждение"), StubBlock("text", "ответ")])
    assert extract_text(reply) == "ответ"


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


async def test_a_refusal_is_not_retried_and_is_not_the_users_fault() -> None:
    claude, messages = client(
        message(stop_reason="refusal", stop_details=StubDetails(category="cyber"))
    )
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")

    assert caught.value.outcome is Outcome.REFUSED
    assert "cyber" in str(caught.value)
    assert len(messages.calls) == 1


async def test_a_refusal_still_reports_its_usage() -> None:
    """It was billed, so it belongs in the ledger even though it failed."""
    claude, _ = client(message(stop_reason="refusal"))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")
    assert caught.value.usage.input_tokens == 1000


async def test_stop_reason_is_checked_before_the_content() -> None:
    """A refusal arrives as an ordinary 200 with text in it."""
    claude, _ = client(message("что-то похожее на ответ", stop_reason="refusal"))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")
    assert caught.value.outcome is Outcome.REFUSED


# --------------------------------------------------------------------------- #
# Retrying
# --------------------------------------------------------------------------- #


async def test_a_rate_limit_is_retried_then_succeeds() -> None:
    claude, messages = client(RateLimitError("429"), RateLimitError("429"), message("готово"))
    result = await claude.generate("СИСТЕМА", "СРЕЗ")

    assert result.text == "готово"
    assert len(messages.calls) == 3
    assert claude.slept == [2.0, 4.0]  # type: ignore[attr-defined]


async def test_retries_give_up_after_the_last_delay() -> None:
    claude, messages = client(APIConnectionError("network"))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")

    assert caught.value.outcome is Outcome.UNAVAILABLE
    assert len(messages.calls) == 4  # three delays, four attempts
    assert claude.slept == [2.0, 4.0, 8.0]  # type: ignore[attr-defined]


async def test_a_server_error_is_retryable() -> None:
    claude, _ = client(InternalServerError("503"), message("готово"))
    assert (await claude.generate("СИСТЕМА", "СРЕЗ")).text == "готово"


async def test_a_bad_request_is_ours_to_fix_and_is_not_retried() -> None:
    claude, messages = client(BadRequestError("bad schema"))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")

    assert caught.value.outcome is Outcome.BROKEN
    assert len(messages.calls) == 1


# --------------------------------------------------------------------------- #
# Truncation
# --------------------------------------------------------------------------- #


async def test_truncation_is_retried_once_with_more_room() -> None:
    claude, messages = client(message(stop_reason="max_tokens"), message("целиком"))
    result = await claude.generate("СИСТЕМА", "СРЕЗ")

    assert result.text == "целиком"
    assert messages.calls[1]["max_tokens"] > messages.calls[0]["max_tokens"]


async def test_persistent_truncation_gives_up() -> None:
    claude, _ = client(message(stop_reason="max_tokens"))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")
    assert caught.value.outcome is Outcome.TRUNCATED


async def test_an_empty_response_is_an_error_not_an_empty_twist() -> None:
    claude, _ = client(StubMessage(content=[StubBlock("text", "   ")]))
    with pytest.raises(ClaudeError) as caught:
        await claude.generate("СИСТЕМА", "СРЕЗ")
    assert caught.value.outcome is Outcome.BROKEN


# --------------------------------------------------------------------------- #
# Cost accounting
# --------------------------------------------------------------------------- #


def test_cost_of_a_plain_call() -> None:
    # 1M input at $5 plus 1M output at $25.
    assert cost_usd(Usage(1_000_000, 1_000_000), "claude-opus-5") == Decimal("30")


def test_cache_writes_cost_more_and_reads_cost_less() -> None:
    plain = cost_usd(Usage(input_tokens=1_000_000), "claude-opus-5")
    written = cost_usd(Usage(cache_creation_input_tokens=1_000_000), "claude-opus-5")
    read = cost_usd(Usage(cache_read_input_tokens=1_000_000), "claude-opus-5")

    assert written == plain * Decimal("1.25")
    assert read == plain * Decimal("0.10")


def test_a_realistic_generation_lands_near_the_spec_estimate() -> None:
    """docs/SPEC.md §7.1 budgets ~$0.25; a 21k-in / 4k-out call should be close."""
    amount = cost_usd(Usage(input_tokens=21_000, output_tokens=4_000), "claude-opus-5")
    assert Decimal("0.15") < amount < Decimal("0.30")


def test_unknown_model_raises_rather_than_guessing() -> None:
    with pytest.raises(UnknownModelError, match="no price on file"):
        cost_usd(Usage(1, 1), "claude-imaginary-9")


def test_every_priced_model_has_both_rates() -> None:
    for model, rates in PRICING.items():
        assert len(rates) == 2, model
        assert all(rate > 0 for rate in rates), model


def test_usage_adds_up_across_calls() -> None:
    total = Usage(10, 20) + Usage(1, 2, 3, 4)
    assert total == Usage(11, 22, 3, 4)
    assert total.total_input == 11 + 3 + 4


def test_usage_reads_a_response_that_omits_cache_fields() -> None:
    usage = Usage.from_response(StubUsage(input_tokens=7, output_tokens=8))
    assert usage == Usage(7, 8, 0, 0)


def test_usage_survives_a_missing_usage_object() -> None:
    assert Usage.from_response(None) == Usage()


def test_format_usd_keeps_fractions_of_a_cent() -> None:
    assert format_usd(Decimal("0.001234")) == "$0.001234"
