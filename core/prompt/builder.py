"""Assembling the prompt: the methodology core, plus the tables it refers to.

The core is the constant part of every request — the rules, with nothing
formula-specific in it. A *profile* selects how much of the methodology's prose
it carries:

* ``full``      — every operative section at its full length. The default.
* ``condensed`` — the same manifest, but the long discursive blocks are taken
                  from a hand-written ``.condensed.md`` variant instead.

Keeping both makes "does condensing cost quality?" answerable by experiment —
run the same formulas through each and compare — rather than by argument.

Independently of the profile, the passages listed in
``methodology/redactions.yaml`` are always removed: these are the author's
asides doubting his own system, and fed them the model hedges where it should
be constructing a twist.

See docs/SPEC.md §4.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from core.prompt.redaction import Redaction, apply_redactions, load_redactions

METHODOLOGY_DIR: Final[Path] = Path(__file__).resolve().parent.parent.parent / "methodology"

#: Front matter is metadata for us, never for the model.
_FRONT_MATTER: Final[str] = "---"


class Profile(Enum):
    """How much of the methodology's prose the core carries."""

    #: Every operative section at full length. The default.
    FULL = "full"
    #: Discursive blocks replaced by their hand-written condensed variants.
    CONDENSED = "condensed"


class PromptError(Exception):
    """Raised when the core cannot be assembled. Always fatal at startup."""


@dataclass(frozen=True, slots=True)
class BlockSpec:
    """One piece of the core, and where its text comes from."""

    name: str
    #: Files under ``methodology/``, concatenated in order. A block can draw on
    #: several, which is how a section of the book and a table transcribed from
    #: one of its images end up next to each other.
    sources: tuple[str, ...]
    #: What this block is for, in one line. Never sent to the model.
    purpose: str
    #: Whether a ``.condensed.md`` variant replaces it under that profile.
    condensable: bool = False


#: The core, in the order the model reads it. Numbering follows docs/SPEC.md §4.2.
CORE_MANIFEST: Final[tuple[BlockSpec, ...]] = (
    BlockSpec(
        name="a01_role",
        sources=("core/a01_role.md",),
        purpose="System role: work strictly inside the methodology",
    ),
    BlockSpec(
        name="a02_six_arenas",
        sources=("core/a02_six_arenas.md", "tables/change_codes.md"),
        purpose="§1 — the six arenas of change, and the 12 change codes",
    ),
    BlockSpec(
        name="a03_four_causes",
        sources=("core/a03_four_causes.md", "tables/causes.md"),
        purpose="§2 — the four Aristotelian causes",
    ),
    BlockSpec(
        name="a04_triad",
        sources=("core/a04_triad.md",),
        purpose="§3 — the Necessary / Possible / Actual triad",
    ),
    BlockSpec(
        name="a05_natural_artificial",
        sources=("core/a05_natural_artificial.md", "tables/kinds.md"),
        purpose="§4 — natural vs artificial, and the rule that the kind is read "
        "from the Expectation",
    ),
    BlockSpec(
        name="a06_expectation_revelation",
        sources=("core/a06_expectation_revelation.md",),
        purpose="§5 — the Expectation → Revelation dynamic",
    ),
    BlockSpec(
        name="a07_formula_structure",
        sources=("core/a07_formula_structure.md", "tables/causal_shifts.md"),
        purpose="§6 — formula structure, complex causality, the ФК/КФ difficulty, "
        "content shifts, and the 12 causal shifts",
    ),
    BlockSpec(
        name="a08_paradox_rules",
        sources=(
            "core/a08_paradox_rules.part1.md",
            "core/a08_paradox_rules.part2.md",
            "core/a08_paradox_rules.part3.md",
        ),
        purpose="§8, §9, §11 — what the two paradoxes are and when they combine",
    ),
    BlockSpec(
        name="a09_paradox_mechanics",
        sources=("core/a09_paradox_mechanics.md",),
        purpose="§10 — how the two paradox classes differ, and how to write each",
        condensable=True,
    ),
    BlockSpec(
        name="a10_output_contract",
        sources=("core/a10_output_contract.md",),
        purpose="Output format: two twists, Russian, three parts each",
    ),
)

