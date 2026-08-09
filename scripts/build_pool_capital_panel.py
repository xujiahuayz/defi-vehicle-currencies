#!/usr/bin/env python3
"""Materialize harmonized pool-day accounting capital before any estimator runs."""

from __future__ import annotations

from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.capital_contracts import (
    CAPITAL_CURRENT_COLUMN,
    CAPITAL_COLUMN,
    RETURN_CAPITAL_VALIDATION_STATUS,
    capital_contract,
    capital_supported,
    equal_candidate_capital_weights,
)
from ddvc.capital_validation import (
    CapitalPrice,
    canonical_constant_product_closing_reserves,
    capital_price_lookup,
    pool_day_reserve_state,
    validate_constant_product_capital,
    validated_capital_prices,
)
from ddvc.fetch.pool_daily import (
    POOL_DAILY_SCHEMAS,
    apply_pool_identity,
    load_pool_identity_crosswalk,
    pool_day_values,
    pool_identity_files,
    require_pool_daily_coverage,
)
from ddvc.panel_assembly import assert_unique_parquet_keys
from ddvc.paths import (
    DATA_DIR,
    POOL_CANDIDATE_CAPITAL_PANEL,
    POOL_CAPITAL_PANEL,
    POOL_CAPITAL_REJECTIONS,
    RAW_MARKET_DATA_LOCK,
    TOKEN_PRICE_DAILY_PANEL,
)
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.state_data import STATE_ROOT, read_cp_partition
from ddvc.tables import write_exhibit


RAW = DATA_DIR / "raw" / "thegraph"
OUT = POOL_CAPITAL_PANEL
CANDIDATE_OUT = POOL_CANDIDATE_CAPITAL_PANEL
REJECTIONS_OUT = POOL_CAPITAL_REJECTIONS
SUMMARY = DATA_DIR.parent / "output" / "exhibits" / "pool_capital_coverage.jsonl"
VENUES = tuple(
    venue
    for venue in POOL_DAILY_SCHEMAS
    if capital_supported(venue)
)

