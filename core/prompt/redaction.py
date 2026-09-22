"""Applying the author's redactions to the imported methodology blocks.

The importer keeps the source verbatim. Everything the prompt must *not* carry
is declared in ``methodology/redactions.yaml`` and applied here, so that every
departure from the author's own words is visible in one small file and can be
undone by deleting a line.

A redaction that no longer matches its block is a hard error. Silently skipping
it would mean shipping text the author asked to remove.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

DEFAULT_REDACTIONS: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent / "methodology" / "redactions.yaml"
)


class RedactionError(Exception):
    """Raised when a redaction cannot be applied. Always fatal."""


@dataclass(frozen=True, slots=True)
class Redaction:
    block: str
    reason: str
    action: str  # "remove" | "replace"
    text: str
    replacement: str | None = None

    def apply(self, body: str) -> str:
        """Apply this redaction to a block body, whitespace-insensitively.

        The imported blocks wrap differently from the YAML, so matching is done
        on a whitespace-normalised view and the span is then cut from the
        original text.
        """
        pattern = re.compile(r"\s+".join(re.escape(word) for word in self.text.split()))
        matches = list(pattern.finditer(body))
        if not matches:
            raise RedactionError(
                f"{self.block}: redacted passage not found — the source text has "
                f"changed. Update or delete this entry in redactions.yaml.\n"
                f"  looking for: {self.text[:120]}…"
            )
        if len(matches) > 1:
            raise RedactionError(
                f"{self.block}: redacted passage matches {len(matches)} times; "
                f"it must identify exactly one passage."
            )

        match = matches[0]
        if self.action == "remove":
            cut = body[: match.start()] + body[match.end() :]
            return re.sub(r"[ \t]{2,}", " ", cut).replace(" \n", "\n")
        if self.action == "replace":
            if self.replacement is None:
                raise RedactionError(f"{self.block}: 'replace' needs a 'with' value")
            return body[: match.start()] + self.replacement + body[match.end() :]
        raise RedactionError(f"{self.block}: unknown action {self.action!r}")


def _require(item: dict[str, Any], key: str, index: int) -> Any:
    if key not in item:
        raise RedactionError(f"redactions.yaml[{index}]: missing required key {key!r}")
    return item[key]


def load_redactions(path: Path | None = None) -> list[Redaction]:
    path = path or DEFAULT_REDACTIONS
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(document, list):
        raise RedactionError(f"{path.name}: expected a list of redactions")

    redactions: list[Redaction] = []
    for index, item in enumerate(document):
        if not isinstance(item, dict):
            raise RedactionError(f"{path.name}[{index}]: expected a mapping")
        action = str(_require(item, "action", index))
        if action not in ("remove", "replace"):
            raise RedactionError(f"{path.name}[{index}]: unknown action {action!r}")
        redactions.append(
            Redaction(
                block=str(_require(item, "block", index)),
                reason=str(_require(item, "reason", index)),
                action=action,
                text=" ".join(str(_require(item, "text", index)).split()),
                replacement=(" ".join(str(item["with"]).split()) if "with" in item else None),
            )
        )
    return redactions


def apply_redactions(block: str, body: str, redactions: list[Redaction]) -> str:
    """Apply every redaction declared for this block, in file order."""
    for redaction in redactions:
        if redaction.block == block:
            body = redaction.apply(body)
    return body
