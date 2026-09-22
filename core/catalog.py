"""The example catalogue: canonical twists and their film and book references.

Loaded from ``methodology/examples/*.yaml``, which ``scripts/import_fb2.py``
generates from the methodology's appendices. Only the groups whose appendix the
author has finished are present — today ``1е`` and ``6и``. Everything else is
*uncatalogued*, which is a legitimate state and not an error: the bot still
generates for those formulas, from the rules alone.

See docs/SPEC.md §3.3 and §6.1.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

import yaml

from core.formula import CHANGE_KINDS, CHANGE_TYPES, Formula, FormulaError

DEFAULT_EXAMPLES_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "methodology" / "examples"
)


class CatalogError(Exception):
    """Raised when a catalogue file is malformed. Always fatal at startup."""


class Coverage(Enum):
    """How well the methodology covers a formula.

    ``UNREFERENCED`` is the state that earns the user the "малоисследованный
    твист" message: the methodology has a worked example but found no film or
    book realising it.
    """

    FULL = "full"
    UNREFERENCED = "unreferenced"
    UNCATALOGUED = "uncatalogued"


@dataclass(frozen=True, slots=True)
class Example:
    expectation: str
    revelation: str


@dataclass(frozen=True, slots=True)
class Reference:
    kind: str  # "film" | "book"
    title: str
    credit: str | None
    year: int | None
    analysis: str
    note: str | None

    @property
    def label(self) -> str:
        """``Фильм «Шоу Трумана» (The Truman Show, 1998)`` — for the formula card."""
        word = "Фильм" if self.kind == "film" else "Книга"
        meta = ", ".join(
            part for part in (self.credit, str(self.year) if self.year else None) if part
        )
        return f"{word} «{self.title}»" + (f" ({meta})" if meta else "")


@dataclass(frozen=True, slots=True)
class Entry:
    """Everything the methodology has to say about one formula."""

    code: str
    examples: tuple[Example, ...]
    references: tuple[Reference, ...]

    @property
    def coverage(self) -> Coverage:
        if self.references:
            return Coverage.FULL
        return Coverage.UNREFERENCED


@dataclass(frozen=True, slots=True)
class Slice:
    """The catalogue material selected for one generation.

    ``seed`` is recorded alongside the generation so the same slice can be
    rebuilt later from the same catalogue.
    """

    formula: Formula
    coverage: Coverage
    example: Example | None
    reference: Reference | None
    seed: int


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise CatalogError(f"{where}: missing required key {key!r}")
    return mapping[key]


class Catalog:
    """An immutable, in-memory view of the example catalogue."""

    def __init__(self, entries: dict[str, Entry]) -> None:
        self._entries = entries

    # -- loading ------------------------------------------------------------ #

    @classmethod
    def load(cls, directory: Path | None = None) -> Catalog:
        directory = directory or DEFAULT_EXAMPLES_DIR
        if not directory.is_dir():
            raise CatalogError(f"catalogue directory not found: {directory}")

        entries: dict[str, Entry] = {}
        for path in sorted(directory.glob("*.yaml")):
            for entry in cls._read_file(path):
                if entry.code in entries:
                    raise CatalogError(f"{path.name}: duplicate formula {entry.code}")
                entries[entry.code] = entry
        return cls(entries)

    @staticmethod
    def _read_file(path: Path) -> list[Entry]:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CatalogError(f"{path.name}: invalid YAML: {exc}") from exc
        if not isinstance(document, dict):
            raise CatalogError(f"{path.name}: expected a mapping at the top level")

        group = str(_require(document, "group", path.name))
        change_type = _require(document, "change_type", path.name)
        change_kind = str(_require(document, "change_kind", path.name))
        if change_type not in CHANGE_TYPES or change_kind not in CHANGE_KINDS:
            raise CatalogError(f"{path.name}: bad group header {group!r}")

        raw_formulas = _require(document, "formulas", path.name)
        if not isinstance(raw_formulas, list):
            raise CatalogError(f"{path.name}: 'formulas' must be a list")

        entries: list[Entry] = []
        for index, raw in enumerate(raw_formulas):
            where = f"{path.name}[{index}]"
            if not isinstance(raw, dict):
                raise CatalogError(f"{where}: expected a mapping")
            try:
                formula = Formula.parse(str(_require(raw, "code", where)))
            except FormulaError as exc:
                raise CatalogError(f"{where}: {exc}") from exc
            if formula.group != group:
                raise CatalogError(
                    f"{where}: formula {formula.code} does not belong to group {group!r}"
                )
            entries.append(
                Entry(
                    code=formula.code,
                    examples=tuple(
                        Example(
                            expectation=str(_require(item, "expectation", where)),
                            revelation=str(_require(item, "revelation", where)),
                        )
                        for item in raw.get("examples") or []
                    ),
                    references=tuple(
                        Reference(
                            kind=str(_require(item, "kind", where)),
                            title=str(_require(item, "title", where)),
                            credit=item.get("credit"),
                            year=item.get("year"),
                            analysis=str(_require(item, "analysis", where)),
                            note=item.get("note"),
                        )
                        for item in raw.get("references") or []
                    ),
                )
            )
        return entries

    # -- lookup ------------------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, formula: Formula | str) -> bool:
        return self._key(formula) in self._entries

    def get(self, formula: Formula | str) -> Entry | None:
        return self._entries.get(self._key(formula))

    def coverage(self, formula: Formula | str) -> Coverage:
        entry = self.get(formula)
        return entry.coverage if entry else Coverage.UNCATALOGUED

    def groups(self) -> set[str]:
        """The change codes the catalogue covers, e.g. ``{"1е", "6и"}``."""
        return {code[:2] for code in self._entries}

    def unreferenced(self) -> list[str]:
        """Formulas with a worked example but no film or book, in catalogue order."""
        return [code for code, entry in self._entries.items() if not entry.references]

    @staticmethod
    def _key(formula: Formula | str) -> str:
        return formula.code if isinstance(formula, Formula) else Formula.parse(formula).code

    # -- selection ---------------------------------------------------------- #

    def build_slice(self, formula: Formula, seed: int | None = None) -> Slice:
        """Pick one example and one reference for this formula.

        The methodology often gives several variants; the bot shows one of each,
        chosen at random so repeat visits to the same formula stay interesting.
        The seed is returned so the choice can be reproduced exactly.
        """
        if seed is None:
            seed = random.randrange(2**31)
        rng = random.Random(seed)
        entry = self.get(formula)
        if entry is None:
            return Slice(
                formula=formula,
                coverage=Coverage.UNCATALOGUED,
                example=None,
                reference=None,
                seed=seed,
            )
        return Slice(
            formula=formula,
            coverage=entry.coverage,
            example=rng.choice(entry.examples) if entry.examples else None,
            reference=rng.choice(entry.references) if entry.references else None,
            seed=seed,
        )
