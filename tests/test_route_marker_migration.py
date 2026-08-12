from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ddvc.artifact_release import file_sha256
from ddvc.fetch.raw import RawFetchInvariantError
from ddvc.data_release import ReleasedPartition, ReleasedPartitionSet
from ddvc.reconstruct import (
    RECONSTRUCTION_ENGINE,
    UNIFIED_QUALITY_COLUMNS,
    _process_one,
    route_input_fingerprint,
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


def test_fresh_validation_removes_its_bounded_serialization_scratch(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from scripts import migrate_route_release_markers as migration

    day = days[0]
    marker = json.loads(
        unified_quality_path(day, root=paths["unified_root"]).read_text(
            encoding="utf-8"
        )
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    migration._validate_fresh_day(
        day,
        dexes=["uniswap_v2"],
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        legacy_marker=marker,
        current_input_fingerprint=route_input_fingerprint(
            "2020-05-05",
            ["uniswap_v2"],
            data_root=paths["data_root"],
        ),
        scratch=scratch,
    )
    assert list(scratch.iterdir()) == []


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


@pytest.mark.parametrize("cut_point", ["marker_swap", "ledger_swap"])
def test_restart_recovers_each_durable_publication_cut_point(
    tmp_path: Path,
    cut_point: str,
) -> None:
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
    original = {
        label: migration._content_identity(path)
        for label, path, _backup in targets
    }
    (stage / migration._JOURNAL_NAME).write_text(
        json.dumps(
            {
                "policy": migration.MIGRATION_POLICY,
                "state": migration._PREPARED,
                "legacy_engine": migration.LEGACY_ENGINE,
                "current_engine": migration.RECONSTRUCTION_ENGINE,
                "original_identities": original,
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
    if cut_point == "ledger_swap":
        panel_target.replace(panel_backup)
        panel_target.write_text("partial")
    migrate(paths, days, publish=False)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger
    assert not stage.exists()


def test_rollback_failure_preserves_recovery_state_for_the_next_run(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from scripts import migrate_route_release_markers as migration

    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    with (
        patch.object(
            migration,
            "write_panel",
            side_effect=RuntimeError("injected publication failure"),
        ),
        patch.object(
            migration,
            "_restore",
            side_effect=RuntimeError("injected rollback failure"),
        ),
        pytest.raises(RuntimeError, match="injected rollback failure"),
    ):
        migrate(paths, days, publish=True)
    stages = list(
        paths["unified_root"].parent.glob(f"{migration._STAGE_PREFIX}*")
    )
    assert len(stages) == 1
    assert (stages[0] / migration._JOURNAL_NAME).is_file()
    assert (stages[0] / "legacy-quality").is_dir()
    assert (stages[0] / "legacy-quality-panel").is_file()
    migrate(paths, days, publish=False)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger
    assert not stages[0].exists()


def test_route_reader_lease_blocks_marker_and_ledger_publication(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from scripts import migrate_route_release_markers as migration

    day = days[0]
    panel = unified_path(day, root=paths["unified_root"])
    marker = unified_quality_path(day, root=paths["unified_root"])
    quality = json.loads(marker.read_text(encoding="utf-8"))
    release = ReleasedPartitionSet(
        kind="route",
        columns=("tx_hash",),
        ledger_path=paths["quality_panel"],
        ledger_sha256=file_sha256(paths["quality_panel"]),
        partitions=(
            ReleasedPartition(
                day=day,
                path=panel,
                marker_path=marker,
                expected_rows=int(quality["output_rows"]),
                expected_bytes=int(quality["output_bytes"]),
                expected_sha256=str(quality["output_sha256"]),
                marker_sha256=file_sha256(marker),
                input_fingerprint=str(quality["input_fingerprint"]),
            ),
        ),
        content_identity_sha256="a" * 64,
        provenance_inputs=(paths["quality_panel"], panel, marker),
    )
    reader_entered = threading.Event()
    release_reader = threading.Event()
    publisher_entered = threading.Event()
    original_read = ReleasedPartitionSet._read_day_unlocked
    original_plan = migration.plan_migration

    def blocked_read(selected, partition):
        reader_entered.set()
        assert release_reader.wait(timeout=5)
        return original_read(selected, partition)

    def observed_plan(*args, **kwargs):
        publisher_entered.set()
        return original_plan(*args, **kwargs)

    with (
        patch.object(ReleasedPartitionSet, "_read_day_unlocked", blocked_read),
        patch.object(migration, "plan_migration", side_effect=observed_plan),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        reader = pool.submit(release.read_day, day)
        assert reader_entered.wait(timeout=5)
        publisher = pool.submit(migrate, paths, days, publish=True)
        assert not publisher_entered.wait(timeout=0.2)
        release_reader.set()
        assert reader.result(timeout=5)["tx_hash"].tolist() == ["0xtx"]
        publisher.result(timeout=10)
    assert publisher_entered.is_set()


def test_public_route_release_binding_holds_one_reader_lease(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from ddvc import data_release
    from scripts import migrate_route_release_markers as migration

    binding_entered = threading.Event()
    release_binding = threading.Event()
    publisher_entered = threading.Event()
    original_partition = data_release._released_partition
    original_plan = migration.plan_migration

    def validate_test_ledger(kind: str) -> pd.DataFrame:
        assert kind == "route"
        quality = pd.read_parquet(paths["quality_panel"])
        quality.attrs["ledger_sha256"] = file_sha256(paths["quality_panel"])
        return quality

    def blocked_partition(**kwargs):
        binding_entered.set()
        assert release_binding.wait(timeout=5)
        return original_partition(**kwargs)

    def observed_plan(*args, **kwargs):
        publisher_entered.set()
        return original_plan(*args, **kwargs)

    def test_unified_path(day: object, *, root: Path | None = None) -> Path:
        return unified_path(day, root=paths["unified_root"])

    def test_quality_path(day: object, *, root: Path | None = None) -> Path:
        return unified_quality_path(day, root=paths["unified_root"])

    with (
        patch.object(data_release, "UNIFIED_QUALITY_PANEL", paths["quality_panel"]),
        patch.object(data_release, "ROUTE_RELEASE_ROOT", paths["unified_root"]),
        patch.object(data_release, "unified_path", test_unified_path),
        patch.object(data_release, "unified_quality_path", test_quality_path),
        patch.object(
            data_release,
            "_validated_release_ledger_unlocked",
            side_effect=validate_test_ledger,
        ),
        patch.object(
            data_release,
            "_released_partition",
            side_effect=blocked_partition,
        ),
        patch.object(migration, "plan_migration", side_effect=observed_plan),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        reader = pool.submit(data_release.released_route_partitions, ("tx_hash",))
        assert binding_entered.wait(timeout=5)
        publisher = pool.submit(migrate, paths, days, publish=True)
        assert not publisher_entered.wait(timeout=0.2)
        release_binding.set()
        release = reader.result(timeout=5)
        assert release.days == tuple(days)
        publisher.result(timeout=10)
    assert publisher_entered.is_set()


@pytest.mark.parametrize("durable_replace_count", [2, 3])
def test_real_sigkill_recovers_reachable_durable_replace_cut_points(
    tmp_path: Path,
    durable_replace_count: int,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    program = """
import json
import os
import signal
import sys
from pathlib import Path
from scripts import migrate_route_release_markers as migration

config = json.loads(sys.argv[1])
original = migration._durable_replace
calls = 0

def kill_after_replace(source, target):
    global calls
    original(source, target)
    calls += 1
    if calls == config["cut"]:
        os.kill(os.getpid(), signal.SIGKILL)

migration._durable_replace = kill_after_replace
migration.migrate_route_release_markers(
    data_root=Path(config["data_root"]),
    unified_root=Path(config["unified_root"]),
    quality_panel=Path(config["quality_panel"]),
    quality_exhibit=Path(config["quality_exhibit"]),
    dexes=["uniswap_v2"],
    days=config["days"],
    workers=1,
    publish=True,
    raw_lock=Path(config["raw_lock"]),
)
"""
    config = {
        **{name: str(path) for name, path in paths.items()},
        "days": days,
        "cut": durable_replace_count,
    }
    killed = subprocess.run(
        [sys.executable, "-c", program, json.dumps(config)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert killed.returncode == -9, killed.stderr
    stages = list(
        paths["unified_root"].parent.glob(
            ".route-marker-migration-*"
        )
    )
    assert len(stages) == 1
    migrate(paths, days, publish=False)
    assert file_sha256(marker_path) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger
    assert not stages[0].exists()


@pytest.mark.parametrize(
    ("cut_point", "expected_state", "keeps_published_release"),
    [
        ("ledger_installed", "prepared", False),
        ("cleanup:panel", "committed", True),
    ],
)
def test_real_sigkill_recovers_installed_ledger_and_committed_cleanup(
    tmp_path: Path,
    cut_point: str,
    expected_state: str,
    keeps_published_release: bool,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    program = """
import json
import os
import signal
import sys
from pathlib import Path
from scripts import migrate_route_release_markers as migration

config = json.loads(sys.argv[1])

def kill_at_cut(label):
    if label == config["cut"]:
        os.kill(os.getpid(), signal.SIGKILL)

migration._publication_cut = kill_at_cut
migration.migrate_route_release_markers(
    data_root=Path(config["data_root"]),
    unified_root=Path(config["unified_root"]),
    quality_panel=Path(config["quality_panel"]),
    quality_exhibit=Path(config["quality_exhibit"]),
    dexes=["uniswap_v2"],
    days=config["days"],
    workers=1,
    publish=True,
    raw_lock=Path(config["raw_lock"]),
)
"""
    config = {
        **{name: str(path) for name, path in paths.items()},
        "days": days,
        "cut": cut_point,
    }
    killed = subprocess.run(
        [sys.executable, "-c", program, json.dumps(config)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert killed.returncode == -9, killed.stderr
    stages = list(
        paths["unified_root"].parent.glob(".route-marker-migration-*")
    )
    assert len(stages) == 1
    journal = json.loads(
        (stages[0] / "publication-journal.json").read_text(encoding="utf-8")
    )
    assert journal["state"] == expected_state
    recovered = migrate(paths, days, publish=False)
    assert not stages[0].exists()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if keeps_published_release:
        assert marker["engine"] == RECONSTRUCTION_ENGINE
        assert file_sha256(marker_path) != before_marker
        assert file_sha256(paths["quality_panel"]) != before_ledger
        assert recovered.validation["exact_frame_equal"].all()
    else:
        assert marker["engine"] == LEGACY_ENGINE
        assert file_sha256(marker_path) == before_marker
        assert file_sha256(paths["quality_panel"]) == before_ledger
