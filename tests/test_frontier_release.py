from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.artifact_release import bind_file_lineage, current_file_lineage
from ddvc.frontier_release import (
    publish_frontier_release,
    resolve_frontier_release,
)


def test_file_lineage_lease_binds_absence_as_well_as_content(tmp_path: Path) -> None:
    missing = tmp_path / "not-yet-present.json"
    lease = bind_file_lineage([missing], allow_missing=True)
    with current_file_lineage(lease):
        lease.assert_current()
    missing.write_text("late source\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="absent source file appeared"):
        lease.assert_current()


def _publish(
    tmp_path: Path,
    values: tuple[int, int, int],
    *,
    fail: bool = False,
):
    marker = tmp_path / "current.json"
    source = tmp_path / "source.json"
    source.write_text("{}\n", encoding="utf-8")
    names = ("panel", "rejections", "support")

    def writer(name: str, value: int):
        def write(path: Path) -> None:
            if fail and name == "support":
                raise RuntimeError("crash before marker")
            pd.DataFrame({"value": [value]}).to_parquet(path, index=False)

        return write

    return publish_frontier_release(
        writers={
            name: writer(name, value)
            for name, value in zip(names, values, strict=True)
        },
        row_counts={name: 1 for name in names},
        code_sources=["tests/test_frontier_release.py"],
        inputs=[source],
        notes="test frontier",
        source_identity_sha256="a" * 64,
        validate_staged=lambda paths: None,
        marker_path=marker,
    )


def test_frontier_uses_generic_marker_last_release_owner(tmp_path: Path) -> None:
    first = _publish(tmp_path, (1, 2, 3))
    assert resolve_frontier_release(
        marker_path=first.marker_path,
        expected_source_identity_sha256="a" * 64,
    ).generation_id == first.generation_id
    with pytest.raises(RuntimeError, match="crash before marker"):
        _publish(tmp_path, (4, 5, 6), fail=True)
    reopened = resolve_frontier_release(marker_path=first.marker_path)
    assert reopened.generation_id == first.generation_id
    assert pd.read_parquet(reopened.artifacts["support"])["value"].tolist() == [3]
