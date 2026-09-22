"""Tests for prompt assembly and the redaction layer.

The redaction layer is the only place where the prompt departs from the
author's own words, so the tests here are mostly about it failing loudly rather
than quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.prompt.builder import (
    CORE_MANIFEST,
    SUPPLEMENTS,
    Block,
    Profile,
    PromptBuilder,
    PromptError,
    estimate_tokens,
    strip_front_matter,
)
from core.prompt.redaction import (
    Redaction,
    RedactionError,
    apply_redactions,
    load_redactions,
)

METHODOLOGY = Path(__file__).resolve().parent.parent / "methodology"


@pytest.fixture(scope="module")
def full() -> str:
    return PromptBuilder(Profile.FULL).build_core().text


@pytest.fixture(scope="module")
def condensed() -> str:
    return PromptBuilder(Profile.CONDENSED).build_core().text


# --------------------------------------------------------------------------- #
# The two profiles
# --------------------------------------------------------------------------- #


def test_full_is_the_default() -> None:
    """The author chose the unabridged core; condensed exists to be compared."""
    assert PromptBuilder().profile is Profile.FULL


def test_the_hedges_are_gone_from_both_profiles(full: str, condensed: str) -> None:
    """Removing the author's doubts about his own system is unconditional —
    it is not what the profiles differ by."""
    for text in (full, condensed):
        assert "галлюцинац" not in text


def test_condensed_is_materially_smaller() -> None:
    full_core = PromptBuilder(Profile.FULL).build_core()
    condensed_core = PromptBuilder(Profile.CONDENSED).build_core()
    assert condensed_core.tokens < full_core.tokens
    # §10 is the only condensable block in the core, so the saving is modest
    # there; the appendices are where it tells (see the supplement test below).
    assert full_core.tokens - condensed_core.tokens > 1000


def test_condensed_supplements_are_much_smaller() -> None:
    for paradox in SUPPLEMENTS:
        verbose = PromptBuilder(Profile.FULL).build_supplement(paradox).tokens
        brief = PromptBuilder(Profile.CONDENSED).build_supplement(paradox).tokens
        assert brief < verbose / 2, paradox


def test_condensed_blocks_are_marked_as_such() -> None:
    core = PromptBuilder(Profile.CONDENSED).build_core()
    condensed_blocks = {block.name for block in core.blocks if block.condensed}
    assert condensed_blocks == {"a09_paradox_mechanics"}
    assert not any(block.condensed for block in PromptBuilder(Profile.FULL).build_core().blocks)


def test_a_missing_condensed_variant_is_a_clear_error(tmp_path: Path) -> None:
    """Rather than silently falling back to the full text."""
    (tmp_path / "redactions.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "core").mkdir()
    for spec in CORE_MANIFEST:
        for source in spec.sources:
            path = tmp_path / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("текст", encoding="utf-8")
    with pytest.raises(PromptError, match="needs core/a09_paradox_mechanics.condensed.md"):
        PromptBuilder(Profile.CONDENSED, methodology_dir=tmp_path).build_core()


def test_no_operative_section_is_missing(full: str, condensed: str) -> None:
    """Even condensed, every section of the methodology is represented."""
    for marker in (
        "Изменение №1",  # §1
        "Формальная причина",  # §2
        "Необходимое",  # §3, the triad the author asked to restore
        "Естественные изменения",  # §4
        "Ожидание",  # §5
        "каузальных сдвигов",  # §6
        "Парадокс",  # §8, §9, §11
        "онтологическ",  # §10
    ):
        assert marker in condensed, marker
        assert marker in full, marker


def test_the_triad_is_in_the_core(condensed: str) -> None:
    """Restored on the author's instruction after being excluded at first."""
    assert any(block.name == "a04_triad" for block in CORE_MANIFEST)
    assert "Возможное" in condensed


@pytest.mark.parametrize("profile", list(Profile))
def test_core_size_is_within_the_documented_budget(profile: Profile) -> None:
    core = PromptBuilder(profile).build_core()
    assert 14_000 < core.tokens < 20_000, core.report()


def test_every_manifest_block_contributes_text() -> None:
    builder = PromptBuilder()
    for spec in CORE_MANIFEST:
        block = builder.build_block(spec)
        assert block.text.strip(), spec.name
        assert block.tokens > 100, spec.name


def test_blocks_appear_in_manifest_order() -> None:
    core = PromptBuilder().build_core()
    assert [block.name for block in core.blocks] == [spec.name for spec in CORE_MANIFEST]


def test_role_comes_first_and_the_contract_last() -> None:
    core = PromptBuilder().build_core()
    assert core.blocks[0].name == "a01_role"
    assert core.blocks[-1].name == "a10_output_contract"


def test_tables_are_folded_into_their_sections(condensed: str) -> None:
    """The reference tables exist only as images in the source; the hand
    transcriptions must actually reach the prompt."""
    assert "Модус Бытия" in condensed  # tables/causes.md
    assert "Думали, что" in condensed  # tables/causal_shifts.md
    assert "Kinēsis" in condensed  # tables/change_codes.md


def test_front_matter_never_reaches_the_model(full: str, condensed: str) -> None:
    for text in (full, condensed):
        assert "source_section:" not in text
        assert "frozen:" not in text
        assert not text.startswith("---")


