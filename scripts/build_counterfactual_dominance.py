#!/usr/bin/env python3
"""Cost-dominance windows, measured against a same-state counterfactual.

The question the paper's inertia claim depends on: are there windows in which an
incumbent intermediary keeps carrying routed volume while a direct route would
have returned strictly more output at the same market state?

Why this design and not the previous one. Comparing realised trades across a day
fails, because intraday price movement swamps execution cost by roughly 34 to 1
(`docs/finding-cost-dominance-not-yet-established.md`). Here both routes are
priced against the *same* reconstructed pre-trade reserves, so price movement
cannot enter the comparison at all.

Method, per executed indirect (two-leg) route:
  1. reconstruct exact pre-trade reserves for every v2-family pool in that hour by
     unwinding the hour's swaps backward from the stored end-of-hour reserve
     (validated at median absolute error 0.0000%, 95.2% within 0.01%)
  2. replay fetched Uniswap v2 mints and burns in the same block-log timeline and
     keep only pool-hours whose full reserve continuity checks out; SushiSwap hours
     remain swap-only because their liquidity-event stream is unavailable
  3. read the realised output of the canonical two-leg route component
  4. quote the best available DIRECT pool for the same endpoints and input size at
     the same reserves
  5. the gap in basis points is the cost of the road taken against the road not
     taken, gross of gas

A cell is a cost-dominance window when the direct quote strictly exceeds the
intermediated quote, meaning the trade would have been better off going direct at
the moment it was made.

Bias directions:
  - venue coverage is v2-family only, so the best alternative is understated and
    dominance incidence is a LOWER bound
  - quotes are gross of gas, and a two-hop route burns more gas, so omitting gas
    favours the realised vehicle route. Gross-of-gas dominance is also a LOWER
    bound on all-in dominance. The gas-inclusive version requires historical gas
    prices and receipt-measured gas per route topology.

Reads   data/raw/thegraph/{uniswap_v2,sushiswap_v2}/*_{swaps,hourly_reserves}_*.gz
Writes  data/processed/counterfactual_dominance.parquet
        output/exhibits/counterfactual_dominance_summary.jsonl
        output/exhibits/counterfactual_dominance_support.jsonl
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
from decimal import Decimal

import pandas as pd

from ddvc.analysis.regression import mean_clustered
from ddvc.asset_types import WETH, classify
from ddvc.calendar import nearest_monthly_days
from ddvc.cpquote import (
    Pool,
    ReserveEvent,
    all_in_direct_advantage_bps_from_units,
    cost_gap_bps,
    hour_is_clean,
    ordered_reserve_events,
    prior_observed_state,
    quote_one_hop,
    reserve_state_before,
)
from ddvc.gas import load_daily_gas_prices
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.prices import PRICE_COLUMNS, day_prices
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.route_gas import GAS_ESTIMATE_COLUMNS, estimate_route_gas
from ddvc.tables import write_exhibit, write_panel

RAW = DATA_DIR / "raw" / "thegraph"
UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "counterfactual_dominance.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "counterfactual_dominance_summary.jsonl"
OUT_SUPPORT = OUTPUT_DIR / "exhibits" / "counterfactual_dominance_support.jsonl"
GAS_PANEL = DATA_DIR / "processed" / "daily_gas_price_graph.parquet"
ROUTE_GAS_PANEL = DATA_DIR / "processed" / "route_gas_units.parquet"
CODE_SOURCES = [
    "scripts/build_counterfactual_dominance.py",
    "src/ddvc/calendar.py",
    "src/ddvc/cpquote.py",
    "src/ddvc/gas.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/prices.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_gas.py",
    "src/ddvc/route_roles.py",
]

VENUES = ("uniswap_v2", "sushiswap_v2")
MIN_USD = 100.0            # below this, gas dominates and the comparison is moot


def counterfactual_days(
    available: list[str], *, explicit: list[str] | None = None, limit: int | None = None
) -> list[str]:
    """Select the prespecified monthly calendar, or exact explicit validation days."""
    days = list(dict.fromkeys(explicit)) if explicit else nearest_monthly_days(available)
    return days[:limit] if limit is not None else days


def _net(s: dict) -> tuple[Decimal, Decimal]:
    return (Decimal(s.get("amount0In", "0")) - Decimal(s.get("amount0Out", "0")),
            Decimal(s.get("amount1In", "0")) - Decimal(s.get("amount1Out", "0")))


def _load_day(day: str) -> tuple[dict, dict, dict, dict]:
    """Return reserves, pool metadata, swaps and ordered liquidity changes."""
    reserves: dict[tuple[str, int], tuple[Decimal, Decimal]] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    swaps: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    liquidity: dict[
        tuple[str, int],
        list[tuple[tuple[int, int], tuple[Decimal, Decimal]]],
    ] = collections.defaultdict(list)
    previous_day = (
        pd.to_datetime(day, format="%Y%m%d") - pd.Timedelta(days=1)
    ).strftime("%Y%m%d")
    for venue in VENUES:
        previous_path = (
            RAW
            / venue
            / f"{venue}_hourly_reserves_{previous_day}.jsonl.gz"
        )
        latest_previous: dict[
            str, tuple[int, tuple[Decimal, Decimal], tuple[str, str, str]]
        ] = {}
        if previous_path.exists():
            with gzip.open(previous_path, "rt") as handle:
                for line in handle:
                    row = json.loads(line)
                    pair = row.get("pair") or {}
                    pid = str(pair.get("id") or "").lower()
                    try:
                        hour = int(row["hourStartUnix"])
                        state = (
                            Decimal(row["reserve0"]),
                            Decimal(row["reserve1"]),
                        )
                        pool_meta = (
                            pair["token0"]["id"].lower(),
                            pair["token1"]["id"].lower(),
                            venue,
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                    prior = latest_previous.get(pid)
                    if pid and (prior is None or hour > prior[0]):
                        latest_previous[pid] = (hour, state, pool_meta)
        for pid, (hour, state, pool_meta) in latest_previous.items():
            reserves[(pid, hour)] = state
            meta[pid] = pool_meta

        rp = RAW / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz"
        sp = RAW / venue / f"{venue}_swaps_{day}.jsonl.gz"
        if rp.exists():
            with gzip.open(rp, "rt") as fh:
                for line in fh:
                    d = json.loads(line)
                    pr = d.get("pair") or {}
                    pid = str(pr.get("id") or "").lower()
                    if not pid:
                        continue
                    reserves[(pid, int(d["hourStartUnix"]))] = (
                        Decimal(d["reserve0"]), Decimal(d["reserve1"]))
                    meta[pid] = (pr["token0"]["id"].lower(),
                                 pr["token1"]["id"].lower(), venue)
        if sp.exists():
            with gzip.open(sp, "rt") as fh:
                for line in fh:
                    s = json.loads(line)
                    pid = str((s.get("pair") or {}).get("id") or "").lower()
                    ts = int(s.get("timestamp", 0))
                    transaction = s.get("transaction") or {}
                    try:
                        order = (int(transaction.get("blockNumber")), int(s.get("logIndex")))
                    except (TypeError, ValueError):
                        continue
                    if pid and ts:
                        s["_tx"] = str(
                            transaction.get("id") or s.get("id", "")
                        ).lower()
                        s["_order"] = order
                        swaps[(pid, ts - (ts % 3600))].append(s)
        for stream, sign in (("mints", Decimal(1)), ("burns", Decimal(-1))):
            liquidity_path = RAW / venue / f"{venue}_{stream}_{day}.jsonl.gz"
            if not liquidity_path.exists():
                continue
            with gzip.open(liquidity_path, "rt") as handle:
                for line in handle:
                    event = json.loads(line)
                    pid = str(
                        ((event.get("pair") or {}).get("id") or "")
                    ).lower()
                    transaction = event.get("transaction") or {}
                    try:
                        timestamp = int(event["timestamp"])
                        order = (
                            int(transaction["blockNumber"]),
                            int(event["logIndex"]),
                        )
                        delta = (
                            sign * Decimal(event["amount0"]),
                            sign * Decimal(event["amount1"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                    if pid:
                        hour = timestamp - (timestamp % 3600)
                        liquidity[(pid, hour)].append((order, delta))
    return reserves, meta, swaps, liquidity


def one_day(day: str) -> pd.DataFrame | None:
    reserves, meta, swaps, liquidity = _load_day(day)
    if not reserves or not swaps:
        return None

    # Exact block-log ordered state timelines for pool-hours whose reserve
    # continuity is explained by the fetched swaps, mints and burns.
    clean_hours: set[tuple[str, int]] = set()
    candidate_events: dict[tuple[str, int], list[ReserveEvent]] = {}
    event_deltas: dict[
        tuple[str, int], list[tuple[Decimal, Decimal]]
    ] = {}
    for pid, hour in sorted(set(swaps) | set(liquidity)):
        stored = reserves.get((pid, hour))
        if stored is None:
            continue
        group = swaps.get((pid, hour), [])
        group.sort(key=lambda row: row["_order"])
        changes = [
            *((swap["_order"], _net(swap)) for swap in group),
            *liquidity.get((pid, hour), []),
        ]
        events = ordered_reserve_events(stored, changes)
        deltas = [
            (
                event.after[0] - event.before[0],
                event.after[1] - event.before[1],
            )
            for event in events
        ]
        if any(
            value <= 0
            for event in events
            for state in (event.before, event.after)
            for value in state
        ):
            continue
        candidate_events[(pid, hour)] = events
        event_deltas[(pid, hour)] = deltas

    reserve_states: dict[
        str, dict[int, tuple[Decimal, Decimal]]
    ] = collections.defaultdict(dict)
    deltas_by_pool: dict[
        str, dict[int, list[tuple[Decimal, Decimal]]]
    ] = collections.defaultdict(dict)
    for (pid, hour), state in reserves.items():
        reserve_states[pid][hour] = state
    for (pid, hour), deltas in event_deltas.items():
        deltas_by_pool[pid][hour] = deltas

    pool_hour_events: dict[tuple[str, int], list[ReserveEvent]] = {}
    state_support: dict[tuple[str, int], tuple[int, int]] = {}
    for (pid, hour), events in candidate_events.items():
        prior = prior_observed_state(
            reserve_states[pid], deltas_by_pool[pid], hour
        )
        if prior is None:
            continue
        expected_start, previous_hour = prior
        if not hour_is_clean(
            expected_start, reserves[(pid, hour)], event_deltas[(pid, hour)]
        ):
            continue
        clean_hours.add((pid, hour))
        pool_hour_events[(pid, hour)] = events
        state_support[(pid, hour)] = (
            (hour - previous_hour) // 3600,
            len(liquidity.get((pid, hour), [])),
        )

    # Keep pool-hour boundaries: a clean state in an earlier hour cannot stand in for an
    # unobserved or contaminated current hour.
    pair_index: dict[frozenset, dict[str, dict[int, list[ReserveEvent]]]] = collections.defaultdict(dict)
    for (pid, hour), events in pool_hour_events.items():
        mm = meta.get(pid)
        if mm:
            pair_index[frozenset((mm[0], mm[1]))].setdefault(pid, {})[hour] = events

    unified_path = UNIFIED / f"{day}.parquet"
    if not unified_path.exists():
        return None
    unified = pd.read_parquet(unified_path, columns=LINEAR_ROUTE_COLUMNS)
    prices = day_prices(unified[PRICE_COLUMNS])
    routes = extract_linear_realised_routes(unified)
    if routes.empty:
        return None
    routes = routes[
        routes["realised_hop1_source"].isin(VENUES)
        & routes["realised_hop2_source"].isin(VENUES)
    ].copy()
    if routes.empty:
        return None
    component_keys = ["tx_hash", "component_id"]
    eligible_keys = {
        (str(tx_hash).lower(), int(component_id))
        for tx_hash, component_id in zip(
            routes["tx_hash"], routes["component_id"], strict=True
        )
    }
    route_legs = unified[
        unified["route_class"].eq("coherent")
        & unified["source"].isin(VENUES)
    ].copy()
    route_legs = route_legs[
        [
            (str(tx_hash).lower(), int(component_id)) in eligible_keys
            for tx_hash, component_id in zip(
                route_legs["tx_hash"], route_legs["component_id"], strict=True
            )
        ]
    ]
    grouped_legs = {
        (str(key[0]).lower(), int(key[1])): group.sort_values(
            "log_index", kind="stable"
        )
        for key, group in route_legs.groupby(component_keys, sort=False)
    }

    raw_events: dict[tuple[str, int], dict] = {}
    for (pid, hour), group in swaps.items():
        for s in group:
            s["_pool"] = pid
            s["_hour"] = hour
            key = (s["_tx"], int(s["logIndex"]))
            prior = raw_events.get(key)
            if prior is not None:
                if (
                    prior["_pool"] == pid
                    and prior["_order"] == s["_order"]
                    and _net(prior) == _net(s)
                ):
                    continue
                raise ValueError(f"conflicting V2 transaction-log event: {key}")
            raw_events[key] = s

    rows = []
    for route in routes.to_dict("records"):
        tx = str(route["tx_hash"]).lower()
        component_key = (tx, int(route["component_id"]))
        legs = grouped_legs.get(component_key)
        if legs is None or len(legs) != 2:
            continue
        raw_legs = [
            raw_events.get((tx, int(log_index)))
            for log_index in legs["log_index"]
        ]
        if any(leg is None for leg in raw_legs):
            continue
        l1, l2 = raw_legs
        assert l1 is not None and l2 is not None
        if any(
            (leg["_pool"], leg["_hour"]) not in clean_hours
            for leg in (l1, l2)
        ):
            continue
        if l1["_order"][0] != l2["_order"][0] or l1["_hour"] != l2["_hour"]:
            continue
        route_order = min(l1["_order"], l2["_order"])
        a_in = str(route["src"]).lower()
        mid1 = str(route["vehicle"]).lower()
        b_out = str(route["tgt"]).lower()
        amt_in = Decimal(str(route["realised_amount_in"]))
        out_amt = Decimal(str(route["realised_amount_out"]))
        usd = float(route["input_usd"])
        if usd < MIN_USD:
            continue

        # counterfactual: best DIRECT pool for the same endpoints at the same state.
        # Indexed by unordered pair, so this is a lookup instead of a scan.
        cands = pair_index.get(frozenset((a_in, b_out)))
        if not cands:
            continue                            # no direct pool existed: not a window
        best_direct = None
        best_direct_pool = None
        t_route = int(l1["timestamp"])
        route_hour = t_route - (t_route % 3600)
        for pid_d, hours in cands.items():
            mm = meta[pid_d]
            events = hours.get(route_hour)
            st = reserve_state_before(events, route_order) if events else None
            if st is None:
                continue
            q = quote_one_hop(Pool(pid_d, mm[0], mm[1], st[0], st[1], mm[2]), a_in, amt_in)
            if q and (best_direct is None or q > best_direct):
                best_direct = q
                best_direct_pool = pid_d
        if best_direct is None:
            continue
        assert best_direct_pool is not None

        sym, typ = classify(mid1)
        hop1_source = str(route["realised_hop1_source"])
        hop2_source = str(route["realised_hop2_source"])
        direct_source = meta[best_direct_pool][2]
        realised_venue_set = {hop1_source, hop2_source}
        target_price = prices[b_out][1]
        direct_output_usd = float(best_direct) * target_price
        realised_output_usd = float(route["output_usd"])
        gross_direct_advantage_bps = (
            10_000 * (direct_output_usd - realised_output_usd) / usd
        )
        direct_output_improvement_bps = cost_gap_bps(best_direct, out_amt)
        eth_price = prices.get(WETH)
        hop1_support = state_support[(l1["_pool"], l1["_hour"])]
        hop2_support = state_support[(l2["_pool"], l2["_hour"])]
        direct_support = state_support[(best_direct_pool, route_hour)]
        rows.append({
            "date": pd.to_datetime(day, format="%Y%m%d"),
            "route_id": route["route_id"], "tx": tx,
            "component_id": int(route["component_id"]),
            "block": route_order[0], "first_log_index": route_order[1],
            "token_in": a_in, "token_out": b_out, "mid": mid1,
            "mid_symbol": sym, "mid_type": typ, "usd": usd,
            "realised_out": float(out_amt), "direct_quote": float(best_direct),
            "realised_output_usd": realised_output_usd,
            "direct_output_usd": direct_output_usd,
            "realised_to_input_value_ratio": realised_output_usd / usd,
            "eth_usd": eth_price[1] if eth_price else None,
            "hop1_pool": l1["_pool"], "hop2_pool": l2["_pool"],
            "hop1_source": hop1_source, "hop2_source": hop2_source,
            "direct_pool": best_direct_pool, "direct_source": direct_source,
            "hop1_prior_state_gap_hours": hop1_support[0],
            "hop2_prior_state_gap_hours": hop2_support[0],
            "direct_prior_state_gap_hours": direct_support[0],
            "hop1_liquidity_events_replayed": hop1_support[1],
            "hop2_liquidity_events_replayed": hop2_support[1],
            "direct_liquidity_events_replayed": direct_support[1],
            "best_direct_outside_realised_venue_set": (
                direct_source not in realised_venue_set
            ),
            "gross_direct_advantage_bps": gross_direct_advantage_bps,
            "direct_output_improvement_bps": direct_output_improvement_bps,
        })
    return pd.DataFrame(rows) if rows else None


def add_topology_gas_adjustment(
    frame: pd.DataFrame,
    gas_panel=GAS_PANEL,
    route_gas_panel=ROUTE_GAS_PANEL,
) -> pd.DataFrame:
    """Join historical prices and receipt-calibrated gas by exact route support."""
    out = frame.copy()
    out = out.drop(columns=["gas_gwei"], errors="ignore")
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["year"] = out["date"].dt.year
    gas = load_daily_gas_prices(
        gas_panel,
        required_dates=out["date"],
    )[["date", "gas_gwei_median"]].rename(
        columns={"gas_gwei_median": "gas_gwei"}
    )
    out = out.merge(gas, on="date", how="left", validate="many_to_one")
    receipt_panel = (
        route_gas_panel.copy()
        if isinstance(route_gas_panel, pd.DataFrame)
        else pd.read_parquet(route_gas_panel)
    )
    direct_requests = pd.DataFrame(
        {
            "year": out["year"],
            "legs": 1,
            "venue_sequence": out["direct_source"],
            "gas_vehicle": "direct",
            "mid_type": "direct",
        },
        index=out.index,
    )
    vehicle_requests = pd.DataFrame(
        {
            "year": out["year"],
            "legs": 2,
            "venue_sequence": out["hop1_source"] + ">" + out["hop2_source"],
            "gas_vehicle": out["mid"],
            "mid_type": out["mid_type"],
        },
        index=out.index,
    )
    for prefix, estimates in (
        ("direct", estimate_route_gas(direct_requests, receipt_panel)),
        ("vehicle", estimate_route_gas(vehicle_requests, receipt_panel)),
    ):
        out[[f"{prefix}_{column}" for column in GAS_ESTIMATE_COLUMNS]] = (
            estimates[GAS_ESTIMATE_COLUMNS]
        )

    def apply_units(direct_column: str, vehicle_column: str) -> list[float | None]:
        return [
            all_in_direct_advantage_bps_from_units(
                gross,
                direct_gas_units=direct_units,
                vehicle_gas_units=vehicle_units,
                notional_usd=notional,
                gas_price_gwei=gas_gwei,
                eth_usd=eth_usd,
            )
            if all(
                pd.notna(value)
                for value in (
                    direct_units,
                    vehicle_units,
                    gas_gwei,
                    eth_usd,
                )
            )
            else None
            for gross, direct_units, vehicle_units, notional, gas_gwei, eth_usd in zip(
                out["gross_direct_advantage_bps"],
                out[direct_column],
                out[vehicle_column],
                out["usd"],
                out["gas_gwei"],
                out["eth_usd"],
                strict=True,
            )
        ]

    out["all_in_direct_advantage_bps"] = apply_units(
        "direct_gas_units_median", "vehicle_gas_units_median"
    )
    out["all_in_direct_advantage_bps_iqr_lower"] = apply_units(
        "direct_gas_units_p75", "vehicle_gas_units_p25"
    )
    out["all_in_direct_advantage_bps_iqr_upper"] = apply_units(
        "direct_gas_units_p25", "vehicle_gas_units_p75"
    )
    return out


def classify_state_support(frame: pd.DataFrame) -> pd.Series:
    """Label whether three pre-trade states are adjacent, bridged, or replayed."""
    gap_columns = [
        "hop1_prior_state_gap_hours",
        "hop2_prior_state_gap_hours",
        "direct_prior_state_gap_hours",
    ]
    liquidity_columns = [
        "hop1_liquidity_events_replayed",
        "hop2_liquidity_events_replayed",
        "direct_liquidity_events_replayed",
    ]
    missing = sorted(set(gap_columns + liquidity_columns) - set(frame.columns))
    if missing:
        raise ValueError("state-support classification is missing " + ", ".join(missing))
    liquidity_replayed = frame[liquidity_columns].gt(0).any(axis=1)
    adjacent = frame[gap_columns].eq(1).all(axis=1) & ~liquidity_replayed
    labels = pd.Series("bridged_no_liquidity", index=frame.index, dtype="object")
    labels.loc[adjacent] = "adjacent_no_liquidity"
    labels.loc[liquidity_replayed] = "liquidity_replayed"
    return labels


def state_support_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Annual and pooled dominance diagnostics by reserve-state support class."""
    data = frame.copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    rows: list[dict[str, object]] = []

    def append(scope: str, year: int | None, support: str, group: pd.DataFrame) -> None:
        coherent = group[group["valuation_coherent_20pct"]]
        gas = group[group["all_in_direct_advantage_bps"].notna()]
        dominated = group[group["dominated_gross"]]
        rows.append(
            {
                "scope": scope,
                "year": year,
                "state_support": support,
                "routes": len(group),
                "pct_dominated_gross": 100 * float(group["dominated_gross"].mean()),
                "valuation_coherent_20pct_routes": len(coherent),
                "pct_dominated_valuation_coherent_20pct": (
                    100 * float(coherent["dominated_gross"].mean())
                    if len(coherent)
                    else None
                ),
                "gas_supported_routes": len(gas),
                "pct_dominated_topology_gas_adjusted": (
                    100 * float(gas["all_in_direct_advantage_bps"].gt(0).mean())
                    if len(gas)
                    else None
                ),
                "pct_dominated_gas_iqr_lower": (
                    100
                    * float(
                        group["all_in_direct_advantage_bps_iqr_lower"]
                        .dropna()
                        .gt(0)
                        .mean()
                    )
                    if group["all_in_direct_advantage_bps_iqr_lower"].notna().any()
                    else None
                ),
                "pct_dominated_gas_iqr_upper": (
                    100
                    * float(
                        group["all_in_direct_advantage_bps_iqr_upper"]
                        .dropna()
                        .gt(0)
                        .mean()
                    )
                    if group["all_in_direct_advantage_bps_iqr_upper"].notna().any()
                    else None
                ),
                "dominated_routes": len(dominated),
                "pct_dominated_outside_realised_venue_set": (
                    100
                    * float(
                        dominated["best_direct_outside_realised_venue_set"].mean()
                    )
                    if len(dominated)
                    else None
                ),
                "median_price_free_output_improvement_bps": float(
                    group["direct_output_improvement_bps"].median()
                ),
            }
        )

    for support, group in data.groupby("state_support", sort=True):
        append("pooled", None, str(support), group)
    for (year, support), group in data.groupby(["year", "state_support"], sort=True):
        append("annual", int(year), str(support), group)
    return pd.DataFrame(rows)


