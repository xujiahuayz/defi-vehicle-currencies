#!/usr/bin/env python3
"""Materialize harmonized pool-day accounting capital before any estimator runs."""

from __future__ import annotations

from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime
import gzip
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.capital_contracts import (
    CAPITAL_COLUMN,
    MAX_POOL_CAPITAL_USD,
    capital_contract,
    capital_supported,
    equal_candidate_capital_weights,
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
)
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output, exclusive_job
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
        pa.field(CAPITAL_COLUMN, pa.float64()),
        pa.field("reported_volume_usd", pa.float64()),
        pa.field("reported_fees_usd", pa.float64()),
        pa.field("capital_source", pa.string(), nullable=False),
        pa.field("quantity_kind", pa.string(), nullable=False),
        pa.field("pool_family", pa.string(), nullable=False),
        pa.field("invariant_family", pa.string(), nullable=False),
        pa.field("state_generation", pa.string(), nullable=False),
        pa.field("capital_validation_status", pa.string(), nullable=False),
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
        pa.field("token0_symbol", pa.string()),
        pa.field("token1_symbol", pa.string()),
        pa.field("reported_capital_usd", pa.float64(), nullable=False),
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


def valid_capital(value: object) -> bool:
    try:
        capital = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(capital) and 0 < capital <= MAX_POOL_CAPITAL_USD)


def with_exact_capital_lag(
    row: dict[str, object],
    *,
    venue: str,
    day: str,
    ordinal: int,
    prior: tuple[int, float, bool] | None,
) -> tuple[dict[str, object], tuple[int, float, bool]]:
    """Attach capital semantics while preserving a gap as a missing exact lag."""

    current = float(row["reported_capital_usd"])
    current_valid = valid_capital(current)
    lag_valid = bool(prior and prior[0] == ordinal - 1 and prior[2])
    contract = capital_contract(venue)
    materialized = {
        **row,
        "venue": venue,
        "day": day,
        CAPITAL_COLUMN: prior[1] if lag_valid else None,
        "quantity_kind": "deposited_capital",
        "pool_family": contract.pool_family,
        "invariant_family": contract.invariant_family,
        "state_generation": contract.state_generation,
        "capital_validation_status": (
            "reported_plausible" if current_valid else "quarantined"
        ),
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
    current = float(row["reported_capital_usd"])
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


def capital_identity_rejection(row: dict[str, object]) -> dict[str, object] | None:
    """Quarantine candidate allocation when capital exists but identity does not."""

    if not row["capital_valid"] or (row["token0_address"] and row["token1_address"]):
        return None
    return {
        "venue": row["venue"],
        "day": row["day"],
        "pool": row["pool"],
        "token0_symbol": row["token0_symbol"],
        "token1_symbol": row["token1_symbol"],
        "reported_capital_usd": row["reported_capital_usd"],
        "quantity_kind": "deposited_capital",
        "pool_family": row["pool_family"],
        "invariant_family": row["invariant_family"],
        "state_generation": row["state_generation"],
        "capital_validation_status": "quarantined_missing_exact_identity",
        "failure_reason": "candidate allocation requires exact token addresses",
    }


def materialize() -> tuple[int, int, int, list[dict[str, object]], list[Path]]:
    sources: list[Path] = []
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
                            row, current_state = with_exact_capital_lag(
                                row,
                                venue=venue,
                                day=day,
                                ordinal=ordinal,
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
                            counts["capital_valid_missing_token_identity"] += int(
                                row["capital_valid"]
                                and not (row["token0_address"] and row["token1_address"])
                            )
                            rejection = capital_identity_rejection(row)
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
                        counts["rejected_capital_usd"] += sum(
                            float(item["reported_capital_usd"])
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
    rows, candidate_rows, rejection_rows, summaries, sources = materialize()
    code_sources = [
        "scripts/build_pool_capital_panel.py",
        "src/ddvc/fetch/pool_daily.py",
        "src/ddvc/fetch/sources.py",
        "src/ddvc/calendar.py",
        "src/ddvc/capital_contracts.py",
        "src/ddvc/asset_types.py",
        "src/ddvc/paths.py",
    ]
    stamp(
        OUT,
        code_sources=code_sources,
        inputs=sources,
        notes=f"rows={rows}; venues={VENUES}; quantity=deposited_capital",
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
        inputs=sources,
        notes=(
            f"rows={rejection_rows}; quantity=deposited_capital; "
            "candidate allocation quarantined without exact token identity"
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
