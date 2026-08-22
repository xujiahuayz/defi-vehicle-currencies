#!/usr/bin/env python3
"""Validate Uniswap v4 endpoint, intermediary, and leg-order labels on chain."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import time

import duckdb
import pandas as pd

from ddvc.analysis.v4_route_label_validation import (
    event_validation_counts,
    exact_swap,
    exact_swap_is_directional,
    initialize_registry,
    label_frame,
    pooled_metric_rows,
    provider_swap,
    provider_swap_is_directional,
    route_validation_counts,
)
from ddvc.ethereum_day_cuts import load_utc_day_block_bounds
from ddvc.ethereum_logs import RAW_LOG_STORAGE_FORMAT
from ddvc.fetch.raw import verified_source_day_rows
from ddvc.paths import DATA_DIR, OUTPUT_DIR, PRIMARY_REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.v4_contract import (
    UNISWAP_V4_INITIALIZE_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
    UNISWAP_V4_SWAP_TOPIC,
)


EXISTING_ROOT = DATA_DIR / "raw" / "ethereum" / "tick_state_events" / "chunks" / "uniswap_v4"
OWNED_ROOT = DATA_DIR / "raw" / "ethereum" / "v4_route_label_validation" / "chunks"
DEFAULT_OUTPUT = OUTPUT_DIR / "exhibits" / "v4_route_label_validation.jsonl"
EXECUTION_ONLY_COLUMNS = (
    "runtime_seconds",
    "parallel_shard_wall_seconds",
    "source_shards",
)
OUTPUT_COLUMN_ORDER = (
    "record_type",
    "day",
    "dimension",
    "true_positive",
    "provider_assignments",
    "exact_assignments",
    "precision",
    "recall",
    "scope_transactions",
    "provider_label_transactions",
    "exact_label_transactions",
    "union_label_transactions",
    "exact_match_transactions",
    "unconditional_exact_match_share",
    "conditional_exact_match_share",
    "scope",
    "transaction_hash",
    "provider_label",
    "exact_label",
)
SUPPORT_SUM_COLUMNS = (
    "requested_days",
    "covered_days",
    "skipped_days",
    "provider_swaps",
    "exact_swaps",
    "provider_zero_amount_swaps",
    "exact_zero_amount_swaps",
    "raw_amount_comparable_swaps",
    "v4_touch_observed_transactions",
    "v4_only_observed_transactions",
)
SUPPORT_CONSTANT_COLUMNS = (
    "route_scope",
    "route_provider_source",
    "cross_venue_scope",
    "poolmanager_direction_rule",
    "provider_amount_sign_mapping",
    "owned_exact_log_chunks",
)
CHAIN_COLUMNS = (
    "address",
    "block_number",
    "block_hash",
    "transaction_hash",
    "transaction_index",
    "log_index",
    "topics",
    "data",
    "removed",
)
EXISTING_GENERATION = "exact_v4_poolmanager_state_event_census_v1"
OWNED_GENERATION = "exact_v4_route_label_initialize_swap_v1"
REQUIRED_TOPICS = {UNISWAP_V4_INITIALIZE_TOPIC, UNISWAP_V4_SWAP_TOPIC}


def _mismatch_sort_key(row: dict[str, object]) -> tuple[object, ...]:
    priority = {
        "chain_only": 0,
        "provider_only": 0,
        "raw_amount_identity": 2,
        "raw_amount_unavailable": 3,
    }
    return (
        priority.get(str(row.get("reason")), 1),
        str(row.get("day") or ""),
        str(row.get("scope") or ""),
        str(row.get("dimension") or ""),
        str(row.get("transaction_hash") or ""),
        int(row.get("log_index") or -1),
    )


def _range_from_name(path: Path) -> tuple[int, int]:
    try:
        lower, upper = path.name.removeprefix("blocks_").removesuffix(".parquet").split("_", 1)
        return int(lower), int(upper)
    except ValueError as error:
        raise ValueError(f"invalid exact V4 chunk name: {path}") from error


def _complete_chunks(root: Path, *, existing: bool) -> list[tuple[int, int, Path]]:
    suffix = ".meta.json" if existing else ".complete.json"
    rows = []
    for path in sorted(root.glob("blocks_*.parquet")):
        lower, upper = _range_from_name(path)
        marker = path.with_name(path.name.removesuffix(".parquet") + suffix)
        if not marker.is_file():
            continue
        record = json.loads(marker.read_text(encoding="utf-8"))
        topics = {str(topic).lower() for topic in record.get("event_topics") or []}
        expected_generation = EXISTING_GENERATION if existing else OWNED_GENERATION
        topic_scope_ok = REQUIRED_TOPICS.issubset(topics) if existing else topics == REQUIRED_TOPICS
        if (
            record.get("status") != "complete"
            or int(record.get("start_block", -1)) != lower
            or int(record.get("end_block", -1)) != upper
            or record.get("generation") != expected_generation
            or not topic_scope_ok
            or str(record.get("address_filter") or "").lower()
            != UNISWAP_V4_POOL_MANAGER_ADDRESS
            or record.get("storage_format") != RAW_LOG_STORAGE_FORMAT
            or path.stat().st_size <= 0
        ):
            continue
        rows.append((lower, upper, path))
    return rows


def exact_chunks(existing_root: Path, owned_root: Path) -> list[tuple[int, int, Path]]:
    chunks = _complete_chunks(existing_root, existing=True) + _complete_chunks(
        owned_root, existing=False
    )
    chunks.sort(key=lambda row: (row[0], row[1], str(row[2])))
    for left, right in zip(chunks, chunks[1:]):
        if right[0] <= left[1]:
            raise ValueError(f"overlapping exact V4 chunks: {left[2]} and {right[2]}")
    return chunks


def covering_chunks(
    chunks: list[tuple[int, int, Path]],
    start_block: int,
    end_block: int,
) -> list[Path] | None:
    selected = [row for row in chunks if row[1] >= start_block and row[0] <= end_block]
    cursor = start_block
    paths = []
    for lower, upper, path in selected:
        if lower > cursor:
            return None
        if upper >= cursor:
            paths.append(path)
            cursor = upper + 1
        if cursor > end_block:
            return paths
    return None


def calendar_days(start: str, end: str) -> list[str]:
    lower = date.fromisoformat(start)
    upper = date.fromisoformat(end)
    if upper < lower:
        raise ValueError("V4 validation end precedes start")
    return [
        (lower + timedelta(days=offset)).isoformat()
        for offset in range((upper - lower).days + 1)
    ]


def chain_rows(
    paths: list[Path],
    *,
    topic: str,
    start_block: int,
    end_block: int,
    connection: duckdb.DuckDBPyConnection,
) -> list[dict[str, object]]:
    """Read one topic from complete chunks with block predicate pushdown."""

    if not paths:
        return []
    columns = ", ".join(CHAIN_COLUMNS)
    table = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?, union_by_name = true)
        WHERE block_number BETWEEN ? AND ?
          AND topics[1] = ?
        ORDER BY block_number, transaction_index, log_index
        """,
        [[str(path) for path in paths], start_block, end_block, topic],
    ).to_arrow_table()
    return table.to_pylist()


