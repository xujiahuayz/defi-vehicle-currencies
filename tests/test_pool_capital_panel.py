from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.capital_validation import CAPITAL_PRICE_SOURCE, CAPITAL_PRICE_VALIDATION_STATUS, CapitalPrice
from ddvc.capital_release import exact_file_bindings, resolve_capital_release
from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.cp_state_stream import _reserve_identity
from ddvc.state_data import CP_COLUMNS, SCHEMA_VERSION, STATE_ENGINE
from scripts import build_pool_capital_panel as builder


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
POOL = "0x" + "01" * 20


@dataclass(frozen=True)
class Partition:
    day: str
    expected_bytes: int = 100
    expected_rows: int = 2
    path: Path = Path(__file__)
    marker_path: Path = Path(__file__)


class FakeRelease:
    def __init__(self, venue: str, frames: dict[str, pd.DataFrame]):
        self.venue = venue
        self.frames = frames
        self.days = tuple(frames)
        self.partitions = tuple(
            Partition(day, expected_rows=int(frame["record_type"].eq("snapshot").sum()))
            for day, frame in frames.items()
        )
        self.content_identity_sha256 = ("1" if venue == "uniswap_v2" else "2") * 64
        self.ledger_path = Path(__file__)
        self.ledger_sha256 = file_sha256(self.ledger_path)
        self.provenance_inputs = ()

    def read_day(self, day: str) -> pd.DataFrame:
        return self.frames[day].copy()

    def assert_current(self) -> None:
        return None

    def certified_rows(self, day: str) -> int:
        return int(self.frames[day]["record_type"].eq("snapshot").sum())

    def manifest_record(self) -> dict[str, object]:
        digest = file_sha256(Path(__file__))
        return {
            "authority_kind": "local_certified_reserve_stream_v1",
            "venue": self.venue,
            "content_identity_sha256": self.content_identity_sha256,
            "certificate_path": str(Path(__file__).resolve()),
            "certificate_sha256": digest,
            "ledger_path": str(Path(__file__).resolve()),
            "ledger_sha256": digest,
            "partitions": [
                {
                    "day": partition.day,
                    "expected_bytes": partition.expected_bytes,
                    "expected_rows": partition.expected_rows,
                    "input_fingerprint": "a" * 64,
                }
                for partition in self.partitions
            ],
        }


def cp_frame(day: str, *, broken: bool = False) -> pd.DataFrame:
    base = {column: None for column in CP_COLUMNS}
    rows = []
    for record_type, timestamp, reserve0, reserve1, delta0, delta1, order in (
        ("snapshot", 100, "10", "20000", None, None, 0),
        ("swap", 150, None, None, "1", "-1000", 1),
        ("snapshot", 200, "11", "18000" if broken else "19000", None, None, 2),
    ):
        rows.append(
            {
                **base,
                "schema_version": 1,
                "venue": "uniswap_v2",
                "day": day,
                "record_type": record_type,
                "source_stream": "hourly_reserves" if record_type == "snapshot" else "swaps",
                "event_id": f"{day}-{order}",
                "tx_hash": None if record_type == "snapshot" else "0x" + "02" * 32,
                "block_number": order,
                "log_index": order,
                "timestamp": timestamp,
                "period_start": timestamp - 100 if record_type == "snapshot" else None,
                "period_end": timestamp if record_type == "snapshot" else None,
                "pool": POOL,
                "pool_family": "full_range_constant_product",
                "invariant_family": "full_range_constant_product",
                "state_generation": "constant_product_state_v2",
                "token0_raw": WETH,
                "token1_raw": USDC,
                "token0": WETH,
                "token1": USDC,
                "symbol0": "WETH",
                "symbol1": "USDC",
                "decimals0": 18,
                "decimals1": 6,
                "amount0_delta": delta0,
                "amount1_delta": delta1,
                "reserve0": reserve0,
                "reserve1": reserve1,
                "quote_supported": True,
                "usable": True,
            }
        )
    return pd.DataFrame(rows, columns=CP_COLUMNS)


