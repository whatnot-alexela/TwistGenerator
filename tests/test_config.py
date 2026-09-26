"""Tests for configuration loading.

Two things matter here beyond the parsing: a misconfigured money cap must be
caught at startup rather than discovered on the bill, and a secret must not be
printable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bot.config import ConfigError, Settings, load_settings
from core.prompt.builder import Profile

REQUIRED = {
    "BOT_TOKEN": "123:abc",
    "ANTHROPIC_API_KEY": "sk-ant-secret",
    "OWNER_TELEGRAM_ID": "42",
    "DATABASE_URL": "postgresql+asyncpg://localhost/twist",
    "METHODOLOGY_URL": "https://kiloslov.ru",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from a blank environment so a stray variable cannot leak in."""
    for key in list(REQUIRED) + [
        "ANTHROPIC_MODEL",
        "GENERATION_EFFORT",
        "ANALYSIS_EFFORT",
        "PROMPT_PROFILE",
        "ANTHROPIC_PROMPT_CACHE",
        "MAX_TOKENS",
        "FREE_FORMULA_GENS_PER_DAY",
        "DAILY_FREE_BUDGET_USD",
        "MONTHLY_FREE_BUDGET_USD",
        "EMERGENCY_STOP_USD",
        "PACK_SMALL_UNITS",
        "PACK_SMALL_STARS",
    ]:
        monkeypatch.delenv(key, raising=False)


def configure(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for key, value in {**REQUIRED, **overrides}.items():
        monkeypatch.setenv(key, value)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


def test_defaults_match_the_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    settings = load_settings()

    assert settings.model == "claude-opus-5"
    assert settings.generation_effort == "high"
    assert settings.profile is Profile.FULL
    assert settings.prompt_cache is False  # docs/SPEC.md §5.5
    assert settings.free_formula_gens_per_day == 3
    assert settings.free_expectation_gens_per_day == 1
    assert settings.monthly_free_budget_usd == Decimal("100")


def test_a_missing_required_setting_names_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    monkeypatch.delenv("BOT_TOKEN")
    with pytest.raises(ConfigError, match="BOT_TOKEN is not set"):
        load_settings()


def test_an_empty_required_setting_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, ANTHROPIC_API_KEY="")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings()


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_profile_can_be_switched(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, PROMPT_PROFILE="condensed")
    assert load_settings().profile is Profile.CONDENSED


def test_an_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, PROMPT_PROFILE="abridged")
    with pytest.raises(ConfigError, match="PROMPT_PROFILE"):
        load_settings()


def test_an_unknown_effort_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, GENERATION_EFFORT="maximum")
    with pytest.raises(ConfigError, match="GENERATION_EFFORT"):
        load_settings()


def test_cache_is_a_switch_not_a_truthy_string(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, ANTHROPIC_PROMPT_CACHE="on")
    assert load_settings().prompt_cache is True
    configure(monkeypatch, ANTHROPIC_PROMPT_CACHE="yes")
    with pytest.raises(ConfigError, match="ANTHROPIC_PROMPT_CACHE"):
        load_settings()


def test_a_non_numeric_count_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, FREE_FORMULA_GENS_PER_DAY="три")
    with pytest.raises(ConfigError, match="expected a whole number"):
        load_settings()


def test_a_non_numeric_amount_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, MONTHLY_FREE_BUDGET_USD="сто долларов")
    with pytest.raises(ConfigError, match="expected an amount in USD"):
        load_settings()


def test_a_zero_budget_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, MONTHLY_FREE_BUDGET_USD="0")
    with pytest.raises(ConfigError, match="must be positive"):
        load_settings()


def test_max_tokens_has_a_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, MAX_TOKENS="100")
    with pytest.raises(ConfigError, match="at least 1024"):
        load_settings()


# --------------------------------------------------------------------------- #
# Caps that only make sense together
# --------------------------------------------------------------------------- #


def test_a_daily_cap_above_the_monthly_one_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, DAILY_FREE_BUDGET_USD="500", MONTHLY_FREE_BUDGET_USD="100")
    with pytest.raises(ConfigError, match="daily cap would never bind"):
        load_settings()


def test_an_emergency_stop_below_the_monthly_cap_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, MONTHLY_FREE_BUDGET_USD="100", EMERGENCY_STOP_USD="50")
    with pytest.raises(ConfigError, match="EMERGENCY_STOP_USD must exceed"):
        load_settings()


def test_a_pack_priced_below_the_floor_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """15 stars per unit was the first draft's price; at the measured cost it
    loses money, so the floor is enforced rather than documented."""
    configure(monkeypatch, PACK_SMALL_UNITS="10", PACK_SMALL_STARS="150")
    with pytest.raises(ConfigError, match="below the floor of 20"):
        load_settings()


def test_the_default_packs_clear_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    for name, units, stars in load_settings().packs:
        assert stars / units >= 20, name


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #


def test_repr_hides_the_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """A settings object turns up in tracebacks; the key must not ride along."""
    configure(monkeypatch)
    text = repr(load_settings())

    assert "sk-ant-secret" not in text
    assert "123:abc" not in text
    assert "bot_token='<set>'" in text
    assert "anthropic_api_key='<set>'" in text
    # Non-secret settings stay visible, or the repr would be useless.
    assert "claude-opus-5" in text


def test_the_secret_fields_are_actually_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    settings = load_settings()
    assert settings.anthropic_api_key == "sk-ant-secret"
    assert settings.bot_token == "123:abc"


def test_settings_are_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    with pytest.raises(Exception, match="cannot assign"):
        load_settings().model = "claude-haiku-4-5"  # type: ignore[misc]


def test_settings_can_be_built_directly_for_tests() -> None:
    settings = Settings(
        bot_token="t",
        anthropic_api_key="k",
        owner_telegram_id=1,
        database_url="sqlite://",
        methodology_url="https://example.org",
    )
    settings.validate()
    assert settings.profile is Profile.FULL
