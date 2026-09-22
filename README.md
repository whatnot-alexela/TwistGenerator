# TwistGenerator

Telegram bot that generates plot twists strictly according to the **Twist Generator 1.0**
methodology — 188 twist formulas built on Aristotle's four causes and six types of change.

Bot: [@twist_generator](https://t.me/twist_generator) · Methodology: https://kiloslov.ru

## Status

Specification approved. Implementation not started.

- **[docs/SPEC.md](docs/SPEC.md)** — full technical specification
- `methodology/source/` — the methodology source (FB2)

## Formula notation

```
<change type 1-6><kind е|и>-<cause in Expectation><cause in Revelation>
                                    e.g.  1е-ФД,  6и-КМ
```

Change types: 1 Место · 2 Качество · 3 Рост · 4 Убыль · 5 Возникновение · 6 Исчезновение
Kinds: е естественное · и искусственное
Causes: Ф Формальная · М Материальная · Д Действующая · К Конечная

Stage 1 works against the two groups whose example appendices are complete: `1е` and `6и`.