#: Paradox-class supplements. Not part of the core — the slice carries the one
#: that matches the formula's paradoxes (docs/SPEC.md §4.3, B5).
SUPPLEMENTS: Final[dict[str, BlockSpec]] = {
    "paradox_1": BlockSpec(
        name="b01_appendix6",
        sources=("core/b01_appendix6.md",),
        purpose="Appendix 6 — why paradox №1 arises and how it reads",
        condensable=True,
    ),
    "paradox_2": BlockSpec(
        name="b02_appendix7",
        sources=("core/b02_appendix7.md",),
        purpose="Appendix 7 — the natural↔artificial shift behind paradox №2",
        condensable=True,
    ),
}


def strip_front_matter(text: str) -> str:
    """Drop the leading ``---`` block. It is our bookkeeping, not content."""
    if not text.startswith(_FRONT_MATTER):
        return text.strip()
    end = text.find(f"\n{_FRONT_MATTER}", len(_FRONT_MATTER))
    if end == -1:
        return text.strip()
    return text[end + len(_FRONT_MATTER) + 1 :].strip()


def estimate_tokens(text: str) -> int:
    """Rough token count for Russian prose — about 2.6 characters per token.

    Good enough for budgeting and for the cost figures in docs/SPEC.md §4.1.
    The real count comes from ``usage`` on the response and is what gets logged.
    """
    return round(len(text) / 2.6)


@dataclass(frozen=True, slots=True)
class Block:
    """An assembled block, ready to be concatenated into the core."""

    name: str
    purpose: str
    text: str
    condensed: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass(frozen=True, slots=True)
class Core:
    """The constant part of every prompt."""

    profile: Profile
    blocks: tuple[Block, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def report(self) -> str:
        """A per-block breakdown, for eyeballing the budget."""
        lines = [f"profile: {self.profile.value}"]
        for block in self.blocks:
            mark = " (condensed)" if block.condensed else ""
            lines.append(f"  {block.name:<28} {block.tokens:>6} tok{mark}   {block.purpose}")
        lines.append(f"  {'TOTAL':<28} {self.tokens:>6} tok")
        return "\n".join(lines)


class PromptBuilder:
    """Reads the methodology from disk and assembles prompt pieces."""

    def __init__(
        self,
        profile: Profile = Profile.FULL,
        methodology_dir: Path | None = None,
        redactions: list[Redaction] | None = None,
    ) -> None:
        self.profile = profile
        self.dir = methodology_dir or METHODOLOGY_DIR
        if not self.dir.is_dir():
            raise PromptError(f"methodology directory not found: {self.dir}")
        self.redactions = (
            redactions if redactions is not None else load_redactions(self.dir / "redactions.yaml")
        )

    # -- one block ---------------------------------------------------------- #

    def build_block(self, spec: BlockSpec) -> Block:
        parts: list[str] = []
        condensed = False
        for source in spec.sources:
            path = self._resolve(source, spec)
            condensed = condensed or path.name.endswith(".condensed.md")
            body = strip_front_matter(path.read_text(encoding="utf-8"))
            # Keyed on the file stem, so a redaction targets the verbatim file
            # and never a condensed variant, which is written without the hedge
            # in the first place.
            parts.append(apply_redactions(path.stem, body, self.redactions))
        return Block(
            name=spec.name,
            purpose=spec.purpose,
            text="\n\n".join(parts),
            condensed=condensed,
        )

    def _resolve(self, source: str, spec: BlockSpec) -> Path:
        path = self.dir / source
        if self.profile is Profile.CONDENSED and spec.condensable:
            variant = path.with_suffix("").with_suffix(".condensed.md")
            if not variant.exists():
                raise PromptError(
                    f"profile 'condensed' needs {variant.relative_to(self.dir)}, which does "
                    f"not exist. Write the condensed variant, or use profile 'full'."
                )
            return variant
        if not path.exists():
            raise PromptError(f"missing methodology file: {source}")
        return path

    # -- the whole core ----------------------------------------------------- #

    def build_core(self) -> Core:
        return Core(
            profile=self.profile,
            blocks=tuple(self.build_block(spec) for spec in CORE_MANIFEST),
        )

    def build_supplement(self, paradox: str) -> Block:
        """The appendix that explains one paradox class."""
        spec = SUPPLEMENTS.get(paradox)
        if spec is None:
            raise PromptError(f"no supplement for {paradox!r}")
        return self.build_block(spec)

    def verify(self) -> None:
        """Assemble every profile once, so a broken file or a stale redaction
        fails at startup rather than on the first generation."""
        for profile in Profile:
            builder = PromptBuilder(profile, self.dir, self.redactions)
            builder.build_core()
            for paradox in SUPPLEMENTS:
                builder.build_supplement(paradox)
