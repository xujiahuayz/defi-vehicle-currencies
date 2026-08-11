#!/usr/bin/env python3
"""Build V2 deposited capital from the immutable node-D state release.

Provider ``reserveUSD`` is retained only as an overlap diagnostic. It neither
defines the pool-day perimeter nor determines scientific row eligibility.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Iterable, Mapping, NamedTuple

import numpy as np
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.artifact_release import canonical_json_sha256, file_sha256, file_stat_identity, publish_artifact_release
from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.calendar import uniswap_v3_era
from ddvc.capital_release import (
    CAPITAL_RELEASE_FILENAMES,
    CAPITAL_RELEASE_KIND,
    CAPITAL_RELEASE_POINTER,
    CAPITAL_RELEASE_SCHEMA_VERSION,
    exact_file_bindings,
    resolve_capital_release,
    validate_exact_file_bindings,
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
    validate_constant_product_capital,
    validated_capital_prices,
)
from ddvc.data_release import (
    ReleasedPartitionSet,
    release_preinstall_validator,
    released_state_partitions,
    require_market_state_prerelease,
    require_v2_event_source_release,
)
from ddvc.fetch.pool_daily import pool_day_values, verified_pool_provider_rows
from ddvc.fetch.raw import write_json
from ddvc.panel_assembly import assert_unique_parquet_keys
from ddvc.paths import (
    DATA_DIR,
    POOL_CAPITAL_RELEASE_LOCK,
    TOKEN_PRICE_DAILY_PANEL,
    V2_AUDITED_TOKEN_DECIMALS_REGISTRY,
)
from ddvc.provenance import code_fingerprint, require_current_artifacts, sidecar_path
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import CP_COLUMNS
from ddvc.token_decimals import validate_token_decimals_registry
from ddvc.v2_event_completeness import resolve_v2_event_source_release


RAW = DATA_DIR / "raw" / "thegraph"
VENUES = tuple(venue for venue in ("uniswap_v2", "sushiswap_v2") if capital_supported(venue))
PROVIDER_RATIO_BOUNDS = (0.5, 2.0)
LIMITED_TRANSITION_DIAGNOSTIC_REFERENCE_SHARE = 0.10
CAPITAL_CODE_SOURCES = [
    "scripts/build_pool_capital_panel.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/calendar.py",
    "src/ddvc/capital_contracts.py",
    "src/ddvc/capital_release.py",
    "src/ddvc/capital_validation.py",
    "src/ddvc/data_release.py",
    "src/ddvc/token_decimals.py",
]


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


class ProviderDiagnostic(NamedTuple):
    rows: dict[str, dict[str, object]]
    input_sha256: dict[str, str]
    status: str


def _era(day: str) -> str:
    return uniswap_v3_era(day)


def _contiguous_byte_ranges(release: ReleasedPartitionSet, pieces: int) -> list[tuple[str, ...]]:
    if pieces < 1:
        raise ValueError("capital shard count must be positive")
    partitions = list(release.partitions)
    if not partitions:
        raise ValueError(f"released state perimeter is empty for {release.venue}")
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
    releases: Mapping[str, ReleasedPartitionSet],
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
    releases: Mapping[str, ReleasedPartitionSet],
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


def assert_released_state_current_stable(release: ReleasedPartitionSet) -> None:
    """Revalidate a complete state release with mutation detection around the scan."""

    paths = (
        release.ledger_path,
        *(path for partition in release.partitions for path in (partition.path, partition.marker_path)),
    )
    before = {path: file_stat_identity(path) for path in paths}
    release.assert_current()
    changed = [path for path in paths if before[path] != file_stat_identity(path)]
    if changed:
        raise RuntimeError(f"released state mutated during final revalidation: {changed[0]}")


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


def _pool_mechanics_status(rows: pd.DataFrame) -> str:
    """Quarantine a pool-day when observed reserve transitions do not reconcile."""

    snapshots = rows.loc[rows["record_type"].eq("snapshot")].copy()
    snapshots["period_end"] = pd.to_numeric(snapshots["period_end"], errors="coerce")
    snapshots = snapshots.dropna(subset=["period_end"]).sort_values("period_end")
    if len(snapshots) < 2:
        return "no_detected_nonstandard_mechanics_limited_transition_support"
    events = rows.loc[rows["record_type"].isin(["swap", "liquidity"])].copy()
    events["timestamp"] = pd.to_numeric(events["timestamp"], errors="coerce")
    checked = 0
    for previous, current in zip(snapshots.iloc[:-1].to_dict("records"), snapshots.iloc[1:].to_dict("records"), strict=True):
        previous_state = (_decimal(previous["reserve0"]), _decimal(previous["reserve1"]))
        current_state = (_decimal(current["reserve0"]), _decimal(current["reserve1"]))
        if None in previous_state or None in current_state:
            return "quarantined_nonstandard_token_mechanics"
        start, end = int(previous["period_end"]), int(current["period_end"])
        between = events.loc[events["timestamp"].ge(start) & events["timestamp"].lt(end)]
        expected0, expected1 = previous_state
        assert expected0 is not None and expected1 is not None
        for event in between.sort_values(["block_number", "log_index"]).to_dict("records"):
            delta0, delta1 = _decimal(event["amount0_delta"]), _decimal(event["amount1_delta"])
            if delta0 is None or delta1 is None:
                return "quarantined_nonstandard_token_mechanics"
            expected0 += delta0
            expected1 += delta1
        actual0, actual1 = current_state
        assert actual0 is not None and actual1 is not None
        if expected0 <= 0 or expected1 <= 0 or actual0 <= 0 or actual1 <= 0:
            return "quarantined_nonstandard_token_mechanics"
        if abs(float((expected0 - actual0) / actual0)) >= 1e-9 or abs(float((expected1 - actual1) / actual1)) >= 1e-9:
            return "quarantined_nonstandard_token_mechanics"
        checked += 1
    return "reserve_transition_continuity_passed" if checked else "no_detected_nonstandard_mechanics_limited_transition_support"


def released_closing_reserve_rows(
    state: pd.DataFrame,
    exact_decimals: Mapping[str, int],
) -> list[dict[str, object]]:
    """Return one exact released closing-reserve record per pool."""

    missing = set(CP_COLUMNS) - set(state.columns)
    if missing:
        raise ValueError(f"released constant-product state lacks columns: {sorted(missing)}")
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
            later = pool_rows.loc[
                pool_rows["record_type"].isin(["swap", "liquidity"])
                & pd.to_numeric(pool_rows["timestamp"], errors="coerce").ge(timestamp)
            ].sort_values(["block_number", "log_index"])
            if reserve0 is not None and reserve1 is not None:
                for event in later.to_dict("records"):
                    delta0, delta1 = _decimal(event["amount0_delta"]), _decimal(event["amount1_delta"])
                    if delta0 is None or delta1 is None:
                        reserve0 = reserve1 = None
                        break
                    reserve0 += delta0
                    reserve1 += delta1
                    timestamp = max(timestamp, int(event["timestamp"]))
            reserve_status = "released_closing_state_replayed_through_last_event"
        rows.append(
            {
                "pool": pool,
                "token0_address": token0 or None,
                "token0_symbol": symbol0,
                "token1_address": token1 or None,
                "token1_symbol": symbol1,
                "reserve0": float(reserve0) if reserve0 is not None and reserve0 > 0 else None,
                "reserve1": float(reserve1) if reserve1 is not None and reserve1 > 0 else None,
                "reserve_source": "released_constant_product_closing_reserves",
                "reserve_state_timestamp": timestamp,
                "reserve_validation_status": reserve_status,
                "identity_validation_status": identity_status,
                "token_mechanics_status": _pool_mechanics_status(pool_rows),
            }
        )
    return rows


def _provider_path(venue: str, day: str, raw_root: Path = RAW) -> Path:
    return raw_root / venue / f"{venue}_daily_{day}.jsonl.gz"


def provider_diagnostics(venue: str, day: str, raw_root: Path = RAW) -> ProviderDiagnostic:
    """Read an optional provider comparison without defining eligibility."""

    path = _provider_path(venue, day, raw_root)
    if not path.is_file():
        return ProviderDiagnostic({}, {}, "provider_diagnostic_file_absent")
    result: dict[str, dict[str, object]] = {}
    inputs = [path, path.with_name(f"{venue}_meta_{day}.json")]
    existing = [item for item in inputs if item.exists()]
    before = {str(item): file_sha256(item) for item in existing}
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
        return ProviderDiagnostic({}, before, "provider_diagnostic_validation_failed")
    try:
        after = {str(item): file_sha256(item) for item in inputs}
    except OSError:
        return ProviderDiagnostic({}, before, "provider_diagnostic_mutated_during_read")
    if before != after:
        return ProviderDiagnostic({}, after, "provider_diagnostic_mutated_during_read")
    return ProviderDiagnostic(result, after, "provider_diagnostic_valid")


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
    release: ReleasedPartitionSet,
    prices_by_day: Mapping[str, Mapping[str, CapitalPrice]],
    exact_decimals: Mapping[str, int],
    output_directory: Path,
    *,
    raw_root: Path = RAW,
    provider_loader: Callable[[str, str, Path], ProviderDiagnostic] = provider_diagnostics,
    scientific_input_sha256: Mapping[str, str],
    scientific_input_paths: tuple[Path, ...],
) -> ShardOutputs:
    if spec.venue != release.venue:
        raise ValueError("capital shard and release venue differ")
    validate_exact_file_bindings(scientific_input_sha256, scientific_input_paths)
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs = _shard_outputs(output_directory, spec.shard_id)
    counts = {"pool": 0, "candidate": 0, "rejection": 0}
    provider_input_sha256: dict[str, str] = {}
    prior: dict[str, tuple[int, float, bool]] = {}
    read_days = (*((spec.predecessor_day,) if spec.predecessor_day else ()), *spec.owned_days)
    with ExitStack() as stack:
        pool_temporary = stack.enter_context(atomic_output(outputs.pool))
        candidate_temporary = stack.enter_context(atomic_output(outputs.candidate))
        rejection_temporary = stack.enter_context(atomic_output(outputs.rejection))
        writers = {
            "pool": pq.ParquetWriter(pool_temporary, SCHEMA, compression="snappy"),
            "candidate": pq.ParquetWriter(candidate_temporary, CANDIDATE_SCHEMA, compression="snappy"),
            "rejection": pq.ParquetWriter(rejection_temporary, REJECTION_SCHEMA, compression="snappy"),
        }
        try:
            for day in read_days:
                state = release.read_day(day)
                diagnostic = provider_loader(spec.venue, day, raw_root)
                for path, digest in diagnostic.input_sha256.items():
                    prior_digest = provider_input_sha256.setdefault(path, digest)
                    if prior_digest != digest:
                        raise RuntimeError(f"provider diagnostic identity changed within shard: {path}")
                ordinal = datetime.strptime(day, "%Y%m%d").date().toordinal()
                emitted = day in spec.owned_days
                day_pool_rows: list[dict[str, object]] = []
                day_candidate_rows: list[dict[str, object]] = []
                day_rejection_rows: list[dict[str, object]] = []
                for base in released_closing_reserve_rows(state, exact_decimals):
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
        "release_content_identity_sha256": release.content_identity_sha256,
        "scientific_input_sha256": dict(sorted(scientific_input_sha256.items())),
        "outputs": {
            "pool": {"rows": counts["pool"], "sha256": file_sha256(outputs.pool)},
            "candidate": {"rows": counts["candidate"], "sha256": file_sha256(outputs.candidate)},
            "rejection": {"rows": counts["rejection"], "sha256": file_sha256(outputs.rejection)},
        },
        "provider_diagnostic_inputs": [
            {"path": path, "sha256": provider_input_sha256[path]}
            for path in sorted(provider_input_sha256)
        ],
    }
    validate_exact_file_bindings(scientific_input_sha256, scientific_input_paths)
    manifest["identity_sha256"] = canonical_json_sha256(manifest)
    with atomic_output(outputs.manifest) as temporary:
        temporary.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return outputs


def _materialize_payload(payload: tuple[CapitalShard, ReleasedPartitionSet, dict[str, dict[str, CapitalPrice]], dict[str, int], Path, Path, dict[str, str], tuple[Path, ...]]) -> ShardOutputs:
    spec, release, prices, decimals, output_directory, raw_root, scientific_inputs, scientific_paths = payload
    return materialize_shard(
        spec,
        release,
        prices,
        decimals,
        output_directory,
        raw_root=raw_root,
        scientific_input_sha256=scientific_inputs,
        scientific_input_paths=scientific_paths,
    )


def _validate_shard_output(spec: CapitalShard, release: ReleasedPartitionSet, outputs: ShardOutputs) -> dict[str, object]:
    manifest = json.loads(outputs.manifest.read_text(encoding="utf-8"))
    identity = manifest.get("identity_sha256")
    body = {key: value for key, value in manifest.items() if key != "identity_sha256"}
    if identity != canonical_json_sha256(body):
        raise RuntimeError(f"capital shard manifest identity failed: {spec.shard_id}")
    if manifest.get("status") != "complete" or manifest.get("release_content_identity_sha256") != release.content_identity_sha256:
        raise RuntimeError(f"capital shard belongs to a stale release: {spec.shard_id}")
    if manifest.get("spec") != {**spec._asdict(), "owned_days": list(spec.owned_days)}:
        raise RuntimeError(f"capital shard manifest scope differs: {spec.shard_id}")
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
                and file_sha256(path) == record["sha256"]
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
        "limited_transition_rows", "limited_transition_capital_usd", "limited_transition_row_share",
        "limited_transition_capital_share", "limited_transition_materiality_status",
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
                sum(candidate_capital_usd) FILTER (WHERE provider_reconciliation_status='provider_overlap_outside_diagnostic_bounds') AS provider_disagreement_capital_usd,
                count(*) FILTER (WHERE token_mechanics_status='no_detected_nonstandard_mechanics_limited_transition_support') AS limited_transition_rows,
                sum(candidate_capital_usd) FILTER (WHERE token_mechanics_status='no_detected_nonstandard_mechanics_limited_transition_support') AS limited_transition_capital_usd
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
        limited_rows = int(record["limited_transition_rows"])
        limited_capital = 0.0 if pd.isna(record["limited_transition_capital_usd"]) else float(record["limited_transition_capital_usd"])
        overlap_capital_share = overlap_capital / total_capital if total_capital else 0.0
        disagreement_capital_share = disagreement_capital / overlap_capital if overlap_capital else None
        limited_row_share = limited_rows / candidate_rows
        limited_capital_share = limited_capital / total_capital if total_capital else 0.0
        materiality = (
            "indeterminate_provider_overlap_below_half_capital_weight"
            if overlap_capital_share < 0.5
            else "potentially_material_provider_disagreement"
            if disagreement_capital_share is not None and disagreement_capital_share > 0.1
            else "provider_disagreement_bounded_below_ten_percent_overlap_capital"
        )
        limited_materiality = (
            "limited_transition_support_above_ten_percent_diagnostic_reference"
            if max(limited_row_share, limited_capital_share)
            > LIMITED_TRANSITION_DIAGNOSTIC_REFERENCE_SHARE
            else "limited_transition_support_at_or_below_ten_percent_diagnostic_reference"
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
                limited_transition_rows=limited_rows, limited_transition_capital_usd=limited_capital,
                limited_transition_row_share=limited_row_share, limited_transition_capital_share=limited_capital_share,
                limited_transition_materiality_status=limited_materiality,
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
        writer = pq.ParquetWriter(temporary, schema, compression="snappy")
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
    releases: Mapping[str, ReleasedPartitionSet],
    outputs: Iterable[ShardOutputs],
    *,
    pointer_path: Path,
    scientific_input_sha256: Mapping[str, str],
    scientific_input_paths: tuple[Path, ...],
    v2_event_generation_id: str,
    upstream_validator: Callable[[], None],
    write_pointer: Callable[[Path, dict[str, object]], None] = write_json,
):
    """Validate all workers, then perform the only serial publication boundary."""

    specs, outputs = tuple(specs), tuple(outputs)
    if len(specs) != len(outputs):
        raise ValueError("capital publisher received an incomplete shard set")
    validate_capital_shard_plan(specs, releases)
    provider_input_sha256: dict[Path, str] = {}
    exact_scientific = validate_exact_file_bindings(scientific_input_sha256, scientific_input_paths)
    shard_manifests: list[dict[str, object]] = []
    for spec, shard in zip(specs, outputs, strict=True):
        manifest = _validate_shard_output(spec, releases[spec.venue], shard)
        shard_scientific = dict(manifest.get("scientific_input_sha256") or {})
        if shard_scientific != exact_scientific:
            raise RuntimeError("capital shards were built from different scientific inputs")
        shard_manifests.append(manifest)
        for record in manifest["provider_diagnostic_inputs"]:
            path = Path(str(record["path"]))
            digest = str(record["sha256"])
            if path in provider_input_sha256 and provider_input_sha256[path] != digest:
                raise RuntimeError(f"provider diagnostic input identity differs across shards: {path}")
            if not path.is_file() or file_sha256(path) != digest:
                raise RuntimeError(f"provider diagnostic input changed before publication: {path}")
            provider_input_sha256[path] = digest
    validator = release_preinstall_validator(*releases.values())
    for release in releases.values():
        assert_released_state_current_stable(release)
    with tempfile.TemporaryDirectory(prefix="ddvc-v2-capital-release-") as directory:
        assembled = Path(directory)
        staged = {
            name: assembled / filename
            for name, filename in CAPITAL_RELEASE_FILENAMES.items()
        }
        rows = {
            "pool": _concatenate_shards((shard.pool for shard in outputs), SCHEMA, staged["pool"], ("venue", "day", "pool"), preinstall_validator=validator),
            "candidate": _concatenate_shards((shard.candidate for shard in outputs), CANDIDATE_SCHEMA, staged["candidate"], ("venue", "day", "pool", "candidate"), preinstall_validator=validator),
            "rejection": _concatenate_shards((shard.rejection for shard in outputs), REJECTION_SCHEMA, staged["rejection"], ("venue", "day", "pool"), preinstall_validator=validator),
        }
        summary = provider_overlap_summary(shard.candidate for shard in outputs)
        summary.to_json(staged["overlap"], orient="records", lines=True)
        rows["overlap"] = len(summary)
        manifest = {
            "schema_version": CAPITAL_RELEASE_SCHEMA_VERSION,
            "kind": CAPITAL_RELEASE_KIND,
            "artifacts": {
                name: {"filename": CAPITAL_RELEASE_FILENAMES[name], "rows": rows[name], "sha256": file_sha256(staged[name])}
                for name in ("pool", "candidate", "rejection", "overlap")
            },
            "shards": shard_manifests,
            "released_state": {
                venue: {
                    "content_identity_sha256": release.content_identity_sha256,
                    "ledger_sha256": release.ledger_sha256,
                    "partitions": len(release.partitions),
                    "first_day": release.days[0],
                    "last_day": release.days[-1],
                }
                for venue, release in sorted(releases.items())
            },
            "upstream_releases": {"v2_event_source_generation_id": v2_event_generation_id},
            "scientific_inputs": dict(sorted(exact_scientific.items())),
            "code_sources": sorted(CAPITAL_CODE_SOURCES),
            "code_fingerprint": code_fingerprint(CAPITAL_CODE_SOURCES),
            "limited_transition_diagnostic_reference_share": LIMITED_TRANSITION_DIAGNOSTIC_REFERENCE_SHARE,
        }
        staged["manifest"].write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        rows["manifest"] = 1

        def validate_staged(paths: Mapping[str, Path]) -> None:
            if pq.read_schema(paths["pool"]) != SCHEMA or pq.read_schema(paths["candidate"]) != CANDIDATE_SCHEMA or pq.read_schema(paths["rejection"]) != REJECTION_SCHEMA:
                raise RuntimeError("capital release staged schema differs")
            assert_unique_parquet_keys(paths["pool"], ("venue", "day", "pool"))
            assert_unique_parquet_keys(paths["candidate"], ("venue", "day", "pool", "candidate"))
            assert_unique_parquet_keys(paths["rejection"], ("venue", "day", "pool"))
            validator(paths["pool"])
            validate_exact_file_bindings(exact_scientific, scientific_input_paths)
            if code_fingerprint(CAPITAL_CODE_SOURCES) != manifest["code_fingerprint"]:
                raise RuntimeError("capital generation code changed before publication")
            observed_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            if observed_manifest != manifest:
                raise RuntimeError("capital generation manifest changed during staging")
            for name in ("pool", "candidate", "rejection", "overlap"):
                if file_sha256(paths[name]) != manifest["artifacts"][name]["sha256"]:
                    raise RuntimeError(f"capital generation artifact changed during staging: {name}")

        def marker_last(path: Path, payload: dict[str, object]) -> None:
            upstream_validator()
            for release in releases.values():
                assert_released_state_current_stable(release)
            validate_exact_file_bindings(exact_scientific, scientific_input_paths)
            for provider_input, expected in provider_input_sha256.items():
                if not provider_input.is_file() or file_sha256(provider_input) != expected:
                    raise RuntimeError(f"provider diagnostic input changed at capital release boundary: {provider_input}")
            if code_fingerprint(CAPITAL_CODE_SOURCES) != manifest["code_fingerprint"]:
                raise RuntimeError("capital generation code changed at release boundary")
            write_pointer(path, payload)

        bundle = publish_artifact_release(
            pointer_path=pointer_path,
            kind=CAPITAL_RELEASE_KIND,
            schema_version=CAPITAL_RELEASE_SCHEMA_VERSION,
            filenames=CAPITAL_RELEASE_FILENAMES,
            writers={name: (lambda path, source=source: shutil.copyfile(source, path)) for name, source in staged.items()},
            row_counts=rows,
            code_sources=CAPITAL_CODE_SOURCES,
            inputs=[*scientific_input_paths, *sorted(provider_input_sha256), *(release.ledger_path for release in releases.values())],
            notes="released exact V2 deposited capital; provider fields diagnostic only",
            validate_staged=validate_staged,
            write_pointer=marker_last,
        )
    return resolve_capital_release(bundle.pointer_path)


def publish_shards(
    specs: Iterable[CapitalShard],
    releases: Mapping[str, ReleasedPartitionSet],
    outputs: Iterable[ShardOutputs],
    *,
    pointer_path: Path = CAPITAL_RELEASE_POINTER,
    scientific_input_sha256: Mapping[str, str],
    scientific_input_paths: tuple[Path, ...],
    v2_event_generation_id: str,
    upstream_validator: Callable[[], None],
    write_pointer: Callable[[Path, dict[str, object]], None] = write_json,
):
    with exclusive_job(
        POOL_CAPITAL_RELEASE_LOCK,
        job="serial released V2 capital publisher",
    ):
        return _publish_shards_unlocked(
            specs,
            releases,
            outputs,
            pointer_path=pointer_path,
            scientific_input_sha256=scientific_input_sha256,
            scientific_input_paths=scientific_input_paths,
            v2_event_generation_id=v2_event_generation_id,
            upstream_validator=upstream_validator,
            write_pointer=write_pointer,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    require_market_state_prerelease()
    require_v2_event_source_release()
    require_current_artifacts(
        [TOKEN_PRICE_DAILY_PANEL, V2_AUDITED_TOKEN_DECIMALS_REGISTRY],
        consumer="released V2 capital materializer",
    )
    releases = {venue: released_state_partitions("constant_product", venue, CP_COLUMNS) for venue in VENUES}
    specs = plan_capital_shards(releases)
    v2_release = resolve_v2_event_source_release()
    scientific_paths = tuple([
        TOKEN_PRICE_DAILY_PANEL,
        sidecar_path(TOKEN_PRICE_DAILY_PANEL),
        V2_AUDITED_TOKEN_DECIMALS_REGISTRY,
        sidecar_path(V2_AUDITED_TOKEN_DECIMALS_REGISTRY),
        v2_release.pointer_path,
        *v2_release.artifact_paths,
        *v2_release.provenance_paths,
    ])
    scientific_input_sha256 = exact_file_bindings(scientific_paths)
    decimals, _registry = validate_token_decimals_registry(V2_AUDITED_TOKEN_DECIMALS_REGISTRY)
    prices = capital_price_lookup(validated_capital_prices())
    validate_exact_file_bindings(scientific_input_sha256, scientific_paths)
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
                scientific_input_sha256,
                scientific_paths,
            )
            for spec in specs
        ]
        with interruptible_process_pool(workers) as pool:
            outputs = tuple(pool.map(_materialize_payload, payloads, chunksize=1))
        def upstream_validator() -> None:
            selected = resolve_v2_event_source_release()
            if selected.generation_id != v2_release.generation_id:
                raise RuntimeError("V2 event-source release changed during capital build")

        release = publish_shards(
            specs,
            releases,
            outputs,
            scientific_input_sha256=scientific_input_sha256,
            scientific_input_paths=scientific_paths,
            v2_event_generation_id=v2_release.generation_id,
            upstream_validator=upstream_validator,
        )
    rows = release.manifest["artifacts"]
    print(f"pool capital release {release.generation_id}: {rows['pool']['rows']:,} pool rows; {rows['candidate']['rows']:,} candidate rows; {rows['rejection']['rows']:,} quarantined rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
