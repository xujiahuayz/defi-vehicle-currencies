from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.artifact_release import bind_file_lineage
from ddvc.frontier_release import (
    publish_frontier_release_marker,
    resolve_frontier_release,
)
from ddvc.tables import write_panel


def test_file_lineage_lease_binds_absence_as_well_as_content(tmp_path: Path) -> None:
    missing = tmp_path / "not-yet-present.json"
    lease = bind_file_lineage([missing], allow_missing=True)
    lease.assert_current()
    missing.write_text("late source\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="absent source file appeared"):
        lease.assert_current()


def test_frontier_release_rejects_a_split_multi_output_generation(tmp_path: Path) -> None:
    artifacts = {
        "panel": tmp_path / "panel.parquet",
        "rejections": tmp_path / "rejections.parquet",
        "support": tmp_path / "support.parquet",
    }
    source = tmp_path / "source.json"
    source.write_text("{}\n", encoding="utf-8")
    for index, path in enumerate(artifacts.values()):
        write_panel(
            pd.DataFrame({"value": [index]}),
            path,
            code_sources=["tests/test_frontier_release.py"],
            inputs=[source],
        )
    marker = tmp_path / "release.json"
    release = publish_frontier_release_marker(
        artifacts,
        marker_path=marker,
        source_identity_sha256="a" * 64,
    )
    assert resolve_frontier_release(
        marker_path=marker,
        artifacts=artifacts,
        expected_source_identity_sha256="a" * 64,
    ).generation_id == release.generation_id
    release.assert_current()
    with pytest.raises(ValueError, match="different source generation"):
        resolve_frontier_release(
            marker_path=marker,
            artifacts=artifacts,
            expected_source_identity_sha256="b" * 64,
        )

    write_panel(
        pd.DataFrame({"value": [99]}),
        artifacts["support"],
        code_sources=["tests/test_frontier_release.py"],
        inputs=[source],
    )
    with pytest.raises(ValueError, match="do not form the selected generation"):
        resolve_frontier_release(marker_path=marker, artifacts=artifacts)
    with pytest.raises(ValueError, match="do not form the selected generation"):
        release.assert_current()