def prices(*days: str) -> dict[str, dict[str, CapitalPrice]]:
    return {
        day: {
            WETH: CapitalPrice(2_000.0, CAPITAL_PRICE_SOURCE, CAPITAL_PRICE_VALIDATION_STATUS),
            USDC: CapitalPrice(1.0, CAPITAL_PRICE_SOURCE, CAPITAL_PRICE_VALIDATION_STATUS),
        }
        for day in days
    }


def no_provider(_venue: str, _day: str, _root: Path):
    return builder.ProviderDiagnostic({}, {}, "provider_diagnostic_file_absent")


def scientific_inputs(tmp_path: Path) -> tuple[dict[str, str], tuple[Path, ...]]:
    paths = (tmp_path / "prices", tmp_path / "decimals", tmp_path / "certificate")
    for index, path in enumerate(paths):
        path.write_text(str(index), encoding="utf-8")
    return exact_file_bindings(paths), paths


def storage_forecast(releases: dict[str, FakeRelease]) -> builder.CapitalStorageForecast:
    return builder.forecast_capital_storage(
        releases,
        prices_by_day=prices(*(day for release in releases.values() for day in release.days)),
        exact_decimals={WETH: 18, USDC: 6},
        sample_days_per_venue=2,
    )


def test_capital_uses_last_certified_snapshot_without_replaying_events() -> None:
    exact = {WETH: 18, USDC: 6}
    clean = builder.released_closing_reserve_rows(cp_frame("20250101"), exact)[0]
    assert clean["reserve0"] == 11.0
    assert clean["reserve1"] == 19_000.0
    assert clean["identity_validation_status"] == "exact_identity_and_decimals_passed"
    assert clean["reserve_state_timestamp"] == 200
    assert clean["reserve_validation_status"] == "certified_last_hourly_reserve_snapshot"
    assert clean["token_mechanics_status"] == "not_applicable_snapshot_measurement"


def test_capital_era_uses_the_canonical_v3_launch_boundary() -> None:
    assert builder._era("20210504") == "pre_uniswap_v3"
    assert builder._era("20210505") == "post_uniswap_v3"


def test_storage_forecast_scales_from_thin_pool_day_cardinality() -> None:
    frames = {
        f"2025010{day}": cp_frame(f"2025010{day}")
        for day in range(1, 4)
    }
    release = FakeRelease("uniswap_v2", frames)
    forecast = builder.forecast_capital_storage(
        {"uniswap_v2": release},
        prices_by_day=prices(*frames),
        exact_decimals={WETH: 18, USDC: 6},
        sample_days_per_venue=2,
    )
    assert forecast.raw_input_bytes == 300
    assert forecast.sampled_pool_days == 2
    assert forecast.projected_pool_days == 4
    assert forecast.sampled_release_bytes > 0
    assert forecast.projected_release_bytes < 2 * 1024**3
    assert forecast.peak_workspace_bytes > forecast.projected_release_bytes


def test_day_without_reserve_observations_emits_no_invented_pool() -> None:
    frame = cp_frame("20250101")
    frame = frame.loc[~frame["record_type"].eq("snapshot")].reset_index(drop=True)
    assert builder.released_closing_reserve_rows(frame.iloc[0:0], {WETH: 18, USDC: 6}) == []


def test_missing_or_disagreeing_provider_capital_never_controls_eligibility() -> None:
    row = builder.released_closing_reserve_rows(cp_frame("20250101"), {WETH: 18, USDC: 6})[0]
    first, _state = builder.with_exact_capital_lag(
        {**row, **builder._provider_fields(None)},
        venue="uniswap_v2",
        day="20250101",
        ordinal=pd.Timestamp("2025-01-01").date().toordinal(),
        prices=prices("20250101")["20250101"],
        prior=None,
    )
    distant, _state = builder.with_exact_capital_lag(
        {**row, **builder._provider_fields({"reported_capital_usd": 1.0, "capital_source": "uniswap_v2.reserveUSD"})},
        venue="uniswap_v2",
        day="20250101",
        ordinal=pd.Timestamp("2025-01-01").date().toordinal(),
        prices=prices("20250101")["20250101"],
        prior=None,
    )
    assert first["capital_valid"] and distant["capital_valid"]
    assert first["capital_usd"] == distant["capital_usd"] == 41_000.0
    assert first["provider_reconciliation_status"] == "provider_not_observed"
    assert distant["provider_reconciliation_status"] == "provider_overlap_outside_diagnostic_bounds"