# --------------------------------------------------------------------------- #
# Supplements
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("paradox", sorted(SUPPLEMENTS))
@pytest.mark.parametrize("profile", list(Profile))
def test_supplements_build(paradox: str, profile: Profile) -> None:
    block: Block = PromptBuilder(profile).build_supplement(paradox)
    assert block.tokens > 800


def test_supplements_are_not_part_of_the_core(condensed: str) -> None:
    """They ride in the per-formula slice, only when the formula needs them."""
    appendix7 = PromptBuilder().build_supplement("paradox_2").text
    assert appendix7 not in condensed


def test_unknown_supplement_is_an_error() -> None:
    with pytest.raises(PromptError, match="no supplement"):
        PromptBuilder().build_supplement("paradox_3")


# --------------------------------------------------------------------------- #
# Failing loudly
# --------------------------------------------------------------------------- #


def test_verify_checks_both_profiles() -> None:
    """A missing condensed variant would otherwise hide until someone switched."""
    PromptBuilder().verify()


def test_missing_methodology_directory_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="not found"):
        PromptBuilder(methodology_dir=tmp_path / "nowhere")


def test_missing_block_file_is_fatal(tmp_path: Path) -> None:
    (tmp_path / "redactions.yaml").write_text("[]", encoding="utf-8")
    with pytest.raises(PromptError, match="missing methodology file"):
        PromptBuilder(methodology_dir=tmp_path).build_core()


def test_a_redaction_that_no_longer_matches_is_fatal() -> None:
    stale = Redaction(
        block="a02_six_arenas",
        reason="test",
        action="remove",
        text="этого предложения в книге нет и никогда не было",
    )
    with pytest.raises(RedactionError, match="not found"):
        apply_redactions("a02_six_arenas", "любой текст", [stale])


def test_an_ambiguous_redaction_is_fatal() -> None:
    ambiguous = Redaction(block="b", reason="test", action="remove", text="повтор")
    with pytest.raises(RedactionError, match="matches 2 times"):
        apply_redactions("b", "повтор и ещё раз повтор", [ambiguous])


def test_replace_without_a_replacement_is_fatal() -> None:
    broken = Redaction(block="b", reason="test", action="replace", text="цель")
    with pytest.raises(RedactionError, match="needs a 'with' value"):
        apply_redactions("b", "цель", [broken])


def test_unknown_action_is_rejected_at_load(tmp_path: Path) -> None:
    (tmp_path / "r.yaml").write_text(
        "- block: b\n  reason: r\n  action: obliterate\n  text: t\n", encoding="utf-8"
    )
    with pytest.raises(RedactionError, match="unknown action"):
        load_redactions(tmp_path / "r.yaml")


def test_missing_key_is_rejected_at_load(tmp_path: Path) -> None:
    (tmp_path / "r.yaml").write_text("- block: b\n  action: remove\n", encoding="utf-8")
    with pytest.raises(RedactionError, match="missing required key 'reason'"):
        load_redactions(tmp_path / "r.yaml")


# --------------------------------------------------------------------------- #
# Redaction mechanics
# --------------------------------------------------------------------------- #


def test_matching_ignores_how_the_text_is_wrapped() -> None:
    """The YAML wraps differently from the imported blocks; both must match."""
    redaction = Redaction(block="b", reason="test", action="remove", text="длинная фраза из книги")
    wrapped = "До.  Длинная\nфраза   из\nкниги. После."
    assert "фраза" not in apply_redactions("b", wrapped.replace("Д", "д"), [redaction])


def test_replace_keeps_the_surrounding_text() -> None:
    redaction = Redaction(
        block="b",
        reason="test",
        action="replace",
        text="возможно, в силу галлюцинаций ИИ, рассматриваются 40 формул",
        replacement="рассматриваются 40 формул",
    )
    body = "Итог: возможно, в силу галлюцинаций ИИ, рассматриваются 40 формул. Конец."
    result = apply_redactions("b", body, [redaction])
    assert result == "Итог: рассматриваются 40 формул. Конец."


def test_redactions_only_touch_their_own_block() -> None:
    redaction = Redaction(block="other", reason="test", action="remove", text="текст")
    assert apply_redactions("mine", "текст остаётся", [redaction]) == "текст остаётся"


def test_the_committed_redactions_all_apply() -> None:
    """Every entry in redactions.yaml must match its block exactly once."""
    redactions = load_redactions(METHODOLOGY / "redactions.yaml")
    assert redactions, "expected at least one redaction"
    builder = PromptBuilder(Profile.FULL)
    for redaction in redactions:
        block = next(
            spec
            for spec in CORE_MANIFEST
            if any(Path(source).stem == redaction.block for source in spec.sources)
        )
        assert builder.build_block(block).text  # raises if the redaction fails


def test_every_redaction_states_a_reason() -> None:
    for redaction in load_redactions(METHODOLOGY / "redactions.yaml"):
        assert len(redaction.reason) > 30, redaction.block


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def test_strip_front_matter() -> None:
    assert strip_front_matter("---\nfrozen: true\n---\n\n# Заголовок\n") == "# Заголовок"
    assert strip_front_matter("# Без метаданных") == "# Без метаданных"
    assert strip_front_matter("---\nнезакрытый блок") == "---\nнезакрытый блок"


def test_estimate_tokens_is_in_the_right_order_of_magnitude() -> None:
    assert estimate_tokens("a" * 2600) == 1000
    assert estimate_tokens("") == 0
