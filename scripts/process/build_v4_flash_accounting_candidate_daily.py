#!/usr/bin/env python3
"""Build candidate-day V4 flash-accounting and singleton-netting proxies.

Reads:
  data/raw/thegraph/uniswap_v4/uniswap_v4_swaps_*.jsonl.gz
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  data/processed/v4_flash_accounting_candidate_daily.parquet
  output/exhibits/v4_flash_accounting_candidate_daily_support.jsonl

The output is a transaction-level netting proxy. For each V4 transaction and
vehicle candidate we compare gross absolute token flow across swap legs with
the absolute net token flow inside the same singleton transaction:

    netting_reduction_share = 1 - abs(sum(amount_delta)) / sum(abs(amount_delta))

This is unit-free within token and therefore comparable across tokens as a
netting intensity, but it is not a dollar-flow, capital-flow, or provider-return
measure. Native ETH is mapped to the WETH candidate family.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import NATIVE_ETH, VEHICLE_CANDIDATES, WETH
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
UNISWAP_V4_EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
OUTPUT = REPO_ROOT / "data/processed/v4_flash_accounting_candidate_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_flash_accounting_candidate_daily_support.jsonl"
NATIVE_ETH_ADDRESS = NATIVE_ETH
WETH_ADDRESS = WETH

CODE_SOURCES = ["scripts/process/build_v4_flash_accounting_candidate_daily.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _day_from_path(path: Path) -> pd.Timestamp:
    stamp = path.stem.split("_")[-1].split(".")[0]
    if len(stamp) != 8 or not stamp.isdigit():
        raise ValueError(f"cannot parse V4 swap date from {path.name}")
    return pd.Timestamp(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")


def vehicle_candidate_map(path: Path = CANDIDATE_DAY_INPUT) -> dict[str, tuple[str, str]]:
    """Return raw token-address to canonical candidate address and symbol."""

    frame = pd.read_parquet(path, columns=["candidate_address", "candidate_symbol"])
    observed = {
        str(row.candidate_address).lower(): str(row.candidate_symbol)
        for row in frame.drop_duplicates().itertuples(index=False)
    }
    mapping = {
        address: (address, symbol)
        for address, symbol in VEHICLE_CANDIDATES.items()
        if address in observed
    }
    if not mapping:
        raise ValueError("candidate-day panel has no canonical vehicle candidates")
    mapping[NATIVE_ETH_ADDRESS] = (WETH_ADDRESS, VEHICLE_CANDIDATES[WETH_ADDRESS])
    return mapping


def _candidate_amounts(
    swap: dict[str, object],
    candidate_map: dict[str, tuple[str, str]],
) -> list[tuple[str, str, float]]:
    pool = swap.get("pool") or {}
    rows: list[tuple[str, str, float]] = []
    for token_key, amount_key in (("token0", "amount0"), ("token1", "amount1")):
        token = pool.get(token_key) or {}
        raw_address = str(token.get("id") or "").lower()
        candidate = candidate_map.get(raw_address)
        if candidate is None:
            continue
        candidate_address, candidate_symbol = candidate
        rows.append((candidate_address, candidate_symbol, _float(swap.get(amount_key))))
    return rows


def load_raw_uniswap_v4_flash_accounting(
    *,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return candidate-day singleton-netting proxies from raw V4 swap rows."""

    candidate_day: dict[tuple[pd.Timestamp, str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    event_files = 0
    raw_swap_rows = 0
    transactions = 0
    matched_candidate_leg_assignments = 0
    native_eth_to_weth_assignments = 0
    for path in sorted(event_dir.glob("uniswap_v4_swaps_*.jsonl.gz")):
        event_files += 1
        day = _day_from_path(path)
        tx_state: dict[str, dict[str, object]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_swap_rows += 1
                swap = json.loads(line)
                tx = (
                    (swap.get("transaction") or {}).get("id")
                    or str(swap.get("id") or "").split("-")[0]
                )
                if not tx:
                    continue
                state = tx_state.get(tx)
                if state is None:
                    state = {
                        "tx_legs": 0,
                        "gross": defaultdict(float),
                        "net": defaultdict(float),
                        "legs": defaultdict(int),
                        "symbols": {},
                    }
                    tx_state[tx] = state
                state["tx_legs"] = int(state["tx_legs"]) + 1
                pool = swap.get("pool") or {}
                raw_addresses = {
                    str((pool.get("token0") or {}).get("id") or "").lower(),
                    str((pool.get("token1") or {}).get("id") or "").lower(),
                }
                for candidate_address, candidate_symbol, amount in _candidate_amounts(
                    swap,
                    candidate_map,
                ):
                    state["gross"][candidate_address] += abs(amount)
                    state["net"][candidate_address] += amount
                    state["legs"][candidate_address] += 1
                    state["symbols"][candidate_address] = candidate_symbol
                    matched_candidate_leg_assignments += 1
                    if (
                        candidate_address == WETH_ADDRESS
                        and NATIVE_ETH_ADDRESS in raw_addresses
                    ):
                        native_eth_to_weth_assignments += 1

        transactions += len(tx_state)
        for state in tx_state.values():
            tx_legs = int(state["tx_legs"])
            for candidate_address, gross in state["gross"].items():
                if gross <= 0:
                    continue
                candidate_symbol = state["symbols"][candidate_address]
                legs = int(state["legs"][candidate_address])
                net = abs(float(state["net"][candidate_address]))
                reduction = max(float(gross) - net, 0.0)
                key = (day, candidate_address, candidate_symbol)
                bucket = candidate_day[key]
                bucket["candidate_tx_count"] += 1.0
                bucket["swap_leg_assignments"] += float(legs)
                bucket["multi_leg_tx_count"] += 1.0 if tx_legs >= 2 else 0.0
                bucket["internal_tx_count"] += 1.0 if legs >= 2 else 0.0
                bucket["gross_abs_amount"] += float(gross)
                bucket["net_abs_amount"] += net
                bucket["netting_reduction_amount"] += reduction
                bucket["netting_reduction_tx_count"] += (
                    1.0 if reduction > 1e-18 else 0.0
                )

    rows: list[dict[str, object]] = []
    for (day, candidate_address, candidate_symbol), bucket in candidate_day.items():
        candidate_tx_count = float(bucket["candidate_tx_count"])
        gross_abs_amount = float(bucket["gross_abs_amount"])
        net_abs_amount = float(bucket["net_abs_amount"])
        netting_reduction_amount = float(bucket["netting_reduction_amount"])
        rows.append(
            {
                "origin_date": day,
                "candidate_address": candidate_address,
                "candidate_symbol": candidate_symbol,
                "candidate_tx_count": candidate_tx_count,
                "swap_leg_assignments": float(bucket["swap_leg_assignments"]),
                "multi_leg_tx_count": float(bucket["multi_leg_tx_count"]),
                "internal_tx_count": float(bucket["internal_tx_count"]),
                "gross_abs_amount": gross_abs_amount,
                "net_abs_amount": net_abs_amount,
                "netting_reduction_amount": netting_reduction_amount,
                "netting_reduction_tx_count": float(
                    bucket["netting_reduction_tx_count"]
                ),
                "multi_leg_tx_share": (
                    float(bucket["multi_leg_tx_count"]) / candidate_tx_count
                    if candidate_tx_count
                    else np.nan
                ),
                "internal_tx_share": (
                    float(bucket["internal_tx_count"]) / candidate_tx_count
                    if candidate_tx_count
                    else np.nan
                ),
                "netting_reduction_share": (
                    netting_reduction_amount / gross_abs_amount
                    if gross_abs_amount
                    else np.nan
                ),
                "net_to_gross_share": (
                    net_abs_amount / gross_abs_amount if gross_abs_amount else np.nan
                ),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(
            ["origin_date", "candidate_symbol", "candidate_address"]
        ).reset_index(drop=True)
    support = {
        "record_type": "v4_flash_accounting_support",
        "analysis_status": "exploratory_descriptive",
        "event_source": "uniswap_v4_graph_swap_events",
        "event_dir": str(event_dir.relative_to(REPO_ROOT))
        if event_dir.is_relative_to(REPO_ROOT)
        else str(event_dir),
        "event_files": int(event_files),
        "raw_swap_rows": int(raw_swap_rows),
        "transactions": int(transactions),
        "matched_candidate_leg_assignments": int(matched_candidate_leg_assignments),
        "native_eth_to_weth_assignments": int(native_eth_to_weth_assignments),
        "candidate_day_rows": int(len(frame)),
        "candidate_count": int(frame["candidate_address"].nunique())
        if not frame.empty
        else 0,
        "first_date": frame["origin_date"].min().strftime("%Y-%m-%d")
        if not frame.empty
        else None,
        "last_date": frame["origin_date"].max().strftime("%Y-%m-%d")
        if not frame.empty
        else None,
        "native_eth_mapping": "native_eth_zero_address_to_weth_candidate_family",
        "quantity": (
            "within-transaction gross-versus-net swap-flow proxy for V4 singleton "
            "flash accounting; unit-free netting intensity, not dollar flow or "
            "LP capital"
        ),
    }
    return frame, support


def run(
    *,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    event_dir: Path = UNISWAP_V4_EVENT_DIR,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    candidate_map = vehicle_candidate_map(candidate_day_path)
    frame, support = load_raw_uniswap_v4_flash_accounting(
        event_dir=event_dir,
        candidate_map=candidate_map,
    )
    with atomic_output(output_path) as temporary:
        frame.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    output_label = (
        output_path.relative_to(REPO_ROOT)
        if output_path.is_relative_to(REPO_ROOT)
        else output_path
    )
    print(
        f"wrote {len(frame):,} V4 flash-accounting candidate-day rows to "
        f"{output_label}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--event-dir", type=Path, default=UNISWAP_V4_EVENT_DIR)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    args = parser.parse_args()
    return run(
        output_path=args.output,
        support_path=args.support,
        event_dir=args.event_dir,
        candidate_day_path=args.candidate_day,
    )


if __name__ == "__main__":
    raise SystemExit(main())