def test_invalid_optional_provider_file_is_typed_without_blocking_state_rows(tmp_path: Path) -> None:
    path = tmp_path / "uniswap_v2" / "uniswap_v2_daily_20250101.jsonl.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-gzip")
    diagnostic = builder.provider_diagnostics("uniswap_v2", "20250101", tmp_path)
    fields = builder._provider_fields(None, diagnostic_status=diagnostic.status)
    assert diagnostic.rows == {}
    assert diagnostic.status == "provider_diagnostic_validation_failed"
    assert fields["provider_overlap_status"] == "provider_diagnostic_validation_failed"


def test_shard_reads_predecessor_only_for_exact_lag_seed(tmp_path: Path) -> None:
    frames = {day: cp_frame(day) for day in ("20250101", "20250102")}
    release = FakeRelease("uniswap_v2", frames)
    spec = builder.CapitalShard("uniswap_v2-01", "uniswap_v2", ("20250102",), "20250101", 100)
    bindings, input_paths = scientific_inputs(tmp_path)
    outputs = builder.materialize_shard(
        spec,
        release,
        prices("20250101", "20250102"),
        {WETH: 18, USDC: 6},
        tmp_path,
        provider_loader=no_provider,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
    )
    pool = pd.read_parquet(outputs.pool)
    candidates = pd.read_parquet(outputs.candidate)
    assert pool["day"].tolist() == ["20250102"]
    assert pool["exact_lag_valid"].tolist() == [True]
    assert pool["capital_usd_lagged"].tolist() == [41_000.0]
    assert candidates.groupby("day")["candidate_capital_usd"].sum().to_dict() == {"20250102": 41_000.0}
    support = json.loads(outputs.manifest.read_text())["daily_support"]
    assert support == [
        {
            "day": "20250102",
            "certified_source_rows": 2,
            "normalised_reserve_rows": 2,
            "pool_rows": 1,
            "status": "observed",
        }
    ]


def test_shard_preserves_certified_empty_reserve_day(tmp_path: Path) -> None:
    empty = pd.DataFrame(columns=CP_COLUMNS)
    release = FakeRelease("uniswap_v2", {"20250101": empty})
    spec = builder.CapitalShard("uniswap_v2-00", "uniswap_v2", ("20250101",), None, 100)
    bindings, input_paths = scientific_inputs(tmp_path)
    outputs = builder.materialize_shard(
        spec,
        release,
        prices("20250101"),
        {WETH: 18, USDC: 6},
        tmp_path,
        provider_loader=no_provider,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
    )
    assert pq.ParquetFile(outputs.pool).metadata.num_rows == 0
    assert json.loads(outputs.manifest.read_text())["daily_support"] == [
        {
            "day": "20250101",
            "certified_source_rows": 0,
            "normalised_reserve_rows": 0,
            "pool_rows": 0,
            "status": "certified_empty",
        }
    ]


def test_shard_manifest_rejects_post_completion_mutation(tmp_path: Path) -> None:
    release = FakeRelease("uniswap_v2", {"20250101": cp_frame("20250101")})
    spec = builder.CapitalShard("uniswap_v2-00", "uniswap_v2", ("20250101",), None, 100)
    bindings, input_paths = scientific_inputs(tmp_path)
    outputs = builder.materialize_shard(
        spec,
        release,
        prices("20250101"),
        {WETH: 18, USDC: 6},
        tmp_path,
        provider_loader=no_provider,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
    )
    with outputs.pool.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(RuntimeError, match="artifact failed validation"):
        builder._validate_shard_output(spec, release, outputs)


