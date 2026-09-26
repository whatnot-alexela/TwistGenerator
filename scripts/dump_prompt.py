#!/usr/bin/env python3
"""Write out the assembled prompt for reading.

    python scripts/dump_prompt.py --out /tmp/prompts

Produces one file per profile containing the core exactly as the model receives
it, plus the two paradox appendices, with a header listing each block and its
size. Nothing here feeds the bot — it exists so the author can read what is
actually being sent, rather than inferring it from fourteen separate files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.prompt.builder import SUPPLEMENTS, Profile, PromptBuilder  # noqa: E402

RULE = "=" * 78


def dump(profile: Profile, out_dir: Path) -> Path:
    builder = PromptBuilder(profile)
    core = builder.build_core()

    lines = [
        RULE,
        f"МЕТОДИКА В ПРОМПТЕ — профиль «{profile.value}»",
        RULE,
        "",
        "Это текст, который получает модель на каждом запросе, до среза по",
        "формуле и до пользовательского ввода. Собран автоматически из",
        "methodology/ — читать здесь, править в исходных файлах.",
        "",
        "Состав:",
        "",
    ]
    for block in core.blocks:
        lines.append(f"  {block.name:<28} {block.tokens:>6} токенов   {block.purpose}")
    lines.append(f"  {'ИТОГО ЯДРО':<28} {core.tokens:>6} токенов")
    lines.append("")
    lines.append("Приложения — едут не всегда, а только когда в формуле есть")
    lines.append("соответствующий парадокс:")
    lines.append("")
    for key, spec in SUPPLEMENTS.items():
        block = builder.build_supplement(key)
        label = "Парадокс №1" if key == "paradox_1" else "Парадокс №2"
        lines.append(f"  {spec.name:<28} {block.tokens:>6} токенов   {label}")
    lines.append("")

    for index, block in enumerate(core.blocks, start=1):
        lines += [
            "",
            RULE,
            f"БЛОК {index}/{len(core.blocks)} — {block.name}   ({block.tokens} токенов)",
            f"{block.purpose}",
            RULE,
            "",
            block.text,
        ]

    for key, spec in SUPPLEMENTS.items():
        block = builder.build_supplement(key)
        label = "Парадокс №1" if key == "paradox_1" else "Парадокс №2"
        lines += [
            "",
            RULE,
            f"ПРИЛОЖЕНИЕ — {spec.name}   ({block.tokens} токенов)",
            f"Отправляется только для формул, где есть {label}",
            RULE,
            "",
            block.text,
        ]

    path = out_dir / f"methodology_{profile.value}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("."))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for profile in Profile:
        path = dump(profile, args.out)
        size = len(path.read_text(encoding="utf-8"))
        print(f"{path}  ({size:,} знаков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
