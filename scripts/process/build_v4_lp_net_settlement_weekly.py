#!/usr/bin/env python3
"""Build V4 LP transaction and provider-pool-week net-settlement panels.

Reads:
  data/raw/thegraph/uniswap_v4/uniswap_v4_modify_liquidities_*.jsonl.gz
  data/raw/thegraph/uniswap_v4/uniswap_v4_swaps_*.jsonl.gz
  data/processed/token_price_daily.parquet

Writes:
  data/processed/v4_lp_net_settlement_transactions.parquet
  data/processed/v4_lp_net_settlement_weekly.parquet
  output/exhibits/v4_lp_net_settlement_weekly_support.jsonl

For each transaction containing a modify-liquidity event in a vehicle-linked
pool, the processor combines signed token deltas from all observed V4 swap and
modify-liquidity events in that transaction.  It retains two distinct measures:

* settlement-count economy: gross nonzero event-token obligations relative to
  the nonzero token obligations left after transaction-level netting; and
* amount netting: cancellation in the USD value of gross versus net token
  deltas, conditional on canonical daily-price coverage.

``origin`` is a transaction-origin participation proxy.  It is not the
beneficial owner of a position.  The event data do not expose settle/take calls,
position identifiers, transaction gas, or gas price, so these outputs measure
implied event-flow netting rather than actual settlement calls or gas savings.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from ddvc.asset_types import NATIVE_ETH, VEHICLE_CANDIDATES, WETH
from ddvc.capital_validation import (
    CAPITAL_PRICE_SOURCE,
    CAPITAL_PRICE_VALIDATION_STATUS,
    PRICE_MEDIAN_FACTOR,
    PRICE_ROLLING_DAYS,
    USD_STABLE_PRICE_BOUNDS,
    USD_STABLE_TOKENS,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
TRANSACTION_OUTPUT = (
    REPO_ROOT / "data/processed/v4_lp_net_settlement_transactions.parquet"
)
WEEKLY_OUTPUT = REPO_ROOT / "data/processed/v4_lp_net_settlement_weekly.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_net_settlement_weekly_support.jsonl"
MAX_TOKEN_SIDE_EVENT_USD = 100_000_000.0
EPSILON = 1e-12
NATIVE_ETH_ADDRESS = NATIVE_ETH
WETH_ADDRESS = WETH
CANDIDATE_ADDRESSES = frozenset(VEHICLE_CANDIDATES)

CODE_SOURCES = [
    "scripts/process/build_v4_lp_net_settlement_weekly.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
    "data/processed/token_price_daily.parquet",
]


def _float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if np.isfinite(result) else 0.0


def _transaction_id(event: Mapping[str, object]) -> str:
    transaction = event.get("transaction") or {}
    if isinstance(transaction, Mapping):
        identifier = transaction.get("id")
        if identifier:
            return str(identifier).lower()
    return str(event.get("id") or "").split("-")[0].split("#")[0].lower()


def _event_date(event: Mapping[str, object]) -> pd.Timestamp:
    timestamp = event.get("timestamp")
    transaction = event.get("transaction") or {}
    if not timestamp and isinstance(transaction, Mapping):
        timestamp = transaction.get("timestamp")
    return pd.Timestamp(datetime.fromtimestamp(int(timestamp or 0), tz=timezone.utc).date())


def _week_start(value: pd.Timestamp) -> pd.Timestamp:
    day = pd.Timestamp(value).normalize()
    return day - pd.Timedelta(days=day.weekday())


def _canonical_address(address: str) -> str:
    address = str(address or "").lower()
    return WETH_ADDRESS if address == NATIVE_ETH_ADDRESS else address


def _pool_tokens(event: Mapping[str, object]) -> list[tuple[str, str]]:
    pool = event.get("pool") or {}
    if not isinstance(pool, Mapping):
        return []
    tokens: list[tuple[str, str]] = []
    for key in ("token0", "token1"):
        token = pool.get(key) or {}
        if not isinstance(token, Mapping):
            tokens.append(("", ""))
            continue
        tokens.append(
            (
                str(token.get("id") or "").lower(),
                str(token.get("symbol") or ""),
            )
        )
    return tokens


def _pool_id(event: Mapping[str, object]) -> str:
    pool = event.get("pool") or {}
    return str(pool.get("id") or "").lower() if isinstance(pool, Mapping) else ""


def _new_transaction_flow() -> dict[str, object]:
    return {
        "gross_by_token": defaultdict(float),
        "net_by_token": defaultdict(float),
        "legs_by_token": defaultdict(int),
        "modify_events": 0,
        "swap_events": 0,
    }


def _new_action_state() -> dict[str, object]:
    return {
        "senders": set(),
        "candidate_symbols": set(),
        "add_events": 0,
        "remove_events": 0,
        "zero_liquidity_events": 0,
        "supply_side_assignments": 0,
        "valued_supply_side_assignments": 0,
        "missing_price_assignments": 0,
        "above_screen_assignments": 0,
        "gross_lp_flow_usd": 0.0,
        "add_lp_flow_usd": 0.0,
        "remove_lp_flow_usd": 0.0,
        "add_log_tick_width_sum": 0.0,
        "add_range_observations": 0,
    }


def _add_event_deltas(
    state: dict[str, object],
    event: Mapping[str, object],
    *,
    kind: str,
) -> None:
    tokens = _pool_tokens(event)
    for side, (address, _symbol) in enumerate(tokens):
        amount = _float(event.get(f"amount{side}"))
        if not address or abs(amount) <= EPSILON:
            continue
        state["gross_by_token"][address] += abs(amount)
        state["net_by_token"][address] += amount
        state["legs_by_token"][address] += 1
    state[f"{kind}_events"] = int(state[f"{kind}_events"]) + 1


def _settlement_metrics(
    state: Mapping[str, object],
    *,
    day: str,
    prices: Mapping[tuple[str, str], float],
) -> dict[str, float | int]:
    gross_by_token = state["gross_by_token"]
    net_by_token = state["net_by_token"]
    legs_by_token = state["legs_by_token"]
    gross_count = int(sum(legs_by_token.values()))
    net_count = 0
    priced_legs = 0
    gross_usd = 0.0
    net_usd = 0.0
    token_netting_shares: list[float] = []
    netted_tokens = 0
    for address, gross in gross_by_token.items():
        if gross <= 0:
            continue
        net = abs(float(net_by_token[address]))
        tolerance = max(EPSILON, float(gross) * EPSILON)
        if net > tolerance:
            net_count += 1
        reduction_share = float(np.clip(1.0 - net / float(gross), 0.0, 1.0))
        token_netting_shares.append(reduction_share)
        if reduction_share > EPSILON:
            netted_tokens += 1
        price = prices.get((day, _canonical_address(address)))
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        priced_legs += int(legs_by_token[address])
        gross_usd += float(gross) * float(price)
        net_usd += net * float(price)
    reduction_count = max(gross_count - net_count, 0)
    reduction_usd = max(gross_usd - net_usd, 0.0)
    return {
        "gross_obligation_count": gross_count,
        "net_obligation_count": net_count,
        "settlement_reduction_count": reduction_count,
        "settlement_count_reduction_share": (
            reduction_count / gross_count if gross_count else np.nan
        ),
        "netted_token_count": netted_tokens,
        "mean_token_amount_netting_share": (
            float(np.mean(token_netting_shares)) if token_netting_shares else np.nan
        ),
        "priced_obligation_legs": priced_legs,
        "gross_event_flow_usd": gross_usd,
        "net_obligation_flow_usd": net_usd,
        "amount_netting_reduction_usd": reduction_usd,
        "amount_netting_value_share": (
            reduction_usd / gross_usd if gross_usd > 0 else np.nan
        ),
        "settlement_value_coverage_share": (
            priced_legs / gross_count if gross_count else np.nan
        ),
    }


def build_day_transactions(
    modify_path: Path,
    swap_path: Path | None,
    *,
    prices: Mapping[tuple[str, str], float],
    max_token_side_event_usd: float = MAX_TOKEN_SIDE_EVENT_USD,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return provider-pool transaction rows for one raw event day."""

    transaction_flows: dict[str, dict[str, object]] = defaultdict(
        _new_transaction_flow
    )
    actions: dict[tuple[str, str, str], dict[str, object]] = defaultdict(
        _new_action_state
    )
    metadata: dict[tuple[str, str, str], dict[str, object]] = {}
    raw_modify_events = 0
    candidate_modify_events = 0
    blank_origin_events = 0
    with gzip.open(modify_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            raw_modify_events += 1
            transaction_id = _transaction_id(event)
            if not transaction_id:
                continue
            _add_event_deltas(transaction_flows[transaction_id], event, kind="modify")
            tokens = _pool_tokens(event)
            canonical_tokens = [_canonical_address(address) for address, _ in tokens]
            if not any(address in CANDIDATE_ADDRESSES for address in canonical_tokens):
                continue
            candidate_modify_events += 1
            origin = str(event.get("origin") or "").lower()
            if not origin:
                blank_origin_events += 1
                continue
            pool = _pool_id(event)
            if not pool:
                continue
            key = (transaction_id, origin, pool)
            state = actions[key]
            date = _event_date(event)
            day = date.strftime("%Y%m%d")
            metadata.setdefault(
                key,
                {
                    "transaction_id": transaction_id,
                    "origin_date": date,
                    "week_start": _week_start(date),
                    "origin": origin,
                    "pool": pool,
                    "token0_address": tokens[0][0] if len(tokens) > 0 else "",
                    "token0_symbol": tokens[0][1] if len(tokens) > 0 else "",
                    "token1_address": tokens[1][0] if len(tokens) > 1 else "",
                    "token1_symbol": tokens[1][1] if len(tokens) > 1 else "",
                },
            )
            sender = str(event.get("sender") or "").lower()
            if sender:
                state["senders"].add(sender)
            for (raw_address, symbol), canonical in zip(
                tokens, canonical_tokens, strict=False
            ):
                if raw_address and canonical in CANDIDATE_ADDRESSES:
                    state["candidate_symbols"].add(
                        VEHICLE_CANDIDATES.get(canonical, symbol)
                    )
            liquidity = _float(event.get("amount"))
            sign = "add" if liquidity > 0 else "remove" if liquidity < 0 else "zero_liquidity"
            state[f"{sign}_events"] = int(state[f"{sign}_events"]) + 1
            if sign == "add":
                try:
                    width = int(event.get("tickUpper")) - int(event.get("tickLower"))
                except (TypeError, ValueError):
                    width = 0
                if width > 0:
                    state["add_log_tick_width_sum"] = float(
                        state["add_log_tick_width_sum"]
                    ) + float(np.log(width))
                    state["add_range_observations"] = int(
                        state["add_range_observations"]
                    ) + 1
            if sign == "zero_liquidity":
                continue
            for side, (raw_address, _symbol) in enumerate(tokens):
                amount = abs(_float(event.get(f"amount{side}")))
                if not raw_address or amount <= EPSILON:
                    continue
                state["supply_side_assignments"] = int(
                    state["supply_side_assignments"]
                ) + 1
                price = prices.get((day, _canonical_address(raw_address)))
                if price is None or not np.isfinite(price) or price <= 0:
                    state["missing_price_assignments"] = int(
                        state["missing_price_assignments"]
                    ) + 1
                    continue
                value = amount * float(price)
                if not np.isfinite(value) or value <= 0:
                    continue
                if value > max_token_side_event_usd:
                    state["above_screen_assignments"] = int(
                        state["above_screen_assignments"]
                    ) + 1
                    continue
                state["valued_supply_side_assignments"] = int(
                    state["valued_supply_side_assignments"]
                ) + 1
                state["gross_lp_flow_usd"] = float(state["gross_lp_flow_usd"]) + value
                state[f"{sign}_lp_flow_usd"] = float(
                    state[f"{sign}_lp_flow_usd"]
                ) + value

    relevant_transactions = {key[0] for key in actions}
    transaction_flows = {
        transaction_id: transaction_flows[transaction_id]
        for transaction_id in relevant_transactions
    }
    raw_swap_events = 0
    matched_swap_events = 0
    if swap_path is not None and swap_path.exists():
        with gzip.open(swap_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_swap_events += 1
                event = json.loads(line)
                transaction_id = _transaction_id(event)
                state = transaction_flows.get(transaction_id)
                if state is None:
                    continue
                matched_swap_events += 1
                _add_event_deltas(state, event, kind="swap")

    rows: list[dict[str, object]] = []
    for key, state in actions.items():
        transaction_id = key[0]
        record = dict(metadata[key])
        day = pd.Timestamp(record["origin_date"]).strftime("%Y%m%d")
        settlement = _settlement_metrics(
            transaction_flows[transaction_id], day=day, prices=prices
        )
        add_flow = float(state["add_lp_flow_usd"])
        remove_flow = float(state["remove_lp_flow_usd"])
        supply_sides = int(state["supply_side_assignments"])
        valued_sides = int(state["valued_supply_side_assignments"])
        record.update(
            {
                "candidate_symbols": "+".join(sorted(state["candidate_symbols"])),
                "sender_count": len(state["senders"]),
                "modify_events_in_tx": int(
                    transaction_flows[transaction_id]["modify_events"]
                ),
                "swap_events_in_tx": int(
                    transaction_flows[transaction_id]["swap_events"]
                ),
                "contains_swap": int(
                    int(transaction_flows[transaction_id]["swap_events"]) > 0
                ),
                "add_events": int(state["add_events"]),
                "remove_events": int(state["remove_events"]),
                "zero_liquidity_events": int(state["zero_liquidity_events"]),
                "reposition_tx": int(
                    int(state["add_events"]) > 0 and int(state["remove_events"]) > 0
                ),
                "supply_side_assignments": supply_sides,
                "valued_supply_side_assignments": valued_sides,
                "missing_price_assignments": int(state["missing_price_assignments"]),
                "above_screen_assignments": int(state["above_screen_assignments"]),
                "lp_flow_value_coverage_share": (
                    valued_sides / supply_sides if supply_sides else np.nan
                ),
                "gross_lp_flow_usd": add_flow + remove_flow,
                "add_lp_flow_usd": add_flow,
                "remove_lp_flow_usd": remove_flow,
                "net_add_lp_flow_usd": add_flow - remove_flow,
                "add_log_tick_width_sum": float(state["add_log_tick_width_sum"]),
                "add_range_observations": int(state["add_range_observations"]),
                **settlement,
            }
        )
        record["lp_tx_has_netting"] = int(int(record["netted_token_count"]) > 0)
        record["lp_tx_has_settlement_compression"] = int(
            int(record["settlement_reduction_count"]) > 0
        )
        rows.append(record)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(
            ["origin_date", "transaction_id", "origin", "pool"]
        ).reset_index(drop=True)
    support = {
        "raw_modify_events": raw_modify_events,
        "candidate_modify_events": candidate_modify_events,
        "blank_origin_events": blank_origin_events,
        "relevant_transactions": len(relevant_transactions),
        "raw_swap_events_scanned": raw_swap_events,
        "matched_swap_events": matched_swap_events,
        "provider_pool_transaction_rows": len(frame),
    }
    return frame, support


def aggregate_provider_pool_week(transactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transaction inputs without discarding their support counts."""

    if transactions.empty:
        raise ValueError("V4 LP net-settlement transaction panel is empty")
    required = {
        "week_start",
        "origin",
        "pool",
        "transaction_id",
        "candidate_symbols",
        "add_events",
        "remove_events",
        "zero_liquidity_events",
        "reposition_tx",
        "gross_lp_flow_usd",
        "add_lp_flow_usd",
        "remove_lp_flow_usd",
        "supply_side_assignments",
        "valued_supply_side_assignments",
        "gross_obligation_count",
        "settlement_reduction_count",
        "priced_obligation_legs",
        "gross_event_flow_usd",
        "net_obligation_flow_usd",
        "amount_netting_reduction_usd",
        "lp_tx_has_netting",
        "lp_tx_has_settlement_compression",
        "add_log_tick_width_sum",
        "add_range_observations",
    }
    missing = sorted(required - set(transactions.columns))
    if missing:
        raise ValueError(f"V4 LP transaction panel lacks columns: {missing}")
    key = ["week_start", "origin", "pool"]
    weekly = (
        transactions.groupby(key, as_index=False, sort=True)
        .agg(
            candidate_symbols=("candidate_symbols", lambda x: "+".join(sorted(set(x)))),
            lp_tx_count=("transaction_id", "nunique"),
            netted_lp_tx_count=("lp_tx_has_netting", "sum"),
            compressed_lp_tx_count=("lp_tx_has_settlement_compression", "sum"),
            add_events=("add_events", "sum"),
            remove_events=("remove_events", "sum"),
            zero_liquidity_events=("zero_liquidity_events", "sum"),
            reposition_tx_count=("reposition_tx", "sum"),
            gross_lp_flow_usd=("gross_lp_flow_usd", "sum"),
            add_lp_flow_usd=("add_lp_flow_usd", "sum"),
            remove_lp_flow_usd=("remove_lp_flow_usd", "sum"),
            supply_side_assignments=("supply_side_assignments", "sum"),
            valued_supply_side_assignments=("valued_supply_side_assignments", "sum"),
            gross_obligation_count=("gross_obligation_count", "sum"),
            settlement_reduction_count=("settlement_reduction_count", "sum"),
            priced_obligation_legs=("priced_obligation_legs", "sum"),
            gross_event_flow_usd=("gross_event_flow_usd", "sum"),
            net_obligation_flow_usd=("net_obligation_flow_usd", "sum"),
            amount_netting_reduction_usd=("amount_netting_reduction_usd", "sum"),
            add_log_tick_width_sum=("add_log_tick_width_sum", "sum"),
            add_range_observations=("add_range_observations", "sum"),
        )
    )
    weekly["provider_pool_id"] = weekly["origin"] + "|" + weekly["pool"]
    weekly["net_add_lp_flow_usd"] = (
        weekly["add_lp_flow_usd"] - weekly["remove_lp_flow_usd"]
    )
    weekly["net_add_flow_balance"] = weekly["net_add_lp_flow_usd"] / (
        weekly["gross_lp_flow_usd"] + 1.0
    )
    weekly["netting_tx_share"] = weekly["netted_lp_tx_count"] / weekly["lp_tx_count"]
    weekly["settlement_compression_tx_share"] = (
        weekly["compressed_lp_tx_count"] / weekly["lp_tx_count"]
    )
    weekly["settlement_count_reduction_share"] = (
        weekly["settlement_reduction_count"] / weekly["gross_obligation_count"]
    )
    weekly["amount_netting_value_share"] = np.where(
        weekly["gross_event_flow_usd"] > 0,
        weekly["amount_netting_reduction_usd"] / weekly["gross_event_flow_usd"],
        np.nan,
    )
    weekly["settlement_value_coverage_share"] = np.where(
        weekly["gross_obligation_count"] > 0,
        weekly["priced_obligation_legs"] / weekly["gross_obligation_count"],
        np.nan,
    )
    weekly["lp_flow_value_coverage_share"] = np.where(
        weekly["supply_side_assignments"] > 0,
        weekly["valued_supply_side_assignments"] / weekly["supply_side_assignments"],
        np.nan,
    )
    weekly["reposition_tx_share"] = weekly["reposition_tx_count"] / weekly["lp_tx_count"]
    weekly["mean_add_log_tick_width"] = np.where(
        weekly["add_range_observations"] > 0,
        weekly["add_log_tick_width_sum"] / weekly["add_range_observations"],
        np.nan,
    )
    grouped = weekly.groupby("provider_pool_id", sort=False)["week_start"]
    weekly["first_observed_week"] = grouped.transform("min")
    weekly["last_observed_week"] = grouped.transform("max")
    weekly["first_observed_participation_proxy"] = weekly["week_start"].eq(
        weekly["first_observed_week"]
    ).astype(int)
    weekly["last_observed_participation_proxy"] = weekly["week_start"].eq(
        weekly["last_observed_week"]
    ).astype(int)
    return weekly.sort_values(key).reset_index(drop=True)


def _price_lookup(path: Path) -> dict[tuple[str, str], float]:
    """Return every canonical address-day price that passes the shared checks."""

    prices = pd.read_parquet(
        path,
        columns=["day", "token", "price_usd", "price_source", "validation_status"],
    )
    if prices.empty:
        raise ValueError("canonical token-price panel is empty")
    prices = prices.copy()
    prices["day"] = prices["day"].astype(str)
    prices["token"] = prices["token"].astype(str).str.lower()
    prices["price_usd"] = pd.to_numeric(prices["price_usd"], errors="coerce")
    if prices.duplicated(["day", "token"]).any():
        raise ValueError("canonical token-price panel has duplicate address-days")
    prices = prices.sort_values(["token", "day"]).reset_index(drop=True)
    median = prices.groupby("token", sort=False)["price_usd"].transform(
        lambda values: values.rolling(PRICE_ROLLING_DAYS, min_periods=5).median()
    )
    price = prices["price_usd"]
    valid = (
        np.isfinite(price)
        & price.gt(0)
        & np.isfinite(median)
        & median.gt(0)
        & price.between(median / PRICE_MEDIAN_FACTOR, median * PRICE_MEDIAN_FACTOR)
        & prices["price_source"].eq("canonical_repriced_route_legs")
        & prices["validation_status"].eq(
            "minimum_observations_and_price_consensus_passed"
        )
    )
    usd_stable = prices["token"].isin(USD_STABLE_TOKENS)
    valid &= ~usd_stable | price.between(*USD_STABLE_PRICE_BOUNDS)
    prices = prices.loc[valid, ["day", "token", "price_usd"]]
    if prices.empty:
        raise ValueError("canonical token-price panel has no usable address-days")
    return {
        (str(row.day), str(row.token).lower()): float(row.price_usd)
        for row in prices.itertuples(index=False)
    }


def build_full_panels(
    *,
    event_dir: Path,
    prices: Mapping[tuple[str, str], float],
    max_token_side_event_usd: float = MAX_TOKEN_SIDE_EVENT_USD,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Read daily raw files and return transaction and weekly panels."""

    swap_files = {
        path.name.removeprefix("uniswap_v4_swaps_").removesuffix(".jsonl.gz"): path
        for path in event_dir.glob("uniswap_v4_swaps_*.jsonl.gz")
    }
    frames: list[pd.DataFrame] = []
    daily_support: list[dict[str, int]] = []
    missing_swap_days = 0
    modify_files = sorted(event_dir.glob("uniswap_v4_modify_liquidities_*.jsonl.gz"))
    for modify_path in modify_files:
        day = modify_path.name.removeprefix(
            "uniswap_v4_modify_liquidities_"
        ).removesuffix(".jsonl.gz")
        swap_path = swap_files.get(day)
        if swap_path is None:
            missing_swap_days += 1
        frame, support = build_day_transactions(
            modify_path,
            swap_path,
            prices=prices,
            max_token_side_event_usd=max_token_side_event_usd,
        )
        if not frame.empty:
            frames.append(frame)
        daily_support.append(support)
    if not frames:
        raise ValueError("raw V4 files produced no provider-pool transaction rows")
    transactions = pd.concat(frames, ignore_index=True, sort=False)
    weekly = aggregate_provider_pool_week(transactions)
    support: dict[str, object] = {
        "record_type": "v4_lp_net_settlement_weekly_support",
        "analysis_status": "exploratory_lp_supply_association",
        "modify_event_files": len(modify_files),
        "missing_same_day_swap_files": missing_swap_days,
        "transaction_rows": len(transactions),
        "provider_pool_week_rows": len(weekly),
        "provider_proxies": int(weekly["origin"].nunique()),
        "pools": int(weekly["pool"].nunique()),
        "provider_pools": int(weekly["provider_pool_id"].nunique()),
        "first_week": str(weekly["week_start"].min().date()),
        "last_week": str(weekly["week_start"].max().date()),
        "identity_boundary": (
            "transaction origin is a participation proxy, not verified LP-position "
            "beneficial ownership"
        ),
        "settlement_boundary": (
            "gross event-token deltas versus transaction-net token obligations; "
            "settle/take calls are not observed"
        ),
        "gas_boundary": "raw Graph events contain no transaction gas or gas price",
        "price_source": CAPITAL_PRICE_SOURCE,
        "price_validation_status": CAPITAL_PRICE_VALIDATION_STATUS,
        "participation_boundary": (
            "first/last observed origin-pool weeks are censoring-sensitive "
            "persistence proxies, not entry or exit"
        ),
    }
    for name in daily_support[0] if daily_support else ():
        support[name] = int(sum(item[name] for item in daily_support))
    return transactions, weekly, support


def run(
    *,
    event_dir: Path = EVENT_DIR,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    transaction_output: Path = TRANSACTION_OUTPUT,
    weekly_output: Path = WEEKLY_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    max_token_side_event_usd: float = MAX_TOKEN_SIDE_EVENT_USD,
) -> int:
    prices = _price_lookup(price_path)
    transactions, weekly, support = build_full_panels(
        event_dir=event_dir,
        prices=prices,
        max_token_side_event_usd=max_token_side_event_usd,
    )
    with atomic_output(transaction_output) as temporary:
        transactions.to_parquet(temporary, index=False)
    with atomic_output(weekly_output) as temporary:
        weekly.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(transactions):,} V4 provider-pool transactions and "
        f"{len(weekly):,} provider-pool weeks"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument("--transactions", type=Path, default=TRANSACTION_OUTPUT)
    parser.add_argument("--weekly", type=Path, default=WEEKLY_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument(
        "--max-token-side-event-usd",
        type=float,
        default=MAX_TOKEN_SIDE_EVENT_USD,
    )
    args = parser.parse_args()
    return run(
        event_dir=args.event_dir,
        price_path=args.price,
        transaction_output=args.transactions,
        weekly_output=args.weekly,
        support_output=args.support,
        max_token_side_event_usd=args.max_token_side_event_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
