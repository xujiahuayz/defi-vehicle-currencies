#!/usr/bin/env python3
"""Build V2 deposited capital directly from validated hourly reserve snapshots.

Provider ``reserveUSD`` is retained only as an overlap diagnostic. It neither
defines the pool-day perimeter nor determines scientific row eligibility.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Iterable, Mapping, NamedTuple, Protocol

import numpy as np
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days, uniswap_v3_era
from ddvc.capital_data import (
    POOL_CANDIDATE_CAPITAL_DAILY,
    POOL_CAPITAL_COVERAGE,
    POOL_CAPITAL_DAILY,
    POOL_CAPITAL_REJECTIONS,
)
from ddvc.capital_contracts import (
    CAPITAL_COLUMN,
    CAPITAL_CURRENT_COLUMN,
    RETURN_CAPITAL_VALIDATION_STATUS,
    capital_contract,
    capital_supported,
    equal_candidate_capital_weights,
)
from ddvc.capital_validation import (
    CapitalPrice,
    capital_price_lookup,
    load_token_decimals,
    validate_constant_product_capital,
    validated_capital_prices,
)
from ddvc.cp_state_stream import CPStateStreamSet, cp_state_stream
from ddvc.fetch.sources import get_source
from ddvc.fetch.pool_daily import pool_day_values, verified_pool_provider_rows
from ddvc.panel_assembly import assert_unique_parquet_keys
from ddvc.paths import (
    DATA_DIR,
    POOL_CAPITAL_RELEASE_LOCK,
    TOKEN_PRICE_DAILY_PANEL,
    V2_TOKEN_DECIMALS_PANEL,
)
from ddvc.workflow import current_inputs
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import CP_COLUMNS


RAW = DATA_DIR / "raw" / "thegraph"
CAPITAL_DATA_TARGETS = {
    "pool": POOL_CAPITAL_DAILY,
    "candidate": POOL_CANDIDATE_CAPITAL_DAILY,
    "rejection": POOL_CAPITAL_REJECTIONS,
    "overlap": POOL_CAPITAL_COVERAGE,
}
VENUES = tuple(venue for venue in ("uniswap_v2", "sushiswap_v2") if capital_supported(venue))
PROVIDER_RATIO_BOUNDS = (0.5, 2.0)
CAPITAL_FORECAST_CARDINALITY_MARGIN = 1.25
CAPITAL_FORECAST_PEAK_MULTIPLIER = 2.25
CAPITAL_FORECAST_FIXED_BYTES = 1024**3
CAPITAL_FORECAST_RESERVE_BYTES = 10 * 1024**3


class CapitalPartition(Protocol):
    day: str
    expected_bytes: int
    expected_rows: int


class CapitalStateSource(Protocol):
    """Minimum immutable reserve-source contract required by the capital builder."""

    venue: str
    days: tuple[str, ...]
    partitions: tuple[CapitalPartition, ...]
    input_paths: tuple[Path, ...]

    def assert_current(self) -> None: ...

    def read_day(self, day: str) -> pd.DataFrame | Iterable[Mapping[str, object]]: ...

    def source_rows(self, day: str) -> int: ...


SCHEMA = pa.schema(
    [
        pa.field("venue", pa.string(), nullable=False),
        pa.field("day", pa.string(), nullable=False),
        pa.field("era", pa.string(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token0_address", pa.string()),
        pa.field("token0_symbol", pa.string()),
        pa.field("token1_address", pa.string()),
        pa.field("token1_symbol", pa.string()),
        pa.field("reported_capital_usd", pa.float64()),
        pa.field("reported_capital_source", pa.string(), nullable=False),
        pa.field("provider_overlap_status", pa.string(), nullable=False),
        pa.field("provider_reconciliation_status", pa.string(), nullable=False),
        pa.field("reserve0", pa.float64()),
        pa.field("reserve1", pa.float64()),
        pa.field("reserve_source", pa.string(), nullable=False),
        pa.field("reserve_state_timestamp", pa.int64()),
        pa.field("reserve_validation_status", pa.string(), nullable=False),
        pa.field("identity_validation_status", pa.string(), nullable=False),
        pa.field("token_mechanics_status", pa.string(), nullable=False),
        pa.field("reconstructed_capital_usd", pa.float64()),
        pa.field(CAPITAL_CURRENT_COLUMN, pa.float64()),
        pa.field(CAPITAL_COLUMN, pa.float64()),
        pa.field("capital_reconciliation_ratio", pa.float64()),
        pa.field("balance_value_ratio", pa.float64()),
        pa.field("reported_volume_usd", pa.float64()),
        pa.field("reported_fees_usd", pa.float64()),
        pa.field("capital_source", pa.string(), nullable=False),
        pa.field("price_source", pa.string(), nullable=False),
        pa.field("quantity_kind", pa.string(), nullable=False),
        pa.field("pool_family", pa.string(), nullable=False),
        pa.field("invariant_family", pa.string(), nullable=False),
        pa.field("state_generation", pa.string(), nullable=False),
        pa.field("capital_validation_status", pa.string(), nullable=False),
        pa.field("failure_reason", pa.string()),
        pa.field("capital_valid", pa.bool_(), nullable=False),
        pa.field("exact_lag_valid", pa.bool_(), nullable=False),
    ]
)

CANDIDATE_SCHEMA = pa.schema(
    [
        pa.field("venue", pa.string(), nullable=False),
        pa.field("day", pa.string(), nullable=False),
        pa.field("era", pa.string(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("pool_candidate_id", pa.string(), nullable=False),
        pa.field("candidate", pa.string(), nullable=False),
        pa.field("candidate_address", pa.string(), nullable=False),
        pa.field("candidate_symbol_raw", pa.string()),
        pa.field("allocation_weight", pa.float64(), nullable=False),
        pa.field("candidate_capital_usd", pa.float64(), nullable=False),
        pa.field("candidate_capital_usd_lagged", pa.float64()),
        pa.field("provider_overlap_status", pa.string(), nullable=False),
        pa.field("provider_reconciliation_status", pa.string(), nullable=False),
        pa.field("token_mechanics_status", pa.string(), nullable=False),
        pa.field("capital_source", pa.string(), nullable=False),
        pa.field("price_source", pa.string(), nullable=False),
        pa.field("quantity_kind", pa.string(), nullable=False),
        pa.field("pool_family", pa.string(), nullable=False),
        pa.field("invariant_family", pa.string(), nullable=False),
        pa.field("state_generation", pa.string(), nullable=False),
        pa.field("capital_validation_status", pa.string(), nullable=False),
        pa.field("exact_lag_valid", pa.bool_(), nullable=False),
    ]
)

REJECTION_SCHEMA = pa.schema(
    [
        *[field for field in SCHEMA if field.name not in {CAPITAL_CURRENT_COLUMN, CAPITAL_COLUMN, "capital_valid", "exact_lag_valid"}],
    ]
)


class CapitalShard(NamedTuple):
    shard_id: str
    venue: str
    owned_days: tuple[str, ...]
    predecessor_day: str | None
    expected_input_bytes: int


class ShardOutputs(NamedTuple):
    pool: Path
    candidate: Path
    rejection: Path
    manifest: Path


class CapitalStorageForecast(NamedTuple):
    raw_input_bytes: int
    sampled_days: int
    sampled_bytes: int
    sampled_pool_days: int
    sampled_release_bytes: int
    projected_pool_days: int
    projected_release_bytes: int
    peak_workspace_bytes: int


def _stratified_partition_sample(release: CPStateStreamSet, count: int) -> tuple:
    partitions = release.partitions
    if len(partitions) <= count:
        return partitions
    indices = sorted({round(index * (len(partitions) - 1) / (count - 1)) for index in range(count)})
    return tuple(partitions[index] for index in indices)


def forecast_capital_storage(
    releases: Mapping[str, CPStateStreamSet],
    *,
    prices_by_day: Mapping[str, Mapping[str, CapitalPrice]],
    exact_decimals: Mapping[str, int],
    sample_days_per_venue: int = 18,
) -> CapitalStorageForecast:
    """Project final and peak physical bytes from a stratified raw-backed pool sample."""

    if sample_days_per_venue < 2:
        raise ValueError("capital storage forecast requires at least two sample days per venue")
    raw_bytes = sampled_bytes = sampled_pool_days = sampled_days = 0
    projected_pool_days = 0
    sample_pool_rows: list[dict[str, object]] = []
    sample_candidate_rows: list[dict[str, object]] = []
    sample_rejection_rows: list[dict[str, object]] = []
    for release in releases.values():
        venue_bytes = sum(partition.expected_bytes for partition in release.partitions)
        raw_bytes += venue_bytes
        sample = _stratified_partition_sample(release, sample_days_per_venue)
        venue_sample_bytes = 0
        venue_sample_pools = 0
        for partition in sample:
            venue_sample_bytes += partition.expected_bytes
            source = release.read_day(partition.day)
            state = source if isinstance(source, pd.DataFrame) else pd.DataFrame.from_records(source, columns=CP_COLUMNS)
            pools = set(state["pool"].dropna().astype(str).str.lower())
            venue_sample_pools += len(pools)
            ordinal = datetime.strptime(partition.day, "%Y%m%d").date().toordinal()
            for base in closing_reserve_rows(state, exact_decimals):
                row, _current = with_exact_capital_lag(
                    {**base, **_provider_fields(None)},
                    venue=release.venue,
                    day=partition.day,
                    ordinal=ordinal,
                    prices=prices_by_day.get(partition.day, {}),
                    prior=None,
                )
                sample_pool_rows.append(row)
                sample_candidate_rows.extend(candidate_capital_rows(row))
                rejection = capital_validation_rejection(row)
                if rejection is not None:
                    sample_rejection_rows.append(rejection)
        sampled_days += len(sample)
        sampled_bytes += venue_sample_bytes
        sampled_pool_days += venue_sample_pools
        by_day = venue_sample_pools * len(release.partitions) / len(sample)
        by_bytes = venue_sample_pools * venue_bytes / max(1, venue_sample_bytes)
        projected_pool_days += math.ceil(max(by_day, by_bytes) * CAPITAL_FORECAST_CARDINALITY_MARGIN)
    with tempfile.TemporaryDirectory(prefix="ddvc-capital-storage-calibration-") as directory:
        sample_paths = []
        for name, rows, schema in (
            ("pool", sample_pool_rows, SCHEMA),
            ("candidate", sample_candidate_rows, CANDIDATE_SCHEMA),
            ("rejection", sample_rejection_rows, REJECTION_SCHEMA),
        ):
            path = Path(directory) / f"{name}.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
            sample_paths.append(path)
        sampled_release_bytes = sum(path.stat().st_size for path in sample_paths)
    bytes_per_pool_day = sampled_release_bytes / max(1, len(sample_pool_rows))
    release_bytes = math.ceil(projected_pool_days * bytes_per_pool_day) + CAPITAL_FORECAST_FIXED_BYTES
    peak_bytes = math.ceil(release_bytes * CAPITAL_FORECAST_PEAK_MULTIPLIER)
    return CapitalStorageForecast(raw_bytes, sampled_days, sampled_bytes, sampled_pool_days, sampled_release_bytes, projected_pool_days, release_bytes, peak_bytes)


def require_capital_storage_capacity(forecast: CapitalStorageForecast, path: Path) -> None:
    available = shutil.disk_usage(path).free
    required = forecast.peak_workspace_bytes + CAPITAL_FORECAST_RESERVE_BYTES
    if available < required:
        raise RuntimeError(
            f"capital build needs {required / 1024**3:.1f} GiB including reserve; "
            f"only {available / 1024**3:.1f} GiB is free"
        )


class ProviderDiagnostic(NamedTuple):
    rows: dict[str, dict[str, object]]
    input_paths: tuple[Path, ...]
    status: str


def _era(day: str) -> str:
    return uniswap_v3_era(day)


def _contiguous_byte_ranges(release: CapitalStateSource, pieces: int) -> list[tuple[str, ...]]:
    if pieces < 1:
        raise ValueError("capital shard count must be positive")
    partitions = list(release.partitions)
    if not partitions:
        raise ValueError(f"validated reserve perimeter is empty for {release.venue}")
    pieces = min(pieces, len(partitions))
    total = sum(max(1, partition.expected_bytes) for partition in partitions)
    ranges: list[tuple[str, ...]] = []
    start = 0
    consumed = 0
    for split in range(1, pieces):
        target = total * split / pieces
        stop = start
        while stop < len(partitions) - (pieces - split):
            consumed += max(1, partitions[stop].expected_bytes)
            stop += 1
            if consumed >= target:
                break
        ranges.append(tuple(partition.day for partition in partitions[start:stop]))
        start = stop
    ranges.append(tuple(partition.day for partition in partitions[start:]))
    if any(not days for days in ranges):
        raise RuntimeError("capital shard planner produced an empty range")
    return ranges


def plan_capital_shards(
    releases: Mapping[str, CapitalStateSource],
) -> tuple[CapitalShard, ...]:
    """Plan seven byte-balanced Uni ranges and one serial Sushi range."""

    if set(releases) != set(VENUES):
        raise ValueError("capital shard planner requires the exact admitted venue perimeter")
    specs: list[CapitalShard] = []
    for venue, pieces in (("uniswap_v2", 7), ("sushiswap_v2", 1)):
        release = releases[venue]
        days = list(release.days)
        positions = {day: index for index, day in enumerate(days)}
        bytes_by_day = {partition.day: partition.expected_bytes for partition in release.partitions}
        for index, owned in enumerate(_contiguous_byte_ranges(release, pieces)):
            first = positions[owned[0]]
            predecessor = days[first - 1] if first else None
            specs.append(
                CapitalShard(
                    shard_id=f"{venue}-{index:02d}",
                    venue=venue,
                    owned_days=owned,
                    predecessor_day=predecessor,
                    expected_input_bytes=sum(bytes_by_day[day] for day in owned),
                )
            )
    validate_capital_shard_plan(specs, releases)
    return tuple(specs)


def validate_capital_shard_plan(
    specs: Iterable[CapitalShard],
    releases: Mapping[str, CapitalStateSource],
) -> None:
    specs = tuple(specs)
    if not specs or len(specs) > 8 or len({spec.shard_id for spec in specs}) != len(specs):
        raise ValueError("capital build must have one to eight uniquely named shards")
    for venue, release in releases.items():
        selected = [spec for spec in specs if spec.venue == venue]
        flattened = [day for spec in selected for day in spec.owned_days]
        if flattened != list(release.days) or len(flattened) != len(set(flattened)):
            raise ValueError(f"capital shards do not exactly partition {venue}")
        positions = {day: index for index, day in enumerate(release.days)}
        for spec in selected:
            indices = [positions[day] for day in spec.owned_days]
            if indices != list(range(indices[0], indices[-1] + 1)):
                raise ValueError(f"capital shard is not contiguous: {spec.shard_id}")
            expected_predecessor = release.days[indices[0] - 1] if indices[0] else None
            if spec.predecessor_day != expected_predecessor:
                raise ValueError(f"capital shard predecessor is stale: {spec.shard_id}")


def assert_reserve_stream_current_stable(release: CapitalStateSource) -> None:
    """Revalidate a complete reserve stream with mutation detection around the scan."""

    paths = release.input_paths
    before = {path: path.stat() for path in paths}
    release.assert_current()
    changed = [
        path
        for path in paths
        if not path.is_file()
        or (
            path.stat().st_dev,
            path.stat().st_ino,
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        != (
            before[path].st_dev,
            before[path].st_ino,
            before[path].st_size,
            before[path].st_mtime_ns,
        )
    ]
    if changed:
        raise RuntimeError(f"validated reserve stream mutated during final revalidation: {changed[0]}")


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _pool_identity(rows: pd.DataFrame, exact_decimals: Mapping[str, int]) -> tuple[str, str, str | None, str | None, str]:
    identities = rows[["token0", "token1", "symbol0", "symbol1", "decimals0", "decimals1"]].drop_duplicates()
    address_pairs = identities[["token0", "token1"]].drop_duplicates()
    if len(address_pairs) != 1:
        return "", "", None, None, "quarantined_conflicting_exact_identity"
    first = identities.iloc[-1]
    token0, token1 = str(first["token0"] or "").lower(), str(first["token1"] or "").lower()
    if (
        len(token0) != 42
        or len(token1) != 42
        or not token0.startswith("0x")
        or not token1.startswith("0x")
        or any(character not in "0123456789abcdef" for character in token0[2:] + token1[2:])
        or token0 not in exact_decimals
        or token1 not in exact_decimals
    ):
        return token0, token1, None, None, "quarantined_missing_audited_decimals"
    observed0 = {int(value) for value in identities["decimals0"].dropna()}
    observed1 = {int(value) for value in identities["decimals1"].dropna()}
    if observed0 - {exact_decimals[token0]} or observed1 - {exact_decimals[token1]}:
        return token0, token1, None, None, "quarantined_decimals_disagreement"
    return (
        token0,
        token1,
        str(first["symbol0"]) if pd.notna(first["symbol0"]) else None,
        str(first["symbol1"]) if pd.notna(first["symbol1"]) else None,
        "exact_identity_and_decimals_passed",
    )


def closing_reserve_rows(
    state: pd.DataFrame,
    exact_decimals: Mapping[str, int],
) -> list[dict[str, object]]:
    """Return the last admissible validated reserve observation per pool-day."""

    missing = set(CP_COLUMNS) - set(state.columns)
    if missing:
        raise ValueError(f"validated hourly reserve state lacks columns: {sorted(missing)}")
    rows: list[dict[str, object]] = []
    for pool, pool_rows in state.groupby(state["pool"].astype(str).str.lower(), sort=True):
        snapshots = pool_rows.loc[pool_rows["record_type"].eq("snapshot")].copy()
        snapshots["period_end"] = pd.to_numeric(snapshots["period_end"], errors="coerce")
        snapshots = snapshots.dropna(subset=["period_end"]).sort_values("period_end")
        token0, token1, symbol0, symbol1, identity_status = _pool_identity(pool_rows, exact_decimals)
        if snapshots.empty:
            observed_timestamps = pd.to_numeric(pool_rows["timestamp"], errors="coerce").dropna()
            reserve0 = reserve1 = None
            timestamp = int(observed_timestamps.max()) if not observed_timestamps.empty else None
            reserve_status = "quarantined_missing_released_closing_snapshot"
        else:
            latest = snapshots.iloc[-1]
            reserve0, reserve1 = _decimal(latest["reserve0"]), _decimal(latest["reserve1"])
            timestamp = int(latest["period_end"])
            reserve_status = "validated_last_hourly_reserve_snapshot"
        rows.append(
            {
                "pool": pool,
                "token0_address": token0 or None,
                "token0_symbol": symbol0,
                "token1_address": token1 or None,
                "token1_symbol": symbol1,
                "reserve0": float(reserve0) if reserve0 is not None and reserve0 > 0 else None,
                "reserve1": float(reserve1) if reserve1 is not None and reserve1 > 0 else None,
                "reserve_source": "validated_hourly_reserve_snapshot",
                "reserve_state_timestamp": timestamp,
                "reserve_validation_status": reserve_status,
                "identity_validation_status": identity_status,
                "token_mechanics_status": "not_applicable_snapshot_measurement",
            }
        )
    return rows


def _provider_path(venue: str, day: str, raw_root: Path = RAW) -> Path:
    return raw_root / venue / f"{venue}_daily_{day}.jsonl.gz"


def provider_diagnostics(venue: str, day: str, raw_root: Path = RAW) -> ProviderDiagnostic:
    """Read an optional provider comparison without defining eligibility."""

    path = _provider_path(venue, day, raw_root)
    if not path.is_file():
        return ProviderDiagnostic({}, (), "provider_diagnostic_file_absent")
    result: dict[str, dict[str, object]] = {}
    inputs = [path, path.with_name(f"{venue}_meta_{day}.json")]
    existing = [item for item in inputs if item.exists()]
    before = {
        item: (item.stat().st_dev, item.stat().st_ino, item.stat().st_size, item.stat().st_mtime_ns)
        for item in existing
    }
    try:
        with verified_pool_provider_rows(venue, "daily", path) as records:
            for record in records:
                row = pool_day_values(venue, record)
                if row is None:
                    continue
                pool = str(row["pool"]).lower()
                if pool in result:
                    raise ValueError(f"duplicate provider diagnostic row: {venue} {day} {pool}")
                result[pool] = row
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return ProviderDiagnostic({}, tuple(existing), "provider_diagnostic_validation_failed")
    try:
        existing_after = [item for item in inputs if item.exists()]
        if existing_after != existing:
            return ProviderDiagnostic({}, tuple(existing), "provider_diagnostic_mutated_during_read")
        after = {
            item: (item.stat().st_dev, item.stat().st_ino, item.stat().st_size, item.stat().st_mtime_ns)
            for item in existing_after
        }
    except OSError:
        return ProviderDiagnostic({}, tuple(existing), "provider_diagnostic_mutated_during_read")
    if before != after:
        return ProviderDiagnostic({}, tuple(existing_after), "provider_diagnostic_mutated_during_read")
    return ProviderDiagnostic(result, tuple(existing), "provider_diagnostic_valid")


def _provider_fields(
    provider: Mapping[str, object] | None,
    *,
    diagnostic_status: str = "provider_diagnostic_valid",
) -> dict[str, object]:
    if provider is None:
        return {
            "reported_capital_usd": None,
            "reported_capital_source": "provider_diagnostic_absent",
            "reported_volume_usd": None,
            "reported_fees_usd": None,
            "provider_overlap_status": (
                "provider_row_absent"
                if diagnostic_status == "provider_diagnostic_valid"
                else diagnostic_status
            ),
        }
    reported = provider.get("reported_capital_usd")
    valid = reported is not None and np.isfinite(float(reported)) and float(reported) > 0
    return {
        "reported_capital_usd": float(reported) if valid else None,
        "reported_capital_source": str(provider.get("capital_source") or "provider_diagnostic_unknown"),
        "reported_volume_usd": provider.get("reported_volume_usd"),
        "reported_fees_usd": provider.get("reported_fees_usd"),
        "provider_overlap_status": "provider_row_positive_finite" if valid else "provider_row_nonpositive_or_invalid",
    }


def with_exact_capital_lag(
    row: dict[str, object],
    *,
    venue: str,
    day: str,
    ordinal: int,
    prices: Mapping[str, CapitalPrice],
    prior: tuple[int, float, bool] | None,
) -> tuple[dict[str, object], tuple[int, float, bool]]:
    validation = validate_constant_product_capital(row, prices)
    current_valid = validation.valid
    current = float(validation.capital_usd) if current_valid else float("nan")
    lag_valid = bool(current_valid and prior and prior[0] == ordinal - 1 and prior[2])
    ratio = validation.reconciliation_ratio
    provider_status = (
        "provider_not_observed"
        if ratio is None
        else "provider_overlap_within_diagnostic_bounds"
        if PROVIDER_RATIO_BOUNDS[0] <= ratio <= PROVIDER_RATIO_BOUNDS[1]
        else "provider_overlap_outside_diagnostic_bounds"
    )
    contract = capital_contract(venue)
    materialized = {
        **row,
        "venue": venue,
        "day": day,
        "era": _era(day),
        "reconstructed_capital_usd": validation.reconstructed_capital_usd,
        CAPITAL_CURRENT_COLUMN: current if current_valid else None,
        CAPITAL_COLUMN: prior[1] if lag_valid else None,
        "capital_reconciliation_ratio": ratio,
        "balance_value_ratio": validation.balance_value_ratio,
        "provider_reconciliation_status": provider_status,
        "capital_source": contract.capital_sources[0],
        "price_source": validation.price_source,
        "quantity_kind": "deposited_capital",
        "pool_family": contract.pool_family,
        "invariant_family": contract.invariant_family,
        "state_generation": contract.state_generation,
        "capital_validation_status": RETURN_CAPITAL_VALIDATION_STATUS if lag_valid else validation.validation_status,
        "failure_reason": validation.failure_reason,
        "capital_valid": current_valid,
        "exact_lag_valid": lag_valid,
    }
    return materialized, (ordinal, current, current_valid)


def candidate_capital_rows(row: Mapping[str, object]) -> list[dict[str, object]]:
    if not row["capital_valid"]:
        return []
    token_addresses = (str(row.get("token0_address") or "").lower(), str(row.get("token1_address") or "").lower())
    weights = equal_candidate_capital_weights(token_addresses, frozenset(VEHICLE_CANDIDATES))
    if not weights:
        return []
    symbols = {token_addresses[0]: row.get("token0_symbol"), token_addresses[1]: row.get("token1_symbol")}
    current = float(row[CAPITAL_CURRENT_COLUMN])
    lagged = float(row[CAPITAL_COLUMN]) if row["exact_lag_valid"] else None
    return [
        {
            "venue": row["venue"], "day": row["day"], "era": row["era"], "pool": row["pool"],
            "pool_candidate_id": f"{row['venue']}|{row['pool']}|{candidate}",
            "candidate": candidate, "candidate_address": address, "candidate_symbol_raw": symbols.get(address),
            "allocation_weight": weight, "candidate_capital_usd": weight * current,
            "candidate_capital_usd_lagged": weight * lagged if lagged is not None else None,
            "provider_overlap_status": row["provider_overlap_status"],
            "provider_reconciliation_status": row["provider_reconciliation_status"],
            "token_mechanics_status": row["token_mechanics_status"],
            "capital_source": row["capital_source"], "price_source": row["price_source"],
            "quantity_kind": "deposited_capital", "pool_family": row["pool_family"],
            "invariant_family": row["invariant_family"], "state_generation": row["state_generation"],
            "capital_validation_status": row["capital_validation_status"], "exact_lag_valid": row["exact_lag_valid"],
        }
        for address, weight in weights.items()
        for candidate in (VEHICLE_CANDIDATES[address],)
    ]


def capital_validation_rejection(row: Mapping[str, object]) -> dict[str, object] | None:
    if row["capital_valid"]:
        return None
    return {field.name: row.get(field.name) for field in REJECTION_SCHEMA}


def _shard_outputs(directory: Path, shard_id: str) -> ShardOutputs:
    return ShardOutputs(
        pool=directory / f"{shard_id}.pool.parquet",
        candidate=directory / f"{shard_id}.candidate.parquet",
        rejection=directory / f"{shard_id}.rejection.parquet",
        manifest=directory / f"{shard_id}.manifest.json",
    )


def materialize_shard(
    spec: CapitalShard,
    release: CapitalStateSource,
    prices_by_day: Mapping[str, Mapping[str, CapitalPrice]],
    exact_decimals: Mapping[str, int],
    output_directory: Path,
    *,
    raw_root: Path = RAW,
    provider_loader: Callable[[str, str, Path], ProviderDiagnostic] = provider_diagnostics,
) -> ShardOutputs:
    if spec.venue != release.venue:
        raise ValueError("capital shard and release venue differ")
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs = _shard_outputs(output_directory, spec.shard_id)
    counts = {"pool": 0, "candidate": 0, "rejection": 0}
    daily_support: list[dict[str, object]] = []
    prior: dict[str, tuple[int, float, bool]] = {}
    read_days = (*((spec.predecessor_day,) if spec.predecessor_day else ()), *spec.owned_days)
    with ExitStack() as stack:
        pool_temporary = stack.enter_context(atomic_output(outputs.pool))
        candidate_temporary = stack.enter_context(atomic_output(outputs.candidate))
        rejection_temporary = stack.enter_context(atomic_output(outputs.rejection))
        writers = {
            "pool": pq.ParquetWriter(pool_temporary, SCHEMA, compression="zstd"),
            "candidate": pq.ParquetWriter(candidate_temporary, CANDIDATE_SCHEMA, compression="zstd"),
            "rejection": pq.ParquetWriter(rejection_temporary, REJECTION_SCHEMA, compression="zstd"),
        }
        try:
            for day in read_days:
                state_source = release.read_day(day)
                state = state_source if isinstance(state_source, pd.DataFrame) else pd.DataFrame.from_records(state_source, columns=CP_COLUMNS)
                diagnostic = provider_loader(spec.venue, day, raw_root)
                ordinal = datetime.strptime(day, "%Y%m%d").date().toordinal()
                emitted = day in spec.owned_days
                day_pool_rows: list[dict[str, object]] = []
                day_candidate_rows: list[dict[str, object]] = []
                day_rejection_rows: list[dict[str, object]] = []
                for base in closing_reserve_rows(state, exact_decimals):
                    pool = str(base["pool"])
                    row = {
                        **base,
                        **_provider_fields(
                            diagnostic.rows.get(pool),
                            diagnostic_status=diagnostic.status,
                        ),
                    }
                    row, current_state = with_exact_capital_lag(
                        row,
                        venue=spec.venue,
                        day=day,
                        ordinal=ordinal,
                        prices=prices_by_day.get(day, {}),
                        prior=prior.get(pool),
                    )
                    prior[pool] = current_state
                    if not emitted:
                        continue
                    day_pool_rows.append(row)
                    day_candidate_rows.extend(candidate_capital_rows(row))
                    rejection = capital_validation_rejection(row)
                    if rejection is not None:
                        day_rejection_rows.append(rejection)
                if emitted:
                    source_rows = release.source_rows(day)
                    normalised_reserve_rows = int(state["record_type"].eq("snapshot").sum())
                    if normalised_reserve_rows != source_rows:
                        raise RuntimeError(
                            "validated reserve source and normalised row counts differ: "
                            f"{spec.venue}/{day} source={source_rows} normalised={normalised_reserve_rows}"
                        )
                    admitted_rows = len(day_pool_rows)
                    daily_support.append(
                        {
                            "day": day,
                            "source_rows": source_rows,
                            "normalised_reserve_rows": normalised_reserve_rows,
                            "pool_rows": admitted_rows,
                            "status": (
                                "validated_empty"
                                if source_rows == 0
                                else "observed"
                                if admitted_rows > 0
                                else "source_rows_none_admitted"
                            ),
                        }
                    )
                for name, rows, schema in (
                    ("pool", day_pool_rows, SCHEMA),
                    ("candidate", day_candidate_rows, CANDIDATE_SCHEMA),
                    ("rejection", day_rejection_rows, REJECTION_SCHEMA),
                ):
                    if rows:
                        writers[name].write_table(pa.Table.from_pylist(rows, schema=schema))
                        counts[name] += len(rows)
        finally:
            for writer in writers.values():
                writer.close()
    assert_unique_parquet_keys(outputs.pool, ("venue", "day", "pool"))
    assert_unique_parquet_keys(outputs.candidate, ("venue", "day", "pool", "candidate"))
    assert_unique_parquet_keys(outputs.rejection, ("venue", "day", "pool"))
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "spec": {**spec._asdict(), "owned_days": list(spec.owned_days)},
        "outputs": {
            "pool": {"rows": counts["pool"]},
            "candidate": {"rows": counts["candidate"]},
            "rejection": {"rows": counts["rejection"]},
        },
        "daily_support": daily_support,
    }
    with atomic_output(outputs.manifest) as temporary:
        temporary.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return outputs


def _materialize_payload(
    payload: tuple[
        CapitalShard,
        CapitalStateSource,
        dict[str, dict[str, CapitalPrice]],
        dict[str, int],
        Path,
        Path,
    ]
) -> ShardOutputs:
    spec, release, prices, decimals, output_directory, raw_root = payload
    return materialize_shard(
        spec,
        release,
        prices,
        decimals,
        output_directory,
        raw_root=raw_root,
    )


def _validate_shard_output(spec: CapitalShard, release: CapitalStateSource, outputs: ShardOutputs) -> dict[str, object]:
    manifest = json.loads(outputs.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"capital shard is incomplete: {spec.shard_id}")
    if manifest.get("spec") != {**spec._asdict(), "owned_days": list(spec.owned_days)}:
        raise RuntimeError(f"capital shard manifest scope differs: {spec.shard_id}")
    support = manifest.get("daily_support")
    if (
        not isinstance(support, list)
        or any(not isinstance(record, dict) for record in support)
        or [str(record.get("day")) for record in support] != list(spec.owned_days)
        or any(
            record.get("status") not in {"observed", "validated_empty", "source_rows_none_admitted"}
            or not isinstance(record.get("source_rows"), int)
            or int(record["source_rows"]) < 0
            or not isinstance(record.get("normalised_reserve_rows"), int)
            or int(record["normalised_reserve_rows"]) < 0
            or record["source_rows"] != record["normalised_reserve_rows"]
            or not isinstance(record.get("pool_rows"), int)
            or int(record["pool_rows"]) < 0
            or (record["status"] == "validated_empty") != (record["source_rows"] == 0)
            or (record["status"] == "observed") != (record["pool_rows"] > 0)
            for record in support
        )
    ):
        raise RuntimeError(f"capital shard support ledger differs: {spec.shard_id}")
    for name, path, schema in (
        ("pool", outputs.pool, SCHEMA),
        ("candidate", outputs.candidate, CANDIDATE_SCHEMA),
        ("rejection", outputs.rejection, REJECTION_SCHEMA),
    ):
        record = manifest["outputs"][name]
        try:
            valid = (
                pq.read_schema(path) == schema
                and pq.ParquetFile(path).metadata.num_rows == int(record["rows"])
            )
        except (OSError, TypeError, ValueError, pa.ArrowException):
            valid = False
        if not valid:
            raise RuntimeError(f"capital shard artifact failed validation: {spec.shard_id}/{name}")
    return manifest


def provider_overlap_summary(candidate_paths: Iterable[Path]) -> pd.DataFrame:
    paths = [path for path in candidate_paths if pq.ParquetFile(path).metadata.num_rows]
    columns = [
        "venue", "era", "candidate", "candidate_rows", "candidate_capital_usd",
        "provider_overlap_rows", "provider_overlap_capital_usd", "provider_disagreement_rows",
        "provider_disagreement_capital_usd", "provider_overlap_row_share", "provider_overlap_capital_share",
        "provider_disagreement_row_share", "provider_disagreement_capital_share", "materiality_status",
    ]
    if not paths:
        return pd.DataFrame(columns=columns)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='512MB'")
    try:
        grouped = connection.execute(
            """
            SELECT
                venue,
                era,
                candidate,
                count(*) AS candidate_rows,
                sum(candidate_capital_usd) AS candidate_capital_usd,
                count(*) FILTER (WHERE provider_overlap_status='provider_row_positive_finite') AS provider_overlap_rows,
                sum(candidate_capital_usd) FILTER (WHERE provider_overlap_status='provider_row_positive_finite') AS provider_overlap_capital_usd,
                count(*) FILTER (WHERE provider_reconciliation_status='provider_overlap_outside_diagnostic_bounds') AS provider_disagreement_rows,
                sum(candidate_capital_usd) FILTER (WHERE provider_reconciliation_status='provider_overlap_outside_diagnostic_bounds') AS provider_disagreement_capital_usd
            FROM read_parquet(?, union_by_name=true)
            GROUP BY venue, era, candidate
            ORDER BY venue, era, candidate
            """,
            [[str(path) for path in paths]],
        ).fetchdf()
    finally:
        connection.close()
    rows: list[dict[str, object]] = []
    for record in grouped.to_dict("records"):
        total_capital = float(record["candidate_capital_usd"])
        overlap_capital = 0.0 if pd.isna(record["provider_overlap_capital_usd"]) else float(record["provider_overlap_capital_usd"])
        disagreement_capital = 0.0 if pd.isna(record["provider_disagreement_capital_usd"]) else float(record["provider_disagreement_capital_usd"])
        overlap_rows = int(record["provider_overlap_rows"])
        disagreement_rows = int(record["provider_disagreement_rows"])
        candidate_rows = int(record["candidate_rows"])
        overlap_capital_share = overlap_capital / total_capital if total_capital else 0.0
        disagreement_capital_share = disagreement_capital / overlap_capital if overlap_capital else None
        materiality = (
            "indeterminate_provider_overlap_below_half_capital_weight"
            if overlap_capital_share < 0.5
            else "potentially_material_provider_disagreement"
            if disagreement_capital_share is not None and disagreement_capital_share > 0.1
            else "provider_disagreement_bounded_below_ten_percent_overlap_capital"
        )
        rows.append(
            dict(
                venue=str(record["venue"]), era=str(record["era"]), candidate=str(record["candidate"]),
                candidate_rows=candidate_rows, candidate_capital_usd=total_capital,
                provider_overlap_rows=overlap_rows, provider_overlap_capital_usd=overlap_capital,
                provider_disagreement_rows=disagreement_rows, provider_disagreement_capital_usd=disagreement_capital,
                provider_overlap_row_share=overlap_rows / candidate_rows, provider_overlap_capital_share=overlap_capital_share,
                provider_disagreement_row_share=disagreement_rows / overlap_rows if overlap_rows else None,
                provider_disagreement_capital_share=disagreement_capital_share, materiality_status=materiality,
            )
        )
    return pd.DataFrame(rows, columns=columns)


def _concatenate_shards(
    paths: Iterable[Path],
    schema: pa.Schema,
    target: Path,
    keys: tuple[str, ...],
    *,
    preinstall_validator: Callable[[Path], object],
) -> int:
    rows = 0
    with atomic_output(target) as temporary:
        writer = pq.ParquetWriter(temporary, schema, compression="zstd")
        try:
            for path in paths:
                parquet = pq.ParquetFile(path)
                for batch in parquet.iter_batches(batch_size=100_000):
                    writer.write_batch(batch)
                    rows += batch.num_rows
        finally:
            writer.close()
        if pq.read_schema(temporary) != schema:
            raise RuntimeError(f"capital publisher wrote a stale schema: {target.name}")
        assert_unique_parquet_keys(temporary, keys)
        preinstall_validator(temporary)
    return rows


def _publish_shards_unlocked(
    specs: Iterable[CapitalShard],
    releases: Mapping[str, CapitalStateSource],
    outputs: Iterable[ShardOutputs],
    *,
    scientific_input_paths: tuple[Path, ...],
    storage_forecast: CapitalStorageForecast | None = None,
    target_paths: Mapping[str, Path] = CAPITAL_DATA_TARGETS,
) -> dict[str, int]:
    """Validate temporary shards and install four direct processed outputs."""

    specs, outputs = tuple(specs), tuple(outputs)
    if len(specs) != len(outputs):
        raise ValueError("capital publisher received an incomplete shard set")
    if storage_forecast is None:
        raise ValueError("capital publisher requires measured storage calibration")
    if set(target_paths) != {"pool", "candidate", "rejection", "overlap"}:
        raise ValueError("capital publisher target map is incomplete")
    validate_capital_shard_plan(specs, releases)
    for spec, shard in zip(specs, outputs, strict=True):
        _validate_shard_output(spec, releases[spec.venue], shard)

    def validate_sources(_path: Path) -> None:
        for selected in releases.values():
            assert_reserve_stream_current_stable(selected)

    for selected in releases.values():
        assert_reserve_stream_current_stable(selected)

    with current_inputs(
        scientific_input_paths,
        consumer="pool-capital direct output publication",
    ), tempfile.TemporaryDirectory(prefix="ddvc-v2-capital-") as directory:
        assembled = Path(directory)
        staged = {
            "pool": assembled / "pool_capital_daily.parquet",
            "candidate": assembled / "pool_candidate_capital_daily.parquet",
            "rejection": assembled / "pool_capital_rejections.parquet",
            "overlap": assembled / "pool_capital_coverage.jsonl",
        }
        rows = {
            "pool": _concatenate_shards(
                (shard.pool for shard in outputs),
                SCHEMA,
                staged["pool"],
                ("venue", "day", "pool"),
                preinstall_validator=validate_sources,
            ),
            "candidate": _concatenate_shards(
                (shard.candidate for shard in outputs),
                CANDIDATE_SCHEMA,
                staged["candidate"],
                ("venue", "day", "pool", "candidate"),
                preinstall_validator=validate_sources,
            ),
            "rejection": _concatenate_shards(
                (shard.rejection for shard in outputs),
                REJECTION_SCHEMA,
                staged["rejection"],
                ("venue", "day", "pool"),
                preinstall_validator=validate_sources,
            ),
        }
        summary = provider_overlap_summary(shard.candidate for shard in outputs)
        summary.to_json(staged["overlap"], orient="records", lines=True)
        rows["overlap"] = len(summary)

        observed_bytes = sum(path.stat().st_size for path in staged.values())
        if observed_bytes > storage_forecast.projected_release_bytes:
            raise RuntimeError(
                "capital outputs exceeded the measured storage forecast: "
                f"observed={observed_bytes} "
                f"projected={storage_forecast.projected_release_bytes}"
            )
        for selected in releases.values():
            assert_reserve_stream_current_stable(selected)
        for name, target in target_paths.items():
            with atomic_output(target) as temporary:
                shutil.copyfile(staged[name], temporary)
    return rows


def publish_shards(
    specs: Iterable[CapitalShard],
    releases: Mapping[str, CapitalStateSource],
    outputs: Iterable[ShardOutputs],
    *,
    scientific_input_paths: tuple[Path, ...],
    storage_forecast: CapitalStorageForecast | None = None,
    target_paths: Mapping[str, Path] = CAPITAL_DATA_TARGETS,
) -> dict[str, int]:
    with exclusive_job(
        POOL_CAPITAL_RELEASE_LOCK,
        job="serial V2 capital output publication",
    ):
        return _publish_shards_unlocked(
            specs,
            releases,
            outputs,
            scientific_input_paths=scientific_input_paths,
            storage_forecast=storage_forecast,
            target_paths=target_paths,
        )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    releases = {
        venue: cp_state_stream(
            venue,
            calendar_days(
                max(RESEARCH_SAMPLE_START, get_source(venue).genesis.strftime("%Y%m%d")),
                RESEARCH_SAMPLE_END,
            ),
            raw_root=RAW,
        )
        for venue in VENUES
    }
    scientific_paths = tuple([
        TOKEN_PRICE_DAILY_PANEL,
        V2_TOKEN_DECIMALS_PANEL,
    ])
    decimals = load_token_decimals(V2_TOKEN_DECIMALS_PANEL)
    prices = capital_price_lookup(validated_capital_prices())
    storage = forecast_capital_storage(
        releases,
        prices_by_day=prices,
        exact_decimals=decimals,
    )
    print(
        "capital physical-byte forecast: "
        f"{storage.sampled_pool_days:,} observed pool-days across {storage.sampled_days:,} stratified days; "
        f"{storage.sampled_release_bytes / 1024**2:.2f} MiB measured sample output; "
        f"{storage.projected_pool_days:,} projected pool-days; "
        f"{storage.projected_release_bytes / 1024**3:.2f} GiB final; "
        f"{storage.peak_workspace_bytes / 1024**3:.2f} GiB peak workspace",
        flush=True,
    )
    require_capital_storage_capacity(storage, DATA_DIR)
    specs = plan_capital_shards(releases)
    workers = bounded_workers(args.workers, maximum=8)
    with tempfile.TemporaryDirectory(prefix="ddvc-v2-capital-shards-") as directory:
        stage = Path(directory)
        payloads = [
            (
                spec,
                releases[spec.venue],
                {
                    day: prices.get(day, {})
                    for day in (*((spec.predecessor_day,) if spec.predecessor_day else ()), *spec.owned_days)
                },
                decimals,
                stage,
                RAW,
            )
            for spec in specs
        ]
        with interruptible_process_pool(workers) as pool:
            outputs = tuple(pool.map(_materialize_payload, payloads, chunksize=1))
        rows = publish_shards(
            specs,
            releases,
            outputs,
            scientific_input_paths=scientific_paths,
            storage_forecast=storage,
        )
    print(
        "pool capital outputs: "
        f"{rows['pool']:,} pool rows; "
        f"{rows['candidate']:,} candidate rows; "
        f"{rows['rejection']:,} quarantined rows"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    with current_inputs(
        [TOKEN_PRICE_DAILY_PANEL, V2_TOKEN_DECIMALS_PANEL],
        consumer="released V2 capital materializer",
    ):
        return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