def test_shard_requires_nonempty_exact_scientific_input_set(tmp_path: Path) -> None:
    release = FakeRelease("uniswap_v2", {"20250101": cp_frame("20250101")})
    spec = builder.CapitalShard("uniswap_v2-00", "uniswap_v2", ("20250101",), None, 100)
    with pytest.raises(ValueError, match="mandatory"):
        builder.materialize_shard(
            spec,
            release,
            prices("20250101"),
            {WETH: 18, USDC: 6},
            tmp_path,
            provider_loader=no_provider,
            scientific_input_sha256={},
            scientific_input_paths=(),
        )


def test_incomplete_shard_set_cannot_replace_existing_outputs(tmp_path: Path) -> None:
    uni = FakeRelease("uniswap_v2", {"20250101": cp_frame("20250101")})
    sushi = FakeRelease("sushiswap_v2", {"20250101": cp_frame("20250101")})
    specs = builder.plan_capital_shards({"uniswap_v2": uni, "sushiswap_v2": sushi})
    target = tmp_path / "existing.parquet"
    target.write_bytes(b"existing")
    bindings, input_paths = scientific_inputs(tmp_path)
    with pytest.raises(ValueError, match="incomplete shard set"):
        builder._publish_shards_unlocked(
            specs,
            {"uniswap_v2": uni, "sushiswap_v2": sushi},
            (),
            pointer_path=tmp_path / "release" / "current.json",
            scientific_input_sha256=bindings,
            scientific_input_paths=input_paths,
        )
    assert target.read_bytes() == b"existing"


def test_shard_plan_is_bounded_contiguous_and_exact() -> None:
    uni = FakeRelease("uniswap_v2", {f"202501{day:02d}": cp_frame(f"202501{day:02d}") for day in range(1, 15)})
    sushi = FakeRelease("sushiswap_v2", {f"202501{day:02d}": cp_frame(f"202501{day:02d}") for day in range(1, 4)})
    specs = builder.plan_capital_shards({"uniswap_v2": uni, "sushiswap_v2": sushi})
    assert len(specs) == 8
    assert sum(spec.venue == "uniswap_v2" for spec in specs) == 7
    assert sum(spec.venue == "sushiswap_v2" for spec in specs) == 1
    builder.validate_capital_shard_plan(specs, {"uniswap_v2": uni, "sushiswap_v2": sushi})
    duplicated = (*specs[:-1], specs[-1]._replace(owned_days=(specs[-1].owned_days[0],) * 2))
    with pytest.raises(ValueError, match="exactly partition"):
        builder.validate_capital_shard_plan(duplicated, {"uniswap_v2": uni, "sushiswap_v2": sushi})


def test_provider_overlap_summary_reports_row_and_capital_weight_materiality(tmp_path: Path) -> None:
    path = tmp_path / "candidate.parquet"
    rows = []
    for capital, overlap, reconciliation in (
        (90.0, "provider_row_positive_finite", "provider_overlap_within_diagnostic_bounds"),
        (10.0, "provider_row_absent", "provider_not_observed"),
    ):
        rows.append(
            {
                field.name: (
                    "uniswap_v2" if field.name == "venue" else "post_uniswap_v3" if field.name == "era" else
                    "WETH" if field.name == "candidate" else capital if field.name == "candidate_capital_usd" else
                    overlap if field.name == "provider_overlap_status" else reconciliation if field.name == "provider_reconciliation_status" else
                    False if pa.types.is_boolean(field.type) else 1.0 if pa.types.is_floating(field.type) else "x"
                )
                for field in builder.CANDIDATE_SCHEMA
            }
        )
    pq.write_table(pa.Table.from_pylist(rows, schema=builder.CANDIDATE_SCHEMA), path)
    summary = builder.provider_overlap_summary([path]).iloc[0]
    assert summary["provider_overlap_row_share"] == 0.5
    assert summary["provider_overlap_capital_share"] == 0.9
    assert summary["materiality_status"] == "provider_disagreement_bounded_below_ten_percent_overlap_capital"


