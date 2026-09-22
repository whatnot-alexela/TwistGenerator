"""The Anthropic API wrapper.

One place where the bot talks to Claude, so retries, refusals, cost recording
and the error taxonomy of docs/SPEC.md §5.7 all live together and cannot drift
apart between call sites.

A generation that fails never costs the user a quota unit: the caller is told
whether the failure was the user's problem or ours, and only a complete response
is charged for.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Final, Protocol

from core.costs import Usage, cost_usd

logger = logging.getLogger(__name__)

#: Server-side routing around a safety refusal, so a declined request falls back
#: to another model instead of failing. See the Claude API docs on fallbacks.
FALLBACK_BETA: Final[str] = "server-side-fallback-2026-07-01"

#: Backoff between retries, in seconds.
RETRY_DELAYS: Final[tuple[float, ...]] = (2.0, 4.0, 8.0)


class Outcome(Enum):
    """How a call ended, from the caller's point of view."""

    OK = "ok"
    #: The model declined. Not retryable, not the user's fault to fix by waiting.
    REFUSED = "refused"
    #: Rate limited, overloaded or a network fault. Retryable; quota untouched.
    UNAVAILABLE = "unavailable"
    #: A bug on our side — bad request, unknown model, malformed schema.
    BROKEN = "broken"
    #: The response was cut off at max_tokens even after a retry with more room.
    TRUNCATED = "truncated"


class ClaudeError(Exception):
    """A call that did not produce a usable response.

    Carries the usage of the failed attempt, because a refused or truncated call
    is still billed and still belongs in the ledger.
    """

    def __init__(self, outcome: Outcome, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.usage = usage or Usage()


@dataclass(frozen=True, slots=True)
class Completion:
    """A successful generation, with everything the ledger needs."""

    text: str
    model: str
    effort: str
    usage: Usage
    cost_usd: Decimal
    latency_ms: int
    stop_reason: str | None


class MessagesClient(Protocol):
    """The slice of the Anthropic SDK this module uses.

    Narrow on purpose: it makes the tests a plain stub rather than a mock of the
    whole SDK, and it documents exactly what the bot depends on.
    """

    async def stream(self, **kwargs: Any) -> Any: ...

    async def create(self, **kwargs: Any) -> Any: ...


@dataclass
class ClaudeClient:
    """Generates twists. One long-lived instance per process."""

    messages: MessagesClient
    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = 8000
    cache_system_prompt: bool = False
    #: Injected so tests do not spend three seconds sleeping through a backoff.
    sleep: Any = field(default=asyncio.sleep)

    async def generate(self, system: str, slice_text: str) -> Completion:
        """Run one generation, retrying the failures that are worth retrying."""
        last: ClaudeError | None = None
        for attempt, delay in enumerate((*RETRY_DELAYS, None)):
            try:
                return await self._attempt(system, slice_text, self.max_tokens)
            except ClaudeError as error:
                last = error
                if error.outcome is not Outcome.UNAVAILABLE or delay is None:
                    raise
                logger.warning(
                    "claude unavailable (attempt %d): %s — retrying in %.0fs",
                    attempt + 1,
                    error,
                    delay,
                )
                await self.sleep(delay)
        raise last if last else ClaudeError(Outcome.BROKEN, "retry loop fell through")

    async def _attempt(self, system: str, slice_text: str, max_tokens: int) -> Completion:
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if self.cache_system_prompt:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        started = time.monotonic()
        try:
            stream = await self.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": slice_text}],
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            async with stream as active:
                message = await active.get_final_message()
        except Exception as exc:  # noqa: BLE001 — classified immediately below
            raise self._classify(exc) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        usage = Usage.from_response(getattr(message, "usage", None))
        stop_reason = getattr(message, "stop_reason", None)

        # Always check stop_reason before reading content: a refusal arrives as
        # a perfectly ordinary HTTP 200.
        if stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            logger.warning("claude refused the request (category=%s)", category)
            raise ClaudeError(
                Outcome.REFUSED,
                f"model declined the request (category={category})",
                usage,
            )

        if stop_reason == "max_tokens":
            if max_tokens < self.max_tokens * 2:
                logger.info("hit max_tokens at %d, retrying with more room", max_tokens)
                return await self._attempt(system, slice_text, int(max_tokens * 1.5))
            raise ClaudeError(Outcome.TRUNCATED, "response truncated at max_tokens", usage)

        text = extract_text(message)
        if not text.strip():
            raise ClaudeError(Outcome.BROKEN, f"empty response (stop_reason={stop_reason})", usage)

        return Completion(
            text=text,
            model=getattr(message, "model", self.model),
            effort=self.effort,
            usage=usage,
            cost_usd=cost_usd(usage, self.model),
            latency_ms=latency_ms,
            stop_reason=stop_reason,
        )

    @staticmethod
    def _classify(exc: Exception) -> ClaudeError:
        """Map an SDK exception onto an outcome.

        Matched by class name rather than by importing the SDK's exception
        types, so this module stays importable — and testable — without the
        `anthropic` package installed.
        """
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)

        if name in ("RateLimitError", "APIConnectionError", "APITimeoutError"):
            return ClaudeError(Outcome.UNAVAILABLE, f"{name}: {exc}")
        if name == "InternalServerError" or (isinstance(status, int) and status >= 500):
            return ClaudeError(Outcome.UNAVAILABLE, f"{name}: {exc}")
        if isinstance(status, int) and 400 <= status < 500:
            return ClaudeError(Outcome.BROKEN, f"{name} ({status}): {exc}")
        return ClaudeError(Outcome.BROKEN, f"{name}: {exc}")


def extract_text(message: Any) -> str:
    """Concatenate the text blocks of a response.

    Thinking blocks are skipped: they are billed as output and reported in
    usage, but they are not the answer.
    """
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts).strip()
