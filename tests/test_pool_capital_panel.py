from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.capital_validation import (
    CAPITAL_PRICE_SOURCE,
    CAPITAL_PRICE_VALIDATION_STATUS,
    CapitalPrice,
)
from ddvc.state_data import CP_COLUMNS
from scripts.process import build_pool_capital_panel as builder


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
POOL = "0x" + "01" * 20


@dataclass(frozen=True)
class Partition:
    day: str
    expected_bytes: int = 100
    expected_rows: int = 2


class FakeRelease:
    def __init__(self, venue: str, frames: dict[str, pd.DataFrame]):
        self.venue = venue
        self.frames = frames
        self.days = tuple(frames)
        self.partitions = tuple(
            Partition(day, expected_rows=int(frame["record_type"].eq("snapshot").sum()))
            for day, frame in frames.items()
        )
        self.input_paths: tuple[Path, ...] = ()

    def read_day(self, day: str) -> pd.DataFrame:
        return self.frames[day].copy()

    def assert_current(self) -> None:
        pass

    def source_rows(self, day: str) -> int:
        return int(self.frames[day]["record_type"].eq("snapshot").sum())


def cp_frame(day: str) -> pd.DataFrame:
    base = {column: None for column in CP_COLUMNS}
    rows = []
    for record_type, timestamp, reserve0, reserve1, delta0, delta1, order in (
        ("snapshot", 100, "10", "20000", None, None, 0),
        ("swap", 150, None, None, "1", "-1000", 1),
        ("snapshot", 200, "11", "19000", None, None, 2),
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


def no_provider(_venue: str, _day: str, _root: Path) -> builder.ProviderDiagnostic:
    return builder.ProviderDiagnostic({}, (), "provider_diagnostic_file_absent")


def storage_forecast(releases: dict[str, FakeRelease]) -> builder.CapitalStorageForecast:
    return builder.forecast_capital_storage(
        releases,
        prices_by_day=prices(*(day for release in releases.values() for day in release.days)),
        exact_decimals={WETH: 18, USDC: 6},
        sample_days_per_venue=2,
    )


def materialize(
    tmp_path: Path, release: FakeRelease, spec: builder.CapitalShard
) -> builder.ShardOutputs:
    return builder.materialize_shard(
        spec,
        release,
        prices(*release.days),
        {WETH: 18, USDC: 6},
        tmp_path,
        provider_loader=no_provider,
    )


def test_capital_uses_last_validated_snapshot_without_replaying_events() -> None:
    row = builder.closing_reserve_rows(
        cp_frame("20250101"), {WETH: 18, USDC: 6}
    )[0]
    assert row["reserve0"] == 11.0
    assert row["reserve1"] == 19_000.0
    assert row["reserve_state_timestamp"] == 200
    assert row["reserve_validation_status"] == "validated_last_hourly_reserve_snapshot"
    assert row["token_mechanics_status"] == "not_applicable_snapshot_measurement"


def test_capital_era_uses_the_canonical_v3_launch_boundary() -> None:
    assert builder._era("20210504") == "pre_uniswap_v3"
    assert builder._era("20210505") == "post_uniswap_v3"


def test_storage_forecast_scales_from_pool_day_cardinality() -> None:
    frames = {f"2025010{day}": cp_frame(f"2025010{day}") for day in range(1, 4)}
    forecast = storage_forecast({"uniswap_v2": FakeRelease("uniswap_v2", frames)})
    assert forecast.raw_input_bytes == 300
    assert forecast.sampled_pool_days == 2
    assert forecast.projected_pool_days == 4
    assert forecast.projected_release_bytes < 2 * 1024**3


def test_provider_capital_never_controls_scientific_eligibility() -> None:
    row = builder.closing_reserve_rows(
        cp_frame("20250101"), {WETH: 18, USDC: 6}
    )[0]
    base = {**row, **builder._provider_fields(None)}
    observed = {
        **row,
        **builder._provider_fields(
            {"reported_capital_usd": 1.0, "capital_source": "uniswap_v2.reserveUSD"}
        ),
    }
    kwargs = {
        "venue": "uniswap_v2",
        "day": "20250101",
        "ordinal": pd.Timestamp("2025-01-01").date().toordinal(),
        "prices": prices("20250101")["20250101"],
        "prior": None,
    }
    first, _ = builder.with_exact_capital_lag(base, **kwargs)
    distant, _ = builder.with_exact_capital_lag(observed, **kwargs)
    assert first["capital_valid"] and distant["capital_valid"]
    assert first["capital_usd"] == distant["capital_usd"] == 41_000.0


def test_shard_reads_predecessor_only_for_exact_lag_seed(tmp_path: Path) -> None:
    frames = {day: cp_frame(day) for day in ("20250101", "20250102")}
    release = FakeRelease("uniswap_v2", frames)
    spec = builder.CapitalShard(
        "uniswap_v2-01", "uniswap_v2", ("20250102",), "20250101", 100
    )
    outputs = materialize(tmp_path, release, spec)
    pool = pd.read_parquet(outputs.pool)
    assert pool["day"].tolist() == ["20250102"]
    assert pool["exact_lag_valid"].tolist() == [True]
    assert pool["capital_usd_lagged"].tolist() == [41_000.0]
    support = json.loads(outputs.manifest.read_text())["daily_support"]
    assert support[0]["status"] == "observed"


def test_shard_preserves_validated_empty_reserve_day(tmp_path: Path) -> None:
    release = FakeRelease("uniswap_v2", {"20250101": pd.DataFrame(columns=CP_COLUMNS)})
    spec = builder.CapitalShard("uniswap_v2-00", "uniswap_v2", ("20250101",), None, 100)
    outputs = materialize(tmp_path, release, spec)
    assert pq.ParquetFile(outputs.pool).metadata.num_rows == 0
    assert json.loads(outputs.manifest.read_text())["daily_support"][0]["status"] == "validated_empty"


def test_shard_validation_rejects_post_completion_mutation(tmp_path: Path) -> None:
    release = FakeRelease("uniswap_v2", {"20250101": cp_frame("20250101")})
    spec = builder.CapitalShard("uniswap_v2-00", "uniswap_v2", ("20250101",), None, 100)
    outputs = materialize(tmp_path, release, spec)
    outputs.pool.write_bytes(b"not parquet")
    with pytest.raises(RuntimeError, match="artifact failed validation"):
        builder._validate_shard_output(spec, release, outputs)


def test_shard_plan_is_bounded_contiguous_and_exact() -> None:
    uni = FakeRelease(
        "uniswap_v2",
        {f"202501{day:02d}": cp_frame(f"202501{day:02d}") for day in range(1, 15)},
    )
    sushi = FakeRelease(
        "sushiswap_v2",
        {f"202501{day:02d}": cp_frame(f"202501{day:02d}") for day in range(1, 4)},
    )
    releases = {"uniswap_v2": uni, "sushiswap_v2": sushi}
    specs = builder.plan_capital_shards(releases)
    assert len(specs) == 8
    builder.validate_capital_shard_plan(specs, releases)


def test_provider_overlap_summary_reports_capital_weight(tmp_path: Path) -> None:
    path = tmp_path / "candidate.parquet"
    rows = []
    for capital, overlap in ((90.0, "provider_row_positive_finite"), (10.0, "provider_row_absent")):
        rows.append(
            {
                field.name: (
                    "uniswap_v2" if field.name == "venue" else
                    "post_uniswap_v3" if field.name == "era" else
                    "WETH" if field.name == "candidate" else
                    capital if field.name == "candidate_capital_usd" else
                    overlap if field.name == "provider_overlap_status" else
                    "provider_overlap_within_diagnostic_bounds" if field.name == "provider_reconciliation_status" else
                    False if pa.types.is_boolean(field.type) else
                    1.0 if pa.types.is_floating(field.type) else "x"
                )
                for field in builder.CANDIDATE_SCHEMA
            }
        )
    pq.write_table(pa.Table.from_pylist(rows, schema=builder.CANDIDATE_SCHEMA), path)
    summary = builder.provider_overlap_summary([path]).iloc[0]
    assert summary["provider_overlap_row_share"] == 0.5
    assert summary["provider_overlap_capital_share"] == 0.9


def test_publication_installs_four_direct_outputs(tmp_path: Path) -> None:
    releases = {
        venue: FakeRelease(venue, {"20250101": cp_frame("20250101")})
        for venue in ("uniswap_v2", "sushiswap_v2")
    }
    specs = builder.plan_capital_shards(releases)
    stage = tmp_path / "shards"
    outputs = tuple(
        materialize(stage, releases[spec.venue], spec) for spec in specs
    )
    scientific = (tmp_path / "prices", tmp_path / "decimals")
    for path in scientific:
        path.write_text("input", encoding="utf-8")
    targets = {
        "pool": tmp_path / "pool.parquet",
        "candidate": tmp_path / "candidate.parquet",
        "rejection": tmp_path / "rejections.parquet",
        "overlap": tmp_path / "coverage.jsonl",
    }
    rows = builder.publish_shards(
        specs,
        releases,
        outputs,
        scientific_input_paths=scientific,
        storage_forecast=storage_forecast(releases),
        target_paths=targets,
    )
    assert all(path.is_file() for path in targets.values())
    assert rows["pool"] == 2
    assert rows["candidate"] == 4
