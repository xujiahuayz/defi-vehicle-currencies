#!/usr/bin/env python3
"""Build daily Uniswap V3 mint/burn action counts for vehicle candidates.

Reads:
  data/raw/thegraph/uniswap_v3/uniswap_v3_mints_*.jsonl.gz
  data/raw/thegraph/uniswap_v3/uniswap_v3_burns_*.jsonl.gz
  data/processed/v3_pool_day_fees.parquet
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v3_lp_action_candidate_daily.parquet
  output/exhibits/v3_lp_action_candidate_daily_support.jsonl

The output is an event-count panel. It is not a dollar-valued LP flow, inventory,
provider return, or active concentrated-liquidity depth measure.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
V3_POOL_DAY_FEES_INPUT = REPO_ROOT / "data/processed/v3_pool_day_fees.parquet"
UNISWAP_V3_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v3"
OUTPUT = REPO_ROOT / "data/processed/v3_lp_action_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_action_candidate_daily_support.jsonl"

CODE_SOURCES = ["scripts/process/build_v3_lp_action_candidate_daily.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v3",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def vehicle_candidate_addresses(path: Path = CANDIDATE_DAY_INPUT) -> set[str]:
    """Return the candidate addresses used by the five-candidate route panel."""

    frame = pd.read_parquet(path, columns=["candidate_address"])
    addresses = {
        str(address).lower()
        for address in frame["candidate_address"].dropna().unique()
    }
    if not addresses:
        raise ValueError("candidate-day panel has no candidate addresses")
    return addresses


def v3_pool_candidate_links(
    *,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    candidate_addresses: set[str],
) -> pd.DataFrame:
    """Map V3 pools to vehicle-candidate token sides."""

    if not candidate_addresses:
        raise ValueError("candidate address set is empty")
    candidate_addresses = {address.lower() for address in candidate_addresses}
    connection = duckdb.connect()
    try:
        connection.register(
            "candidate_addresses",
            pd.DataFrame({"candidate_address": sorted(candidate_addresses)}),
        )
        links = connection.execute(
            """
            SELECT DISTINCT lower(pool) AS pool,
                   lower(token0_address) AS candidate_address,
                   token0_symbol AS candidate_symbol
            FROM read_parquet(?)
            WHERE lower(token0_address) IN (SELECT * FROM candidate_addresses)
            UNION
            SELECT DISTINCT lower(pool) AS pool,
                   lower(token1_address) AS candidate_address,
                   token1_symbol AS candidate_symbol
            FROM read_parquet(?)
            WHERE lower(token1_address) IN (SELECT * FROM candidate_addresses)
            """,
            [str(fee_panel_path), str(fee_panel_path)],
        ).fetchdf()
    finally:
        connection.close()
    if links.empty:
        raise ValueError("no Uniswap V3 pools match vehicle-candidate addresses")
    return links


def load_raw_uniswap_v3_lp_actions(
    *,
    event_dir: Path = UNISWAP_V3_EVENT_DIR,
    pool_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Count raw mint/burn events by day and candidate token side."""

    pool_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in pool_candidates.itertuples(index=False):
        pool_map[str(row.pool)].append(
            (str(row.candidate_address), str(row.candidate_symbol))
        )

    counts: dict[tuple[pd.Timestamp, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "mint_events": 0,
            "burn_events": 0,
            "mint_origins": set(),
            "burn_origins": set(),
        }
    )
    event_files = 0
    raw_events = 0
    matched_candidate_events = 0
    for event_type, pattern in (
        ("mint", "uniswap_v3_mints_*.jsonl.gz"),
        ("burn", "uniswap_v3_burns_*.jsonl.gz"),
    ):
        for path in sorted(event_dir.glob(pattern)):
            event_files += 1
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw_events += 1
                    event = json.loads(line)
                    pool = str(event.get("pool", {}).get("id", "")).lower()
                    candidates = pool_map.get(pool)
                    if not candidates:
                        continue
                    timestamp = int(event.get("timestamp", 0))
                    origin_date = pd.Timestamp(
                        datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
                    )
                    origin = str(event.get("origin") or event.get("owner") or "").lower()
                    for candidate_address, candidate_symbol in candidates:
                        key = (origin_date, candidate_address, candidate_symbol)
                        bucket = counts[key]
                        if event_type == "mint":
                            bucket["mint_events"] = int(bucket["mint_events"]) + 1
                            bucket["mint_origins"].add(origin)
                        else:
                            bucket["burn_events"] = int(bucket["burn_events"]) + 1
                            bucket["burn_origins"].add(origin)
                        matched_candidate_events += 1

    rows: list[dict[str, object]] = []
    for (origin_date, candidate_address, candidate_symbol), bucket in counts.items():
        mint_events = int(bucket["mint_events"])
        burn_events = int(bucket["burn_events"])
        total_actions = mint_events + burn_events
        rows.append(
            {
                "origin_date": origin_date,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "v3_mint_events": mint_events,
                "v3_burn_events": burn_events,
                "v3_total_lp_actions": total_actions,
                "v3_net_mint_events": mint_events - burn_events,
                "v3_mint_origin_count": len(bucket["mint_origins"]),
                "v3_burn_origin_count": len(bucket["burn_origins"]),
                "v3_mint_share": mint_events / total_actions
                if total_actions > 0
                else np.nan,
            }
        )
    actions = pd.DataFrame(rows)
    if not actions.empty:
        actions = actions.sort_values(
            ["origin_date", "candidate_symbol", "candidate_address"]
        ).reset_index(drop=True)
    support = {
        "record_type": "v3_lp_action_support",
        "analysis_status": "exploratory_descriptive",
        "event_source": "uniswap_v3_graph_mint_burn_events",
        "event_dir": str(event_dir.relative_to(REPO_ROOT))
        if event_dir.is_relative_to(REPO_ROOT)
        else str(event_dir),
        "event_files": int(event_files),
        "raw_mint_burn_events": int(raw_events),
        "matched_candidate_event_assignments": int(matched_candidate_events),
        "candidate_day_action_rows": int(len(actions)),
        "candidate_addresses": int(pool_candidates["candidate_address"].nunique()),
        "pool_candidate_links": int(len(pool_candidates)),
        "quantity": (
            "mint/burn event counts and distinct origins, not dollar-valued "
            "provider flows"
        ),
    }
    return actions, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V3_EVENT_DIR,
    fee_panel_path: Path = V3_POOL_DAY_FEES_INPUT,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    candidates = vehicle_candidate_addresses(candidate_day_path)
    links = v3_pool_candidate_links(
        fee_panel_path=fee_panel_path,
        candidate_addresses=candidates,
    )
    actions, support = load_raw_uniswap_v3_lp_actions(
        event_dir=event_dir,
        pool_candidates=links,
    )
    with atomic_output(output_path) as temporary:
        actions.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(actions):,} V3 LP-action candidate-day rows to "
        f"{output_path.relative_to(REPO_ROOT)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V3_EVENT_DIR)
    parser.add_argument("--fee-panel", type=Path, default=V3_POOL_DAY_FEES_INPUT)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        fee_panel_path=args.fee_panel,
        candidate_day_path=args.candidate_day,
    )


if __name__ == "__main__":
    raise SystemExit(main())
