from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import ddvc.provenance as provenance
from ddvc.artifact_release import file_sha256
from ddvc.asset_types import NATIVE, STABLE
from ddvc.data_release import ReleasedPartition, ReleasedPartitionSet
from ddvc.endpoint_candidate_composition import (
    ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES,
    ROUTE_INPUT_COLUMNS,
    endpoint_candidate_composition_for_day,
)
from ddvc.endpoint_candidate_composition_release import (
    publish_endpoint_candidate_composition_release,
    resolve_loaded_endpoint_candidate_composition_release,
    resolve_endpoint_candidate_composition_release,
    validate_endpoint_candidate_composition_paths,
)
from ddvc.provenance import sidecar_path
from scripts import build_endpoint_candidate_composition as builder


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
WETH = next(address for address, symbol in NATIVE.items() if symbol == "WETH")
USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")


def _leg(
    tx_hash: str,
    log_index: int,
    token_in: str,
    token_out: str,
    *,
    timestamp: int,
    source: str = "uniswap_v2",
    amount_usd: float = 100.0,
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "component_id": 0,
        "route_class": "coherent",
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": amount_usd,
        "log_index": log_index,
        "tin_role": "source",
        "tout_role": "sink",
        "timestamp_utc": timestamp,
    }


def _day_frame(timestamp: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _leg("weth", 0, SRC, WETH, timestamp=timestamp),
            _leg("weth", 1, WETH, TGT, timestamp=timestamp),
            _leg("usdc", 2, SRC, USDC, timestamp=timestamp),
            _leg(
                "usdc",
                3,
                USDC,
                TGT,
                timestamp=timestamp,
                source="sushiswap_v2",
            ),
        ]
    )[ROUTE_INPUT_COLUMNS]


def _route_release(
    root: Path,
    *,
    second_timestamp: int | None = None,
) -> ReleasedPartitionSet:
    route_root = root / "routes"
    route_root.mkdir(parents=True)
    ledger = root / "route-ledger.parquet"
    ledger.write_bytes(b"exact-ledger")
    frames = {
        "20240102": _day_frame(1_704_153_600),
        "20240103": (
            pd.DataFrame(columns=ROUTE_INPUT_COLUMNS)
            if second_timestamp is None
            else _day_frame(second_timestamp)
        ),
    }
    partitions = []
    provenance: list[Path] = [ledger]
    for day, frame in frames.items():
        path = route_root / f"{day}.parquet"
        marker = route_root / f"{day}.quality.json"
        frame.to_parquet(path, index=False)
        marker.write_text(json.dumps({"day": day, "passed": True}) + "\n")
        partitions.append(
            ReleasedPartition(
                day=day,
                path=path,
                marker_path=marker,
                expected_rows=len(frame),
                expected_bytes=path.stat().st_size,
                expected_sha256=file_sha256(path),
                marker_sha256=file_sha256(marker),
                input_fingerprint=("a" if day == "20240102" else "b") * 64,
            )
        )
        provenance.extend((path, marker))
    return ReleasedPartitionSet(
        kind="route",
        columns=tuple(ROUTE_INPUT_COLUMNS),
        ledger_path=ledger,
        ledger_sha256=file_sha256(ledger),
        partitions=tuple(partitions),
        content_identity_sha256="c" * 64,
        provenance_inputs=tuple(provenance),
    )


def _build(root: Path, release: ReleasedPartitionSet, pointer: Path):
    return builder.build_endpoint_candidate_composition_release(
        release,
        workers=1,
        pointer_path=pointer,
        scratch_parent=root / "scratch",
        lock_path=root / "build.lock",
    )


def test_full_perimeter_publishes_one_resolvable_bound_generation(tmp_path: Path) -> None:
    release = _route_release(tmp_path / "source")
    pointer = tmp_path / "release" / "current.json"
    outcome = _build(tmp_path, release, pointer)
    assert outcome.days == 2
    assert outcome.release is not None
    resolved = resolve_endpoint_candidate_composition_release(pointer)
    assert resolved.generation_id == outcome.release.generation_id
    assert set(resolved.artifacts) == {
        "choices",
        "choice_audit",
        "pair_support",
        "exclusions",
    }
    assert outcome.row_counts == {
        "choices": 2,
        "choice_audit": 2,
        "pair_support": 1,
        "exclusions": 0,
    }
    loaded = resolve_loaded_endpoint_candidate_composition_release(pointer)
    assert loaded.release.generation_id == resolved.generation_id
    assert len(loaded.composition.choices) == 2
    expected_bindings = {str(path.resolve()) for path in release.provenance_inputs}
    for artifact in resolved.artifacts.values():
        provenance = json.loads(sidecar_path(artifact).read_text(encoding="utf-8"))
        assert {record["path"] for record in provenance["released_input_bindings"]} == expected_bindings
        assert [record["path"] for record in provenance["inputs"]] == [
            str(release.ledger_path.resolve())
        ]


