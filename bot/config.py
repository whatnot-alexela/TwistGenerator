"""Runtime configuration, read from the environment.

Deliberately stdlib-only. The settings are few and mostly numbers, and the
money caps deserve explicit, readable validation rather than a schema library's
coercion rules — a silently-parsed monthly cap is exactly the kind of thing that
costs real money when it goes wrong.

Nothing here logs or repeats a secret. `__repr__` is defined so a settings
object cannot leak the API key into a traceback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Final

from core.prompt.builder import Profile

#: Fields whose value must never be printed, logged or serialised.
SECRET_FIELDS: Final[frozenset[str]] = frozenset({"bot_token", "anthropic_api_key"})


class ConfigError(Exception):
    """Raised for a missing or nonsensical setting. Always fatal at startup."""


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ConfigError(f"{name} is not set")
    return value


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: expected a whole number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name}: must be at least {minimum}, got {value}")
    return value


def _money(name: str, default: str) -> Decimal:
    raw = os.environ.get(name) or default
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ConfigError(f"{name}: expected an amount in USD, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name}: must be positive, got {value}")
    return value


def _choice(name: str, default: str, allowed: frozenset[str]) -> str:
    value = (os.environ.get(name) or default).strip().lower()
    if value not in allowed:
        raise ConfigError(f"{name}: expected one of {sorted(allowed)}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    """Everything the bot needs to run."""

    bot_token: str
    anthropic_api_key: str
    owner_telegram_id: int
    database_url: str
    methodology_url: str

    model: str = "claude-opus-5"
    generation_effort: str = "high"
    analysis_effort: str = "low"
    profile: Profile = Profile.FULL
    prompt_cache: bool = False
    max_tokens: int = 8000

    free_formula_gens_per_day: int = 3
    free_expectation_gens_per_day: int = 1
    free_analyses_per_day: int = 5

    daily_free_budget_usd: Decimal = Decimal("4")
    monthly_free_budget_usd: Decimal = Decimal("100")
    emergency_stop_usd: Decimal = Decimal("250")

    pack_small_units: int = 10
    pack_small_stars: int = 260
    pack_medium_units: int = 30
    pack_medium_stars: int = 700
    pack_large_units: int = 100
    pack_large_stars: int = 2100

    def __repr__(self) -> str:
        shown = {
            field.name: ("<set>" if field.name in SECRET_FIELDS else getattr(self, field.name))
            for field in fields(self)
        }
        body = ", ".join(f"{key}={value!r}" for key, value in shown.items())
        return f"Settings({body})"

    @property
    def packs(self) -> tuple[tuple[str, int, int], ...]:
        """``(id, units, stars)`` for each pack offered by /buy."""
        return (
            ("small", self.pack_small_units, self.pack_small_stars),
            ("medium", self.pack_medium_units, self.pack_medium_stars),
            ("large", self.pack_large_units, self.pack_large_stars),
        )

    def validate(self) -> None:
        """Checks that need more than one field to see.

        The pack floor is the one that matters: Opus 5's thinking length varies,
        and one heavy generation absorbs the margin of several ordinary ones, so
        a pack priced near break-even loses money on real traffic rather than on
        average. docs/SPEC.md §7.4.
        """
        if self.daily_free_budget_usd > self.monthly_free_budget_usd:
            raise ConfigError(
                "DAILY_FREE_BUDGET_USD is larger than MONTHLY_FREE_BUDGET_USD; "
                "the daily cap would never bind"
            )
        if self.emergency_stop_usd <= self.monthly_free_budget_usd:
            raise ConfigError(
                "EMERGENCY_STOP_USD must exceed MONTHLY_FREE_BUDGET_USD, or free "
                "generation could never run to its cap"
            )
        for name, units, stars in self.packs:
            if units <= 0 or stars <= 0:
                raise ConfigError(f"pack {name}: units and stars must both be positive")
            if stars / units < 20:
                raise ConfigError(
                    f"pack {name}: {stars / units:.1f} stars per unit is below the "
                    f"floor of 20. See docs/SPEC.md §7.4 before lowering it."
                )


def load_settings() -> Settings:
    """Read the environment, or fail with a message naming the setting."""
    settings = Settings(
        bot_token=_env("BOT_TOKEN"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        owner_telegram_id=int(_env("OWNER_TELEGRAM_ID")),
        database_url=_env("DATABASE_URL"),
        methodology_url=_env("METHODOLOGY_URL", "https://kiloslov.ru"),
        model=os.environ.get("ANTHROPIC_MODEL") or "claude-opus-5",
        generation_effort=_choice(
            "GENERATION_EFFORT", "high", frozenset({"low", "medium", "high", "xhigh", "max"})
        ),
        analysis_effort=_choice(
            "ANALYSIS_EFFORT", "low", frozenset({"low", "medium", "high", "xhigh", "max"})
        ),
        profile=Profile(_choice("PROMPT_PROFILE", "full", frozenset({"full", "condensed"}))),
        prompt_cache=_choice("ANTHROPIC_PROMPT_CACHE", "off", frozenset({"on", "off"})) == "on",
        max_tokens=_int("MAX_TOKENS", 8000, minimum=1024),
        free_formula_gens_per_day=_int("FREE_FORMULA_GENS_PER_DAY", 3),
        free_expectation_gens_per_day=_int("FREE_EXPECTATION_GENS_PER_DAY", 1),
        free_analyses_per_day=_int("FREE_ANALYSES_PER_DAY", 5),
        daily_free_budget_usd=_money("DAILY_FREE_BUDGET_USD", "4"),
        monthly_free_budget_usd=_money("MONTHLY_FREE_BUDGET_USD", "100"),
        emergency_stop_usd=_money("EMERGENCY_STOP_USD", "250"),
        pack_small_units=_int("PACK_SMALL_UNITS", 10, minimum=1),
        pack_small_stars=_int("PACK_SMALL_STARS", 260, minimum=1),
        pack_medium_units=_int("PACK_MEDIUM_UNITS", 30, minimum=1),
        pack_medium_stars=_int("PACK_MEDIUM_STARS", 700, minimum=1),
        pack_large_units=_int("PACK_LARGE_UNITS", 100, minimum=1),
        pack_large_stars=_int("PACK_LARGE_STARS", 2100, minimum=1),
    )
    settings.validate()
    return settings