def provider_rows(data_root: Path, day: str) -> list[dict[str, object]]:
    stamp = date.fromisoformat(day)
    with verified_source_day_rows(
        "uniswap_v4", "swaps", stamp, data_root=data_root
    ) as rows:
        return [dict(row) for row in rows]


def token_decimals_for_rows(
    data_root: Path,
    rows: list[dict[str, object]],
    cache: dict[str, int | None],
) -> dict[str, int]:
    """Load existing exact ERC-20 decimals only for currencies used that day."""

    addresses = {
        str(token.get("id") or "").lower()
        for row in rows
        for token in (
            ((row.get("pool") or {}).get("token0") or {}),
            ((row.get("pool") or {}).get("token1") or {}),
        )
        if token.get("decimals") is None and token.get("id")
    }
    root = data_root / "raw" / "ethereum" / "token_decimals" / "decimals"
    for address in sorted(addresses - set(cache)):
        values = set()
        for path in (root / address).glob("block_*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("decimals") is not None:
                values.add(int(record["decimals"]))
        if len(values) > 1:
            raise ValueError(f"conflicting exact token decimals for {address}")
        cache[address] = next(iter(values)) if values else None
    return {
        address: int(value)
        for address, value in cache.items()
        if value is not None
    }


def observed_v4_only_routes(
    data_root: Path,
    day: str,
) -> tuple[pd.DataFrame, set[str], int]:
    """Return the published v4 rows for observed v4-only transactions."""

    path = data_root / "unified" / f"{day.replace('-', '')}.parquet"
    frame = pd.read_parquet(path)
    touched = frame[frame["source"].eq("uniswap_v4")]["tx_hash"].astype(str).unique()
    subset = frame[frame["tx_hash"].astype(str).isin(touched)]
    source_counts = subset.groupby("tx_hash")["source"].nunique()
    only = set(source_counts[source_counts.eq(1)].index.astype(str))
    provider_frame = frame[
        frame["tx_hash"].astype(str).isin(only)
        & frame["source"].eq("uniswap_v4")
    ].copy()
    return provider_frame, only, len(touched)


def _provider_metadata(rows: list[dict[str, object]]) -> dict[tuple[str, int], dict[str, object]]:
    metadata = {}
    for row in rows:
        key = str(row["transaction_hash"]), int(row["log_index"])
        if row["token_in"] == row["token0"]:
            token_in_symbol, token_out_symbol = row["token0_symbol"], row["token1_symbol"]
        else:
            token_in_symbol, token_out_symbol = row["token1_symbol"], row["token0_symbol"]
        metadata[key] = {
            **row,
            "token_in_symbol": token_in_symbol,
            "token_out_symbol": token_out_symbol,
        }
    return metadata


def validate_day(
    *,
    day: str,
    data_root: Path,
    day_paths: list[Path],
    pools: dict[str, dict[str, object]],
    connection: duckdb.DuckDBPyConnection,
    bounds: dict[str, object],
    decimals_cache: dict[str, int | None],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    started = time.monotonic()
    raw_provider = provider_rows(data_root, day)
    token_decimals = token_decimals_for_rows(data_root, raw_provider, decimals_cache)
    directional_provider = [
        row for row in raw_provider if provider_swap_is_directional(row)
    ]
    provider = [
        provider_swap(row, token_decimals=token_decimals)
        for row in directional_provider
    ]
    raw_exact = chain_rows(
        day_paths,
        topic=UNISWAP_V4_SWAP_TOPIC,
        start_block=int(bounds["start_block"]),
        end_block=int(bounds["end_block"]),
        connection=connection,
    )
    directional_exact = [row for row in raw_exact if exact_swap_is_directional(row)]
    exact = [exact_swap(row, pools) for row in directional_exact]
    event_rows, event_examples = event_validation_counts(provider, exact)
    provider_frame, v4_only, v4_touch = observed_v4_only_routes(data_root, day)
    metadata = _provider_metadata(provider)
    exact_frame = label_frame(
        [row for row in exact if row["transaction_hash"] in v4_only],
        metadata=metadata,
    )
    route_rows, route_examples = route_validation_counts(
        provider_frame,
        exact_frame,
        day=day,
        transactions=v4_only,
    )
    records = [
        {"record_type": "event_label", "day": day, **row} for row in event_rows
    ] + [
        {"record_type": "route_label", "day": day, **row} for row in route_rows
    ]
    support = {
        "day": day,
        "provider_swaps": len(provider),
        "exact_swaps": len(exact),
        "provider_zero_amount_swaps": len(raw_provider) - len(directional_provider),
        "exact_zero_amount_swaps": len(raw_exact) - len(directional_exact),
        "raw_amount_comparable_swaps": sum(
            bool(row.get("raw_amount_comparable")) for row in provider
        ),
        "v4_touch_observed_transactions": v4_touch,
        "v4_only_observed_transactions": len(v4_only),
        "v4_only_provider_legs": len(provider_frame),
        "v4_only_exact_legs": len(exact_frame),
        "runtime_seconds": time.monotonic() - started,
    }
    examples = [{"day": day, **row} for row in event_examples + route_examples]
    examples.sort(key=_mismatch_sort_key)
    return records, examples, support


def _write_jsonl(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(path) as temporary:
        frame.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )


def canonical_output_frame(records: list[dict[str, object]]) -> pd.DataFrame:
    """Remove execution metadata and impose stable row and column ordering."""

    frame = pd.DataFrame(records).drop(
        columns=list(EXECUTION_ONLY_COLUMNS), errors="ignore"
    )
    if frame.empty:
        return frame
    record_order = {
        "event_label": 0,
        "route_label": 1,
        "pooled_event_label": 2,
        "pooled_route_label": 3,
        "mismatch_example": 4,
        "support": 5,
    }
    sort_frame = pd.DataFrame(index=frame.index)
    sort_frame["record_order"] = (
        frame["record_type"].map(record_order).fillna(len(record_order)).astype(int)
    )
    for column in ("day", "dimension", "scope", "transaction_hash", "reason"):
        values = frame[column] if column in frame else pd.Series("", index=frame.index)
        sort_frame[column] = values.fillna("").astype(str)
    values = (
        frame["log_index"]
        if "log_index" in frame
        else pd.Series(-1, index=frame.index)
    )
    sort_frame["log_index"] = pd.to_numeric(values, errors="coerce").fillna(-1)
    ordered_index = sort_frame.sort_values(
        list(sort_frame.columns), kind="stable"
    ).index
    frame = frame.loc[ordered_index].reset_index(drop=True)
    preferred = [column for column in OUTPUT_COLUMN_ORDER if column in frame]
    remainder = sorted(column for column in frame if column not in preferred)
    return frame[preferred + remainder]


def _read_jsonl_records(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def merge_shard_outputs(
    paths: list[Path],
    *,
    output: Path,
    mismatch_limit: int,
) -> pd.DataFrame:
    """Merge disjoint date shards into the same canonical output as one run."""

    if not paths:
        raise ValueError("at least one V4 validation shard is required")
    daily_records: list[dict[str, object]] = []
    mismatch_records: list[dict[str, object]] = []
    supports: list[dict[str, object]] = []
    intervals: list[tuple[date, date]] = []
    metric_keys: set[tuple[str, str, str]] = set()
    for path in sorted(path.resolve() for path in paths):
        records = _read_jsonl_records(path)
        shard_supports = [
            row for row in records if row.get("record_type") == "support"
        ]
        if len(shard_supports) != 1:
            raise ValueError(f"V4 validation shard has {len(shard_supports)} support rows: {path}")
        support = shard_supports[0]
        lower = date.fromisoformat(str(support["requested_start"]))
        upper = date.fromisoformat(str(support["requested_end"]))
        if upper < lower:
            raise ValueError(f"V4 validation shard has a reversed interval: {path}")
        expected_days = (upper - lower).days + 1
        if int(support["requested_days"]) != expected_days:
            raise ValueError(f"V4 validation shard has an inconsistent day count: {path}")
        intervals.append((lower, upper))
        supports.append(support)
        for row in records:
            record_type = str(row.get("record_type") or "")
            if record_type in {"event_label", "route_label"}:
                key = record_type, str(row.get("day")), str(row.get("dimension"))
                if key in metric_keys:
                    raise ValueError(f"overlapping V4 validation shard metric: {key}")
                metric_keys.add(key)
                daily_records.append(row)
            elif record_type == "mismatch_example":
                mismatch_records.append(row)
    intervals.sort()
    for prior, current in zip(intervals, intervals[1:]):
        if current[0] != prior[1] + timedelta(days=1):
            raise ValueError("V4 validation shard intervals are not disjoint and contiguous")

    constant_values: dict[str, object] = {}
    for column in SUPPORT_CONSTANT_COLUMNS:
        values = {row.get(column) for row in supports}
        if len(values) != 1 or None in values:
            raise ValueError(f"V4 validation shards disagree on {column}")
        value = values.pop()
        constant_values[column] = (
            int(value) if column == "owned_exact_log_chunks" else value
        )
    first_covered = sorted(
        str(row["first_covered_day"])
        for row in supports
        if row.get("first_covered_day")
    )
    last_covered = sorted(
        str(row["last_covered_day"])
        for row in supports
        if row.get("last_covered_day")
    )
    first_skipped = sorted(
        str(row["first_skipped_day"])
        for row in supports
        if row.get("first_skipped_day")
    )
    support = {
        "record_type": "support",
        "requested_start": intervals[0][0].isoformat(),
        "requested_end": intervals[-1][1].isoformat(),
        **{
            column: sum(int(row[column]) for row in supports)
            for column in SUPPORT_SUM_COLUMNS
        },
        "first_covered_day": first_covered[0] if first_covered else None,
        "last_covered_day": last_covered[-1] if last_covered else None,
        "first_skipped_day": first_skipped[0] if first_skipped else None,
        "exact_initializes": max(int(row["exact_initializes"]) for row in supports),
        **constant_values,
    }
    if support["covered_days"] + support["skipped_days"] != support["requested_days"]:
        raise ValueError("V4 validation shard coverage does not reconcile")

    mismatch_records.sort(key=_mismatch_sort_key)
    records = [
        *daily_records,
        *pooled_metric_rows(daily_records),
        *mismatch_records[:mismatch_limit],
        support,
    ]
    frame = canonical_output_frame(records)
    _write_jsonl(frame, output)
    print(f"merged {len(paths):,} shards into {len(frame):,} rows at {output}", flush=True)
    return frame


def run(
    *,
    data_root: Path,
    existing_root: Path,
    owned_root: Path,
    start: str,
    end: str,
    output: Path,
    mismatch_limit: int,
) -> pd.DataFrame:
    chunks = exact_chunks(existing_root, owned_root)
    days = calendar_days(start, end)
    bounds_by_day = {
        day: load_utc_day_block_bounds(
            day.replace("-", ""),
            root=data_root / "raw" / "ethereum" / "utc_day_block_bounds",
        )
        for day in days
    }
    covered_days: list[tuple[str, list[Path]]] = []
    skipped = []
    for day in days:
        bounds = bounds_by_day[day]
        # A complete Initialize history is required before any route label is
        # certified, even when the day's own Swap chunks exist after a gap.
        history = covering_chunks(
            chunks,
            UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
            int(bounds["end_block"]),
        )
        current = covering_chunks(
            chunks,
            int(bounds["start_block"]),
            int(bounds["end_block"]),
        )
        if history is None or current is None:
            skipped.append(day)
        else:
            covered_days.append((day, current))
    if not covered_days:
        raise RuntimeError("no requested H1 day has complete V4 Initialize/Swap coverage")
    last_end = int(bounds_by_day[covered_days[-1][0]]["end_block"])
    history_paths = covering_chunks(
        chunks, UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK, last_end
    )
    if history_paths is None:
        raise RuntimeError("complete V4 initialization history disappeared")
    connection = duckdb.connect()
    initialize_rows = chain_rows(
        history_paths,
        topic=UNISWAP_V4_INITIALIZE_TOPIC,
        start_block=UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
        end_block=last_end,
        connection=connection,
    )
    pools = initialize_registry(initialize_rows)
    records: list[dict[str, object]] = []
    examples: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    decimals_cache: dict[str, int | None] = {}
    for index, (day, paths) in enumerate(covered_days, 1):
        rows, day_examples, support = validate_day(
            day=day,
            data_root=data_root,
            day_paths=paths,
            pools=pools,
            connection=connection,
            bounds=bounds_by_day[day],
            decimals_cache=decimals_cache,
        )
        records.extend(rows)
        support_rows.append(support)
        examples.extend(day_examples[:mismatch_limit])
        examples.sort(key=_mismatch_sort_key)
        del examples[mismatch_limit:]
        print(
            f"  {index}/{len(covered_days)} {day}: "
            f"{support['provider_swaps']:,} provider / {support['exact_swaps']:,} exact swaps, "
            f"{support['v4_only_observed_transactions']:,} v4-only tx, "
            f"{support['runtime_seconds']:.1f}s",
            flush=True,
        )
    records.extend(pooled_metric_rows(records))
    records.extend(
        {"record_type": "mismatch_example", **row} for row in examples
    )
    records.append(
        {
            "record_type": "support",
            "requested_start": start,
            "requested_end": end,
            "requested_days": len(days),
            "covered_days": len(covered_days),
            "skipped_days": len(skipped),
            "first_covered_day": covered_days[0][0],
            "last_covered_day": covered_days[-1][0],
            "first_skipped_day": skipped[0] if skipped else None,
            "exact_initializes": len(pools),
            "provider_swaps": sum(int(row["provider_swaps"]) for row in support_rows),
            "exact_swaps": sum(int(row["exact_swaps"]) for row in support_rows),
            "provider_zero_amount_swaps": sum(
                int(row["provider_zero_amount_swaps"]) for row in support_rows
            ),
            "exact_zero_amount_swaps": sum(
                int(row["exact_zero_amount_swaps"]) for row in support_rows
            ),
            "raw_amount_comparable_swaps": sum(
                int(row["raw_amount_comparable_swaps"]) for row in support_rows
            ),
            "v4_touch_observed_transactions": sum(
                int(row["v4_touch_observed_transactions"]) for row in support_rows
            ),
            "v4_only_observed_transactions": sum(
                int(row["v4_only_observed_transactions"]) for row in support_rows
            ),
            "route_scope": "observed_v4_only_transactions",
            "route_provider_source": "data/unified/{YYYYMMDD}.parquet",
            "cross_venue_scope": "v4_leg_only_no_full_route_certification",
            "poolmanager_direction_rule": "negative_delta_is_input_positive_delta_is_output",
            "provider_amount_sign_mapping": "provider_amount_equals_negative_poolmanager_delta",
            "owned_exact_log_chunks": sum(
                path.resolve().is_relative_to(owned_root.resolve())
                for _lower, _upper, path in chunks
            ),
        }
    )
    frame = canonical_output_frame(records)
    _write_jsonl(frame, output)
    print(f"wrote {len(frame):,} rows to {output}", flush=True)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=PRIMARY_REPO_ROOT / "data")
    parser.add_argument("--existing-root", type=Path, default=EXISTING_ROOT)
    parser.add_argument("--owned-root", type=Path, default=OWNED_ROOT)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mismatch-limit", type=int, default=50)
    parser.add_argument(
        "--merge-shards",
        nargs="+",
        type=Path,
        help="merge disjoint date-shard outputs instead of reading source data",
    )
    args = parser.parse_args()
    if args.merge_shards:
        merge_shard_outputs(
            args.merge_shards,
            output=args.output,
            mismatch_limit=args.mismatch_limit,
        )
        return 0
    run(
        data_root=args.data_root,
        existing_root=args.existing_root,
        owned_root=args.owned_root,
        start=args.start,
        end=args.end,
        output=args.output,
        mismatch_limit=args.mismatch_limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