SCHEMA = pa.schema(
    [
        pa.field("venue", pa.string(), nullable=False),
        pa.field("day", pa.string(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token0_address", pa.string()),
        pa.field("token0_symbol", pa.string()),
        pa.field("token1_address", pa.string()),
        pa.field("token1_symbol", pa.string()),
        pa.field("reported_capital_usd", pa.float64()),
        pa.field("reported_capital_source", pa.string(), nullable=False),
        pa.field("reserve0", pa.float64()),
        pa.field("reserve1", pa.float64()),
        pa.field("reserve_source", pa.string(), nullable=False),
        pa.field("reserve_state_timestamp", pa.int64()),
        pa.field("reserve_validation_status", pa.string(), nullable=False),
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
        pa.field("pool", pa.string(), nullable=False),
        pa.field("pool_candidate_id", pa.string(), nullable=False),
        pa.field("candidate", pa.string(), nullable=False),
        pa.field("candidate_address", pa.string(), nullable=False),
        pa.field("candidate_symbol_raw", pa.string()),
        pa.field("allocation_weight", pa.float64(), nullable=False),
        pa.field("candidate_capital_usd", pa.float64(), nullable=False),
        pa.field("candidate_capital_usd_lagged", pa.float64()),
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
        pa.field("venue", pa.string(), nullable=False),
        pa.field("day", pa.string(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token0_address", pa.string()),
        pa.field("token0_symbol", pa.string()),
        pa.field("token1_address", pa.string()),
        pa.field("token1_symbol", pa.string()),
        pa.field("reported_capital_usd", pa.float64()),
        pa.field("reported_capital_source", pa.string(), nullable=False),
        pa.field("reconstructed_capital_usd", pa.float64()),
        pa.field("capital_reconciliation_ratio", pa.float64()),
        pa.field("balance_value_ratio", pa.float64()),
        pa.field("reserve_source", pa.string(), nullable=False),
        pa.field("reserve_state_timestamp", pa.int64()),
        pa.field("reserve_validation_status", pa.string(), nullable=False),
        pa.field("capital_source", pa.string(), nullable=False),
        pa.field("price_source", pa.string(), nullable=False),
        pa.field("quantity_kind", pa.string(), nullable=False),
        pa.field("pool_family", pa.string(), nullable=False),
        pa.field("invariant_family", pa.string(), nullable=False),
        pa.field("state_generation", pa.string(), nullable=False),
        pa.field("capital_validation_status", pa.string(), nullable=False),
        pa.field("failure_reason", pa.string(), nullable=False),
    ]
)


def daily_files(venue: str) -> list[Path]:
    pattern = f"{venue}_daily_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].jsonl.gz"
    return sorted((RAW / venue).glob(pattern))


def stamp_from_path(path: Path) -> str:
    stamp = path.name.removesuffix(".jsonl.gz").rsplit("_", 1)[-1]
    datetime.strptime(stamp, "%Y%m%d")
    return stamp


def with_exact_capital_lag(
    row: dict[str, object],
    *,
    venue: str,
    day: str,
    ordinal: int,
    prices: dict[str, CapitalPrice],
    prior: tuple[int, float, bool] | None,
) -> tuple[dict[str, object], tuple[int, float, bool]]:
    """Validate current capital and attach only an exact validated prior-day lag."""

    validation = validate_constant_product_capital(row, prices)
    current_valid = validation.valid
    current = float(validation.capital_usd) if current_valid else float("nan")
    lag_valid = bool(current_valid and prior and prior[0] == ordinal - 1 and prior[2])
    contract = capital_contract(venue)
    materialized = {
        **row,
        "venue": venue,
        "day": day,
        "reported_capital_source": row["capital_source"],
        "reconstructed_capital_usd": validation.reconstructed_capital_usd,
        CAPITAL_CURRENT_COLUMN: current if current_valid else None,
        CAPITAL_COLUMN: prior[1] if lag_valid else None,
        "capital_reconciliation_ratio": validation.reconciliation_ratio,
        "balance_value_ratio": validation.balance_value_ratio,
        "capital_source": contract.capital_sources[0],
        "price_source": validation.price_source,
        "quantity_kind": "deposited_capital",
        "pool_family": contract.pool_family,
        "invariant_family": contract.invariant_family,
        "state_generation": contract.state_generation,
        "capital_validation_status": (
            RETURN_CAPITAL_VALIDATION_STATUS
            if lag_valid
            else validation.validation_status
        ),
        "failure_reason": validation.failure_reason,
        "capital_valid": current_valid,
        "exact_lag_valid": lag_valid,
    }
    return materialized, (ordinal, current, current_valid)


def candidate_capital_rows(row: dict[str, object]) -> list[dict[str, object]]:
    """Allocate one valid pool's deposited capital once across candidate sides."""

    if not row["capital_valid"]:
        return []
    token_addresses = (
        str(row.get("token0_address") or "").lower(),
        str(row.get("token1_address") or "").lower(),
    )
    weights = equal_candidate_capital_weights(
        token_addresses,
        frozenset(VEHICLE_CANDIDATES),
    )
    if not weights:
        return []
    symbols = {
        token_addresses[0]: row.get("token0_symbol"),
        token_addresses[1]: row.get("token1_symbol"),
    }
    current = float(row[CAPITAL_CURRENT_COLUMN])
    lagged = float(row[CAPITAL_COLUMN]) if row["exact_lag_valid"] else None
    return [
        {
            "venue": row["venue"],
            "day": row["day"],
            "pool": row["pool"],
            "pool_candidate_id": f"{row['venue']}|{row['pool']}|{candidate}",
            "candidate": candidate,
            "candidate_address": address,
            "candidate_symbol_raw": symbols.get(address),
            "allocation_weight": weight,
            "candidate_capital_usd": weight * current,
            "candidate_capital_usd_lagged": weight * lagged if lagged is not None else None,
            "capital_source": row["capital_source"],
            "price_source": row["price_source"],
            "quantity_kind": "deposited_capital",
            "pool_family": row["pool_family"],
            "invariant_family": row["invariant_family"],
            "state_generation": row["state_generation"],
            "capital_validation_status": row["capital_validation_status"],
            "exact_lag_valid": row["exact_lag_valid"],
        }
        for address, weight in weights.items()
        for candidate in (VEHICLE_CANDIDATES[address],)
    ]


def capital_validation_rejection(row: dict[str, object]) -> dict[str, object] | None:
    """Write every failed current-capital validation to the rejection ledger."""

    if row["capital_valid"]:
        return None
    return {
        "venue": row["venue"],
        "day": row["day"],
        "pool": row["pool"],
        "token0_address": row["token0_address"],
        "token0_symbol": row["token0_symbol"],
        "token1_address": row["token1_address"],
        "token1_symbol": row["token1_symbol"],
        "reported_capital_usd": row["reported_capital_usd"],
        "reported_capital_source": row["reported_capital_source"],
        "reconstructed_capital_usd": row["reconstructed_capital_usd"],
        "capital_reconciliation_ratio": row["capital_reconciliation_ratio"],
        "balance_value_ratio": row["balance_value_ratio"],
        "reserve_source": row["reserve_source"],
        "reserve_state_timestamp": row["reserve_state_timestamp"],
        "reserve_validation_status": row["reserve_validation_status"],
        "capital_source": row["capital_source"],
        "price_source": row["price_source"],
        "quantity_kind": "deposited_capital",
        "pool_family": row["pool_family"],
        "invariant_family": row["invariant_family"],
        "state_generation": row["state_generation"],
        "capital_validation_status": row["capital_validation_status"],
        "failure_reason": row["failure_reason"],
    }


def missing_state_pool_keys(
    venue: str,
    capital_path: Path = OUT,
    state_root: Path = STATE_ROOT,
) -> list[tuple[str, str]]:
    """Return canonical constant-product pool-days absent from provider capital."""

    directory = state_root / "constant_product" / venue
    if not directory.is_dir():
        raise RuntimeError(f"canonical constant-product state is missing for {venue}")
    con = duckdb.connect()
    con.execute("SET threads=1")
    con.execute("SET memory_limit='1200MB'")
    con.execute("SET preserve_insertion_order=false")
    try:
        rows = con.execute(
            """
            WITH state AS (
                SELECT day, pool FROM read_parquet(?) GROUP BY day, pool
            ), capital AS (
                SELECT day, pool FROM read_parquet(?) WHERE venue=?
            )
            SELECT s.day, s.pool
            FROM state s LEFT JOIN capital c USING (day, pool)
            WHERE c.pool IS NULL
            ORDER BY s.day, s.pool
            """,
            [str(directory / "*.parquet"), str(capital_path), venue],
        ).fetchall()
    finally:
        con.close()
    return [(str(day), str(pool)) for day, pool in rows]


def state_coverage_rejections(
    venue: str,
    capital_path: Path = OUT,
    state_root: Path = STATE_ROOT,
) -> list[dict[str, object]]:
    """Represent every missing state/capital join as an explicit failed quantity."""

    keys = missing_state_pool_keys(venue, capital_path, state_root)
    if not keys:
        return []
    by_day: defaultdict[str, set[str]] = defaultdict(set)
    for day, pool in keys:
        by_day[day].add(pool)
    contract = capital_contract(venue)
    rows: list[dict[str, object]] = []
    columns = ["pool", "token0", "token1", "symbol0", "symbol1"]
    for day, pools in sorted(by_day.items()):
        path = state_root / "constant_product" / venue / f"{day}.parquet"
        table = pq.read_table(path, columns=columns)
        table = table.filter(
            pc.is_in(table["pool"], value_set=pa.array(sorted(pools)))
        )
        identities: dict[str, tuple[str, str, str | None, str | None]] = {}
        values = table.to_pydict()
        for pool, token0, token1, symbol0, symbol1 in zip(
            values["pool"],
            values["token0"],
            values["token1"],
            values["symbol0"],
            values["symbol1"],
            strict=True,
        ):
            if token0 is None or token1 is None:
                raise RuntimeError(
                    f"canonical state token identity missing for {venue} {day} {pool}"
                )
            identity = (
                str(token0).lower(),
                str(token1).lower(),
                str(symbol0) if symbol0 is not None else None,
                str(symbol1) if symbol1 is not None else None,
            )
            prior = identities.get(str(pool))
            if prior is not None and prior[:2] != identity[:2]:
                raise ValueError(f"state token identity changes within {venue} {day} {pool}")
            identities[str(pool)] = identity
        unresolved = pools.difference(identities)
        if unresolved:
            raise RuntimeError(
                f"canonical state identities missing for {venue} {day}: {len(unresolved):,}"
            )
        for pool in sorted(pools):
            token0, token1, symbol0, symbol1 = identities[pool]
            rows.append(
                {
                    "venue": venue,
                    "day": day,
                    "pool": pool,
                    "token0_address": token0,
                    "token0_symbol": symbol0,
                    "token1_address": token1,
                    "token1_symbol": symbol1,
                    "reported_capital_usd": None,
                    "reported_capital_source": "unavailable_missing_provider_pool_day",
                    "reconstructed_capital_usd": None,
                    "capital_reconciliation_ratio": None,
                    "balance_value_ratio": None,
                    "reserve_source": "unavailable_missing_provider_pool_day",
                    "reserve_state_timestamp": None,
                    "reserve_validation_status": "unavailable_missing_provider_pool_day",
                    "capital_source": contract.capital_sources[0],
                    "price_source": "unavailable_missing_provider_pool_day",
                    "quantity_kind": "deposited_capital",
                    "pool_family": contract.pool_family,
                    "invariant_family": contract.invariant_family,
                    "state_generation": contract.state_generation,
                    "capital_validation_status": "missing_pool_day_capital",
                    "failure_reason": "canonical state pool-day lacks provider capital",
                }
            )
    return rows


def append_state_coverage_rejections(
    venues: tuple[str, ...] = VENUES,
) -> tuple[int, dict[str, int], list[Path]]:
    """Stream the state/capital anti-join onto the existing rejection ledger."""

    counts: dict[str, int] = {}
    state_inputs: list[Path] = []
    added: list[dict[str, object]] = []
    for venue in venues:
        state_directory = STATE_ROOT / "constant_product" / venue
        state_inputs.append(state_directory)
        rejected = state_coverage_rejections(venue)
        counts[venue] = len(rejected)
        added.extend(rejected)
    existing = pq.ParquetFile(REJECTIONS_OUT)
    existing_rows = existing.metadata.num_rows
    with atomic_output(REJECTIONS_OUT) as temporary:
        writer = pq.ParquetWriter(temporary, REJECTION_SCHEMA, compression="snappy")
        try:
            for batch in existing.iter_batches(batch_size=100_000):
                writer.write_table(pa.Table.from_batches([batch], schema=REJECTION_SCHEMA))
            if added:
                writer.write_table(pa.Table.from_pylist(added, schema=REJECTION_SCHEMA))
        finally:
            writer.close()
        assert_unique_parquet_keys(temporary, ("venue", "day", "pool"))
    return existing_rows + len(added), counts, state_inputs


def materialize(
    prices_by_day: dict[str, dict[str, CapitalPrice]],
) -> tuple[int, int, int, list[dict[str, object]], list[Path]]:
    sources: list[Path] = [TOKEN_PRICE_DAILY_PANEL]
    summaries: list[dict[str, object]] = []
    total_rows = 0
    total_candidate_rows = 0
    total_rejection_rows = 0
    with ExitStack() as stack:
        temporary = stack.enter_context(atomic_output(OUT))
        candidate_temporary = stack.enter_context(atomic_output(CANDIDATE_OUT))
        rejection_temporary = stack.enter_context(atomic_output(REJECTIONS_OUT))
        writer = pq.ParquetWriter(temporary, SCHEMA, compression="snappy")
        candidate_writer = pq.ParquetWriter(
            candidate_temporary,
            CANDIDATE_SCHEMA,
            compression="snappy",
        )
        rejection_writer = pq.ParquetWriter(
            rejection_temporary,
            REJECTION_SCHEMA,
            compression="snappy",
        )
        try:
            for venue in VENUES:
                state_directory = STATE_ROOT / "constant_product" / venue
                sources.append(state_directory)
                files = daily_files(venue)
                if not files:
                    raise RuntimeError(f"no canonical pool-day source files for {venue}")
                sources.extend(files)
                identity_sources = pool_identity_files(venue, RAW)
                identities = load_pool_identity_crosswalk(identity_sources)
                sources.extend(identity_sources)
                last: dict[str, tuple[int, float, bool]] = {}
                counts: defaultdict[str, int] = defaultdict(int)
                pools: set[str] = set()
                candidate_pools: set[str] = set()
                for index, path in enumerate(files, 1):
                    day = stamp_from_path(path)
                    ordinal = datetime.strptime(day, "%Y%m%d").date().toordinal()
                    day_end_timestamp = int(
                        (
                            datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
                            + timedelta(days=1, seconds=-1)
                        ).timestamp()
                    )
                    reserve_states = canonical_constant_product_closing_reserves(
                        read_cp_partition(venue, day)
                    )
                    rows: list[dict[str, object]] = []
                    candidate_rows: list[dict[str, object]] = []
                    rejection_rows: list[dict[str, object]] = []
                    seen: set[str] = set()
                    with gzip.open(path, "rt") as handle:
                        for line in handle:
                            if not line.strip():
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                counts["invalid_json"] += 1
                                continue
                            row = pool_day_values(venue, record)
                            if row is None:
                                counts["unresolved_pool"] += 1
                                continue
                            row = apply_pool_identity(row, identities)
                            pool = str(row["pool"])
                            if pool in seen:
                                raise ValueError(f"duplicate {venue} pool-day row: {day} {pool}")
                            seen.add(pool)
                            reserve_state = pool_day_reserve_state(
                                row,
                                reserve_states.get(pool),
                                day_end_timestamp=day_end_timestamp,
                            )
                            row.update(
                                reserve0=reserve_state.reserve0,
                                reserve1=reserve_state.reserve1,
                                reserve_source=reserve_state.source,
                                reserve_state_timestamp=reserve_state.state_timestamp,
                                reserve_validation_status=reserve_state.validation_status,
                            )
                            row, current_state = with_exact_capital_lag(
                                row,
                                venue=venue,
                                day=day,
                                ordinal=ordinal,
                                prices=prices_by_day.get(day, {}),
                                prior=last.get(pool),
                            )
                            rows.append(row)
                            allocated = candidate_capital_rows(row)
                            candidate_rows.extend(allocated)
                            last[pool] = current_state
                            pools.add(pool)
                            candidate_pools.update(str(item["pool"]) for item in allocated)
                            counts["rows"] += 1
                            counts["capital_valid"] += int(row["capital_valid"])
                            counts["exact_lag_valid"] += int(row["exact_lag_valid"])
                            if row["failure_reason"]:
                                counts[f"rejected_{row['failure_reason']}"] += 1
                            rejection = capital_validation_rejection(row)
                            if rejection is not None:
                                rejection_rows.append(rejection)
                    if rows:
                        writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
                        total_rows += len(rows)
                        counts["days_with_rows"] += 1
                    if candidate_rows:
                        candidate_writer.write_table(
                            pa.Table.from_pylist(candidate_rows, schema=CANDIDATE_SCHEMA)
                        )
                        total_candidate_rows += len(candidate_rows)
                        counts["candidate_rows"] += len(candidate_rows)
                        counts["days_with_candidate_rows"] += 1
                    if rejection_rows:
                        rejection_writer.write_table(
                            pa.Table.from_pylist(rejection_rows, schema=REJECTION_SCHEMA)
                        )
                        total_rejection_rows += len(rejection_rows)
                        counts["rejection_rows"] += len(rejection_rows)
                        counts["rejected_reported_capital_usd"] += sum(
                            float(item["reported_capital_usd"] or 0.0)
                            for item in rejection_rows
                        )
                    if index % 250 == 0 or index == len(files):
                        print(f"  {venue}: {index}/{len(files)} days, {counts['rows']:,} rows", flush=True)
                summaries.append(
                    {
                        "venue": venue,
                        "source_days": len(files),
                        "days_with_rows": counts["days_with_rows"],
                        "empty_source_days": len(files) - counts["days_with_rows"],
                        "days_with_candidate_rows": counts["days_with_candidate_rows"],
                        "pools": len(pools),
                        "candidate_pools": len(candidate_pools),
                        "identity_crosswalk_pools": len(identities),
                        "identity_source_files": len(identity_sources),
                        **dict(counts),
                    }
                )
        finally:
            writer.close()
            candidate_writer.close()
            rejection_writer.close()
        assert_unique_parquet_keys(temporary, ("venue", "day", "pool"))
        assert_unique_parquet_keys(
            candidate_temporary,
            ("venue", "day", "pool", "candidate"),
        )
        assert_unique_parquet_keys(rejection_temporary, ("venue", "day", "pool"))
    return total_rows, total_candidate_rows, total_rejection_rows, summaries, sources


def main() -> int:
    for venue in VENUES:
        require_pool_daily_coverage(venue, daily_files(venue))
    require_current_artifacts(
        [TOKEN_PRICE_DAILY_PANEL],
        consumer="canonical pool-capital materializer",
    )
    price_rows = validated_capital_prices()
    prices_by_day = capital_price_lookup(price_rows)
    rows, candidate_rows, rejection_rows, summaries, sources = materialize(
        prices_by_day
    )
    rejection_rows, missing_state_counts, state_inputs = append_state_coverage_rejections()
    for summary in summaries:
        summary["missing_provider_state_rows"] = missing_state_counts.get(
            str(summary["venue"]), 0
        )
    code_sources = [
        "scripts/build_pool_capital_panel.py",
        "src/ddvc/fetch/pool_daily.py",
        "src/ddvc/fetch/sources.py",
        "src/ddvc/calendar.py",
        "src/ddvc/capital_contracts.py",
        "src/ddvc/capital_validation.py",
        "src/ddvc/asset_types.py",
        "src/ddvc/paths.py",
        "src/ddvc/state_data.py",
    ]
    stamp(
        OUT,
        code_sources=code_sources,
        inputs=sources,
        notes=(
            f"rows={rows}; venues={VENUES}; quantity=deposited_capital; "
            "current capital reconstructed from validated anchored reserve value"
        ),
    )
    stamp(
        CANDIDATE_OUT,
        code_sources=code_sources,
        inputs=sources,
        notes=(
            f"rows={candidate_rows}; venues={VENUES}; candidates="
            f"{tuple(VEHICLE_CANDIDATES.values())}; one pool's capital allocated once"
        ),
    )
    stamp(
        REJECTIONS_OUT,
        code_sources=code_sources,
        inputs=[*sources, *state_inputs],
        notes=(
            f"rows={rejection_rows}; quantity=deposited_capital; "
            "candidate allocation quarantined without exact token identity; "
            f"missing provider state rows={missing_state_counts}"
        ),
    )
    import pandas as pd

    write_exhibit(
        pd.DataFrame(summaries),
        SUMMARY,
        code_sources=code_sources,
        inputs=[OUT, CANDIDATE_OUT, REJECTIONS_OUT],
    )
    print(
        f"pool capital panel: {rows:,} pool rows; "
        f"{candidate_rows:,} candidate rows; {rejection_rows:,} quarantined rows"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        raise SystemExit(main())
