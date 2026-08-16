from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.fetch.raw import RawFetchInvariantError
from ddvc.data_release import ReleasedPartition, ReleasedPartitionSet
from ddvc.reconstruct import (
    RECONSTRUCTION_ENGINE,
    UNIFIED_QUALITY_COLUMNS,
    _process_one,
    read_unified_quality,
    route_input_fingerprint,
    route_input_paths,
    unified_path,
    unified_quality_path,
)
from scripts.migrate_route_release_markers import (
    LEGACY_ENGINE,
    RELOCATION_POLICY,
    derive_perimeter_expansion_authority_snapshot,
    migrate_route_release_markers,
    parse_expanded_source_specs,
    write_route_authority_snapshot,
)
from ddvc.raw_certification import (
    RawPartition,
    contract_identity,
    local_scan_certificate_path,
    raw_partition_relocation_identity,
    scan_installed_generation,
    write_local_scan_certificate,
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


def _certify_local_v2(
    data_root: Path, days: list[str], *, work_name: str
) -> None:
    partitions = [RawPartition("uniswap_v2", "swaps", day) for day in days]
    rows = scan_installed_generation(
        data_root,
        data_root / "interim" / work_name,
        workers=1,
        partitions=partitions,
    )
    write_local_scan_certificate(
        local_scan_certificate_path("uniswap_v2", data_root=data_root),
        rows,
        expected_partitions=partitions,
    )


def prepare_relocation_release(
    tmp_path: Path, days: list[str]
) -> tuple[dict[str, Path], Path, dict[str, tuple[int, str]]]:
    paths = {
        "data_root": tmp_path / "data",
        "unified_root": tmp_path / "data" / "unified",
        "quality_panel": tmp_path / "data" / "processed" / "unified_route_quality.parquet",
        "quality_exhibit": tmp_path / "output" / "unified_route_quality.jsonl",
        "raw_lock": tmp_path / "raw.lock",
    }
    backing = tmp_path / "old-authority"
    backing.mkdir()
    for index, day in enumerate(days):
        calendar_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        raw = write_v2_swap(
            paths["data_root"], calendar_day, amount_in=str(100 + index)
        )
        raw.with_name(f"uniswap_v2_meta_{day}.json").unlink()
        referent = backing / raw.name
        raw.replace(referent)
        raw.symlink_to(referent)
    _certify_local_v2(paths["data_root"], days, work_name="old-scan")
    quality_rows = []
    for day in days:
        quality, status = _process_one(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            True,
            paths["data_root"],
            paths["unified_root"],
        )
        assert status == "written"
        quality_rows.append(quality)
    paths["quality_panel"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(quality_rows, columns=UNIFIED_QUALITY_COLUMNS).to_parquet(
        paths["quality_panel"], index=False
    )
    snapshot = tmp_path / "route-authority-before-relocation.json"
    write_route_authority_snapshot(
        snapshot,
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        dexes=["uniswap_v2"],
        days=days,
        raw_lock=paths["raw_lock"],
    )
    outputs = {
        day: (
            unified_path(day, root=paths["unified_root"]).stat().st_ino,
            file_sha256(unified_path(day, root=paths["unified_root"])),
        )
        for day in days
    }
    for day in days:
        raw = route_input_paths(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            data_root=paths["data_root"],
        )[0]
        payload = raw.read_bytes()
        raw.unlink()
        raw.write_bytes(payload)
        os.utime(raw, None)
    _certify_local_v2(paths["data_root"], days, work_name="new-scan")
    return paths, snapshot, outputs


def relocate(
    paths: dict[str, Path],
    days: list[str],
    snapshot: Path,
    *,
    publish: bool,
):
    return migrate_route_release_markers(
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        quality_exhibit=paths["quality_exhibit"],
        dexes=["uniswap_v2"],
        days=days,
        workers=1,
        publish=publish,
        raw_lock=paths["raw_lock"],
        authority_snapshot=snapshot,
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


def test_storage_relocation_dry_run_never_reconstructs_route_legs(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    marker_hashes = {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    }
    ledger_hash = file_sha256(paths["quality_panel"])
    from scripts import migrate_route_release_markers as migration

    with patch.object(
        migration,
        "reconstruct_day_with_quality",
        side_effect=AssertionError("relocation must not reconstruct"),
    ):
        plan = relocate(paths, days, snapshot, publish=False)
    assert plan.migration_policy == RELOCATION_POLICY
    assert plan.validation["scientific_identity_equal"].all()
    assert plan.validation["input_fingerprint_changed"].all()
    assert {
        day: file_sha256(unified_quality_path(day, root=paths["unified_root"]))
        for day in days
    } == marker_hashes
    assert file_sha256(paths["quality_panel"]) == ledger_hash


def test_storage_relocation_publishes_only_fingerprints_and_global_outputs(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, outputs = prepare_relocation_release(tmp_path, days)
    old_markers = {
        day: json.loads(
            unified_quality_path(day, root=paths["unified_root"]).read_text()
        )
        for day in days
    }
    plan = relocate(paths, days, snapshot, publish=True)
    for day in days:
        output = unified_path(day, root=paths["unified_root"])
        assert (output.stat().st_ino, file_sha256(output)) == outputs[day]
        marker = json.loads(
            unified_quality_path(day, root=paths["unified_root"]).read_text()
        )
        assert marker["engine"] == old_markers[day]["engine"] == RECONSTRUCTION_ENGINE
        assert marker["input_fingerprint"] == plan.current_input_fingerprints[day]
        assert marker["input_fingerprint"] != old_markers[day]["input_fingerprint"]
        assert {
            key: value
            for key, value in marker.items()
            if key != "input_fingerprint"
        } == {
            key: value
            for key, value in old_markers[day].items()
            if key != "input_fingerprint"
        }


def test_storage_relocation_rejects_scientific_content_change(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    raw = route_input_paths(
        "2020-05-05", ["uniswap_v2"], data_root=paths["data_root"]
    )[0]
    write_v2_swap(paths["data_root"], "2020-05-05", amount_in="999")
    raw.with_name("uniswap_v2_meta_20200505.json").unlink()
    _certify_local_v2(paths["data_root"], days, work_name="mutated-scan")
    marker = unified_quality_path(days[0], root=paths["unified_root"])
    before = file_sha256(marker)
    with pytest.raises(ValueError, match="scientific identity changed"):
        relocate(paths, days, snapshot, publish=True)
    assert file_sha256(marker) == before


def test_promoted_source_relocation_identity_reopens_live_payload(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    raw = write_v2_swap(data_root, "2020-05-05")
    marker = raw.with_name("uniswap_v2_meta_20200505.json")
    marker_bytes = marker.read_bytes()
    raw_partition_relocation_identity(
        "uniswap_v2", "swaps", "20200505", data_root=data_root
    )
    write_v2_swap(data_root, "2020-05-05", amount_in="999")
    marker.write_bytes(marker_bytes)
    with pytest.raises(ValueError, match="payload changed after its marker"):
        raw_partition_relocation_identity(
            "uniswap_v2", "swaps", "20200505", data_root=data_root
        )


def test_storage_relocation_rejects_foreign_or_mutated_snapshot(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    from scripts import migrate_route_release_markers as migration

    original = json.loads(snapshot.read_text())
    payload = dict(original)
    payload["policy"] = "foreign"
    snapshot.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="snapshot envelope mismatch"):
        relocate(paths, days, snapshot, publish=False)
    payload = original
    payload["entries"][0]["scientific_identity"]["logical_content_sha256"] = "0" * 64
    payload["entries"][0]["scientific_identity_sha256"] = canonical_json_sha256(
        payload["entries"][0]["scientific_identity"]
    )
    payload["snapshot_sha256"] = migration._snapshot_digest(payload)
    snapshot.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="scientific identity changed"):
        relocate(paths, days, snapshot, publish=False)


def test_storage_relocation_rejects_release_changed_after_snapshot(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    marker = json.loads(marker_path.read_text())
    marker["raw_rows"] += 1
    marker_path.write_text(json.dumps(marker, indent=1, sort_keys=True) + "\n")
    pd.DataFrame([marker], columns=UNIFIED_QUALITY_COLUMNS).to_parquet(
        paths["quality_panel"], index=False
    )
    with pytest.raises(ValueError, match="changed after authority snapshot"):
        relocate(paths, days, snapshot, publish=False)


def prepare_perimeter_expansion_release(
    tmp_path: Path, days: list[str]
) -> tuple[dict[str, Path], dict[str, tuple[int, str]]]:
    """Release certified over swaps only, then expand the certificate in place."""

    paths = {
        "data_root": tmp_path / "data",
        "unified_root": tmp_path / "data" / "unified",
        "quality_panel": tmp_path / "data" / "processed" / "unified_route_quality.parquet",
        "quality_exhibit": tmp_path / "output" / "unified_route_quality.jsonl",
        "raw_lock": tmp_path / "raw.lock",
    }
    for index, day in enumerate(days):
        calendar_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        raw = write_v2_swap(
            paths["data_root"], calendar_day, amount_in=str(100 + index)
        )
        raw.with_name(f"uniswap_v2_meta_{day}.json").unlink()
    _certify_local_v2(paths["data_root"], days, work_name="route-only-scan")
    quality_rows = []
    for day in days:
        quality, status = _process_one(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            True,
            paths["data_root"],
            paths["unified_root"],
        )
        assert status == "written"
        quality_rows.append(quality)
    paths["quality_panel"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(quality_rows, columns=UNIFIED_QUALITY_COLUMNS).to_parquet(
        paths["quality_panel"], index=False
    )
    outputs = {
        day: (
            unified_path(day, root=paths["unified_root"]).stat().st_ino,
            file_sha256(unified_path(day, root=paths["unified_root"])),
        )
        for day in days
    }
    expand_certificate_beyond_route_stream(paths["data_root"], days)
    return paths, outputs


def expand_certificate_beyond_route_stream(
    data_root: Path, days: list[str], *, work_name: str = "expanded-scan"
) -> None:
    """Re-certify uniswap_v2 with an added non-route stream, as a capital consumer would."""

    swap_partitions = [RawPartition("uniswap_v2", "swaps", day) for day in days]
    rows = scan_installed_generation(
        data_root,
        data_root / "interim" / work_name,
        workers=1,
        partitions=swap_partitions,
    )
    extra = {
        "source": "uniswap_v2",
        "stream": "hourly_reserves",
        "day": days[0],
        "path": (
            f"raw/thegraph/uniswap_v2/uniswap_v2_hourly_reserves_{days[0]}.jsonl.gz"
        ),
        "local_pass": True,
        "errors": [],
        "logical_content_sha256": canonical_json_sha256({"fixture": "reserves"}),
        "contract_sha256": contract_identity("uniswap_v2", "hourly_reserves"),
        "container_bytes": 1,
        "container_mtime_ns": 1,
        "container_ctime_ns": 1,
        "metadata_present": False,
    }
    write_local_scan_certificate(
        local_scan_certificate_path("uniswap_v2", data_root=data_root),
        [*rows, extra],
        expected_partitions=[
            *swap_partitions,
            RawPartition("uniswap_v2", "hourly_reserves", days[0]),
        ],
    )


def derive_expansion_snapshot(
    paths: dict[str, Path], days: list[str], snapshot: Path
) -> dict[str, object]:
    return derive_perimeter_expansion_authority_snapshot(
        snapshot,
        expanded_sources=["uniswap_v2"],
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        dexes=["uniswap_v2"],
        days=days,
        raw_lock=paths["raw_lock"],
    )


def test_perimeter_expansion_derivation_rebinds_stale_markers(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, outputs = prepare_perimeter_expansion_release(tmp_path, days)
    for day in days:
        assert (
            read_unified_quality(
                f"{day[:4]}-{day[4:6]}-{day[6:]}",
                ["uniswap_v2"],
                data_root=paths["data_root"],
                unified_root=paths["unified_root"],
            )
            is None
        )
    snapshot = tmp_path / "derived-perimeter-expansion.json"
    payload = derive_expansion_snapshot(paths, days, snapshot)
    assert payload["derivation"]["rebound_days"] == len(days)
    plan = relocate(paths, days, snapshot, publish=True)
    assert plan.migration_policy == RELOCATION_POLICY
    for day in days:
        output = unified_path(day, root=paths["unified_root"])
        assert (output.stat().st_ino, file_sha256(output)) == outputs[day]
        quality = read_unified_quality(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            data_root=paths["data_root"],
            unified_root=paths["unified_root"],
        )
        assert quality is not None
        assert quality["input_fingerprint"] == route_input_fingerprint(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            data_root=paths["data_root"],
        )


def test_perimeter_expansion_derivation_rejects_changed_route_payload(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, _outputs = prepare_perimeter_expansion_release(tmp_path, days)
    raw = route_input_paths(
        "2020-05-05", ["uniswap_v2"], data_root=paths["data_root"]
    )[0]
    write_v2_swap(paths["data_root"], "2020-05-05", amount_in="999")
    raw.with_name("uniswap_v2_meta_20200505.json").unlink()
    expand_certificate_beyond_route_stream(
        paths["data_root"], days, work_name="mutated-expanded-scan"
    )
    snapshot = tmp_path / "derived-perimeter-expansion.json"
    with pytest.raises(ValueError, match="does not reproduce the released"):
        derive_expansion_snapshot(paths, days, snapshot)
    assert not snapshot.exists()


def test_perimeter_expansion_derivation_requires_actual_expansion(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, _outputs = prepare_perimeter_expansion_release(tmp_path, days)
    _certify_local_v2(paths["data_root"], days, work_name="route-only-rescan")
    snapshot = tmp_path / "derived-perimeter-expansion.json"
    with pytest.raises(ValueError, match="was not expanded beyond the route stream"):
        derive_expansion_snapshot(paths, days, snapshot)
    assert not snapshot.exists()


def _synthetic_stream_row(stream: str, day: str) -> dict[str, object]:
    return {
        "source": "uniswap_v2",
        "stream": stream,
        "day": day,
        "path": f"raw/thegraph/uniswap_v2/uniswap_v2_{stream}_{day}.jsonl.gz",
        "local_pass": True,
        "errors": [],
        "logical_content_sha256": canonical_json_sha256({"fixture": stream}),
        "contract_sha256": contract_identity("uniswap_v2", stream),
        "container_bytes": 1,
        "container_mtime_ns": 1,
        "container_ctime_ns": 1,
        "metadata_present": False,
    }


def _certify_local_v2_with_streams(
    data_root: Path,
    days: list[str],
    *,
    work_name: str,
    extra_streams: list[str],
) -> None:
    """Certify swaps plus synthetic rows for named non-route streams."""

    swap_partitions = [RawPartition("uniswap_v2", "swaps", day) for day in days]
    rows = scan_installed_generation(
        data_root,
        data_root / "interim" / work_name,
        workers=1,
        partitions=swap_partitions,
    )
    extras = [_synthetic_stream_row(stream, days[0]) for stream in extra_streams]
    write_local_scan_certificate(
        local_scan_certificate_path("uniswap_v2", data_root=data_root),
        [*rows, *extras],
        expected_partitions=[
            *swap_partitions,
            *(
                RawPartition("uniswap_v2", stream, days[0])
                for stream in extra_streams
            ),
        ],
    )


def test_perimeter_expansion_derivation_accepts_named_prior_streams(
    tmp_path: Path,
) -> None:
    """A prior certificate covering swaps+hourly rebinds only with its exact spec."""

    days = ["20200505"]
    paths = {
        "data_root": tmp_path / "data",
        "unified_root": tmp_path / "data" / "unified",
        "quality_panel": tmp_path
        / "data"
        / "processed"
        / "unified_route_quality.parquet",
        "quality_exhibit": tmp_path / "output" / "unified_route_quality.jsonl",
        "raw_lock": tmp_path / "raw.lock",
    }
    for index, day in enumerate(days):
        raw = write_v2_swap(
            paths["data_root"],
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            amount_in=str(100 + index),
        )
        raw.with_name(f"uniswap_v2_meta_{day}.json").unlink()
    _certify_local_v2_with_streams(
        paths["data_root"],
        days,
        work_name="two-stream-scan",
        extra_streams=["hourly_reserves"],
    )
    quality_rows = []
    for day in days:
        quality, status = _process_one(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            True,
            paths["data_root"],
            paths["unified_root"],
        )
        assert status == "written"
        quality_rows.append(quality)
    paths["quality_panel"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(quality_rows, columns=UNIFIED_QUALITY_COLUMNS).to_parquet(
        paths["quality_panel"], index=False
    )
    outputs = {
        day: (
            unified_path(day, root=paths["unified_root"]).stat().st_ino,
            file_sha256(unified_path(day, root=paths["unified_root"])),
        )
        for day in days
    }
    _certify_local_v2_with_streams(
        paths["data_root"],
        days,
        work_name="three-stream-scan",
        extra_streams=["hourly_reserves", "mints"],
    )
    for day in days:
        assert (
            read_unified_quality(
                f"{day[:4]}-{day[4:6]}-{day[6:]}",
                ["uniswap_v2"],
                data_root=paths["data_root"],
                unified_root=paths["unified_root"],
            )
            is None
        )
    bare_snapshot = tmp_path / "bare-derivation.json"
    with pytest.raises(ValueError, match="does not reproduce the released"):
        derive_perimeter_expansion_authority_snapshot(
            bare_snapshot,
            expanded_sources=["uniswap_v2"],
            data_root=paths["data_root"],
            unified_root=paths["unified_root"],
            quality_panel=paths["quality_panel"],
            dexes=["uniswap_v2"],
            days=days,
            raw_lock=paths["raw_lock"],
        )
    assert not bare_snapshot.exists()
    snapshot = tmp_path / "named-prior-derivation.json"
    payload = derive_perimeter_expansion_authority_snapshot(
        snapshot,
        expanded_sources=["uniswap_v2=swaps,hourly_reserves"],
        data_root=paths["data_root"],
        unified_root=paths["unified_root"],
        quality_panel=paths["quality_panel"],
        dexes=["uniswap_v2"],
        days=days,
        raw_lock=paths["raw_lock"],
    )
    assert payload["derivation"]["rebound_days"] == len(days)
    assert payload["derivation"]["prior_stream_perimeters"] == {
        "uniswap_v2": ["hourly_reserves", "swaps"]
    }
    plan = relocate(paths, days, snapshot, publish=True)
    assert plan.migration_policy == RELOCATION_POLICY
    for day in days:
        output = unified_path(day, root=paths["unified_root"])
        assert (output.stat().st_ino, file_sha256(output)) == outputs[day]
        quality = read_unified_quality(
            f"{day[:4]}-{day[4:6]}-{day[6:]}",
            ["uniswap_v2"],
            data_root=paths["data_root"],
            unified_root=paths["unified_root"],
        )
        assert quality is not None


def test_perimeter_expansion_derivation_requires_route_stream_in_spec(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, _outputs = prepare_perimeter_expansion_release(tmp_path, days)
    snapshot = tmp_path / "no-route-stream.json"
    with pytest.raises(ValueError, match="must include the route stream"):
        derive_perimeter_expansion_authority_snapshot(
            snapshot,
            expanded_sources=["uniswap_v2=hourly_reserves"],
            data_root=paths["data_root"],
            unified_root=paths["unified_root"],
            quality_panel=paths["quality_panel"],
            dexes=["uniswap_v2"],
            days=days,
            raw_lock=paths["raw_lock"],
        )
    assert not snapshot.exists()


def test_parse_expanded_source_specs_shapes() -> None:
    assert parse_expanded_source_specs(["uniswap_v2"]) == {
        "uniswap_v2": frozenset({"swaps"})
    }
    assert parse_expanded_source_specs(["uniswap_v2=swaps,hourly_reserves"]) == {
        "uniswap_v2": frozenset({"swaps", "hourly_reserves"})
    }
    assert parse_expanded_source_specs(
        ["uniswap_v2=swaps", "uniswap_v2=swaps"]
    ) == {"uniswap_v2": frozenset({"swaps"})}
    with pytest.raises(ValueError, match="conflicting prior perimeters"):
        parse_expanded_source_specs(["uniswap_v2", "uniswap_v2=swaps,hourly_reserves"])
    with pytest.raises(ValueError, match="lacks streams"):
        parse_expanded_source_specs(["uniswap_v2="])
    with pytest.raises(ValueError, match="lacks a source"):
        parse_expanded_source_specs(["=swaps"])


def test_storage_relocation_interruption_rolls_back_complete_bundle(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    marker = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker)
    before_ledger = file_sha256(paths["quality_panel"])

    def interrupt(label: str) -> None:
        if label == "installed:panel":
            raise KeyboardInterrupt("injected interruption")

    with (
        patch(
            "ddvc.journaled_publication._publication_cut",
            side_effect=interrupt,
        ),
        pytest.raises(KeyboardInterrupt, match="injected interruption"),
    ):
        relocate(paths, days, snapshot, publish=True)
    assert file_sha256(marker) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger


def test_storage_relocation_rechecks_route_partition_inside_journal(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    marker = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker)
    before_ledger = file_sha256(paths["quality_panel"])
    output = unified_path(days[0], root=paths["unified_root"])
    from scripts import migrate_route_release_markers as migration

    original_publish = migration.publish_journaled_bundle

    def mutate_then_publish(**kwargs):
        payload = bytearray(output.read_bytes())
        payload[-1] ^= 1
        output.write_bytes(payload)
        return original_publish(**kwargs)

    with (
        patch.object(
            migration,
            "publish_journaled_bundle",
            side_effect=mutate_then_publish,
        ),
        pytest.raises(RuntimeError, match="partition changed before migration commit"),
    ):
        relocate(paths, days, snapshot, publish=True)
    assert file_sha256(marker) == before_marker
    assert file_sha256(paths["quality_panel"]) == before_ledger


def test_storage_relocation_rechecks_raw_authority_inside_journal(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths, snapshot, _outputs = prepare_relocation_release(tmp_path, days)
    marker = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker)
    before_ledger = file_sha256(paths["quality_panel"])
    raw = route_input_paths(
        "2020-05-05", ["uniswap_v2"], data_root=paths["data_root"]
    )[0]
    from scripts import migrate_route_release_markers as migration

    original_publish = migration.publish_journaled_bundle

    def mutate_then_publish(**kwargs):
        raw.write_bytes(raw.read_bytes() + b"mutation")
        return original_publish(**kwargs)

    with (
        patch.object(
            migration,
            "publish_journaled_bundle",
            side_effect=mutate_then_publish,
        ),
        pytest.raises(ValueError, match="changed after scan"),
    ):
        relocate(paths, days, snapshot, publish=True)
    assert file_sha256(marker) == before_marker
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
    def fail_after_panel(label: str) -> None:
        if label == "installed:panel":
            raise RuntimeError("injected publication failure")

    with patch(
        "ddvc.journaled_publication._publication_cut",
        side_effect=fail_after_panel,
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


def test_rollback_failure_preserves_recovery_state_for_the_next_run(
    tmp_path: Path,
) -> None:
    days = ["20200505"]
    paths = prepare_legacy_release(tmp_path, days)
    from ddvc import journaled_publication as publication
    from scripts import migrate_route_release_markers as migration

    marker_path = unified_quality_path(days[0], root=paths["unified_root"])
    before_marker = file_sha256(marker_path)
    before_ledger = file_sha256(paths["quality_panel"])
    def fail_after_panel(label: str) -> None:
        if label == "installed:panel":
            raise RuntimeError("injected publication failure")

    with (
        patch.object(publication, "_publication_cut", side_effect=fail_after_panel),
        patch.object(
            publication,
            "_restore",
            side_effect=RuntimeError("injected rollback failure"),
        ),
        pytest.raises(RuntimeError, match="injected rollback failure"),
    ):
        migrate(paths, days, publish=True)
    journal_root = paths["unified_root"].parent / migration.JOURNAL_ROOT_NAME
    stages = list(journal_root.glob(".ddvc-publish-*"))
    assert len(stages) == 1
    assert (stages[0] / publication.JOURNAL).is_file()
    assert (stages[0] / "backup" / "markers").is_dir()
    assert (stages[0] / "backup" / "panel").is_file()
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
                "current_artifacts",
                return_value=nullcontext(),
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


@pytest.mark.parametrize("cut_point", ["installed:markers", "installed:panel"])
def test_real_sigkill_recovers_prepared_route_bundle_cut_points(
    tmp_path: Path,
    cut_point: str,
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
from ddvc import journaled_publication as publication
from scripts import migrate_route_release_markers as migration

config = json.loads(sys.argv[1])
def kill_at_cut(label):
    if label == config["cut"]:
        os.kill(os.getpid(), signal.SIGKILL)

publication._publication_cut = kill_at_cut
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
        (paths["unified_root"].parent / ".route-marker-migration-journals").glob(
            ".ddvc-publish-*"
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
        ("installed:panel_sidecar", "prepared", False),
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
from ddvc import journaled_publication as publication
from scripts import migrate_route_release_markers as migration

config = json.loads(sys.argv[1])

def kill_at_cut(label):
    if label == config["cut"]:
        os.kill(os.getpid(), signal.SIGKILL)

publication._publication_cut = kill_at_cut
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
        (paths["unified_root"].parent / ".route-marker-migration-journals").glob(".ddvc-publish-*")
    )
    assert len(stages) == 1
    journal = json.loads(
        (stages[0] / "journal.json").read_text(encoding="utf-8")
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


def _sha256_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def prepare_downstream_consumer(tmp_path: Path) -> dict[str, object]:
    """One byte-unchanged consumer whose ledger/marker bindings went stale."""

    from ddvc.provenance import code_fingerprint

    root = tmp_path
    ledger = root / "data" / "processed" / "unified_route_quality.parquet"
    partition = root / "data" / "unified" / "20240101.parquet"
    marker = root / "data" / "unified" / ".quality" / "20240101.json"
    payload = root / "data" / "processed" / "panel.parquet"
    sidecar = root / "manifests" / "panel.parquet.prov.json"
    for path, content in (
        (ledger, b"ledger-v2"),
        (partition, b"partition"),
        (marker, b"marker-v2"),
        (payload, b"payload"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    code_sources = ["scripts/migrate_route_release_markers.py"]
    record = {
        "artefact": "data/processed/panel.parquet",
        "artefact_bytes": len(b"payload"),
        "artefact_sha256": _sha256_of(b"payload"),
        "code_fingerprint": code_fingerprint(code_sources),
        "code_sources": code_sources,
        "inputs": [
            {
                "bytes": len(b"ledger-v1"),
                "exists": True,
                "path": "data/processed/unified_route_quality.parquet",
                "sha256": _sha256_of(b"ledger-v1"),
            }
        ],
        "notes": "built from the certified route release",
        "released_input_bindings": [
            {
                "path": "data/processed/unified_route_quality.parquet",
                "sha256": _sha256_of(b"ledger-v1"),
            },
            {
                "path": "data/unified/20240101.parquet",
                "sha256": _sha256_of(b"partition"),
            },
            {
                "path": "data/unified/.quality/20240101.json",
                "sha256": _sha256_of(b"marker-v1"),
            },
        ],
        "rows": 1,
    }
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    current_bindings = {
        "data/processed/unified_route_quality.parquet": _sha256_of(b"ledger-v2"),
        "data/unified/20240101.parquet": _sha256_of(b"partition"),
        "data/unified/.quality/20240101.json": _sha256_of(b"marker-v2"),
    }
    migratable = frozenset(
        {
            "data/processed/unified_route_quality.parquet",
            "data/unified/.quality/20240101.json",
        }
    )
    return {
        "root": root,
        "payload": payload,
        "sidecar": sidecar,
        "current_bindings": current_bindings,
        "migratable": migratable,
    }


def test_downstream_rebind_updates_only_migrated_identities(tmp_path: Path) -> None:
    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    payload_before = fixture["payload"].read_bytes()
    assert rebind_released_input_bindings(
        fixture["payload"],
        current_bindings=fixture["current_bindings"],
        migratable_paths=fixture["migratable"],
        rebind_note="rebind-test-note",
        sidecar=fixture["sidecar"],
        root=fixture["root"],
    )
    assert fixture["payload"].read_bytes() == payload_before
    record = json.loads(fixture["sidecar"].read_text())
    bound = {item["path"]: item["sha256"] for item in record["released_input_bindings"]}
    assert bound == fixture["current_bindings"]
    assert record["inputs"][0]["sha256"] == _sha256_of(b"ledger-v2")
    assert record["inputs"][0]["bytes"] == len(b"ledger-v2")
    assert "rebind-test-note" in record["notes"]
    assert record["notes"].startswith("built from the certified route release")
    assert record["artefact_sha256"] == _sha256_of(b"payload")
    # a second run finds nothing left to rebind
    assert not rebind_released_input_bindings(
        fixture["payload"],
        current_bindings=fixture["current_bindings"],
        migratable_paths=fixture["migratable"],
        rebind_note="rebind-test-note",
        sidecar=fixture["sidecar"],
        root=fixture["root"],
    )


def test_downstream_rebind_refuses_partition_identity_change(tmp_path: Path) -> None:
    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    sidecar_before = fixture["sidecar"].read_bytes()
    changed = dict(fixture["current_bindings"])
    changed["data/unified/20240101.parquet"] = _sha256_of(b"partition-changed")
    with pytest.raises(RuntimeError, match="outside the migrated"):
        rebind_released_input_bindings(
            fixture["payload"],
            current_bindings=changed,
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            sidecar=fixture["sidecar"],
            root=fixture["root"],
        )
    assert fixture["sidecar"].read_bytes() == sidecar_before


def test_downstream_rebind_refuses_changed_payload(tmp_path: Path) -> None:
    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    fixture["payload"].write_bytes(b"payload-changed")
    with pytest.raises(RuntimeError, match="payload changed"):
        rebind_released_input_bindings(
            fixture["payload"],
            current_bindings=fixture["current_bindings"],
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            sidecar=fixture["sidecar"],
            root=fixture["root"],
        )


def test_downstream_rebind_refuses_stale_code(tmp_path: Path) -> None:
    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    record = json.loads(fixture["sidecar"].read_text())
    record["code_fingerprint"] = "0" * 64
    fixture["sidecar"].write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    with pytest.raises(RuntimeError, match="code is not current"):
        rebind_released_input_bindings(
            fixture["payload"],
            current_bindings=fixture["current_bindings"],
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            sidecar=fixture["sidecar"],
            root=fixture["root"],
        )


def test_downstream_rebind_refuses_unknown_stale_binding(tmp_path: Path) -> None:
    """A stale binding that the current release does not cover is a refusal."""

    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    record = json.loads(fixture["sidecar"].read_text())
    record["released_input_bindings"].append(
        {"path": "data/unified/20240102.parquet", "sha256": "1" * 64}
    )
    fixture["sidecar"].write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    with pytest.raises(RuntimeError, match="outside the migrated"):
        rebind_released_input_bindings(
            fixture["payload"],
            current_bindings=fixture["current_bindings"],
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            sidecar=fixture["sidecar"],
            root=fixture["root"],
        )


def prepare_endpoint_release(tmp_path: Path) -> dict[str, object]:
    """A two-member typed release whose member bindings went stale."""

    from ddvc.artifact_release import generation_id

    root = tmp_path
    consumer = prepare_downstream_consumer(tmp_path)
    pointer = root / "release" / "current.json"
    build_identity = canonical_json_sha256({"policy": "rebind-test-build"})
    code_sources = ["scripts/migrate_route_release_markers.py"]
    members: dict[str, dict[str, object]] = {}
    sidecars: dict[Path, Path] = {}
    artifact_hashes: dict[str, str] = {}
    for name, content in (("alpha", b"alpha-bytes"), ("beta", b"beta-bytes")):
        filename = f"{name}.parquet"
        digest = _sha256_of(content)
        artifact_hashes[name] = digest
        members[name] = {"filename": filename, "content": content, "sha256": digest}
    generation = generation_id(artifact_hashes, build_identity)
    generation_dir = pointer.parent / "generations" / generation
    artifacts: dict[str, dict[str, str]] = {}
    for name, member in members.items():
        target = generation_dir / str(member["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(member["content"])  # type: ignore[arg-type]
        record = {
            "artefact": str(member["filename"]),
            "artefact_bytes": len(member["content"]),  # type: ignore[arg-type]
            "artefact_sha256": member["sha256"],
            # a frozen generation's stamped fingerprint predates later code
            # changes by design; the release contract does not require it
            "code_fingerprint": "0" * 64,
            "code_sources": code_sources,
            "inputs": [],
            "notes": "endpoint member",
            "released_input_bindings": [
                {
                    "path": "data/processed/unified_route_quality.parquet",
                    "sha256": _sha256_of(b"ledger-v1"),
                },
                {
                    "path": "data/unified/20240101.parquet",
                    "sha256": _sha256_of(b"partition"),
                },
                {
                    "path": "data/unified/.quality/20240101.json",
                    "sha256": _sha256_of(b"marker-v1"),
                },
            ],
            "rows": 1,
        }
        member_sidecar = root / "manifests" / f"{member['filename']}.prov.json"
        member_sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
        sidecars[target] = member_sidecar
        artifacts[name] = {
            "filename": str(member["filename"]),
            "sha256": str(member["sha256"]),
            "provenance_sha256": file_sha256(member_sidecar),
        }
    pointer.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"generation_id": generation, "validator_fingerprint": "a" * 64}
    pointer.write_text(
        json.dumps(
            {
                "artifacts": artifacts,
                "build_identity_sha256": build_identity,
                "generation_id": generation,
                "kind": "endpoint_candidate_composition",
                "schema_version": 3,
                "semantic_validation": receipt,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {
        "root": root,
        "pointer": pointer,
        "generation": generation,
        "receipt": receipt,
        "sidecars": sidecars,
        "current_bindings": consumer["current_bindings"],
        "migratable": consumer["migratable"],
    }


def test_endpoint_pointer_rebind_preserves_generation_and_receipt(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import (
        rebind_endpoint_composition_release,
    )

    fixture = prepare_endpoint_release(tmp_path)
    sidecars: dict[Path, Path] = fixture["sidecars"]  # type: ignore[assignment]
    assert rebind_endpoint_composition_release(
        current_bindings=fixture["current_bindings"],
        migratable_paths=fixture["migratable"],
        rebind_note="rebind-test-note",
        pointer_path=fixture["pointer"],
        sidecar_for=lambda path: sidecars[path],
        root=fixture["root"],
    )
    pointer = json.loads(fixture["pointer"].read_text())
    assert pointer["generation_id"] == fixture["generation"]
    assert pointer["semantic_validation"] == fixture["receipt"]
    for target, member_sidecar in sidecars.items():
        record = json.loads(member_sidecar.read_text())
        bound = {
            item["path"]: item["sha256"]
            for item in record["released_input_bindings"]
        }
        assert bound == fixture["current_bindings"]
        name = target.name.removesuffix(".parquet")
        assert pointer["artifacts"][name]["provenance_sha256"] == file_sha256(
            member_sidecar
        )
        assert pointer["artifacts"][name]["sha256"] == file_sha256(target)
    # a second run is a no-op
    assert not rebind_endpoint_composition_release(
        current_bindings=fixture["current_bindings"],
        migratable_paths=fixture["migratable"],
        rebind_note="rebind-test-note",
        pointer_path=fixture["pointer"],
        sidecar_for=lambda path: sidecars[path],
        root=fixture["root"],
    )


def test_endpoint_pointer_rebind_refuses_member_payload_change(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import (
        rebind_endpoint_composition_release,
    )

    fixture = prepare_endpoint_release(tmp_path)
    sidecars: dict[Path, Path] = fixture["sidecars"]  # type: ignore[assignment]
    target = next(iter(sidecars))
    target.write_bytes(b"tampered-member")
    pointer_before = fixture["pointer"].read_bytes()
    with pytest.raises(RuntimeError, match="member payload changed"):
        rebind_endpoint_composition_release(
            current_bindings=fixture["current_bindings"],
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            pointer_path=fixture["pointer"],
            sidecar_for=lambda path: sidecars[path],
            root=fixture["root"],
        )
    assert fixture["pointer"].read_bytes() == pointer_before


def test_owned_artifact_restamp_moves_only_the_code_fingerprint(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import restamp_migration_owned_artifact

    fixture = prepare_downstream_consumer(tmp_path)
    sidecar = fixture["sidecar"]
    record = json.loads(sidecar.read_text())
    # make the ledger input current so only the fingerprint is stale
    ledger = fixture["root"] / "data" / "processed" / "unified_route_quality.parquet"
    record["inputs"][0]["sha256"] = file_sha256(ledger)
    record["inputs"][0]["bytes"] = ledger.stat().st_size
    record["code_fingerprint"] = "0" * 64
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    assert restamp_migration_owned_artifact(
        fixture["payload"],
        restamp_note="restamp-test-note",
        sidecar=sidecar,
        root=fixture["root"],
    )
    restamped = json.loads(sidecar.read_text())
    from ddvc.provenance import code_fingerprint

    assert restamped["code_fingerprint"] == code_fingerprint(
        restamped["code_sources"]
    )
    assert "restamp-test-note" in restamped["notes"]
    assert restamped["released_input_bindings"] == record["released_input_bindings"]
    # a second run is a no-op, and a payload change is a refusal
    assert not restamp_migration_owned_artifact(
        fixture["payload"],
        restamp_note="restamp-test-note",
        sidecar=sidecar,
        root=fixture["root"],
    )
    fixture["payload"].write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="payload changed"):
        restamp_migration_owned_artifact(
            fixture["payload"],
            restamp_note="restamp-test-note",
            sidecar=sidecar,
            root=fixture["root"],
        )


def test_owned_artifact_restamp_refuses_changed_inputs(tmp_path: Path) -> None:
    from scripts.migrate_route_release_markers import restamp_migration_owned_artifact

    fixture = prepare_downstream_consumer(tmp_path)
    sidecar = fixture["sidecar"]
    record = json.loads(sidecar.read_text())
    record["code_fingerprint"] = "0" * 64
    # the recorded ledger input identity (ledger-v1) differs from disk (ledger-v2)
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    with pytest.raises(RuntimeError, match="inputs changed"):
        restamp_migration_owned_artifact(
            fixture["payload"],
            restamp_note="restamp-test-note",
            sidecar=sidecar,
            root=fixture["root"],
        )


def test_downstream_rebind_handles_inputs_only_consumers(tmp_path: Path) -> None:
    """Exhibits bind the release through inputs records, not release bindings."""

    from scripts.migrate_route_release_markers import rebind_released_input_bindings

    fixture = prepare_downstream_consumer(tmp_path)
    sidecar = fixture["sidecar"]
    record = json.loads(sidecar.read_text())
    record["released_input_bindings"] = []
    foreign = fixture["root"] / "data" / "processed" / "certificate.json"
    foreign.write_bytes(b"certificate")
    record["inputs"] = [
        {
            "bytes": len(b"ledger-v1"),
            "exists": True,
            "path": "data/processed/unified_route_quality.parquet",
            "sha256": _sha256_of(b"ledger-v1"),
        },
        {
            "bytes": len(b"partition"),
            "exists": True,
            "path": "data/unified/20240101.parquet",
            "sha256": _sha256_of(b"partition"),
        },
        {
            "bytes": len(b"certificate"),
            "exists": True,
            "path": "data/processed/certificate.json",
            "sha256": _sha256_of(b"certificate"),
        },
    ]
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    assert rebind_released_input_bindings(
        fixture["payload"],
        current_bindings=fixture["current_bindings"],
        migratable_paths=fixture["migratable"],
        rebind_note="rebind-test-note",
        sidecar=sidecar,
        root=fixture["root"],
    )
    rebound = json.loads(sidecar.read_text())
    by_path = {item["path"]: item for item in rebound["inputs"]}
    assert (
        by_path["data/processed/unified_route_quality.parquet"]["sha256"]
        == _sha256_of(b"ledger-v2")
    )
    assert by_path["data/unified/20240101.parquet"]["sha256"] == _sha256_of(
        b"partition"
    )
    assert by_path["data/processed/certificate.json"]["sha256"] == _sha256_of(
        b"certificate"
    )
    # a changed input outside the release perimeter is a refusal
    foreign.write_bytes(b"certificate-changed")
    record = json.loads(sidecar.read_text())
    record["inputs"][0]["sha256"] = _sha256_of(b"ledger-v1")  # re-stale one input
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    with pytest.raises(RuntimeError, match="outside the migrated"):
        rebind_released_input_bindings(
            fixture["payload"],
            current_bindings=fixture["current_bindings"],
            migratable_paths=fixture["migratable"],
            rebind_note="rebind-test-note",
            sidecar=sidecar,
            root=fixture["root"],
        )


def prepare_anchor_manifest(tmp_path: Path) -> dict[str, object]:
    """A minimal anchor manifest whose lineage cites the migration-owned pair."""

    root = tmp_path
    panel = root / "data" / "processed" / "unified_route_quality.parquet"
    panel.parent.mkdir(parents=True, exist_ok=True)
    panel.write_bytes(b"quality-ledger-v1")
    sidecar = (
        root / "data" / "manifests" / "data" / "processed"
        / "unified_route_quality.parquet.prov.json"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"artefact_sha256": "old"}\n')
    evidence = root / "data" / "raw" / "chunk.parquet"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"raw-evidence")
    lineage = [
        {
            "path": "data/manifests/data/processed/unified_route_quality.parquet.prov.json",
            "sha256": file_sha256(sidecar),
        },
        {"path": "data/processed/unified_route_quality.parquet", "sha256": file_sha256(panel)},
        {"path": "data/raw/chunk.parquet", "sha256": file_sha256(evidence)},
    ]
    manifest_path = root / "data" / "raw" / "v2_selected_anchors.json"
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "v2_token_decimals_selected_anchors",
                "lineage_inputs": lineage,
                "lineage_inputs_sha256": canonical_json_sha256(lineage),
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    ledger_path = root / "data" / "raw" / "v2_unresolved_tokens.json"
    ledger_path.write_text(
        json.dumps(
            {
                "kind": "unresolved_token_decimals",
                "anchors_sha256": "anchors-digest",
                "selected_anchor_manifest": {
                    "path": "data/raw/v2_selected_anchors.json",
                    "sha256": file_sha256(manifest_path),
                },
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["anchors_sha256"] = "anchors-digest"
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    ledger = json.loads(ledger_path.read_text())
    ledger["selected_anchor_manifest"]["sha256"] = file_sha256(manifest_path)
    ledger_path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    return {
        "root": root,
        "panel": panel,
        "sidecar": sidecar,
        "evidence": evidence,
        "manifest": manifest_path,
        "ledger": ledger_path,
    }


def test_anchor_manifest_repin_moves_only_migration_owned_records(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import (
        repin_anchor_manifest_migrated_lineage,
    )

    fixture = prepare_anchor_manifest(tmp_path)
    # the proven migration republished exactly the owned pair
    fixture["panel"].write_bytes(b"quality-ledger-v2")
    fixture["sidecar"].write_text('{"artefact_sha256": "new"}\n')
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "ok"},
    ):
        assert repin_anchor_manifest_migrated_lineage(
            manifest_path=fixture["manifest"],
            unresolved_ledger_path=fixture["ledger"],
            quality_panel=fixture["panel"],
            root=fixture["root"],
        )
        manifest = json.loads(fixture["manifest"].read_text())
        by_path = {
            record["path"]: record["sha256"]
            for record in manifest["lineage_inputs"]
        }
        assert by_path["data/processed/unified_route_quality.parquet"] == file_sha256(
            fixture["panel"]
        )
        assert by_path[
            "data/manifests/data/processed/unified_route_quality.parquet.prov.json"
        ] == file_sha256(fixture["sidecar"])
        assert by_path["data/raw/chunk.parquet"] == file_sha256(fixture["evidence"])
        assert manifest["lineage_inputs_sha256"] == canonical_json_sha256(
            manifest["lineage_inputs"]
        )
        repins = manifest["lineage_repins"]
        assert len(repins) == 1 and len(repins[0]["records"]) == 2
        ledger = json.loads(fixture["ledger"].read_text())
        assert ledger["selected_anchor_manifest"]["sha256"] == file_sha256(
            fixture["manifest"]
        )
        # a second run is a no-op
        assert not repin_anchor_manifest_migrated_lineage(
            manifest_path=fixture["manifest"],
            unresolved_ledger_path=fixture["ledger"],
            quality_panel=fixture["panel"],
            root=fixture["root"],
        )


def test_anchor_manifest_repin_refuses_foreign_lineage_drift(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import (
        repin_anchor_manifest_migrated_lineage,
    )

    fixture = prepare_anchor_manifest(tmp_path)
    fixture["panel"].write_bytes(b"quality-ledger-v2")
    fixture["evidence"].write_bytes(b"raw-evidence-tampered")
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "ok"},
    ):
        with pytest.raises(RuntimeError, match="foreign lineage drift"):
            repin_anchor_manifest_migrated_lineage(
                manifest_path=fixture["manifest"],
                unresolved_ledger_path=fixture["ledger"],
                quality_panel=fixture["panel"],
                root=fixture["root"],
            )


def test_anchor_manifest_repin_requires_current_panel_and_exact_digest(
    tmp_path: Path,
) -> None:
    from scripts.migrate_route_release_markers import (
        repin_anchor_manifest_migrated_lineage,
    )

    fixture = prepare_anchor_manifest(tmp_path)
    fixture["panel"].write_bytes(b"quality-ledger-v2")
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "stale"},
    ):
        with pytest.raises(RuntimeError, match="not\\s+current"):
            repin_anchor_manifest_migrated_lineage(
                manifest_path=fixture["manifest"],
                unresolved_ledger_path=fixture["ledger"],
                quality_panel=fixture["panel"],
                root=fixture["root"],
            )
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["lineage_inputs_sha256"] = "0" * 64
    fixture["manifest"].write_text(json.dumps(manifest) + "\n")
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "ok"},
    ):
        with pytest.raises(RuntimeError, match="lineage digest disagrees"):
            repin_anchor_manifest_migrated_lineage(
                manifest_path=fixture["manifest"],
                unresolved_ledger_path=fixture["ledger"],
                quality_panel=fixture["panel"],
                root=fixture["root"],
            )


def test_anchor_manifest_repin_recovers_lagged_ledger_pin(tmp_path: Path) -> None:
    """A ledger pinning the pre-repin manifest heals across a recorded repin."""

    from scripts.migrate_route_release_markers import (
        repin_anchor_manifest_migrated_lineage,
    )

    fixture = prepare_anchor_manifest(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["lineage_repins"] = [{"policy": "test", "records": []}]
    fixture["manifest"].write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    )
    # the manifest bytes moved with the recorded repin; the ledger pin lags
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "ok"},
    ):
        assert repin_anchor_manifest_migrated_lineage(
            manifest_path=fixture["manifest"],
            unresolved_ledger_path=fixture["ledger"],
            quality_panel=fixture["panel"],
            root=fixture["root"],
        )
    ledger = json.loads(fixture["ledger"].read_text())
    assert ledger["selected_anchor_manifest"]["sha256"] == file_sha256(
        fixture["manifest"]
    )


def test_anchor_manifest_repin_refuses_foreign_ledger_pin(tmp_path: Path) -> None:
    """A ledger pinning an unknown manifest state is never silently repinned."""

    from scripts.migrate_route_release_markers import (
        repin_anchor_manifest_migrated_lineage,
    )

    fixture = prepare_anchor_manifest(tmp_path)
    ledger = json.loads(fixture["ledger"].read_text())
    ledger["selected_anchor_manifest"]["sha256"] = "0" * 64
    fixture["ledger"].write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    fixture["panel"].write_bytes(b"quality-ledger-v2")
    with patch(
        "scripts.migrate_route_release_markers.verify",
        return_value={"status": "ok"},
    ):
        with pytest.raises(RuntimeError, match="different manifest state"):
            repin_anchor_manifest_migrated_lineage(
                manifest_path=fixture["manifest"],
                unresolved_ledger_path=fixture["ledger"],
                quality_panel=fixture["panel"],
                root=fixture["root"],
            )
