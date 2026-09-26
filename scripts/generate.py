#!/usr/bin/env python3
"""Generate one twist from the command line.

This is the measuring instrument for docs/SPEC.md §7: it reports what a
generation actually cost, so the estimates there can be replaced with figures.

Inspect the prompt without spending anything:

    python scripts/generate.py 6и-ФК --dry-run

Generate for real — needs ANTHROPIC_API_KEY, and a machine in a region
Anthropic serves (§5.2):

    python scripts/generate.py 6и-ФК --genre "нуар" --characters "детектив, вдова"

Sweep a whole group to compare profiles (§12.4):

    python scripts/generate.py --group 1е --profile full  --out runs/full
    python scripts/generate.py --group 1е --profile condensed --out runs/condensed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.catalog import Catalog  # noqa: E402
from core.claude import ClaudeClient, ClaudeError  # noqa: E402
from core.costs import Usage, cost_usd, format_usd  # noqa: E402
from core.formula import CAUSES, Formula  # noqa: E402
from core.prompt.builder import Profile, PromptBuilder, estimate_tokens  # noqa: E402
from core.prompt.slice import UserInput, build_slice  # noqa: E402

RULE = "-" * 78


def formulas_for(args: argparse.Namespace) -> list[Formula]:
    if args.group:
        return [
            Formula.parse(f"{args.group}-{c1}{c2}")
            for c1 in CAUSES
            for c2 in CAUSES
            if c1 != c2  # the 12 archetypes; content shifts have no examples yet
        ]
    return [Formula.parse(args.formula)]


def build(formula: Formula, args: argparse.Namespace) -> tuple[str, str]:
    builder = PromptBuilder(Profile(args.profile))
    catalog = Catalog.load()
    user_input = UserInput(
        genre=args.genre,
        characters=args.characters,
        setting=args.setting,
        situation=args.situation,
    )
    system = builder.build_core().text
    slice_text = build_slice(
        formula, catalog.build_slice(formula, seed=args.seed), builder, user_input
    )
    return system, slice_text


async def run_one(
    formula: Formula, args: argparse.Namespace, client: ClaudeClient | None
) -> Decimal:
    system, slice_text = build(formula, args)
    estimated = estimate_tokens(system) + estimate_tokens(slice_text)

    print(RULE)
    print(f"{formula.code}   парадокс: {formula.paradox.value}   профиль: {args.profile}")
    print(f"вход (оценка): {estimated} токенов")

    if client is None:
        print(RULE)
        print(slice_text if args.slice_only else f"{system}\n\n{slice_text}")
        projected = cost_usd(Usage(input_tokens=estimated, output_tokens=4000), args.model)
        print(RULE)
        print(f"ничего не потрачено; при 4000 токенах вывода вышло бы {format_usd(projected)}")
        return Decimal(0)

    try:
        result = await client.generate(system, slice_text)
    except ClaudeError as error:
        print(f"ОШИБКА [{error.outcome.value}]: {error}")
        if error.usage.total_input:
            print(f"  списано всё равно: {format_usd(cost_usd(error.usage, args.model))}")
        return cost_usd(error.usage, args.model)

    print(
        f"вход {result.usage.total_input} | выход {result.usage.output_tokens} | "
        f"{result.latency_ms} мс | {format_usd(result.cost_usd)}"
    )
    print(RULE)
    print(result.text)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{formula.code}.txt").write_text(
            f"{formula.code}  профиль={args.profile}  seed={args.seed}\n"
            f"вход={result.usage.total_input} выход={result.usage.output_tokens} "
            f"стоимость={format_usd(result.cost_usd)}\n\n{result.text}\n",
            encoding="utf-8",
        )
    return result.cost_usd


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("formula", nargs="?", help="e.g. 6и-ФК")
    target.add_argument("--group", help="every archetype of a change code, e.g. 1е")

    parser.add_argument("--dry-run", action="store_true", help="print the prompt, spend nothing")
    parser.add_argument("--slice-only", action="store_true", help="with --dry-run, skip the core")
    parser.add_argument("--profile", default="full", choices=[p.value for p in Profile])
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"))
    parser.add_argument("--effort", default=os.environ.get("GENERATION_EFFORT", "high"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--genre")
    parser.add_argument("--characters")
    parser.add_argument("--setting")
    parser.add_argument("--situation")
    parser.add_argument("--out", type=Path, help="write each result to this directory")
    args = parser.parse_args()

    client: ClaudeClient | None = None
    if not args.dry_run:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            parser.error(
                "ANTHROPIC_API_KEY is not set. Use --dry-run to inspect the prompt "
                "without spending anything."
            )
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            parser.error("the anthropic package is not installed: pip install anthropic")
        client = ClaudeClient(
            messages=AsyncAnthropic().beta.messages,
            model=args.model,
            effort=args.effort,
        )

    total = Decimal(0)
    formulas = formulas_for(args)
    for formula in formulas:
        total += await run_one(formula, args, client)
        print()

    if len(formulas) > 1:
        print(RULE)
        print(f"{len(formulas)} формул, суммарно {format_usd(total)}")
        print(f"в среднем {format_usd(total / len(formulas))} за генерацию")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
