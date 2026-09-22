# CLAUDE.md

Telegram bot generating plot twists strictly by the **Twist Generator 1.0**
methodology — 192 formulas from Aristotle's four causes and six types of change.
The author of the methodology is the owner of this repository.

Full design: **docs/SPEC.md**. Read it before touching the
methodology, the prompt or anything.

Keep your replies extremely concise and focus on conveying the key information. 
No unnecessary fluff, no long code snippets.

## Money — read this first

The owner pays for every generation out of his own Anthropic account.

| | |
|---|---|
| Cost per generation | **~$0.25** (est.; measured figures replace this at milestone 3) |
| Monthly cap on free generations | **$100** ≈ 400 generations ≈ 13/day for the whole bot |
| Daily cap | $4 · Emergency stop (free + paid) | $250/month |
| Telegram Stars break-even | **19 ⭐ per unit** — packs are priced at 20–26 |

Rules that exist because they cost real money:

- **Never price a pack below 20 ⭐ per unit.** `bot/config.py` refuses to start
  if you do. Opus 5's thinking length varies; one heavy generation eats the
  margin of several ordinary ones.
- **Caps are evaluated against recorded spend**, never an estimate. Every call
  writes its `usage` and USD cost to `api_calls`.
- **A failed generation never charges a quota unit.** Refusals and truncations
  are still billed, so their usage is still recorded.
- **Appendices ride in the slice, not the core.** Appendix 7 is 8 800 tokens
  and means nothing to a formula without paradox №2. Moving it into the core
  would raise the bill on every single generation.
- Prompt caching is **off** by default (§5.5) — at launch traffic the write is
  paid on nearly every request and almost never read back.

## Invariants

- **The paradox rule is computed, never looked up.** Natural change (`е`):
  foreign causes are Д and К. Artificial (`и`): Ф and М. Paradox №1 when the
  Expectation's cause is foreign, №2 when the Revelation's is. All 192
  combinations are asserted against the author's matrix in `tests/`.
- **The change kind is fixed by the Expectation, never the Revelation.**
- **`methodology/redactions.yaml`** removes the author's asides doubting his own
  system, at prompt assembly. **`methodology/corrections.yaml`** repairs damage
  in the FB2 source, at import. Each entry must match **exactly once**; zero or
  two is a fatal error, never a silent skip.
- **The importer keeps the source verbatim.** Never hand-edit a generated file
  under `methodology/core/` or `methodology/examples/` — change the source, a
  correction, or a redaction, then re-run the importer. Files marked
  `frozen: true` are hand-written and must not be regenerated.
- **Russia is outside Anthropic's supported regions.** The bot runs on a
  European VPS (§5.2, §11.1). Do not work around this with a proxy.
- **Secrets never enter chat, an issue or a commit.** `BOT_TOKEN` and
  `ANTHROPIC_API_KEY` are set on the server. `Settings.__repr__` hides them.

## Data state

Example appendices are finished for **`1е` and `6и` only**: 24 formulas, 29
examples, 20 references. Ten formulas have an example but no film or book and
so earn the *«малоисследованный твист»* message. The other 168 are
uncatalogued — the bot still generates for them, from the rules alone, and the
slice says so rather than pretending an example exists.

When a new appendix is ready: append it to the FB2, re-run the importer, commit.
No code change.

## Commands

```bash
.venv/bin/pytest -q                  # 639 tests
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/mypy core scripts bot db   # strict

python scripts/import_fb2.py methodology/source/twist_generator_v1.fb2
python scripts/dump_prompt.py --out /tmp/prompts   # the prompt, for reading
python scripts/generate.py 6и-ФК --dry-run         # a slice, spending nothing
```

CI runs all of the above and fails if the committed methodology data is stale.

## Conventions

- Code and comments in English; everything the user or the model reads in
  Russian. User-facing strings live only in `bot/texts.py`.
- Prompt text lives in `methodology/`, never inlined in code.
- The author is not a programmer. Explain trade-offs in plain terms, name what
  a decision costs, and never report an estimate as a measurement.