def test_staged_accounting_failure_cannot_replace_prior_release(tmp_path: Path) -> None:
    release = _route_release(tmp_path / "source")
    pointer = tmp_path / "release" / "current.json"
    outcome = _build(tmp_path, release, pointer)
    assert outcome.release is not None
    prior = pointer.read_bytes()
    sources = dict(outcome.release.artifacts)
    bad_support = pd.read_parquet(sources["pair_support"])
    bad_support.loc[0, "market_route_count"] += 1
    tampered = tmp_path / "bad-pair-support.parquet"
    bad_support.to_parquet(tampered, index=False)
    sources["pair_support"] = tampered
    with pytest.raises(ValueError, match="reconcile"):
        publish_endpoint_candidate_composition_release(
            writers={
                name: (lambda target, source=source: target.write_bytes(source.read_bytes()))
                for name, source in sources.items()
            },
            row_counts=outcome.row_counts,
            code_sources=builder.CODE_SOURCES,
            inputs=list(release.provenance_inputs),
            notes="tampered test generation",
            preinstall_validator=lambda _path: None,
            pointer_path=pointer,
        )
    assert pointer.read_bytes() == prior


def test_failed_day_and_interruption_preserve_previous_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _route_release(tmp_path / "source")
    pointer = tmp_path / "release" / "current.json"
    _build(tmp_path, release, pointer)
    prior = pointer.read_bytes()

    invalid = _route_release(
        tmp_path / "invalid-source",
        second_timestamp=1_704_153_600,
    )
    with pytest.raises(ValueError, match="outside supplied UTC day"):
        _build(tmp_path / "invalid-run", invalid, pointer)
    assert pointer.read_bytes() == prior

    original = builder.build_day_shard

    def interrupt(release_subset, day, scratch_root):
        if day == "20240103":
            raise KeyboardInterrupt
        return original(release_subset, day, scratch_root)

    monkeypatch.setattr(builder, "build_day_shard", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _build(tmp_path / "interrupted-run", release, pointer)
    assert pointer.read_bytes() == prior


def test_diagnostic_limit_validates_subset_without_creating_pointer(tmp_path: Path) -> None:
    release = _route_release(tmp_path / "source")
    pointer = tmp_path / "release" / "current.json"
    outcome = builder.build_endpoint_candidate_composition_release(
        release,
        workers=1,
        limit=1,
        pointer_path=pointer,
        scratch_parent=tmp_path / "scratch",
        lock_path=tmp_path / "build.lock",
    )
    assert outcome.days == 1
    assert outcome.release is None
    assert outcome.row_counts == {
        "choices": 2,
        "choice_audit": 2,
        "pair_support": 1,
        "exclusions": 0,
    }
    assert not pointer.exists()


def test_collision_audit_round_trips_through_release_schemas(tmp_path: Path) -> None:
    frame = pd.concat(
        [
            _day_frame(1_704_153_600),
            pd.DataFrame(
                [
                    _leg("collision", 10, SRC, WETH, timestamp=1_704_153_600),
                    _leg(
                        "collision",
                        10,
                        WETH,
                        TGT,
                        timestamp=1_704_153_600,
                        source="sushiswap_v2",
                    ),
                ]
            ),
        ],
        ignore_index=True,
    )[ROUTE_INPUT_COLUMNS]
    bundle = endpoint_candidate_composition_for_day(frame, "20240102")
    paths = {}
    for table in builder.TABLE_COLUMNS:
        path = tmp_path / f"{table}.parquet"
        builder._write_frame(getattr(bundle, table), path, table=table)
        paths[table] = path
    assert validate_endpoint_candidate_composition_paths(paths) == {
        "choices": len(bundle.choices),
        "choice_audit": len(bundle.choice_audit),
        "pair_support": len(bundle.pair_support),
        "exclusions": len(bundle.exclusions),
    }


def test_every_scientific_dependency_invalidates_the_release_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert set(ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES).issubset(
        builder.CODE_SOURCES
    )
    for relative in builder.CODE_SOURCES:
        source = provenance.ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    expected = provenance.code_fingerprint(builder.CODE_SOURCES)
    for relative in ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES:
        target = tmp_path / relative
        original = target.read_bytes()
        target.write_bytes(original + b"\n# scientific mutation\n")
        assert provenance.code_fingerprint(builder.CODE_SOURCES) != expected
        target.write_bytes(original)
