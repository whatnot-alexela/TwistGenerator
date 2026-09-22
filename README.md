# TwistGenerator

Telegram bot that generates plot twists strictly according to the **Twist Generator 1.0**
methodology — 188 twist formulas built on Aristotle's four causes and six types of change.

Bot: [@twist_generator](https://t.me/twist_generator) · Methodology: https://kiloslov.ru

## Status

Milestones 1–3 complete: the methodology is data, the prompt assembles behind a
profile switch, and the bot generates, stores and rates twists in both modes.
Mode 2 (start from a described situation) works too. Payments are not built yet.

- **[docs/SPEC.md](docs/SPEC.md)** — full technical specification
- **[CLAUDE.md](CLAUDE.md)** — working notes, starting with what things cost

## Formula notation

```
<change type 1-6><kind е|и>-<cause in Expectation><cause in Revelation>
                                    e.g.  1е-ФД,  6и-КМ
```

| | |
|---|---|
| Change types | 1 Место · 2 Качество · 3 Рост · 4 Убыль · 5 Возникновение · 6 Исчезновение |
| Kinds | е естественное · и искусственное |
| Causes | Ф Формальная · М Материальная · Д Действующая · К Конечная |

The code space is 6 × 2 × 4 × 4 = **192 formulas**.

### Paradoxes are computed, never looked up

For a natural change (`е`) the foreign causes are Д and К; for an artificial one
(`и`) they are Ф and М. Paradox №1 fires when the Expectation's cause is foreign,
paradox №2 when the Revelation's is. `tests/test_formula.py` checks this against
the author's generation matrix for all 192 formulas.

## Layout

| Path | Contents |
|---|---|
| `core/formula.py` | formula parsing and the paradox rule |
| `core/catalog.py` | the example catalogue and per-generation slice selection |
| `core/prompt/` | prompt assembly: the core behind a profile switch, the per-formula slice, redactions |
| `core/claude.py` | the API wrapper: retries, refusals, cost recording |
| `core/quota.py` | free allowance, paid units, budget caps |
| `core/service.py` | quota → prompt → API → store, in that order |
| `bot/` | handlers, keyboards, and every user-facing string in `texts.py` |
| `db/` | schema and sessions |
| `scripts/import_fb2.py` | turns the methodology's FB2 source into prompt blocks and YAML |
| `methodology/source/` | the methodology, as authored |
| `methodology/core/` | generated prompt core blocks |
| `methodology/tables/` | reference tables, hand-transcribed from the source's images |
| `methodology/examples/` | the example catalogue, generated |
| `tests/fixtures/matrix.csv` | the generation matrix, hand-transcribed |

## Data coverage

Example appendices are finished for groups `1е` and `6и` only — 24 formulas,
29 worked examples, 20 film and book references. Ten of those formulas have an
example but no reference and so earn the *«малоисследованный твист»* message.
The other 168 formulas are uncatalogued: the bot still generates for them, from
the rules alone.

When a new appendix is ready, append it to the FB2 and re-run the importer; no
code changes are needed.

```bash
python scripts/import_fb2.py methodology/source/twist_generator_v1.fb2
```

The script prints a coverage report and never overwrites the hand-transcribed
tables or any core block marked `frozen: true`.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/pytest -q             # 703 tests
.venv/bin/ruff check .          # lint
.venv/bin/ruff format .         # format
.venv/bin/mypy core scripts bot db

python scripts/generate.py 6и-ФК --dry-run   # inspect a prompt, spend nothing
```
