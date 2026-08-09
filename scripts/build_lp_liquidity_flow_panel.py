#!/usr/bin/env python3
"""Build causal V3 LP-flow and candidate-allocation panels before estimation."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.lp_liquidity_flow import (
    CausalRangeClassifier,
    allocate_candidate_event_values,
    finalize_daily_liquidity_flow,
)
from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.data_release import require_node_d_release
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import (
    DATA_DIR,
    LP_LIQUIDITY_FLOW_CANDIDATES,
    LP_LIQUIDITY_FLOW_DAILY,
    LP_LIQUIDITY_FLOW_EVENTS,
    LP_LIQUIDITY_FLOW_REJECTIONS,
    MARKET_STATE_LOCK,
    TOKEN_PRICE_DAILY_PANEL,
)
from ddvc.pricing.v3pools import load_token_decimals
from ddvc.provenance import cache_key, require_current_artifacts, sidecar_path, stamp
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.state_data import STATE_ROOT, available_state_days, read_tick_partition


CODE_SOURCES = [
    "scripts/build_lp_liquidity_flow_panel.py",
    "src/ddvc/analysis/lp_liquidity_flow.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/panel_assembly.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/state_data.py",
]
INPUTS = [
    STATE_ROOT / "tick" / "uniswap_v3",
    TOKEN_PRICE_DAILY_PANEL,
    DATA_DIR / "processed" / "v2_token_decimals.parquet",
]
CACHE_ROOT = STATE_ROOT.parent / "_lp_liquidity_flow_day_cache"
EVENT_KEYS = ("venue", "day", "tx_hash", "log_index")
CANDIDATE_KEYS = (*EVENT_KEYS, "candidate")
EVENT_COLUMNS = (
    "venue", "day", "event_id", "tx_hash", "block_number", "log_index",
    "timestamp", "pool", "source_stream", "pool_family", "invariant_family",
    "state_generation", "token0", "token1", "symbol0", "symbol1", "event_sign",
    "decimals0", "decimals1", "amount0", "amount1", "price0_usd", "price1_usd",
    "price_anchor_token", "price_anchor_symbol", "price_anchor_usd",
    "external_pool_price_gap_bps", "event_value_usd", "signed_event_value_usd",
    "event_value_source", "tick_before", "sqrt_price_x96_before",
    "tick_state_timestamp", "tick_state_age_seconds", "tick_lower", "tick_upper",
    "tick_spacing", "range_width_spacings", "range_active_before",
    "range_near_active_before", "validation_status",
)
CANDIDATE_COLUMNS = (
    *EVENT_COLUMNS,
    "candidate", "candidate_address", "allocation_weight", "allocated_event_value_usd",
    "signed_allocated_event_value_usd",
    "flow_normalization_status",
)
REJECTION_COLUMNS = (
    "venue", "day", "event_id", "tx_hash", "block_number", "log_index", "timestamp",
    "pool", "source_stream", "candidate", "failure_reason",
)


def _frame(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    return frame.reindex(columns=columns)


def _write_shard(frame: pd.DataFrame, path: Path) -> None:
    with atomic_output(path) as temporary:
        frame.to_parquet(temporary, index=False)


def _day_prices(con: duckdb.DuckDBPyConnection, day: str) -> dict[str, float]:
    rows = con.execute(
        "SELECT token, price_usd FROM read_parquet(?) WHERE day=?",
        [str(TOKEN_PRICE_DAILY_PANEL), day],
    ).fetchall()
    return {str(token).lower(): float(price) for token, price in rows}


def _real_field_preflight(days: list[str]) -> None:
    required = {"amount0", "amount1", "tick_lower", "tick_upper", "liquidity_delta"}
    for day in (days[0], days[len(days) // 2], days[-1]):
        state = read_tick_partition("uniswap_v3", day)
        missing = sorted(required - set(state.columns))
        if missing:
            raise RuntimeError(f"V3 real-data preflight {day} misses fields: {missing}")
        liquidity = state[state["record_type"].eq("liquidity")]
        if liquidity.empty:
            continue
        complete = liquidity[list(required)].notna().all(axis=1)
        provider_values = int(liquidity["value_usd"].notna().sum())
        if not complete.all():
            raise RuntimeError(
                f"V3 real-data preflight {day} has {(~complete).sum():,} incomplete liquidity rows"
            )
        print(
            f"LP real-data preflight {day}: liquidity={len(liquidity):,}; "
            f"amount/range complete={complete.mean():.1%}; provider USD={provider_values:,}",
            flush=True,
        )


def _output_candidate_frame(allocated: pd.DataFrame) -> pd.DataFrame:
    if allocated.empty:
        return _frame(allocated, CANDIDATE_COLUMNS)
    return _frame(allocated, CANDIDATE_COLUMNS)


def _candidate_days(days: list[str]) -> pd.DataFrame:
    candidates = sorted(set(VEHICLE_CANDIDATES.values()))
    return pd.DataFrame(
        [(day, candidate) for day in days for candidate in candidates],
        columns=["day", "candidate"],
    )


def _write_daily_panel(
    con: duckdb.DuckDBPyConnection,
    days: list[str],
    generation: str,
) -> int:
    numerators = con.execute(
        """
        SELECT day, candidate,
            sum(allocated_event_value_usd) AS gross_liquidity_flow_usd,
            sum(signed_allocated_event_value_usd) AS net_liquidity_flow_usd,
            sum(CASE WHEN range_active_before THEN signed_allocated_event_value_usd ELSE 0 END)
                AS active_net_liquidity_flow_usd,
            sum(CASE WHEN range_near_active_before THEN signed_allocated_event_value_usd ELSE 0 END)
                AS near_net_liquidity_flow_usd,
            sum(CASE WHEN range_near_active_before THEN allocated_event_value_usd ELSE 0 END)
                AS near_gross_liquidity_flow_usd,
            count(*) AS event_count
        FROM read_parquet(?)
        GROUP BY day, candidate
        """,
        [str(LP_LIQUIDITY_FLOW_CANDIDATES)],
    ).df()
    panel = finalize_daily_liquidity_flow(numerators, _candidate_days(days))
    with atomic_output(LP_LIQUIDITY_FLOW_DAILY) as temporary:
        panel.to_parquet(temporary, index=False)
    stamp(
        LP_LIQUIDITY_FLOW_DAILY,
        code_sources=CODE_SOURCES,
        inputs=[LP_LIQUIDITY_FLOW_CANDIDATES],
        rows=len(panel),
        notes=f"candidate-day V3 LP dollar-flow generation {generation}; no capital proxy",
    )
    return len(panel)


def _assemble(files: list[Path], output: Path, keys: tuple[str, ...], generation: str) -> int:
    sidecar_path(output).unlink(missing_ok=True)
    result = assemble_parquet_shards(files, output, unique_keys=keys)
    stamp(
        output,
        code_sources=CODE_SOURCES,
        inputs=[*INPUTS, files[0].parent],
        rows=result.rows,
        notes=f"causal V3 LP liquidity-flow generation {generation}",
    )
    return result.rows


def _build(*, force: bool = False) -> tuple[int, int, int]:
    require_node_d_release(routes=True, market_state=True)
    require_current_artifacts(
        [
            TOKEN_PRICE_DAILY_PANEL,
            DATA_DIR / "processed" / "v2_token_decimals.parquet",
        ],
        consumer="LP liquidity-flow panel builder",
    )
    days = available_state_days("tick", "uniswap_v3")
    if not days:
        raise RuntimeError("no canonical Uniswap V3 state days")
    _real_field_preflight(days)
    generation = cache_key(CODE_SOURCES, inputs=INPUTS)
    root = CACHE_ROOT / f"engine_{generation}"
    event_dir, candidate_dir, rejection_dir = (
        root / "events",
        root / "candidates",
        root / "rejections",
    )
    for directory in (event_dir, candidate_dir, rejection_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for temporary in directory.glob(".*.tmp"):
            temporary.unlink()
    classifier = CausalRangeClassifier(
        load_token_decimals(DATA_DIR / "processed" / "v2_token_decimals.parquet")
    )
    con = duckdb.connect()
    try:
        for index, day in enumerate(days, 1):
            state = read_tick_partition("uniswap_v3", day)
            events, state_rejections = classifier.classify_day(
                day, state, _day_prices(con, day)
            )
            allocated, allocation_rejections = allocate_candidate_event_values(events)
            rejections = pd.concat(
                [state_rejections, allocation_rejections], ignore_index=True
            )
            targets = (
                (event_dir / f"{day}.parquet", _frame(events, EVENT_COLUMNS)),
                (
                    candidate_dir / f"{day}.parquet",
                    _output_candidate_frame(allocated),
                ),
                (
                    rejection_dir / f"{day}.parquet",
                    _frame(rejections, REJECTION_COLUMNS),
                ),
            )
            for path, frame in targets:
                if force or not path.exists():
                    _write_shard(frame, path)
            if index % 100 == 0 or index == len(days):
                print(
                    f"LP liquidity flow [{index:,}/{len(days):,}] {day}; "
                    f"events={len(events):,}; candidates={len(allocated):,}; "
                    f"rejected={len(rejections):,}",
                    flush=True,
                )
    finally:
        con.close()
    if cache_key(CODE_SOURCES, inputs=INPUTS) != generation:
        raise RuntimeError("LP liquidity-flow inputs or code changed during materialization")
    event_files = [event_dir / f"{day}.parquet" for day in days]
    candidate_files = [candidate_dir / f"{day}.parquet" for day in days]
    rejection_files = [rejection_dir / f"{day}.parquet" for day in days]
    if any(not path.exists() for path in (*event_files, *candidate_files, *rejection_files)):
        raise RuntimeError("LP liquidity-flow day cache is incomplete")
    event_rows = _assemble(event_files, LP_LIQUIDITY_FLOW_EVENTS, EVENT_KEYS, generation)
    candidate_rows = _assemble(
        candidate_files,
        LP_LIQUIDITY_FLOW_CANDIDATES,
        CANDIDATE_KEYS,
        generation,
    )
    rejection_rows = _assemble(
        rejection_files,
        LP_LIQUIDITY_FLOW_REJECTIONS,
        (*EVENT_KEYS, "candidate", "failure_reason"),
        generation,
    )
    con = duckdb.connect()
    try:
        daily_rows = _write_daily_panel(con, days, generation)
    finally:
        con.close()
    print(
        f"PASS: LP liquidity-flow events={event_rows:,}; "
        f"candidate allocations={candidate_rows:,}; rejections={rejection_rows:,}; "
        f"candidate-days={daily_rows:,}",
        flush=True,
    )
    return event_rows, candidate_rows, rejection_rows


def build(*, force: bool = False) -> tuple[int, int, int]:
    with exclusive_job(
        MARKET_STATE_LOCK,
        job="causal LP liquidity-flow panel build",
    ):
        return _build(force=force)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    build(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
