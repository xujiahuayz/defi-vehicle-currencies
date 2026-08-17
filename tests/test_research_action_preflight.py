from pathlib import Path
import sys

import pytest

import scripts.research_action_preflight as preflight


def test_frontmatter_reads_live_graph_fields(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\nprose_node: closed\n---\nbody\n")
    assert preflight.frontmatter(path) == {
        "freeze_status": "red",
        "prose_node": "closed",
    }


def test_frontmatter_requires_closed_header(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\n")
    with pytest.raises(ValueError, match="unterminated"):
        preflight.frontmatter(path)


def test_tiered_prose_keeps_unlocked_coefficients_out() -> None:
    allowed, message = preflight.prose_gate({"prose_node": "tiered"})
    assert allowed
    assert "unlocked exact-state coefficients" in message


def test_closed_prose_blocks_mutation() -> None:
    allowed, message = preflight.prose_gate({"prose_node": "closed"})
    assert not allowed
    assert message.startswith("BLOCKED")


def test_cli_reports_live_scope_without_certificate_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    freeze = tmp_path / "findings-freeze.md"
    freeze.write_text(
        "---\nfreeze_status: red\nmeeting_edge: data -> paper\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "FREEZE", freeze)
    monkeypatch.setattr(
        sys,
        "argv",
        ["research_action_preflight.py", "repository", "--node", "R"],
    )
    assert preflight.main() == 0
    output = capsys.readouterr().out
    assert "node=R" in output
    assert "certificate" not in output
    assert "sha" not in output.lower()
