#!/usr/bin/env python3
"""Build pool-retaining Uniswap V3 mint/burn flows for LP-supply analysis.

Reads the existing V3 event, candidate, fee-panel registry, and validated-price
inputs used by ``build_v3_lp_flow_candidate_daily.py``.  The only substantive
difference is the unit: this output keeps one row per pool, candidate side, and
event day instead of collapsing pools into a candidate-day total.

The USD flows value the candidate-token side of each position change.  Positive
liquidity burn--mint activity in the same pool and transaction is separated as
repositioning.  Transaction counts are retained even when the candidate side
cannot be dollarized, so downstream analysis can check valued flows against
observed provider actions.  Zero-liquidity events remain diagnostics only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v3_lp_flow_candidate_daily import (
    CANDIDATE_DAY_INPUT,
    CODE_SOURCES as CANDIDATE_CODE_SOURCES,
    INPUTS,
    MAX_CANDIDATE_SIDE_EVENT_USD,
    TOKEN_PRICE_DAILY_PANEL,
    UNISWAP_V3_EVENT_DIR,
    V3_POOL_DAY_FEES_INPUT,
    load_raw_uniswap_v3_lp_flows,
    v3_pool_candidate_sides,
    vehicle_candidate_map,
)


OUTPUT = DATA_DIR / "processed/v3_lp_flow_pool_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_flow_pool_daily_support.jsonl"
CODE_SOURCES = [
    "scripts/process/build_v3_lp_flow_pool_daily.py",
    *CANDIDATE_CODE_SOURCES,
]


def v3_pool_registry(fee_panel_path: Path) -> pd.DataFrame:
    """Return one immutable ordered token identity and fee tier per V3 pool."""

    connection = duckdb.connect()
    try:
        registry = connection.execute(
            """
            SELECT
                lower(pool) AS pool,
                min(lower(token0_address)) AS token0_address,
                min(token0_symbol) AS token0_symbol,
                min(lower(token1_address)) AS token1_address,
                min(token1_symbol) AS token1_symbol,
                min(fee_tier)::INTEGER AS fee_tier,
                count(DISTINCT lower(token0_address)) AS token0_identities,
                count(DISTINCT lower(token1_address)) AS token1_identities,
                count(DISTINCT fee_tier) AS fee_tiers
            FROM read_parquet(?)
            GROUP BY 1
            """,
            [str(fee_panel_path)],
        ).fetchdf()
    finally:
        connection.close()
    conflicts = registry[
        registry[["token0_identities", "token1_identities", "fee_tiers"]]
        .ne(1)
        .any(axis=1)
    ]
    if not conflicts.empty:
        raise ValueError("V3 fee panel has inconsistent immutable pool identities")
    return registry.drop(
        columns=["token0_identities", "token1_identities", "fee_tiers"]
    )


def validate_v3_lp_flow_pool_daily(frame: pd.DataFrame) -> None:
    required = {
        "origin_date",
        "pool",
        "candidate_address",
        "candidate_symbol",
        "token0_address",
        "token1_address",
        "paired_token_address",
        "candidate_side_index",
        "fee_tier",
        "v3_add_lp_flow_usd_screened",
        "v3_remove_lp_flow_usd_screened",
        "v3_net_add_lp_flow_usd_screened",
        "v3_add_only_lp_flow_usd_screened",
        "v3_remove_only_lp_flow_usd_screened",
        "v3_net_add_remove_only_lp_flow_usd_screened",
        "v3_add_action_events",
        "v3_remove_action_events",
        "v3_add_only_action_transactions",
        "v3_remove_only_action_transactions",
        "v3_reposition_action_transactions",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V3 pool-day LP-flow panel lacks columns: {missing}")
    if frame.empty:
        raise ValueError("V3 pool-day LP-flow panel is empty")
    if frame.duplicated(
        ["origin_date", "pool", "candidate_address"]
    ).any():
        raise ValueError("V3 pool-day LP-flow panel has duplicate pool-candidate-days")
    for column in (
        "v3_add_lp_flow_usd_screened",
        "v3_remove_lp_flow_usd_screened",
        "v3_add_action_events",
        "v3_remove_action_events",
    ):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or (values < 0).any():
            raise ValueError(f"V3 pool-day LP-flow panel has invalid {column}")


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V3_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
) -> int:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    pool_sides = v3_pool_candidate_sides(
        fee_panel_path=fee_panel_path,
        candidate_map=candidate_map,
    )
    flows, support = load_raw_uniswap_v3_lp_flows(
        event_dir=event_dir,
        candidate_map=candidate_map,
        pool_candidate_sides=pool_sides,
        price_path=price_path,
        max_candidate_side_event_usd=max_candidate_side_event_usd,
        retain_pool=True,
    )
    registry = v3_pool_registry(fee_panel_path)
    flows = flows.merge(registry, on="pool", how="left", validate="many_to_one")
    if flows["token0_address"].isna().any():
        raise ValueError("V3 pool-day LP flows contain a pool absent from the registry")
    candidate_on_token0 = flows["candidate_address"].eq(flows["token0_address"])
    candidate_on_token1 = flows["candidate_address"].eq(flows["token1_address"])
    if not (candidate_on_token0 ^ candidate_on_token1).all():
        raise ValueError("V3 pool-day LP-flow candidate side is not uniquely identified")
    flows["candidate_side_index"] = np.where(candidate_on_token0, 0, 1)
    flows["paired_token_address"] = np.where(
        candidate_on_token0,
        flows["token1_address"],
        flows["token0_address"],
    )
    flows["paired_token_symbol"] = np.where(
        candidate_on_token0,
        flows["token1_symbol"],
        flows["token0_symbol"],
    )
    validate_v3_lp_flow_pool_daily(flows)
    support.update(
        {
            "record_type": "v3_lp_flow_pool_daily_support",
            "pool_candidate_day_flow_rows": int(len(flows)),
            "pools": int(flows["pool"].nunique()),
            "quantity": (
                "pool-retaining screened candidate-token-side USD mint/burn "
                "flow plus all matched mint/burn action counts"
            ),
        }
    )
    with atomic_output(output_path) as temporary:
        flows.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(f"wrote {len(flows):,} V3 LP-flow pool-candidate-days to {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V3_EVENT_DIR)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--fee-panel", type=Path, default=V3_POOL_DAY_FEES_INPUT)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument(
        "--max-candidate-side-event-usd",
        type=float,
        default=MAX_CANDIDATE_SIDE_EVENT_USD,
    )
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        candidate_day_path=args.candidate_day,
        fee_panel_path=args.fee_panel,
        price_path=args.price,
        max_candidate_side_event_usd=args.max_candidate_side_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
