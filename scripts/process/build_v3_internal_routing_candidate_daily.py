#!/usr/bin/env python3
"""Build V3 candidate-day internal-routing measures comparable to V4.

The panel counts, for each vehicle candidate and transaction, how many Uniswap
V3 swap legs contain the candidate.  A candidate is internally routed when it
appears on at least two V3 swap legs in the same transaction.  The default
calendar begins with the V4 comparison period; the measure does not infer a
cross-protocol route or a V4-style settlement rule.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v4_lp_action_candidate_daily import vehicle_candidate_map


EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v3"
OUTPUT = REPO_ROOT / "data/processed/v3_internal_routing_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_internal_routing_candidate_daily_support.jsonl"
DEFAULT_START = pd.Timestamp("2025-01-01")
DEFAULT_END_EXCLUSIVE = pd.Timestamp("2026-07-01")

CODE_SOURCES = ["scripts/process/build_v3_internal_routing_candidate_daily.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v3",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def _day_from_path(path: Path) -> pd.Timestamp:
    stamp = path.name.removeprefix("uniswap_v3_swaps_").removesuffix(".jsonl.gz")
    if len(stamp) != 8 or not stamp.isdigit():
        raise ValueError(f"cannot parse V3 swap date from {path.name}")
    return pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")


def _candidate_addresses(
    swap: dict[str, object],
    candidate_map: dict[str, tuple[str, str]],
) -> list[tuple[str, str]]:
    pool = swap.get("pool") or {}
    matches: dict[str, tuple[str, str]] = {}
    for token_key in ("token0", "token1"):
        token = pool.get(token_key) or {}
        candidate = candidate_map.get(str(token.get("id") or "").lower())
        if candidate is not None:
            matches[candidate[0]] = candidate
    return list(matches.values())


def load_raw_v3_internal_routing(
    *,
    event_dir: Path = EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
    start_date: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate V3 transaction legs into candidate-day routing shares."""

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_exclusive).normalize()
    if start >= end:
        raise ValueError("V3 routing calendar must have start < end")

    candidate_day: dict[tuple[pd.Timestamp, str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    event_files = 0
    raw_swap_rows = 0
    transactions = 0
    matched_candidate_leg_assignments = 0
    for path in sorted(event_dir.glob("uniswap_v3_swaps_*.jsonl.gz")):
        day = _day_from_path(path)
        if day < start or day >= end:
            continue
        event_files += 1
        tx_state: dict[str, dict[str, object]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_swap_rows += 1
                swap = json.loads(line)
                transaction = swap.get("transaction") or {}
                tx = str(transaction.get("id") or str(swap.get("id") or "").split("#")[0])
                if not tx:
                    continue
                state = tx_state.setdefault(
                    tx,
                    {"tx_legs": 0, "candidate_legs": defaultdict(int), "symbols": {}},
                )
                state["tx_legs"] = int(state["tx_legs"]) + 1
                for address, symbol in _candidate_addresses(swap, candidate_map):
                    state["candidate_legs"][address] += 1
                    state["symbols"][address] = symbol
                    matched_candidate_leg_assignments += 1
        transactions += len(tx_state)
        for state in tx_state.values():
            tx_legs = int(state["tx_legs"])
            for address, legs in state["candidate_legs"].items():
                key = (day, address, state["symbols"][address])
                bucket = candidate_day[key]
                bucket["candidate_tx_count"] += 1.0
                bucket["swap_leg_assignments"] += float(legs)
                bucket["multi_leg_tx_count"] += float(tx_legs >= 2)
                bucket["internal_tx_count"] += float(legs >= 2)

    rows: list[dict[str, object]] = []
    for (day, address, symbol), bucket in candidate_day.items():
        count = float(bucket["candidate_tx_count"])
        rows.append(
            {
                "origin_date": day,
                "candidate_address": address,
                "candidate_symbol": symbol,
                "candidate_tx_count": count,
                "swap_leg_assignments": float(bucket["swap_leg_assignments"]),
                "multi_leg_tx_count": float(bucket["multi_leg_tx_count"]),
                "internal_tx_count": float(bucket["internal_tx_count"]),
                "multi_leg_tx_share": (
                    float(bucket["multi_leg_tx_count"]) / count if count else np.nan
                ),
                "internal_tx_share": (
                    float(bucket["internal_tx_count"]) / count if count else np.nan
                ),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("V3 swap files contain no candidate routing rows")
    frame = frame.sort_values(
        ["origin_date", "candidate_symbol", "candidate_address"]
    ).reset_index(drop=True)
    support = {
        "record_type": "v3_internal_routing_candidate_daily_support",
        "analysis_status": "protocol_comparison_input",
        "event_source": "uniswap_v3_graph_swap_events",
        "event_files": int(event_files),
        "raw_swap_rows": int(raw_swap_rows),
        "transactions": int(transactions),
        "matched_candidate_leg_assignments": int(matched_candidate_leg_assignments),
        "candidate_day_rows": int(len(frame)),
        "candidate_count": int(frame["candidate_address"].nunique()),
        "first_date": str(frame["origin_date"].min().date()),
        "last_date": str(frame["origin_date"].max().date()),
        "calendar_start": str(start.date()),
        "calendar_end_exclusive": str(end.date()),
        "quantity": (
            "candidate appearances on Uniswap V3 swap legs grouped within "
            "transactions; comparable internal-routing share, not V4 flash accounting"
        ),
    }
    return frame, support


def run(
    *,
    event_dir: Path = EVENT_DIR,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    start_date: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> int:
    frame, support = load_raw_v3_internal_routing(
        event_dir=event_dir,
        candidate_map=vehicle_candidate_map(),
        start_date=start_date,
        end_exclusive=end_exclusive,
    )
    with atomic_output(output_path) as temporary:
        frame.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(f"wrote {len(frame):,} V3 internal-routing candidate-days")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--start-date", type=pd.Timestamp, default=DEFAULT_START)
    parser.add_argument("--end-exclusive", type=pd.Timestamp, default=DEFAULT_END_EXCLUSIVE)
    args = parser.parse_args()
    return run(
        event_dir=args.event_dir,
        output_path=args.output,
        support_path=args.support,
        start_date=args.start_date,
        end_exclusive=args.end_exclusive,
    )


if __name__ == "__main__":
    raise SystemExit(main())
