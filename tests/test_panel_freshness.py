from __future__ import annotations

import json
import os
from pathlib import Path

from ddvc.panel_freshness import check_canonical_panel_freshness


def _write_spec(root: Path) -> None:
    path = root / "docs/specification-lock.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "stage": "design_seed",
                "claims": [
                    {
                        "id": "open",
                        "status": "candidate_primary",
                        "execution_gate": "open",
                        "inputs": ["data/processed/input.parquet"],
                    }
                ],
            }
        )
    )


def test_panel_freshness_uses_plain_file_timestamps(tmp_path: Path) -> None:
    _write_spec(tmp_path)
    source = tmp_path / "data/processed/input.parquet"
    panel = tmp_path / "data/processed/d3_analysis_release/current.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    panel.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source")
    panel.write_text("{}")
    os.utime(source, ns=(10, 10))
    os.utime(panel, ns=(20, 20))
    assert check_canonical_panel_freshness(root=tmp_path)[0]
    os.utime(source, ns=(30, 30))
    passed, detail = check_canonical_panel_freshness(root=tmp_path)
    assert not passed
    assert "status=stale" in detail


def test_panel_freshness_fails_closed_on_missing_input(tmp_path: Path) -> None:
    _write_spec(tmp_path)
    panel = tmp_path / "data/processed/d3_analysis_release/current.json"
    panel.parent.mkdir(parents=True, exist_ok=True)
    panel.write_text("{}")
    passed, detail = check_canonical_panel_freshness(root=tmp_path)
    assert not passed
    assert "data/processed/input.parquet" in detail
