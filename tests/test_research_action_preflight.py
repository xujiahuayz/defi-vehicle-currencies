from pathlib import Path

import pytest

from scripts.research_action_preflight import frontmatter


def test_frontmatter_reads_live_graph_fields(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\nprose_node: closed\n---\nbody\n")
    assert frontmatter(path) == {"freeze_status": "red", "prose_node": "closed"}


def test_frontmatter_requires_closed_header(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\n")
    with pytest.raises(ValueError, match="unterminated"):
        frontmatter(path)
