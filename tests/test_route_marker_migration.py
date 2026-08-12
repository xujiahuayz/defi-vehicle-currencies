from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ddvc.artifact_release import file_sha256
from ddvc.fetch.raw import RawFetchInvariantError
from ddvc.reconstruct import (
    RECONSTRUCTION_ENGINE,
    UNIFIED_QUALITY_COLUMNS,
    _process_one,
    unified_path,
    unified_quality_path,
)
from scripts.migrate_route_release_markers import (
    LEGACY_ENGINE,
    migrate_route_release_markers,
)
from tests.test_reconstruct_gate import write_v2_swap


def prepare_legacy_release(tmp_path: Path, days: list[str]) -> dict[str, Path]:
    data_root = tmp_path / "data"
    unified_root = data_root / "unified"
    quality_panel = data_root / "processed" / "unified_route_quality.parquet"
    quality_exhibit = tmp_path / "output" / "unified_route_quality.jsonl"
    rows = []
    for index, day in enumerate(days):
        write_v2_swap(data_root, f"{day[:4]}-{day[4:6]}-{day[6:]}", amount_in=str(100 + index))
        quality, status = _process_one(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            True,
            data_root,
            unified_root,
        )
        assert status == "written"
        marker_path = unified_quality_path(day, root=unified_root)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["engine"] = LEGACY_ENGINE
        marker_path.write_text(json.dumps(marker, indent=1, sort_keys=True) + "\n")
        rows.append(marker)
    quality_panel.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=UNIFIED_QUALITY_COLUMNS).to_parquet(
        quality_panel, index=False
    )
    return {
        "data_root": data_root,
        "unified_root": unified_root,
        "quality_panel": quality_panel,
        "quality_exhibit": quality_exhibit,
        "raw_lock": tmp_path / "raw.lock",
    }


def migrate(
    paths: dict[str, Path],
    days: list[str],
    *,
    publish: bool,
    workers: int = 1,
):
    return migrate_route_release_markers(
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        quality_exhibit=paths["quality_exhibit"],
        dexes=["uniswap_v2"],
        days=days,
        workers=workers,
        publish=publish,
        raw_lock=paths["raw_lock"],
    )


def test_dry_run_proves_exact_semantics_without_mutating_release(tmp_path: Path) -> None:
    days = ["20200505", "20200506"]
    paths = prepare_legacy_release(tmp_path, days)
    before_markers = {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    }
    before_ledger = file_sha256(paths["quality_panel"])
    plan = migrate(paths, days, publish=False, workers=2)
    assert plan.validation["exact_frame_equal"].all()
    assert plan.validation["fresh_serialization_deterministic"].all()
    assert {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    } == before_markers
    assert file_sha256(paths["quality_panel"]) == before_ledger


def test_publish_changes_only_markers_and_global_quality_outputs(tmp_path: Path) -> None:
    days = ["20200505", "20200506"]
    paths = prepare_legacy_release(tmp_path, days)
    outputs = [unified_path(day, root=paths["unified_root"]) for day in days]
    before_outputs = {
        path: (path.stat().st_ino, file_sha256(path)) for path in outputs
    }
    migrate(paths, days, publish=True)
    for day in days:
        marker = json.loads(
            unified_quality_path(day, root=paths["unified_root"]).read_text(
                encoding="utf-8"
            )
        )
        assert marker["engine"] == RECONSTRUCTION_ENGINE
        assert marker["output_sha256"] == before_outputs[
            unified_path(day, root=paths["unified_root"])
        ][1]
    for path, identity in before_outputs.items():
        assert (path.stat().st_ino, file_sha256(path)) == identity
    assert set(paths["unified_root"].glob("*.parquet")) == set(outputs)
    quality = pd.read_parquet(paths["quality_panel"])
    assert set(quality["engine"]) == {RECONSTRUCTION_ENGINE}
    assert paths["quality_exhibit"].is_file()


def test_semantic_mismatch_fails_before_any_marker_or_ledger_change(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    from scripts import migrate_route_release_markers as migration

    original = migration.reconstruct_day_with_quality

    def changed(*args, **kwargs):
        frame, quality = original(*args, **kwargs)
        frame = frame.copy()
        frame.loc[0, "amount_in"] += 1.0
        return frame, quality

    with patch.object(migration, "reconstruct_day_with_quality", side_effect=changed):
        with pytest.raises(ValueError, match="semantics differ"):
            migrate(paths, days, publish=True)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger


def test_unsampled_same_era_semantic_change_blocks_the_complete_migration(
    tmp_path: Path,
) -> None:
    days = [f"202005{day:02d}" for day in range(5, 11)]
    paths = prepare_legacy_release(tmp_path, days)
    changed_day = "20200506"
    write_v2_swap(
        paths["data_root"],
        "2020-05-06",
        amount_in="999",
    )
    markers_before = {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    }
    ledger_before = file_sha256(paths["quality_panel"])
    with pytest.raises(ValueError, match=f"semantics differ.*{changed_day}"):
        migrate(paths, days, publish=True, workers=2)
    assert {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    } == markers_before
    assert file_sha256(paths["quality_panel"]) == ledger_before


def test_tampered_legacy_parquet_fails_before_publication(tmp_path: Path) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    output = unified_path(days[0], root=paths["unified_root"])
    payload = bytearray(output.read_bytes())
    payload[-1] ^= 1
    output.write_bytes(payload)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    with pytest.raises(ValueError, match="marker hash or rows"):
        migrate(paths, days, publish=True)
    assert file_sha256(marker_path) == before_marker


def test_publication_failure_restores_the_legacy_release(tmp_path: Path) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    with patch(
        "scripts.migrate_route_release_markers.write_panel",
        side_effect=RuntimeError("injected publication failure"),
    ):
        with pytest.raises(RuntimeError, match="injected publication failure"):
            migrate(paths, days, publish=True)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger
    assert not paths["quality_exhibit"].exists()


def test_missing_current_raw_marker_fails_before_publication(tmp_path: Path) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    raw_marker = next(
        (paths["data_root"] / "raw" / "thegraph" / "uniswap_v2").glob(
            "uniswap_v2_meta_*.json"
        )
    )
    raw_marker.unlink()
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    with pytest.raises(RawFetchInvariantError, match="generation identity"):
        migrate(paths, days, publish=True)
    assert file_sha256(marker_path) == before_marker


def test_restart_recovers_an_interrupted_marker_and_ledger_swap(tmp_path: Path) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from scripts import migrate_route_release_markers as migration

    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    stage = paths["unified_root"].parent / f"{migration._STAGE_PREFIX}crash"
    stage.mkdir()
    targets = migration._publication_targets(
        stage,
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        quality_exhibit=paths["quality_exhibit"],
    )
    original = {label: path.exists() for label, path, _backup in targets}
    (stage / migration._JOURNAL_NAME).write_text(
        json.dumps(
            {
                "policy": migration.MIGRATION_POLICY,
                "legacy_engine": migration.LEGACY_ENGINE,
                "current_engine": migration.RECONSTRUCTION_ENGINE,
                "original_existence": original,
            }
        )
    )
    marker_target, marker_backup = next(
        (path, backup) for label, path, backup in targets if label == "markers"
    )
    panel_target, panel_backup = next(
        (path, backup) for label, path, backup in targets if label == "panel"
    )
    marker_target.replace(marker_backup)
    marker_target.mkdir()
    (marker_target / f"{days[0]}.json").write_text('{"partial": true}\n')
    panel_target.replace(panel_backup)
    panel_target.write_text("partial")
    migrate(paths, days, publish=False)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger
    assert not stage.exists()
