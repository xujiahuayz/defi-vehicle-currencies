from pathlib import Path

import pytest

from scripts.research_action_preflight import frontmatter, prose_gate, regression_checks


def test_frontmatter_reads_live_graph_fields(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\nprose_node: closed\n---\nbody\n")
    assert frontmatter(path) == {"freeze_status": "red", "prose_node": "closed"}


def test_frontmatter_requires_closed_header(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\n")
    with pytest.raises(ValueError, match="unterminated"):
        frontmatter(path)


def test_analysis_preflight_preserves_prior_scientific_corrections() -> None:
    checks = " ".join(regression_checks("analysis")).lower()
    assert "calendar time" in checks
    assert "comparison set fixed" in checks
    assert "hysteresis" in checks


def test_preflight_consolidates_before_adding_and_bounds_review() -> None:
    checks = " ".join(regression_checks("analysis")).lower()
    assert "existing owner before adding" in checks
    assert "remove superseded duplicates" in checks
    assert "only the first two can block" in checks
    assert "one independent challenge" in checks
    assert "new material contradiction" in checks


def test_preflight_makes_corrections_cumulative_until_explicitly_withdrawn() -> None:
    for action in ("data", "analysis", "deck", "prose"):
        checks = " ".join(regression_checks(action)).lower()
        assert "canonical correction as cumulative" in checks
        assert "cannot replace, weaken, or narrow" in checks
        assert "explicitly withdraws" in checks
        assert "silently win" in checks


def test_prose_preflight_requires_raw_passages_not_term_replacement() -> None:
    checks = " ".join(regression_checks("prose")).lower()
    assert "raw published jfe passages" in checks
    assert "term replacement" in checks


def test_tiered_prose_gate_preserves_blocked_coefficient_boundary() -> None:
    allowed, message = prose_gate({"prose_node": "tiered"})
    assert allowed
    assert "certified route-only facts" in message
    assert "exact-state coefficient" in message


def test_closed_prose_gate_still_blocks_paper_mutation() -> None:
    allowed, message = prose_gate({"prose_node": "closed"})
    assert not allowed
    assert "leave paper/ unchanged" in message


def test_deck_preflight_recalls_persistent_visual_backlog() -> None:
    checks = " ".join(regression_checks("deck")).lower()
    assert "persistent visual backlog" in checks
    assert "source comments" in checks
