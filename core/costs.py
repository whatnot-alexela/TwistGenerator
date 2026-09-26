"""What a call costs, and what the bot records about it.

Every figure in docs/SPEC.md §7 is an estimate until these numbers come back
from real traffic, so usage is recorded on every call from the first day.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

#: USD per million tokens. Claude API first-party rates.
PRICING: Final[dict[str, tuple[Decimal, Decimal]]] = {
    #                     input        output
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}

#: Writing to the prompt cache costs more than a plain input token; reading from
#: it costs much less. Multipliers against the input rate.
CACHE_WRITE_MULTIPLIER: Final[Decimal] = Decimal("1.25")  # 5-minute TTL
CACHE_READ_MULTIPLIER: Final[Decimal] = Decimal("0.10")

_PER_TOKEN: Final[Decimal] = Decimal("1000000")


class UnknownModelError(KeyError):
    """Raised for a model with no price on file, rather than guessing one."""


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts as reported by the API.

    Thinking tokens are billed as output and are already inside
    ``output_tokens`` — there is no separate line for them.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_response(cls, usage: object) -> Usage:
        """Read an SDK usage object, tolerating fields an older model omits."""
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cache_read_input_tokens=(self.cache_read_input_tokens + other.cache_read_input_tokens),
        )


def cost_usd(usage: Usage, model: str) -> Decimal:
    """What this call cost, in USD.

    Returned as a ``Decimal`` so it can be summed into the budget ledger without
    the rounding drift a float accumulates over thousands of calls.
    """
    try:
        input_rate, output_rate = PRICING[model]
    except KeyError as exc:
        raise UnknownModelError(
            f"no price on file for {model!r}; add it to core/costs.PRICING "
            f"rather than letting spend go unrecorded"
        ) from exc

    return (
        usage.input_tokens * input_rate
        + usage.cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
        + usage.output_tokens * output_rate
    ) / _PER_TOKEN


def format_usd(amount: Decimal) -> str:
    """Six decimal places — a single generation costs fractions of a cent."""
    return f"${amount:.6f}"
