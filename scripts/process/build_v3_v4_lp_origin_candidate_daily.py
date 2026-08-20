#!/usr/bin/env python3
"""Build comparable V3/V4 vehicle-origin liquidity-action counts.

V3 observations are nonzero mint and burn events assigned through verified
pool-token links. V4 observations are nonzero modify-liquidity events assigned
through the event's pool token sides. The output aggregates actions by protocol,
vehicle, calendar day, and transaction origin. An origin is an account-level
participation proxy, not a verified beneficial owner of an LP position.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v3_lp_action_candidate_daily import v3_pool_candidate_links
from scripts.process.build_v4_lp_action_candidate_daily import (
    _candidate_sides,
    _decimal,
    _event_date,
    vehicle_candidate_map,
)


V3_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v3"
V4_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
OUTPUT = REPO_ROOT / "data/processed/v3_v4_lp_origin_candidate_daily.parquet"
SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits/v3_v4_lp_origin_candidate_daily_support.jsonl"
)

CODE_SOURCES = [
    "scripts/process/build_v3_v4_lp_origin_candidate_daily.py",
    "scripts/process/build_v3_lp_action_candidate_daily.py",
    "scripts/process/build_v4_lp_action_candidate_daily.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v3",
    "data/raw/thegraph/uniswap_v4",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def build_origin_action_panel(
    *,
    v3_event_dir: Path = V3_EVENT_DIR,
    v4_event_dir: Path = V4_EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
    pool_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate nonzero LP actions by protocol, vehicle, day, and origin."""

    required = {"pool", "candidate_address", "candidate_symbol"}
    missing = sorted(required - set(pool_candidates.columns))
    if missing:
        raise ValueError(f"V3 pool-candidate map lacks columns: {missing}")
    pool_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in pool_candidates.itertuples(index=False):
        pool_map[str(row.pool).lower()].append(
            (str(row.candidate_address).lower(), str(row.candidate_symbol))
        )

    counts: dict[tuple[str, str, str, pd.Timestamp, str], int] = defaultdict(int)
    protocol_support: dict[str, dict[str, int]] = {}
    for protocol, event_dir, patterns in (
        (
            "v3",
            v3_event_dir,
            ("uniswap_v3_mints_*.jsonl.gz", "uniswap_v3_burns_*.jsonl.gz"),
        ),
        ("v4", v4_event_dir, ("uniswap_v4_modify_liquidities_*.jsonl.gz",)),
    ):
        event_files = 0
        raw_events = 0
        candidate_assignments = 0
        nonzero_candidate_assignments = 0
        blank_origin_assignments = 0
        for pattern in patterns:
            for path in sorted(event_dir.glob(pattern)):
                event_files += 1
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        raw_events += 1
                        event = json.loads(line)
                        if protocol == "v3":
                            pool = event.get("pool") or {}
                            sides = pool_map.get(str(pool.get("id") or "").lower(), [])
                            if not sides:
                                sides = _candidate_sides(event, candidate_map)
                        else:
                            sides = _candidate_sides(event, candidate_map)
                        if not sides:
                            continue
                        origin = str(event.get("origin") or "").lower()
                        candidate_assignments += len(sides)
                        if not origin:
                            blank_origin_assignments += len(sides)
                            continue
                        if _decimal(event.get("amount")) == 0:
                            continue
                        date = _event_date(event)
                        for address, symbol in sides:
                            counts[(protocol, address, symbol, date, origin)] += 1
                            nonzero_candidate_assignments += 1
        protocol_support[protocol] = {
            "event_files": int(event_files),
            "raw_events": int(raw_events),
            "candidate_event_assignments": int(candidate_assignments),
            "nonzero_candidate_event_assignments": int(
                nonzero_candidate_assignments
            ),
            "blank_origin_assignments": int(blank_origin_assignments),
        }

    rows = [
        {
            "protocol": protocol,
            "candidate_address": address,
            "candidate_symbol": symbol,
            "origin_date": date,
            "origin": origin,
            "action_count": action_count,
        }
        for (protocol, address, symbol, date, origin), action_count in counts.items()
    ]
    panel = pd.DataFrame(rows)
    if panel.empty or set(panel["protocol"]) != {"v3", "v4"}:
        raise ValueError("origin-action panel does not contain both V3 and V4")
    panel = panel.sort_values(
        ["protocol", "origin_date", "candidate_symbol", "origin"]
    ).reset_index(drop=True)
    support = {
        "record_type": "v3_v4_lp_origin_candidate_daily_support",
        "analysis_status": "protocol_comparison_input",
        "quantity": (
            "nonzero LP actions by protocol, vehicle, calendar day, and "
            "transaction origin"
        ),
        "identity_boundary": (
            "transaction origin is an account-participation proxy, not verified "
            "beneficial ownership of an LP position"
        ),
        "pool_candidate_links": int(len(pool_candidates)),
        "rows": int(len(panel)),
        "candidate_count": int(panel["candidate_address"].nunique()),
        "first_date": str(panel["origin_date"].min().date()),
        "last_date": str(panel["origin_date"].max().date()),
        "protocols": protocol_support,
    }
    return panel, support


def run(
    *,
    v3_event_dir: Path = V3_EVENT_DIR,
    v4_event_dir: Path = V4_EVENT_DIR,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    mapping = vehicle_candidate_map()
    canonical_addresses = {
        canonical_address for canonical_address, _symbol in mapping.values()
    }
    pool_candidates = v3_pool_candidate_links(
        candidate_addresses=canonical_addresses
    )
    panel, support = build_origin_action_panel(
        v3_event_dir=v3_event_dir,
        v4_event_dir=v4_event_dir,
        candidate_map=mapping,
        pool_candidates=pool_candidates,
    )
    with atomic_output(output_path) as temporary:
        panel.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(f"wrote {len(panel):,} protocol-vehicle-day-origin rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-event-dir", type=Path, default=V3_EVENT_DIR)
    parser.add_argument("--v4-event-dir", type=Path, default=V4_EVENT_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        v3_event_dir=args.v3_event_dir,
        v4_event_dir=args.v4_event_dir,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())
