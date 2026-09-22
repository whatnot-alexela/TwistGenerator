"""The generation service: quota, prompt, API call, and what gets written down.

The bot handlers call this and nothing else. Keeping the order in one place is
what guarantees the rule that matters most — **a user is charged only for a
generation that actually arrived**.

The order is:

1. decide whether this may run, and on whose money;
2. assemble the prompt;
3. call Claude — the slow, failure-prone step, outside any transaction;
4. only then, in one transaction, charge the quota and store the result.

A crash anywhere in 1–3 costs the owner money, which is recorded, and costs the
user nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession as Session
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import Settings
from core.catalog import Catalog, Coverage
from core.claude import ClaudeClient, ClaudeError, Completion
from core.costs import cost_usd
from core.formula import Formula
from core.prompt.builder import PromptBuilder
from core.prompt.slice import UserInput, build_slice
from core.quota import Decision, Mode, charge, check, record_failure
from db.models import ApiCall, Generation, User
from db.session import transaction

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    """The request was refused before any money was spent."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.verdict.value)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class Result:
    generation_id: int
    text: str
    formula: Formula
    decision: Decision
    completion: Completion


@dataclass
class GenerationService:
    settings: Settings
    catalog: Catalog
    builder: PromptBuilder
    claude: ClaudeClient
    sessions: async_sessionmaker[Session]

    async def generate(
        self,
        user_id: int,
        formula: Formula,
        mode: Mode = Mode.FORMULA,
        user_input: UserInput | None = None,
        seed: int | None = None,
    ) -> Result:
        """Run one generation end to end. Raises on refusal or failure."""
        user_input = user_input or UserInput()

        # 1. May this run?
        async with transaction(self.sessions) as session:
            user = await self._user(session, user_id)
            decision = await check(session, user, mode, self.settings)
            if not decision.allowed:
                raise QuotaExceeded(decision)

        # 2. Assemble. Cheap, deterministic, no side effects.
        catalogue = self.catalog.build_slice(formula, seed=seed)
        system = self.builder.build_core().text
        slice_text = build_slice(formula, catalogue, self.builder, user_input)

        # 3. Call out. Slow, and the step that fails.
        try:
            completion = await self.claude.generate(system, slice_text)
        except ClaudeError as error:
            await self._record_failure(user_id, error, decision)
            raise

        # 4. Write it all down, together.
        async with transaction(self.sessions) as session:
            user = await self._user(session, user_id)
            generation = Generation(
                user_id=user.id,
                mode=mode.value,
                formula=formula.code,
                change_type=formula.change_type,
                change_kind=formula.change_kind,
                cause_1=formula.cause_1,
                cause_2=formula.cause_2,
                paradox_1=formula.paradox.has_paradox_1,
                paradox_2=formula.paradox.has_paradox_2,
                catalogued=catalogue.coverage is not Coverage.UNCATALOGUED,
                had_reference=catalogue.reference is not None,
                genre=user_input.genre,
                characters=user_input.characters,
                setting=user_input.setting,
                audience=user_input.audience,
                user_expectation=user_input.situation,
                override_condition=user_input.condition,
                example_seed=catalogue.seed,
                block_b=slice_text,
                profile=self.builder.profile.value,
                response_text=completion.text,
                model=completion.model,
                effort=completion.effort,
                units_charged=decision.units,
                was_free=decision.was_free,
            )
            session.add(generation)
            await session.flush()

            session.add(
                ApiCall(
                    generation_id=generation.id,
                    user_id=user.id,
                    purpose="generation",
                    model=completion.model,
                    effort=completion.effort,
                    input_tokens=completion.usage.input_tokens,
                    output_tokens=completion.usage.output_tokens,
                    cache_creation_input_tokens=completion.usage.cache_creation_input_tokens,
                    cache_read_input_tokens=completion.usage.cache_read_input_tokens,
                    cost_usd=completion.cost_usd,
                    was_free=decision.was_free,
                    latency_ms=completion.latency_ms,
                    stop_reason=completion.stop_reason,
                )
            )
            await charge(session, user, mode, decision, completion.cost_usd)
            generation_id = generation.id

        logger.info(
            "generated %s for user %s: %s tokens in, %s out, %s",
            formula.code,
            user_id,
            completion.usage.total_input,
            completion.usage.output_tokens,
            completion.cost_usd,
        )
        return Result(
            generation_id=generation_id,
            text=completion.text,
            formula=formula,
            decision=decision,
            completion=completion,
        )

    async def _record_failure(self, user_id: int, error: ClaudeError, decision: Decision) -> None:
        """Bank what a failed call cost, without touching the user's quota."""
        cost = (
            cost_usd(error.usage, self.settings.model) if error.usage.total_input else Decimal("0")
        )
        async with transaction(self.sessions) as session:
            user = await self._user(session, user_id)
            session.add(
                ApiCall(
                    user_id=user.id,
                    purpose="generation",
                    model=self.settings.model,
                    effort=self.settings.generation_effort,
                    input_tokens=error.usage.input_tokens,
                    output_tokens=error.usage.output_tokens,
                    cache_creation_input_tokens=error.usage.cache_creation_input_tokens,
                    cache_read_input_tokens=error.usage.cache_read_input_tokens,
                    cost_usd=cost,
                    was_free=decision.was_free,
                    error=f"{error.outcome.value}: {error}"[:500],
                )
            )
            await record_failure(session, cost, was_free=decision.was_free)
        logger.warning("generation failed for user %s: %s", user_id, error)

    @staticmethod
    async def _user(session: Session, user_id: int) -> User:
        user = await session.get(User, user_id)
        if user is None:
            raise LookupError(f"no user {user_id}")
        return user