def _complete_shards(
    tmp_path: Path,
    releases: dict[str, FakeRelease],
    bindings: dict[str, str],
    input_paths: tuple[Path, ...],
) -> tuple[tuple[builder.CapitalShard, ...], tuple[builder.ShardOutputs, ...]]:
    specs = builder.plan_capital_shards(releases)
    stage = tmp_path / "shards"
    outputs = tuple(
        builder.materialize_shard(
            spec,
            releases[spec.venue],
            prices(*releases[spec.venue].days),
            {WETH: 18, USDC: 6},
            stage,
            provider_loader=no_provider,
            scientific_input_sha256=bindings,
            scientific_input_paths=input_paths,
        )
        for spec in specs
    )
    return specs, outputs


def test_marker_last_capital_release_preserves_prior_generation_on_failure(tmp_path: Path) -> None:
    bindings, input_paths = scientific_inputs(tmp_path)
    releases = {
        venue: FakeRelease(venue, {"20250101": cp_frame("20250101")})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    specs, outputs = _complete_shards(tmp_path, releases, bindings, input_paths)
    pointer = tmp_path / "release" / "current.json"
    first = builder.publish_shards(
        specs,
        releases,
        outputs,
        pointer_path=pointer,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
        storage_forecast=storage_forecast(releases),
    )
    assert len(first.manifest["shards"]) == len(specs)
    changed_releases = {
        venue: FakeRelease(
            venue,
            {"20250101": cp_frame("20250101").assign(symbol0="WETH2")},
        )
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    changed_specs, changed_outputs = _complete_shards(
        tmp_path / "changed",
        changed_releases,
        bindings,
        input_paths,
    )

    def interrupted(_path: Path, _payload: dict[str, object]) -> None:
        raise RuntimeError("injected pointer failure")

    with pytest.raises(RuntimeError, match="injected pointer failure"):
        builder.publish_shards(
            changed_specs,
            changed_releases,
            changed_outputs,
            pointer_path=pointer,
            scientific_input_sha256=bindings,
            scientific_input_paths=input_paths,
            storage_forecast=storage_forecast(changed_releases),
            write_pointer=interrupted,
        )
    assert resolve_capital_release(pointer, require_current_inputs=False).generation_id == first.generation_id


def test_scientific_input_mutation_at_final_boundary_preserves_pointer(tmp_path: Path) -> None:
    bindings, input_paths = scientific_inputs(tmp_path)
    releases = {
        venue: FakeRelease(venue, {"20250101": cp_frame("20250101")})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    specs, outputs = _complete_shards(tmp_path, releases, bindings, input_paths)
    pointer = tmp_path / "release" / "current.json"

    def mutate_before_pointer(_path: Path, _payload: dict[str, object]) -> None:
        input_paths[0].write_text("mutated", encoding="utf-8")
        raise RuntimeError("injected pointer failure")

    with pytest.raises(RuntimeError, match="injected pointer failure"):
        builder.publish_shards(
            specs,
            releases,
            outputs,
            pointer_path=pointer,
            scientific_input_sha256=bindings,
            scientific_input_paths=input_paths,
            storage_forecast=storage_forecast(releases),
            write_pointer=mutate_before_pointer,
        )
    assert not pointer.exists()


def test_capital_release_resolver_rejects_post_release_scientific_input_mutation(tmp_path: Path) -> None:
    bindings, input_paths = scientific_inputs(tmp_path)
    releases = {
        venue: FakeRelease(venue, {"20250101": cp_frame("20250101")})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    specs, outputs = _complete_shards(tmp_path, releases, bindings, input_paths)
    pointer = tmp_path / "release" / "current.json"
    builder.publish_shards(
        specs,
        releases,
        outputs,
        pointer_path=pointer,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
        storage_forecast=storage_forecast(releases),
    )
    input_paths[0].write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance is not current|scientific input is stale"):
        resolve_capital_release(pointer)


def test_capital_release_resolver_reopens_exact_raw_partition_identity(tmp_path: Path, monkeypatch) -> None:
    bindings, input_paths = scientific_inputs(tmp_path)
    raw = tmp_path / "data" / "raw" / "thegraph" / "reserve.jsonl.gz"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"certified raw generation")
    certificate = tmp_path / "data" / "processed" / "raw_generation" / "certificate.json"
    certificate.parent.mkdir(parents=True)
    ledger = certificate.with_name("ledger.jsonl")
    certificate.write_text('{"partition_ledger":"ledger.jsonl"}\n', encoding="utf-8")
    ledger.write_text("immutable ledger\n", encoding="utf-8")

    def certified_row(venue: str, day: str) -> dict[str, object]:
        return {
            "source": venue,
            "stream": "hourly_reserves",
            "day": day,
            "logical_content_sha256": file_sha256(raw),
            "contract_sha256": "b" * 64,
            "observed_query_contract_sha256": "c" * 64,
            "observed_head_block_at_fetch": 123,
            "metadata_sha256": "d" * 64,
            "container_bytes": raw.stat().st_size,
            "rows": 2,
        }

    def load(_certificate, *, data_root, partitions):
        return [certified_row(partition.source, partition.day) for partition in partitions], {}

    monkeypatch.setattr("ddvc.cp_state_stream.load_certified_partition_ledger", load)
    releases = {
        venue: FakeRelease(venue, {"20250101": cp_frame("20250101")})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    for release in releases.values():
        row = certified_row(release.venue, "20250101")
        release.content_identity_sha256 = canonical_json_sha256(
            {
                "policy": "certified-cp-reserve-stream-v1",
                "schema_version": SCHEMA_VERSION,
                "normalizer_engine": STATE_ENGINE,
                "partitions": [
                    {"venue": release.venue, "day": "20250101", "input_fingerprint": _reserve_identity(row)}
                ],
            }
        )
        release.ledger_path = ledger
        release.ledger_sha256 = file_sha256(ledger)

        def manifest_record(selected=release, selected_row=row):
            return {
                "authority_kind": "local_certified_reserve_stream_v1",
                "venue": selected.venue,
                "content_identity_sha256": selected.content_identity_sha256,
                "certificate_path": str(certificate),
                "certificate_sha256": file_sha256(certificate),
                "ledger_path": str(ledger),
                "ledger_sha256": file_sha256(ledger),
                "partitions": [{
                    "day": "20250101",
                    "expected_bytes": selected_row["container_bytes"],
                    "expected_rows": selected_row["rows"],
                    "input_fingerprint": _reserve_identity(selected_row),
                }],
            }

        release.manifest_record = manifest_record
    specs, outputs = _complete_shards(tmp_path, releases, bindings, input_paths)
    pointer = tmp_path / "release" / "current.json"
    builder.publish_shards(
        specs,
        releases,
        outputs,
        pointer_path=pointer,
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
        storage_forecast=storage_forecast(releases),
    )
    resolve_capital_release(pointer)
    raw.write_bytes(b"mutated raw generation")
    with pytest.raises(ValueError, match="partition identity changed"):
        resolve_capital_release(pointer)


def test_snapshot_measurement_does_not_claim_event_transition_validation(tmp_path: Path) -> None:
    bindings, input_paths = scientific_inputs(tmp_path)
    one_snapshot = cp_frame("20250101").loc[lambda frame: ~frame["record_type"].eq("snapshot") | frame["period_end"].eq(200)]
    releases = {
        venue: FakeRelease(venue, {"20250101": one_snapshot})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    specs, outputs = _complete_shards(tmp_path, releases, bindings, input_paths)
    release = builder.publish_shards(
        specs,
        releases,
        outputs,
        pointer_path=tmp_path / "release" / "current.json",
        scientific_input_sha256=bindings,
        scientific_input_paths=input_paths,
        storage_forecast=storage_forecast(releases),
    )
    overlap = pd.read_json(release.artifacts["overlap"], lines=True)
    pool = pd.read_parquet(release.artifacts["pool"])
    assert pool["token_mechanics_status"].eq("not_applicable_snapshot_measurement").all()
