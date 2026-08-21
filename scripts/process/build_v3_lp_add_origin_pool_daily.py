#!/usr/bin/env python3
"""Build V3 positive-liquidity additions by pool, day, and transaction origin.

This narrow Uniswap V3 panel preserves the transaction origin that is lost when the
ordinary V3 LP-flow panel aggregates to pool-day.  It is used to ask whether
origins supplying a newly material endpoint--vehicle pool were already active
elsewhere in the same vehicle's pool network.

The retained vehicle sides are WETH, DAI, USDC, and USDT.  WBTC rows from the
broader candidate registry are outside this analysis and are not materialized.

``origin`` is the decoded transaction origin.  It is a participation proxy,
not a wallet-owner or beneficial-owner identity.  Only positive-liquidity mint
events enter.  Candidate-side dollar values use the same validated price panel
and event-value bound as the ordinary V3 LP-flow build; action and transaction
counts remain available when the candidate side cannot be valued.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v3_lp_flow_candidate_daily import (
    CANDIDATE_DAY_INPUT,
    INPUTS as V3_FLOW_INPUTS,
    MAX_CANDIDATE_SIDE_EVENT_USD,
    TOKEN_PRICE_DAILY_PANEL,
    UNISWAP_V3_EVENT_DIR,
    V3_POOL_DAY_FEES_INPUT,
    _candidate_sides,
    _event_date,
    _event_day,
    _pool_side_map,
    _price_lookup,
    v3_pool_candidate_sides,
    vehicle_candidate_map,
)
from scripts.process.build_v3_lp_flow_pool_daily import v3_pool_registry


OUTPUT = DATA_DIR / "processed/v3_lp_add_origin_pool_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_add_origin_pool_daily_support.jsonl"
MAX_MISSING_REGISTRY_ROWS = 100
MAX_MISSING_REGISTRY_GROSS_FLOW_USD = 100.0
FOUR_VEHICLE_SYMBOLS = frozenset({"WETH", "DAI", "USDC", "USDT"})

CODE_SOURCES = [
    "scripts/process/build_v3_lp_add_origin_pool_daily.py",
    "scripts/process/build_v3_lp_flow_candidate_daily.py",
    "scripts/process/build_v3_lp_flow_pool_daily.py",
]
INPUTS = list(dict.fromkeys(V3_FLOW_INPUTS))


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def four_vehicle_candidate_map(path: Path) -> dict[str, tuple[str, str]]:
    """Restrict the canonical candidate registry to the declared four vehicles."""

    mapping = {
        address: candidate
        for address, candidate in vehicle_candidate_map(path).items()
        if candidate[1] in FOUR_VEHICLE_SYMBOLS
    }
    observed = {symbol for _address, symbol in mapping.values()}
    if observed != FOUR_VEHICLE_SYMBOLS:
        raise ValueError(
            "V3 origin-flow input does not contain the declared WETH/DAI/USDC/USDT scope"
        )
    return mapping


def load_v3_lp_add_origins(
    *,
    event_dir: Path,
    candidate_map: dict[str, tuple[str, str]],
    pool_candidate_sides: pd.DataFrame,
    price_path: Path,
    max_candidate_side_event_usd: float = MAX_CANDIDATE_SIDE_EVENT_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate positive V3 mints to origin--pool--candidate--day rows."""

    if max_candidate_side_event_usd <= 0:
        raise ValueError("V3 origin-flow event-value bound must be positive")
    prices = _price_lookup(price_path)
    pool_sides = _pool_side_map(pool_candidate_sides)
    counts: dict[tuple[pd.Timestamp, str, str, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "add_action_events": 0,
            "transaction_ids": set(),
            "priced_assignments": 0,
            "screened_assignments": 0,
            "missing_price_assignments": 0,
            "nonpositive_value_assignments": 0,
            "above_screen_assignments": 0,
            "add_flow_usd_screened": 0.0,
        }
    )
    support_counts = Counter()
    event_files = 0
    max_seen_value = 0.0

    for path in sorted(event_dir.glob("uniswap_v3_mints_*.jsonl.gz")):
        event_files += 1
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                support_counts["raw_mint_events"] += 1
                event = json.loads(line)
                candidate_sides = _candidate_sides(event, candidate_map, pool_sides)
                if not candidate_sides:
                    continue
                support_counts["candidate_mint_events"] += 1
                liquidity = float(_decimal(event.get("amount")))
                if not np.isfinite(liquidity) or liquidity <= 0:
                    support_counts["nonpositive_liquidity_candidate_events"] += 1
                    continue
                pool = str((event.get("pool") or {}).get("id") or "").lower()
                origin = str(event.get("origin") or "").lower()
                if not pool:
                    support_counts["positive_mints_missing_pool"] += 1
                    continue
                if not origin:
                    support_counts["positive_mints_missing_origin"] += 1
                    continue
                transaction_id = str(
                    (event.get("transaction") or {}).get("id") or ""
                ).lower()
                if not transaction_id:
                    support_counts["positive_mints_missing_transaction"] += 1
                origin_date = _event_date(event)
                day = _event_day(event)
                for side_index, candidate_address, candidate_symbol, price_address in candidate_sides:
                    key = (
                        origin_date,
                        pool,
                        origin,
                        candidate_address,
                        candidate_symbol,
                    )
                    bucket = counts[key]
                    bucket["add_action_events"] = int(bucket["add_action_events"]) + 1
                    if transaction_id:
                        bucket["transaction_ids"].add(transaction_id)
                    support_counts["positive_candidate_side_assignments"] += 1
                    price = prices.get((day, price_address))
                    if price is None:
                        bucket["missing_price_assignments"] = (
                            int(bucket["missing_price_assignments"]) + 1
                        )
                        support_counts["missing_price_assignments"] += 1
                        continue
                    value = abs(float(_decimal(event.get(f"amount{side_index}")))) * price
                    if not np.isfinite(value) or value <= 0:
                        bucket["nonpositive_value_assignments"] = (
                            int(bucket["nonpositive_value_assignments"]) + 1
                        )
                        support_counts["nonpositive_value_assignments"] += 1
                        continue
                    bucket["priced_assignments"] = int(bucket["priced_assignments"]) + 1
                    support_counts["priced_assignments"] += 1
                    max_seen_value = max(max_seen_value, float(value))
                    if value > max_candidate_side_event_usd:
                        bucket["above_screen_assignments"] = (
                            int(bucket["above_screen_assignments"]) + 1
                        )
                        support_counts["above_screen_assignments"] += 1
                        continue
                    bucket["screened_assignments"] = (
                        int(bucket["screened_assignments"]) + 1
                    )
                    bucket["add_flow_usd_screened"] = (
                        float(bucket["add_flow_usd_screened"]) + value
                    )
                    support_counts["screened_assignments"] += 1

    rows: list[dict[str, object]] = []
    for (
        origin_date,
        pool,
        origin,
        candidate_address,
        candidate_symbol,
    ), bucket in counts.items():
        rows.append(
            {
                "origin_date": origin_date,
                "pool": pool,
                "origin": origin,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "v3_add_action_events": int(bucket["add_action_events"]),
                "v3_add_action_transactions": len(bucket["transaction_ids"]),
                "v3_add_flow_priced_assignments": int(bucket["priced_assignments"]),
                "v3_add_flow_screened_assignments": int(bucket["screened_assignments"]),
                "v3_add_flow_missing_price_assignments": int(
                    bucket["missing_price_assignments"]
                ),
                "v3_add_flow_nonpositive_value_assignments": int(
                    bucket["nonpositive_value_assignments"]
                ),
                "v3_add_flow_above_screen_assignments": int(
                    bucket["above_screen_assignments"]
                ),
                "v3_add_flow_usd_screened": float(bucket["add_flow_usd_screened"]),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("V3 mints produced no positive-liquidity origin rows")
    support = {
        "event_files": event_files,
        **{key: int(value) for key, value in support_counts.items()},
        "max_seen_candidate_side_event_usd": max_seen_value,
        "max_candidate_side_event_usd": float(max_candidate_side_event_usd),
    }
    return frame, support


def attach_pool_identity(
    flows: pd.DataFrame,
    registry: pd.DataFrame,
    *,
    max_missing_rows: int = MAX_MISSING_REGISTRY_ROWS,
    max_missing_gross_flow_usd: float = MAX_MISSING_REGISTRY_GROSS_FLOW_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attach immutable pool tokens and bound late registry gaps."""

    merged = flows.merge(
        registry,
        on="pool",
        how="left",
        validate="many_to_one",
        indicator="_registry_merge",
    )
    missing = merged.loc[merged["_registry_merge"].ne("both")]
    missing_gross_flow = float(missing["v3_add_flow_usd_screened"].sum())
    if len(missing) > max_missing_rows or missing_gross_flow > max_missing_gross_flow_usd:
        raise ValueError(
            "V3 origin-flow pool registry gap exceeds its immaterial bound: "
            f"{len(missing):,} rows and ${missing_gross_flow:,.2f} flow"
        )
    kept = merged.loc[merged["_registry_merge"].eq("both")].drop(
        columns="_registry_merge"
    )
    candidate_on_token0 = kept["candidate_address"].eq(kept["token0_address"])
    candidate_on_token1 = kept["candidate_address"].eq(kept["token1_address"])
    if not (candidate_on_token0 ^ candidate_on_token1).all():
        raise ValueError("V3 origin-flow candidate side is not uniquely identified")
    kept["paired_token_address"] = np.where(
        candidate_on_token0, kept["token1_address"], kept["token0_address"]
    )
    kept["paired_token_symbol"] = np.where(
        candidate_on_token0, kept["token1_symbol"], kept["token0_symbol"]
    )
    support = {
        "missing_registry_rows": int(len(missing)),
        "missing_registry_pools": int(missing["pool"].nunique()),
        "missing_registry_gross_flow_usd": missing_gross_flow,
        "registry_gap_rule": (
            f"drop_only_if_rows_le_{max_missing_rows}_and_gross_flow_usd_le_"
            f"{max_missing_gross_flow_usd:g}"
        ),
    }
    return kept.reset_index(drop=True), support


def validate_panel(frame: pd.DataFrame) -> None:
    required = {
        "origin_date",
        "pool",
        "origin",
        "candidate_address",
        "paired_token_address",
        "v3_add_action_events",
        "v3_add_action_transactions",
        "v3_add_flow_usd_screened",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V3 origin-flow panel lacks columns: {missing}")
    if frame.duplicated(
        ["origin_date", "pool", "origin", "candidate_address"]
    ).any():
        raise ValueError("V3 origin-flow panel has duplicate origin-pool-candidate-days")
    if frame["origin"].eq("").any():
        raise ValueError("V3 origin-flow panel retains a blank transaction origin")
    for column in (
        "v3_add_action_events",
        "v3_add_action_transactions",
        "v3_add_flow_usd_screened",
    ):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or (values < 0).any():
            raise ValueError(f"V3 origin-flow panel has invalid {column}")


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
    candidate_map = four_vehicle_candidate_map(candidate_day_path)
    pool_sides = v3_pool_candidate_sides(
        fee_panel_path=fee_panel_path,
        candidate_map=candidate_map,
    )
    flows, support = load_v3_lp_add_origins(
        event_dir=event_dir,
        candidate_map=candidate_map,
        pool_candidate_sides=pool_sides,
        price_path=price_path,
        max_candidate_side_event_usd=max_candidate_side_event_usd,
    )
    registry = v3_pool_registry(fee_panel_path)
    flows, registry_support = attach_pool_identity(flows, registry)
    validate_panel(flows)
    support.update(registry_support)
    support.update(
        {
            "record_type": "v3_lp_add_origin_pool_daily_support",
            "origin_pool_candidate_day_rows": int(len(flows)),
            "transaction_origin_proxies": int(flows["origin"].nunique()),
            "pools": int(flows["pool"].nunique()),
            "first_origin_date": str(flows["origin_date"].min().date()),
            "last_origin_date": str(flows["origin_date"].max().date()),
            "identity_rule": (
                "decoded transaction origin is a participation proxy, not a "
                "wallet-owner or beneficial-owner identity"
            ),
            "venue_scope": "Uniswap V3",
            "vehicle_scope": "WETH, DAI, USDC, USDT",
            "quantity": (
                "positive-liquidity V3 mint actions and screened candidate-side "
                "USD value by transaction origin, pool, candidate, and day"
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
    print(f"wrote {len(flows):,} V3 LP-add origin-pool-candidate-days")
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