def dominance_level_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Pooled incidence, weighting sensitivity, uncertainty, and dollar magnitude."""
    definitions = {
        "gross_output": ("gross_direct_advantage_bps", "dominated_gross"),
        "matched_gas_p25_bound": (
            "all_in_direct_advantage_bps_iqr_lower",
            None,
        ),
        "matched_gas_median": ("all_in_direct_advantage_bps", None),
        "matched_gas_p75_bound": (
            "all_in_direct_advantage_bps_iqr_upper",
            None,
        ),
    }
    support_masks = {
        "all_routes": pd.Series(True, index=frame.index),
        "within_20pct": frame["valuation_coherent_20pct"].fillna(False),
    }
    rows: list[dict[str, object]] = []
    for support, support_mask in support_masks.items():
        for economic_object, (advantage_column, indicator_column) in definitions.items():
            sample = frame.loc[support_mask & frame[advantage_column].notna()].copy()
            if sample.empty:
                continue
            dominated = (
                sample[indicator_column].astype(bool)
                if indicator_column is not None
                else sample[advantage_column].gt(0)
            )
            inference = mean_clustered(
                dominated.astype(float), pd.to_datetime(sample["date"])
            )
            savings = (
                sample[advantage_column].where(dominated, 0.0).clip(lower=0)
                * sample["usd"]
                / 10_000
            )
            dominated_savings = savings.loc[dominated]
            top_one_percent_count = max(1, (len(dominated_savings) + 99) // 100)
            aggregate_savings = float(savings.sum())
            rows.append(
                {
                    "scope": "pooled_level",
                    "weighting": "route",
                    "value_support": support,
                    "economic_object": economic_object,
                    "routes": len(sample),
                    "dates": pd.to_datetime(sample["date"]).nunique(),
                    "dominated_routes": int(dominated.sum()),
                    "pct_dominated": 100 * inference.estimate,
                    "date_clustered_standard_error_pp": 100 * inference.standard_error,
                    "confidence_interval_95_lower_pct": 100
                    * max(inference.confidence_interval_lower, 0.0),
                    "confidence_interval_95_upper_pct": 100
                    * min(inference.confidence_interval_upper, 1.0),
                    "median_advantage_bps_if_dominated": float(
                        sample.loc[dominated, advantage_column].median()
                    ),
                    "median_savings_usd_if_dominated": float(
                        dominated_savings.median()
                    ),
                    "aggregate_savings_usd_sampled_dates": aggregate_savings,
                    "top_1pct_savings_share_pct": (
                        100
                        * float(dominated_savings.nlargest(top_one_percent_count).sum())
                        / aggregate_savings
                        if aggregate_savings
                        else None
                    ),
                    "pct_dominated_routes_below_1000_usd_notional": (
                        100 * float(sample.loc[dominated, "usd"].lt(1_000).mean())
                        if dominated.any()
                        else None
                    ),
                }
            )
            daily_incidence = (
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(sample["date"]),
                        "dominated": dominated.to_numpy(dtype=float),
                    }
                )
                .groupby("date", sort=True)["dominated"]
                .mean()
            )
            rows.append(
                {
                    "scope": "pooled_level",
                    "weighting": "equal_date",
                    "value_support": support,
                    "economic_object": economic_object,
                    "routes": len(sample),
                    "dates": len(daily_incidence),
                    "dominated_routes": int(dominated.sum()),
                    "pct_dominated": 100 * float(daily_incidence.mean()),
                    "daily_incidence_p25_pct": 100 * float(daily_incidence.quantile(0.25)),
                    "daily_incidence_p50_pct": 100 * float(daily_incidence.quantile(0.50)),
                    "daily_incidence_p75_pct": 100 * float(daily_incidence.quantile(0.75)),
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", nargs="+", help="explicit YYYYMMDD days")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be positive")

    available = sorted(
        p.name.removeprefix("uniswap_v2_swaps_").removesuffix(".jsonl.gz")
        for p in (RAW / "uniswap_v2").glob("uniswap_v2_swaps_*.jsonl.gz")
    )
    days = counterfactual_days(available, explicit=args.days, limit=args.limit)
    print(f"quoting counterfactuals on {len(days)} day(s)", flush=True)

    parts = []
    for d in days:
        r = one_day(d)
        if r is not None and len(r):
            parts.append(r)
            print(f"  {d}: {len(r):,} comparable two-leg routes", flush=True)
        else:
            print(f"  {d}: none", flush=True)
    if not parts:
        print("no comparable routes")
        return 1

    df = pd.concat(parts, ignore_index=True)
    df = df[df.direct_output_improvement_bps.notna()]
    df = add_topology_gas_adjustment(df)
    df["dominated_gross"] = df["direct_output_improvement_bps"].gt(0)
    df["valuation_coherent_2x"] = df[
        "realised_to_input_value_ratio"
    ].between(0.5, 2.0)
    df["valuation_coherent_20pct"] = df[
        "realised_to_input_value_ratio"
    ].between(0.8, 1.2)
    df["dominated_valuation_coherent_2x"] = df["dominated_gross"].where(
        df["valuation_coherent_2x"]
    )
    df["dominated_valuation_coherent_20pct"] = df["dominated_gross"].where(
        df["valuation_coherent_20pct"]
    )
    df["state_support"] = classify_state_support(df)
    write_panel(
        df,
        OUT_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=[*[RAW / venue for venue in VENUES], UNIFIED, GAS_PANEL, ROUTE_GAS_PANEL],
        notes="V2-family exact-size direct counterfactual at strict pre-transaction block-log state; historical gas prices and receipt-calibrated route gas with explicit fallback support",
    )

    print(f"\ncomparable intermediated routes with a direct alternative: {len(df):,}")
    print(f"date range: {df.date.min().date()} to {df.date.max().date()}")
    dom = df[df.direct_output_improvement_bps > 0]
    print(f"\nroutes where DIRECT would have returned more (gross of gas): "
          f"{len(dom):,} ({100*len(dom)/len(df):.1f}%)")
    print(f"  median advantage among those: "
          f"{dom.gross_direct_advantage_bps.median():.1f} bps of notional")
    print(f"  median advantage over all routes: "
          f"{df.gross_direct_advantage_bps.median():.1f} bps of notional")
    print(
        "  median price-free output improvement over all routes: "
        f"{df.direct_output_improvement_bps.median():.1f} bps of realised output"
    )
    for label, column in (
        ("within 2x", "valuation_coherent_2x"),
        ("within 20%", "valuation_coherent_20pct"),
    ):
        supported = df[df[column]]
        print(
            f"  valuation-coherence sensitivity ({label}): {len(supported):,} routes, "
            f"{100 * supported.dominated_gross.mean():.1f}% dominated"
        )
    outside = dom[dom["best_direct_outside_realised_venue_set"]]
    outside_share = 100 * len(outside) / len(dom) if len(dom) else float("nan")
    print(
        "  dominated via a best direct pool outside the realised venue set: "
        f"{len(outside):,} ({outside_share:.1f}% of dominated routes)"
    )
    gas_supported = df[df["all_in_direct_advantage_bps"].notna()]
    if len(gas_supported):
        all_in_dominated = gas_supported["all_in_direct_advantage_bps"].gt(0)
        lower = gas_supported["all_in_direct_advantage_bps_iqr_lower"].gt(0)
        upper = gas_supported["all_in_direct_advantage_bps_iqr_upper"].gt(0)
        print(
            "  receipt-calibrated direct dominance on historical-gas support: "
            f"{100*all_in_dominated.mean():.1f}% "
            f"(IQR sensitivity {100*lower.mean():.1f}% to {100*upper.mean():.1f}%; "
            f"{len(gas_supported):,} routes)"
        )
        for prefix in ("direct", "vehicle"):
            support = gas_supported[f"{prefix}_gas_support_level"].value_counts()
            print(
                f"    {prefix} gas support: "
                + ", ".join(f"{level}={count:,}" for level, count in support.items())
            )
    print("\nby intermediary type:")
    for t, s in df.groupby("mid_type"):
        d = s[s.direct_output_improvement_bps > 0]
        print(f"  {t:<14} routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median advantage "
              f"{d.gross_direct_advantage_bps.median() if len(d) else float('nan'):8.1f} bps")
    print("\nby size bin:")
    df["bin"] = pd.cut(
        df.usd,
        [100, 1e3, 1e4, 1e5, 1e12],
        labels=["100-1k", "1k-10k", "10k-100k", ">100k"],
        include_lowest=True,
    )
    for b, s in df.groupby("bin", observed=True):
        d = s[s.direct_output_improvement_bps > 0]
        print(f"  {b:>9}  routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median advantage "
              f"{d.gross_direct_advantage_bps.median() if len(d) else float('nan'):8.1f} bps")
    annual = df.groupby(
        [
            pd.Grouper(key="date", freq="YS"),
            "mid_type",
            "best_direct_outside_realised_venue_set",
        ]
    ).agg(
        routes=("gross_direct_advantage_bps", "size"),
        pct_dominated_gross=(
            "direct_output_improvement_bps", lambda x: 100 * (x > 0).mean()
        ),
        median_gross_direct_advantage_bps=(
            "gross_direct_advantage_bps", "median"
        ),
        median_direct_output_improvement_bps=(
            "direct_output_improvement_bps", "median"
        ),
        valuation_coherent_2x_routes=("valuation_coherent_2x", "sum"),
        pct_dominated_valuation_coherent_2x=(
            "dominated_valuation_coherent_2x",
            lambda x: 100 * x.dropna().mean(),
        ),
        valuation_coherent_20pct_routes=("valuation_coherent_20pct", "sum"),
        pct_dominated_valuation_coherent_20pct=(
            "dominated_valuation_coherent_20pct",
            lambda x: 100 * x.dropna().mean(),
        ),
        gas_supported_routes=("all_in_direct_advantage_bps", "count"),
        pct_dominated_topology_gas_adjusted=(
            "all_in_direct_advantage_bps", lambda x: 100 * (x.dropna() > 0).mean()
        ),
        pct_dominated_gas_iqr_lower=(
            "all_in_direct_advantage_bps_iqr_lower",
            lambda x: 100 * (x.dropna() > 0).mean(),
        ),
        pct_dominated_gas_iqr_upper=(
            "all_in_direct_advantage_bps_iqr_upper",
            lambda x: 100 * (x.dropna() > 0).mean(),
        ),
    ).reset_index()
    annual.insert(0, "scope", "annual_type_reach")
    summary = pd.concat(
        [dominance_level_summary(df), annual],
        ignore_index=True,
        sort=False,
    )
    write_exhibit(
        summary,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="pooled and annual exact-size V2-family direct counterfactual; pooled rows retain route and equal-date weighting, date-clustered uncertainty, dollar magnitude, strict valuation support and matched-gas IQR sensitivity; annual rows split intermediary type and realised venue reach",
    )
    support = state_support_summary(df)
    write_exhibit(
        support,
        OUT_SUPPORT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="reserve-state support split; adjacent means all three prior observations are one hour back with no liquidity event, bridged advances a more distant observed state through all intervening raw events, and replayed includes at least one mint or burn",
    )
    print("\nby reserve-state support:")
    print(
        support.loc[
            support["scope"].eq("pooled"),
            [
                "state_support",
                "routes",
                "pct_dominated_gross",
                "pct_dominated_valuation_coherent_20pct",
                "pct_dominated_topology_gas_adjusted",
                "pct_dominated_gas_iqr_lower",
                "pct_dominated_gas_iqr_upper",
            ],
        ].round(2).to_string(index=False)
    )
    print(
        f"\nwrote {OUT_PARQUET.relative_to(REPO_ROOT)}, "
        f"{OUT_EXHIBIT.relative_to(REPO_ROOT)}, and "
        f"{OUT_SUPPORT.relative_to(REPO_ROOT)}"
    )
    print("\nBIAS DIRECTIONS: v2-family venue coverage understates the best direct "
          "alternative, and omitting gas favours the two-hop vehicle route. Both "
          "make gross direct-dominance incidence a LOWER bound. Receipt gas includes "
          "router overhead beyond AMM execution, so the labelled fallback hierarchy "
          "and IQR sensitivity remain part of the estimand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
