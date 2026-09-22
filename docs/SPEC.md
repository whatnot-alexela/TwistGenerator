# Technical Specification — Twist Generator Telegram Bot

**Project:** `twist_generator` · **Bot:** [@twist_generator](https://t.me/twist_generator)
**Repository:** `whatnot-alexela/TwistGenerator`
**Version:** 1.0 (MVP) · **Status:** approved for implementation
**Language of the product:** Russian · **Language of the codebase and docs:** English

---

## 1. Purpose and scope

The bot generates plot twists ("твисты") strictly according to the **Twist Generator 1.0** methodology — a system of 188 twist formulas derived from Aristotle's four causes and six types of change, authored by the project owner.

The bot must **not** invent narrative rules of its own. Every generated twist is traceable to a formula, a paradox classification and, where available, a canonical example from the methodology.

### 1.1 In scope for v1.0

| Capability | Detail |
|---|---|
| Mode 1 — Formula-first | User picks change type, change kind, cause 1, cause 2 → bot shows canonical example + paradox verdict → optional inputs → generates 2 twists |
| Mode 2 — Expectation-first | User describes an initial situation → bot classifies it into the left half of a formula → user picks the Revelation cause → generates 2 twists adapted to the user's situation |
| Rating | 1–5 stars + optional free-text comment, re-rating allowed |
| Quotas | Free daily allowances, global budget caps |
| Payments | Telegram Stars, generation packs |
| Admin | `/export` — full dataset as XLSX/CSV, owner only |
| Methodology access | Menu link to `https://kiloslov.ru` |

### 1.2 Out of scope for v1.0

Multi-language UI, web front-end, user-facing history browser, subscription billing, refunds, genre reference database, Growth/Decline split for content-shift twists (see §3.7).

### 1.3 Data readiness constraint

Example appendices are complete **only for groups `1е` and `6и`** (24 formulas, 25 example records). All other groups are authored but not yet written up. The system must work correctly and be testable today with this partial dataset, and must absorb new appendices later **without code changes** (see §3.6).

---

## 2. Domain model

### 2.1 Formula notation

A formula has the shape `<N><K>-<C1><C2>`, e.g. `1е-ФД`, `6и-КМ`.

| Element | Values | Meaning |
|---|---|---|
| `N` — change type | `1` Место · `2` Качество · `3` Рост · `4` Убыль · `5` Возникновение · `6` Исчезновение | What changes |
| `K` — change kind | `е` естественное · `и` искусственное | Internal impulse (nature, fate, chance) vs external will |
| `C1` — cause in Expectation | `Ф` Формальная · `М` Материальная · `Д` Действующая · `К` Конечная | The cause everyone believes is at work |
| `C2` — cause in Revelation | same four | The cause that is actually at work |

Separator: the methodology uses both `-` and `.` (`1е-ФД` ≡ `1е.ФД`). **Canonical internal form is `-`.** The parser accepts both and normalises.

Total space: 6 × 2 × 4 × 4 = **192 formulas**. The methodology's "188" excludes 8 content-shift formulas for Growth/Decline that v1.0 of the methodology does not split (see §3.7); the bot's code space is the full 192 and treats the 8 as valid-but-uncatalogued.

### 2.2 Invariant rules taken from the methodology

These are load-bearing and are enforced in code, not left to the model:

1. **The change kind (`е`/`и`) is determined by the situation in the Expectation, never by the Revelation.**
2. `C1` is the cause *as perceived* in the Expectation; `C2` is the cause *revealed* to be true.
3. When `C1 == C2`, the formula is a **content-shift twist** (ФФ/ММ/ДД/КК): the type of cause is guessed correctly, its content is not.

---

## 3. The methodology as data

### 3.1 Source

`methodology/source/twist_generator_v1.fb2` — FictionBook 2.0, UTF-8, ~110 000 characters of body text plus 7 embedded JPEG images.

**Critical:** all four reference tables exist in the source **only as images**, not as text. They must be transcribed once into Markdown and version-controlled.

| Image | Content | Destination |
|---|---|---|
| `img2.jpg` | Four causes × mode of being × form of time × role in plot | `methodology/tables/causes.md` |
| `img3.jpg` | Natural vs artificial change — comparison table | `methodology/tables/kinds.md` |
| `img4.jpg` | 12 change codes (`1е`…`6и`) with group and type | `methodology/tables/change_codes.md` |
| `img5.jpg` | 12 causal shifts with "Думали, что… а оказалось…" mechanics | `methodology/tables/causal_shifts.md` |
| `img6.jpg` | Twist generation matrix (grey fill = no paradox) | `methodology/tables/matrix.md` — **reference only**, the runtime uses the rule in §3.4 |
| `img7.jpg`, `cover.jpg` | Illustrative / cover | not used |

### 3.2 Extraction pipeline

`scripts/import_fb2.py` — idempotent, run manually, output committed to the repo.

```
import_fb2.py <source.fb2> [--out methodology/]
  1. Strip <binary> blocks, parse XML, extract <section> by <title>.
  2. Write core blocks to methodology/core/<slug>.md  (see §4.2 for the slug list).
  3. Parse example appendices into methodology/examples/<group>.yaml.
  4. Extract <binary> images to methodology/images/ for manual transcription.
  5. Print a coverage report: formulas found, formulas with film/book references,
     formulas missing from the catalogue.
```

The script never overwrites `methodology/tables/*.md` (hand-transcribed) and never overwrites a core block whose `# frozen: true` front-matter flag is set — this protects manually condensed blocks (A10, A11) from being clobbered on re-import.

### 3.3 Example catalogue schema

`methodology/examples/1e.yaml`, `methodology/examples/6i.yaml`, one file per group, added over time.

```yaml
group: "1е"
change_type: 1
change_kind: "е"
source_section: "1.1. Естественное изменение Места (1е)"
formulas:
  - code: "1е-ФД"
    examples:
      - expectation: "стая животных мигрирует по инстинктивному маршруту (Форма)."
        revelation: "их гонит невидимый хищник (Действующая)."
    references:
      - kind: film            # film | book
        title: "Шоу Трумана"
        author: "Питер Уир"
        year: 1998
        analysis: "Ожидание: Трумен воспринимает свою жизнь ... (Ф). Откровение: ..."
        note: null            # the methodology's "Примечание:" text, if present
      - kind: book
        title: "Граф Монте-Кристо"
        author: "Александр Дюма"
        year: 1844
        analysis: "..."
        note: null
```

Rules:
- `examples` and `references` are both **optional lists**. A formula may have examples but no references, references but no examples, or neither.
- A formula absent from every YAML file is *uncatalogued* — a legitimate state, not an error.
- The loader validates every `code` against §2.1 and fails fast on a malformed file at startup.

Current dataset after import: **24 catalogued formulas** (12 in `1е`, 12 in `6и`), **29 example records** (several formulas carry two or three variants), **20 references** — 9 films and 11 books. **10 formulas have an example but no film or book reference** and therefore trigger the "малоисследованный твист" message:

```
1е-ФМ  1е-МФ  1е-МД  1е-ДМ  1е-ДК  1е-КФ  1е-КМ  1е-КД
6и-ФМ  6и-МФ
```

The 8 content-shift formulas of these two groups (`1е-ФФ/ММ/ДД/КК`, `6и-ФФ/ММ/ДД/КК`) are uncatalogued entirely. The import script's coverage report is the authority on these figures after every re-import.

### 3.4 Paradox rule — deterministic, computed in code

No lookup table is required. Derived from §8, §9 and §11 of the methodology and verified cell-by-cell against the matrix image.

```
Let natural_causes    = {Ф, М}
Let artificial_causes = {Д, К}

For kind = е:  "foreign" causes are {Д, К}
For kind = и:  "foreign" causes are {Ф, М}

paradox_1 (cognitive dissonance, present in the Expectation) := C1 is foreign
paradox_2 (ontological shift, appears at the Revelation)     := C2 is foreign
```

Resulting classification, identical in structure for both kinds:

| `C1` | `C2` | Kind `е` | Kind `и` | Verdict |
|---|---|---|---|---|
| Ф/М | Ф/М | ФФ ФМ МФ ММ | ДД ДК КД КК | **No paradox** |
| Ф/М | Д/К | ФД ФК МД МК | ДФ ДМ КФ КМ | **Paradox №2 only** |
| Д/К | Ф/М | ДФ ДМ КФ КМ | ФД ФК МД МК | **Paradox №1 only** |
| Д/К | Д/К | ДД ДК КД КК | ФФ ФМ МФ ММ | **Both paradoxes** |

(For kind `е` read the third column; for kind `и` the fourth.)

Unit tests assert all 192 combinations against a fixture transcribed from `img6.jpg`.

### 3.5 Paradox explanation text

Each of the four verdicts maps to a fixed explanatory passage condensed from §10, stored in `methodology/core/a11_paradox_mechanics.md` and shown to the user alongside the verdict. Content per verdict:

- **No paradox** — the perceived kind of change and both causes are internally consistent; the twist works purely as a causal substitution.
- **Paradox №1** — epistemological, synchronic. The dissonance is already visible in the Expectation; the audience senses something does not add up. Writing rule: seed subtle signs of inconsistency from the start.
- **Paradox №2** — ontological, diachronic. The Expectation is perfectly coherent; the Revelation redefines the nature of reality. Writing rule: maintain a flawless illusion of coherence, no hints whatsoever.
- **Both** — the change is perceived as one kind, is in fact the other, and flips again at the Revelation.

### 3.6 Adding new appendices later

1. Author writes the appendix, appends it to the FB2 (or supplies it as a new section).
2. Run `python scripts/import_fb2.py methodology/source/twist_generator_v1.fb2`.
3. New `methodology/examples/<group>.yaml` appears; coverage report shows the delta.
4. Commit. **No code change, no redeploy needed beyond restarting the bot.**

### 3.7 Known methodology gaps, carried as-is

Recorded here so implementation does not "helpfully" paper over them:

- Content-shift twists (ФФ/ММ/ДД/КК) are not split between Growth (`3`) and Decline (`4`) in methodology v1.0 — 40 formulas instead of 48. The bot allows all 48 and simply reports the 8 as uncatalogued.
- The 4 "substantial change" twists mentioned in the annotation have no section in the source. Not modelled.
- Appendices 1 (partial), 2, 3, 4, 5 are not in the source file. Appendices 6 and 7 are.

---

## 4. Prompt assembly

Three blocks, assembled per request. Block A is constant across every request; Blocks B and C vary.

### 4.1 Budget

| Block | Content | ~tokens |
|---|---|---|
| A | Methodology core | 11 000 – 12 000 |
| B | Formula-specific slice | 1 500 – 3 000 |
| C | User input | ≤ 200 |
| **Total input** | | **13 000 – 16 000** |

### 4.2 Block A — methodology core (constant, system prompt)

Files under `methodology/core/`, concatenated in this exact order. Each is a plain Markdown file so the author can edit wording without touching code.

| Slug | Content | Source section | ~tok |
|---|---|---|---|
| `a01_role.md` | System role: you work strictly within this methodology, you do not introduce narrative rules of your own, you never contradict the supplied formula | authored | 300 |
| `a02_six_arenas.md` | Six arenas of change with the "инсайт для писателя" note for each | §1 | 1 750 |
| `a03_four_causes.md` | The four Aristotelian causes + the causes table | §2 + `img2` | 1 370 |
| `a04_natural_artificial.md` | Natural vs artificial + the comparison table + **the hard rule that the kind is fixed by the Expectation** | §4 + `img3` + §6.1 callout | 1 340 |
| `a05_expectation_revelation.md` | The Expectation → Revelation dynamic | §5 | 1 020 |
| `a06_formula_structure.md` | Formula structure + the 12 causal shifts table in "Думали, что… а оказалось…" form | §6.1–6.2 + `img5` | 1 200 |
| `a07_complex_causality.md` | Complex causality in artificial changes (ship example, detective example) | §6.3 | 900 |
| `a08_fk_kf_paradox.md` | The ФК/КФ difficulty in natural changes and its resolution via a hidden artificial Д | §6.4 | 800 |
| `a09_content_shifts.md` | Content-shift twists ФФ/ММ/ДД/КК | §6.5 | 900 |
| `a10_paradox_rules.md` | Paradox №1, №2 and combined — condensed to the operative rules | §8, §9, §11 | 1 200 |
| `a11_paradox_mechanics.md` | Practical writing requirements per paradox class — condensed from 2 650 to ~600 tokens | §10 | 600 |
| `a12_output_contract.md` | Output format: exactly 2 twists, Russian, structure `Ожидание / Откровение / Почему это работает по формуле`, no meta-commentary, no markdown headings | authored | 400 |

**Explicitly excluded from Block A:** §3 (the Necessary–Possible–Actual triad — the author states it is only marginally used in v1.0), §7 (matrix explanation — superseded by §3.4 of this spec), "От автора", "Как читать эту книгу", "Введение", "Заключение", and the «Я — Легенда» breakdown (removed by the author: the twist contains a paradox that the breakdown does not describe, so it is not a valid reference analysis).

`a10` and `a11` are hand-condensed and carry `# frozen: true`.

### 4.3 Block B — formula slice (variable)

| Part | Content | Source |
|---|---|---|
| B1 | Formula decoded into words: `6и-ФК = искусственное Исчезновение; в Ожидании воспринимается Формальная причина, в Откровении раскрывается Конечная` | computed |
| B2 | Paradox verdict + the matching mechanics passage | computed + `a11` |
| B3 | **One randomly selected** canonical example (`expectation` / `revelation`) for this formula | `examples/*.yaml` |
| B4 | **One randomly selected** film or book reference with its analysis and note | `examples/*.yaml` |
| B5 | Paradox-class supplement: if Paradox №1 → condensed Appendix 6; if Paradox №2 → Appendix 7 Group А (kind `е`) or Group Б (kind `и`); if both → both, each condensed to ~700 tokens | Appendices 6, 7 |
| B6 | If the formula is uncatalogued: an explicit instruction that no canonical example exists and the model must rely on the rules alone | authored |

Random selection uses a per-request seed recorded in the database so any generation can be reproduced exactly.

### 4.4 Block C — user input (variable)

```
Жанр: <≤64 chars, optional>
Персонажи: <≤300 chars, optional>
Сеттинг / эпоха: <≤100 chars, optional>
Целевая аудитория: <young adult | взрослая | детская | не важно, optional>
Исходная ситуация (Ожидание пользователя): <≤500 chars, Mode 2 only>
```

Empty fields are omitted from the prompt entirely rather than sent as empty strings.

In Mode 2 the user's Expectation text is passed **verbatim** with an instruction that the Revelation must be built for *this* situation and the Expectation must not be rewritten — except in the override case of §6.2.5.

---

## 5. Claude API integration

### 5.1 Client

Official `anthropic` Python SDK. Single long-lived `AsyncAnthropic` client. API key from `ANTHROPIC_API_KEY`, never logged, never echoed to users.

### 5.2 Region constraint — mandatory

**Russia is not on Anthropic's supported-countries list.** The bot process must therefore run outside Russia (see §11). This is a terms-of-service condition, not a network problem, and must not be worked around with a proxy from a Russian host.

### 5.3 Generation call

```python
async with client.messages.stream(
    model="claude-opus-5",
    max_tokens=8000,
    system=[
        {"type": "text", "text": BLOCK_A},          # + cache_control when caching is on
        {"type": "text", "text": block_b},
    ],
    messages=[{"role": "user", "content": block_c}],
    thinking={"type": "adaptive"},
    output_config={"effort": settings.generation_effort},   # default "high"
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
) as stream:
    message = await stream.get_final_message()
```

Notes:
- `thinking.budget_tokens` is **rejected with a 400** on Opus 5 — adaptive only.
- Assistant prefill is **not supported** on Opus 5 — output shape is controlled by `a12_output_contract.md`.
- Streaming is used because `max_tokens` is large; `get_final_message()` returns the complete message.
- `fallbacks="default"` routes around safety refusals server-side. `stop_reason` is checked before reading content; `"refusal"` is surfaced to the user as a neutral "не удалось сгенерировать, попробуйте изменить формулировку" and logged with `stop_details.category`.

### 5.4 Analysis call (Mode 2)

One call, structured output, low effort — it is a classification task, not a creative one.

```python
message = await client.messages.create(
    model="claude-opus-5",
    max_tokens=4000,
    system=[{"type": "text", "text": BLOCK_A_CLASSIFIER}],   # a01–a06, a10 only
    messages=[{"role": "user", "content": user_situation}],
    thinking={"type": "adaptive"},
    output_config={"effort": "low", "format": EXPECTATION_ANALYSIS_SCHEMA},
)
```

`EXPECTATION_ANALYSIS_SCHEMA` (JSON Schema, `strict`-equivalent via `output_config.format`):

```jsonc
{
  "type": "object",
  "additionalProperties": false,
  "required": ["classifiable", "top_readings", "compatibility"],
  "properties": {
    "classifiable": { "type": "boolean" },
    "missing_information": {
      "type": "array", "items": { "type": "string" },
      "description": "Present only when classifiable is false: what the text must state"
    },
    "top_readings": {
      "type": "array", "minItems": 0, "maxItems": 2,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["change_type", "change_kind", "cause_1", "justification"],
        "properties": {
          "change_type": { "type": "integer", "minimum": 1, "maximum": 6 },
          "change_kind": { "type": "string", "enum": ["е", "и"] },
          "cause_1":     { "type": "string", "enum": ["Ф", "М", "Д", "К"] },
          "justification": { "type": "string", "maxLength": 600 }
        }
      }
    },
    "compatibility": {
      "type": "array", "minItems": 48, "maxItems": 48,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["change_type", "change_kind", "cause_1", "verdict"],
        "properties": {
          "change_type": { "type": "integer", "minimum": 1, "maximum": 6 },
          "change_kind": { "type": "string", "enum": ["е", "и"] },
          "cause_1":     { "type": "string", "enum": ["Ф", "М", "Д", "К"] },
          "verdict":     { "type": "string", "enum": ["ok", "conditional", "contradiction"] },
          "condition":   { "type": "string", "maxLength": 300 }
        }
      }
    }
  }
}
```

`compatibility` covers the full left half of formula space: 6 change types × 2 kinds × 4 first causes = **48 entries**. It is produced once per situation and cached in the dialog state — every subsequent button press is answered offline, with no further API calls.

`condition` is required when `verdict == "conditional"` and is injected into Block B on generation.

### 5.5 Prompt caching

Block A is byte-identical across all requests and is a natural cache prefix. However, at the launch traffic level (~17 free generations per day across all users) the gap between requests routinely exceeds the 5-minute TTL, so a cache write would be paid on nearly every request and almost never read back.

**Decision: caching is OFF by default** (`ANTHROPIC_PROMPT_CACHE=off`). Turn it on when sustained traffic exceeds roughly one generation per five minutes. The switch adds `cache_control: {"type": "ephemeral"}` to the last Block A system block; nothing else changes. `usage.cache_read_input_tokens` is logged from day one so the decision can be revisited against real data.

### 5.6 Cost accounting

Every call records `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` and a computed USD cost into `api_calls`. Pricing constants live in `core/costs.py`:

```
claude-opus-5:  input $5.00 / MTok   output $25.00 / MTok
cache write 1.25× input   cache read 0.10× input
```

Thinking tokens are billed as output and are already included in `output_tokens`.

### 5.7 Error handling

Most-specific-first exception chain, no broad catch:

| Exception | Behaviour |
|---|---|
| `NotFoundError` | log, generic apology, alert owner |
| `RateLimitError` | exponential backoff 2s/4s/8s, then "сервис перегружен, попробуйте через минуту" — **quota is not consumed** |
| `APIStatusError` (4xx) | log full body, generic apology, alert owner, quota not consumed |
| `APIStatusError` (5xx) / `APIConnectionError` | retry ×2, then apology, quota not consumed |
| `stop_reason == "refusal"` | neutral message, log category, quota not consumed |
| `stop_reason == "max_tokens"` | retry once with `max_tokens` × 1.5, then deliver truncated with a warning |

**Quota and paid units are decremented only after a successful, complete response.** A failed generation never costs the user anything.

---

## 6. Bot behaviour

### 6.1 Mode 1 — Formula-first

**Entry:** `/start` → «Собрать твист по формуле», or `/formula`.

**FSM:** `M1.ChangeType → M1.ChangeKind → M1.Cause1 → M1.Cause2 → M1.Card → M1.Options → M1.Generate → M1.Rate`

1. **Change type** — 6 inline buttons: `1 Место`, `2 Качество`, `3 Рост`, `4 Убыль`, `5 Возникновение`, `6 Исчезновение`.
2. **Change kind** — 2 buttons: `е Естественное`, `и Искусственное`, with a one-line reminder that the kind describes the situation *in the Expectation*.
3. **Cause 1 (Expectation)** — 4 buttons: `Ф Формальная`, `М Материальная`, `Д Действующая`, `К Конечная`.
4. **Cause 2 (Revelation)** — same 4 buttons. Each button is annotated with the paradox that choice produces, computed locally: `Ф · без парадокса`, `Д · Парадокс №2`, etc.
5. **Formula card** — the bot posts:
   - the formula, e.g. **`6и-ФК`**, decoded in words;
   - the paradox verdict and its explanation (§3.5);
   - **one randomly chosen** canonical example (Ожидание → Откровение), if catalogued;
   - **one randomly chosen** film or book reference with its analysis, if catalogued;
   - if there is no film/book reference: **«🎉 Ура, вы нашли малоисследованный твист»**;
   - if the formula is uncatalogued entirely: a note that canonical examples for this group are not yet written and generation will proceed from the rules alone.
6. **Optional inputs** — buttons `Добавить жанр`, `Добавить персонажей`, `Добавить сеттинг`, `Аудитория`, `Пропустить`. Each opens a text prompt with the limit stated; over-length input is rejected with the limit repeated, not silently truncated.
7. **`Сгенерировать`** — quota check → typing indicator → API call → result.
8. **Result** — 2 twists, each as `Ожидание / Откровение / Почему это работает по формуле`, followed by the rating keyboard.

**Uncatalogued vs unreferenced — three distinct states:**

| State | Condition | User sees |
|---|---|---|
| Full | example + ≥1 reference | example + reference |
| Unreferenced | example, no film/book | example + «🎉 Ура, вы нашли малоисследованный твист» |
| Uncatalogued | neither | notice that the group is not yet written up; generation proceeds from rules alone |

### 6.2 Mode 2 — Expectation-first

**Entry:** `/start` → «Начать с описания ситуации», or `/situation`.

**FSM:** `M2.Situation → M2.Analysis → M2.Readings → [M2.ManualType → M2.ManualKind → M2.ManualCause1] → M2.Cause2 → M2.Options → M2.Generate → M2.Rate`

#### 6.2.1 Situation input

Free text, ≤ 500 characters. Over-length is rejected with the limit restated.

#### 6.2.2 Analysis

One API call (§5.4). Costs ~$0.07. **Free, capped at 5 per user per day**, and it does not consume a generation.

If `classifiable == false`, the bot does not guess. It reports what is missing — who acts, what changes, whether the process reads as natural — and returns to `M2.Situation`. This does not count against the 5/day analysis cap.

#### 6.2.3 Readings

The bot presents the **two** `top_readings` as the left half of a formula, e.g. `1е-Ф[?]`, each with its justification quoted from the methodology's own logic. Buttons: `Вариант 1`, `Вариант 2`, `Выбрать самому`.

#### 6.2.4 Manual override — the compatibility map

The freedom in a formula is asymmetric, and the UI must reflect that:

- **`C2` (Revelation) is always free.** Any of the four causes yields a valid twist; only the paradox changes. No validation applies.
- **The left half (`N`, `K`, `C1`) is fixed by the Expectation text** and is not a matter of taste. The methodology's own rule — the kind of change is determined by the situation in the Expectation — makes an arbitrary left half factually wrong, not merely unusual.

`Выбрать самому` therefore opens a three-step picker (type → kind → cause 1) in which **every button carries a verdict marker read from the cached `compatibility` map**:

| Marker | `verdict` | Behaviour on selection |
|---|---|---|
| ✅ | `ok` | proceed to `M2.Cause2` |
| ⚠️ | `conditional` | show the `condition` text, ask to confirm; on confirm the condition is injected into Block B as a stated premise of the generation |
| ❌ | `contradiction` | do not proceed silently — see §6.2.5 |

At the type and kind steps the marker is the best verdict among that branch's children, so a branch is never shown as ✅ when nothing under it is.

All of this is answered from dialog state. **No additional API calls.**

#### 6.2.5 Handling a `contradiction` choice

The bot does not refuse, and does not generate nonsense. It explains — by quoting the methodology rule that is violated, not by asserting "нельзя" — and offers three ways forward:

1. **`Выбрать другой код`** — back to the picker.
2. **`Переписать Ожидание`** — back to `M2.Situation`, with a statement of what the text would need to contain for the chosen code to hold.
3. **`Сгенерировать всё равно`** — a formula cannot be forced onto a text, but the text can be adjusted to the formula. The generation prompt receives an explicit instruction to rewrite the user's Expectation **minimally** — changing exactly as much as the chosen code requires and no more. The response then carries a separate, clearly flagged block: the rewritten Expectation and a plain statement of what was changed and why.

Path 3 is the pedagogically valuable one: the user sees concretely which situation does and does not produce `1е-Д?`. The rewritten Expectation is stored in `generations.adapted_expectation` and marked `expectation_adapted = true`.

#### 6.2.6 Cause 2 and generation

Identical to Mode 1 steps 4–8, except that Block C carries the user's Expectation (original or adapted) and the generation instruction targets *that* situation.

### 6.3 Rating

After every result: inline keyboard `⭐1 … ⭐5` plus `💬 Комментарий`.

- Rating is optional; the generation is stored regardless.
- Re-rating is allowed — the latest value wins, and every change is appended to `rating_history`.
- Comment: free text, ≤ 500 characters, optional, editable.
- `🔁 Сгенерировать ещё` repeats the same formula and inputs with a new random seed. It consumes a unit and stores a **new** generation row; the previous one is kept.

### 6.4 Menu and commands

| Command | Purpose |
|---|---|
| `/start` | greeting, mode selection |
| `/formula` | Mode 1 |
| `/situation` | Mode 2 |
| `/methodology` | link to `https://kiloslov.ru` |
| `/limits` | remaining free generations today, paid balance |
| `/buy` | generation packs |
| `/help` | how the formula works, in four short paragraphs |
| `/cancel` | reset FSM |
| `/export` | **owner only**, hidden from the public command list |

All user-facing strings live in `bot/texts.py` as a single Russian copy deck. No literal user-facing text anywhere else in the codebase.

---

## 7. Quotas, budget and payments

### 7.1 Accounting unit

| Action | Units | Cost to owner |
|---|---|---|
| Generation by formula (2 twists) | 1 | ~$0.15 |
| Generation from Expectation (2 twists) | 2 | ~$0.25 |
| Situation analysis | 0 | ~$0.07 |

### 7.2 Free allowances, per user per day (UTC+3, reset at 00:00)

| Item | Limit |
|---|---|
| Generations by formula | 3 |
| Generations from Expectation | 1 |
| Situation analyses | 5 |

Worst case per user per day: ~$0.70. The owner's `user_id` is exempt from all user-level limits (but not from the emergency stop).

### 7.3 Global budget caps

| Cap | Value | Effect on breach |
|---|---|---|
| Daily free spend | **$4** | free generations disabled until 00:00, paid continue |
| Monthly free spend | **$100** | free generations disabled until the 1st, paid continue |
| Emergency stop (free + paid) | **$250 / month** | all generation disabled, owner alerted |

The daily cap smooths spikes; the monthly cap is the hard wall and binds first if every day runs hot. All three are configuration values, changeable without redeploy.

Caps are evaluated against **actual recorded USD spend** from `api_calls`, not against an estimate.

### 7.4 Payments — Telegram Stars

Telegram pays the developer approximately **$0.013 per Star**. Break-even is **12 ⭐ per unit**; packs are priced at 13–15 ⭐ per unit.

| Pack | Price | User pays | Owner nets | Cost | Margin |
|---|---|---|---|---|---|
| 10 units | **150 ⭐** | ~$3 | $1.95 | $1.50 | +$0.45 (23%) |
| 30 units | **420 ⭐** | ~$8.4 | $5.46 | $4.50 | +$0.96 (18%) |
| 100 units | **1300 ⭐** | ~$26 | $16.90 | $15.00 | +$1.90 (11%) |

Prices are configuration values. **Do not price below 15 ⭐ per unit:** Opus 5 thinking length varies and one heavy generation absorbs the margin of three ordinary ones.

Implementation: `send_invoice` with `currency="XTR"`, `provider_token=""`, handlers for `pre_checkout_query` (always approve unless the pack id is unknown) and `successful_payment` (credit units atomically, store `telegram_payment_charge_id`).

Policy: **no refunds**, stated in `/buy` and in the offer text. `refundStarPayment` is available for exceptional manual intervention by the owner.

Operational note: Stars withdrawal requires a **1000 ⭐ minimum** and each Star is held **21 days** from receipt.

### 7.5 Anti-abuse

- One in-flight generation per user, enforced by a per-user lock; a second press answers "генерация уже идёт".
- Per-user rate limit: 20 messages/minute (aiogram throttling middleware).
- New accounts (< 24 h since first `/start`) get 1 free generation instead of 3 for the first day.

---

## 8. Data model

PostgreSQL 16. SQLAlchemy 2.x ORM, Alembic migrations. All timestamps `timestamptz`, stored UTC.

```
users
  id                  bigserial pk
  telegram_id         bigint unique not null
  username            text
  first_name          text
  language_code       text
  is_owner            boolean default false
  is_blocked          boolean default false
  paid_units          integer default 0
  created_at          timestamptz
  last_seen_at        timestamptz

generations
  id                  bigserial pk
  user_id             bigint fk users
  mode                text            -- 'formula' | 'expectation'
  formula             text            -- '6и-ФК'
  change_type         smallint
  change_kind         char(1)
  cause_1             char(1)
  cause_2             char(1)
  paradox_1           boolean
  paradox_2           boolean
  catalogued          boolean         -- formula present in examples/*.yaml
  had_reference       boolean         -- a film/book reference was shown
  genre               text
  characters          text
  setting             text
  audience            text
  user_expectation    text            -- Mode 2, verbatim
  adapted_expectation text            -- Mode 2, set when the text was rewritten
  expectation_adapted boolean default false
  override_verdict    text            -- null | 'ok' | 'conditional' | 'contradiction'
  override_condition  text
  example_seed        integer         -- reproduces B3/B4 selection
  block_b             text            -- the assembled slice, verbatim
  response_text       text            -- full model output
  model               text
  effort              text
  units_charged       smallint
  was_free            boolean
  created_at          timestamptz

ratings
  id                  bigserial pk
  generation_id       bigint fk generations unique
  score               smallint check (score between 1 and 5)
  comment             text
  created_at          timestamptz
  updated_at          timestamptz

rating_history
  id                  bigserial pk
  generation_id       bigint fk generations
  score               smallint
  comment             text
  created_at          timestamptz

api_calls
  id                  bigserial pk
  generation_id       bigint fk generations null   -- null for analysis calls
  user_id             bigint fk users
  purpose             text            -- 'generation' | 'analysis'
  model               text
  effort              text
  input_tokens        integer
  output_tokens       integer
  cache_creation_input_tokens integer
  cache_read_input_tokens     integer
  cost_usd            numeric(10,6)
  latency_ms          integer
  stop_reason         text
  error               text
  created_at          timestamptz

payments
  id                  bigserial pk
  user_id             bigint fk users
  pack_id             text
  stars               integer
  units               integer
  telegram_payment_charge_id text unique
  created_at          timestamptz

daily_usage
  id                  bigserial pk
  user_id             bigint fk users
  usage_date          date
  formula_gens        integer default 0
  expectation_gens    integer default 0
  analyses            integer default 0
  unique (user_id, usage_date)

budget_ledger
  id                  bigserial pk
  period_date         date
  free_spend_usd      numeric(10,6)
  paid_spend_usd      numeric(10,6)
  unique (period_date)
```

Indexes: `generations(user_id, created_at desc)`, `generations(formula)`, `api_calls(created_at)`, `ratings(score)`.

### 8.1 Retention

No automatic deletion in v1.0. The bot stores user-authored text (situations, characters, comments); the `/help` text states plainly that generations and ratings are stored for methodology research.

---

## 9. Admin

`/export` — owner only, identified by `OWNER_TELEGRAM_ID`. Any other user gets the standard "неизвестная команда" response; the command is absent from the public command list.

Produces an XLSX with four sheets and sends it as a document:

| Sheet | Contents |
|---|---|
| `generations` | full join of `generations` + `ratings` + aggregated `api_calls` cost |
| `ratings` | score distribution by formula, by paradox class, by mode |
| `costs` | daily and monthly spend, tokens, average cost per generation, cache hit rate |
| `users` | per-user counts, paid units, first and last seen |

Optional arguments: `/export 2026-09-01 2026-09-30` to bound the period. Default: all data.

Additional owner commands: `/stats` (same figures as a short message), `/setlimit <key> <value>` (adjusts a runtime cap, written to the database and audited).

---

## 10. Architecture

```
Telegram  ──webhook──►  aiogram 3 app  ──►  PostgreSQL 16
                              │
                              └──► api.anthropic.com  (claude-opus-5)
```

Single process, `asyncio`, webhook mode behind nginx with a Let's Encrypt certificate. Long polling is available via config for local development.

### 10.1 Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Bot framework | aiogram 3.x |
| LLM SDK | `anthropic` (official) |
| Database | PostgreSQL 16, SQLAlchemy 2.x, asyncpg |
| Migrations | Alembic |
| Config | pydantic-settings |
| Export | openpyxl |
| Packaging | Docker + docker compose |
| Tests | pytest, pytest-asyncio |
| Lint/format | ruff, mypy |

### 10.2 Repository layout

```
bot/
  main.py                 entry point, dispatcher wiring
  config.py               pydantic settings
  texts.py                Russian copy deck — the only place with user-facing strings
  keyboards.py
  handlers/               start, mode_formula, mode_expectation, rating, payments, admin
  middlewares/            quota, antiflood, user_context
  fsm/states.py
core/
  formula.py              parse, validate, paradox rule
  catalog.py              YAML loader, random example selection
  prompt/builder.py       Block A/B/C assembly
  claude.py               API wrapper, retries, cost recording
  costs.py                pricing constants
  budget.py               caps
db/
  models.py  session.py
migrations/
methodology/
  source/twist_generator_v1.fb2
  core/a01_role.md … a12_output_contract.md
  tables/causes.md kinds.md change_codes.md causal_shifts.md matrix.md
  examples/1e.yaml 6i.yaml
  images/
scripts/
  import_fb2.py
  export_report.py
tests/
docs/SPEC.md
.env.example  Dockerfile  docker-compose.yml  pyproject.toml
```

---

## 11. Deployment

### 11.1 Hosting split

| Component | Host | Rationale |
|---|---|---|
| Methodology page, `kiloslov.ru` | **Timeweb, Optimo+** (shared hosting) | already owned; a static page is all it needs |
| Bot + PostgreSQL | **FirstByte KVM SSD, European location** (Amsterdam / Finland / Germany), ≥ 2 GB RAM | Russia is outside Anthropic's supported regions — see §5.2 |

Timeweb Optimo+ is shared hosting: no persistent background process, no Docker, no PostgreSQL. It cannot host the bot. FirstByte's Moscow KVM plan is technically capable but is in an unsupported region for the Anthropic API.

Latency added by the European location is 40–60 ms and is invisible to users, who connect to Telegram rather than to this server.

### 11.2 Runtime

Docker Compose: `bot` + `postgres` + `nginx`. Automatic restart, daily `pg_dump` to a local volume with 14-day rotation. Logs to stdout, collected by journald.

### 11.3 Configuration

`.env`, never committed; `.env.example` is committed with placeholder values.

```dotenv
BOT_TOKEN=                      # from @BotFather — set on the server only
ANTHROPIC_API_KEY=
OWNER_TELEGRAM_ID=
DATABASE_URL=postgresql+asyncpg://twist:...@postgres:5432/twist
WEBHOOK_BASE_URL=https://bot.example.org
WEBHOOK_SECRET=

METHODOLOGY_URL=https://kiloslov.ru

ANTHROPIC_MODEL=claude-opus-5
GENERATION_EFFORT=high
ANALYSIS_EFFORT=low
ANTHROPIC_PROMPT_CACHE=off

FREE_FORMULA_GENS_PER_DAY=3
FREE_EXPECTATION_GENS_PER_DAY=1
FREE_ANALYSES_PER_DAY=5
DAILY_FREE_BUDGET_USD=4
MONTHLY_FREE_BUDGET_USD=100
EMERGENCY_STOP_USD=250

PACK_SMALL_UNITS=10   PACK_SMALL_STARS=150
PACK_MEDIUM_UNITS=30  PACK_MEDIUM_STARS=420
PACK_LARGE_UNITS=100  PACK_LARGE_STARS=1300

MAX_GENRE_CHARS=64
MAX_CHARACTERS_CHARS=300
MAX_SETTING_CHARS=100
MAX_SITUATION_CHARS=500
MAX_COMMENT_CHARS=500
```

**The bot token and API key are never pasted into chat, an issue, or a commit.** They are set directly on the server.

---

## 12. Testing

### 12.1 Unit

- `formula.py`: parse and normalise all 192 codes, both separators, reject malformed input.
- Paradox rule: assert all 192 verdicts against a fixture transcribed from `img6.jpg`. This is the single most important test in the project.
- `catalog.py`: loading, random selection reproducibility by seed, all three catalogue states.
- Quota and budget arithmetic, including the daily reset boundary and the free/paid split.
- Prompt builder: Block A byte-stability, Block B correctness for each of the four paradox classes, omission of empty Block C fields.

### 12.2 Integration (mocked API)

Both FSM flows end to end with a stubbed Anthropic client: every branch of §6.2.4 and §6.2.5, rating, re-rating, regeneration, quota exhaustion, each error class of §5.7.

### 12.3 Live testing — stage 1, restricted to `1е` and `6и`

The only groups with complete appendices. Checklist, run against the real API:

1. All 12 `1е` formulas and all 12 `6и` formulas: card renders, paradox verdict matches the matrix, example and reference appear where the catalogue has them.
2. The 10 formulas listed in §3.3 with no film/book reference: the «малоисследованный твист» message fires, and the canonical example is still shown.
3. `1е-ФФ/ММ/ДД/КК` and `6и-ФФ/ММ/ДД/КК` — uncatalogued: generation proceeds, the notice appears, output still honours the formula.
4. Mode 2 with a deliberately natural situation, a deliberately artificial one, and a deliberately ambiguous one; verify the two readings differ meaningfully.
5. Mode 2 override: pick a ✅, a ⚠️ and a ❌ for the same situation; verify the ❌ path produces an adapted Expectation with an honest statement of the change.
6. Cost check: 20 real generations, compare recorded spend against the $0.15 / $0.25 estimate and adjust §7 if reality differs.

**Acceptance for stage 1:** the author reviews 20 generations across both groups and confirms each one is a correct realisation of its formula and paradox class.

---

## 13. Milestones

| # | Deliverable |
|---|---|
| 1 | FB2 import pipeline, table transcription, `examples/*.yaml` for `1е` and `6и`, formula and paradox modules with full unit tests |
| 2 | Block A core files assembled and reviewed by the author — the quality gate for everything downstream |
| 3 | Mode 1 end to end with a real API call, database writes, rating |
| 4 | Quotas, budget caps, cost logging, `/export` |
| 5 | Mode 2: analysis call, compatibility map, override and contradiction handling |
| 6 | Telegram Stars payments |
| 7 | Deployment to the European VPS, methodology page on `kiloslov.ru`, stage-1 acceptance testing |

Milestone 2 is the gate: if Block A is not right, nothing generated afterwards is trustworthy.

---

## 14. Open items

| # | Item | Owner | Blocks |
|---|---|---|---|
| 1 | Appendices 2–5 (remaining 164 formulas) | author | full formula coverage; the bot works without them |
| 2 | Final pack prices | author | milestone 6; defaults in §7.4 are usable as-is |
| 3 | Methodology page published at `kiloslov.ru` | author | milestone 7 |
| 4 | European VPS provisioned, token and key installed | author | milestone 7 |
| 5 | Genre reference list — free text in v1.0 | author | future version |
| 6 | Whether content-shift twists should be split for Growth/Decline (8 extra formulas → 192) | author | future methodology version |

---

## 15. Requirements traceability

| Original requirement | Spec section |
|---|---|
| Mandatory parameter selection, formula `1е-ФД` | §2.1, §6.1 |
| Example twist from the methodology | §3.3, §4.3 (B3), §6.1 |
| Film or book example | §3.3, §4.3 (B4), §6.1 |
| «Ура, вы нашли малоисследованный твист» | §6.1 |
| Paradox reporting — one, the other, or both | §3.4, §3.5, §6.1 |
| Optional genre and characters, length-limited | §4.4, §6.1 |
| «Сгенерировать» button → Claude → result | §5.3, §6.1 |
| Which Claude account | §5.1, §5.2, §11.1 |
| 5-point rating | §6.3 |
| Twist and rating stored in a private database | §8, §9 |
| Methodology reachable from the bot menu | §6.4 |
| Stage-1 testing limited to `1е` and `6и` | §1.3, §12.3 |
