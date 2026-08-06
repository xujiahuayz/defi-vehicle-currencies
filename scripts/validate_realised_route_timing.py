#!/usr/bin/env python3
"""Validate hourly route gaps against actual V3 route transaction order.

This instrument samples executed exact two-leg routes whose two legs are both
Uniswap V3. For each route it recovers the raw pool and block-log identity of
each leg, takes both pools' last observed state strictly before the transaction's
first V3 swap log, and compares the realised output rate with the marginal rate
through those same pools. It repeats the comparison at the hour-end state.

The own-state shortfall compares the product of the two legs' realised effective
rates with the product of their pre-transaction marginal rates. It includes pool
fees and finite-size price impact because the realised rates do and the marginal
benchmark does not. A negative value is a contract failure unless some unobserved
state transition remains. The difference between own-state and hour-state
shortfalls measures the timing contamination in the hourly diagnostic.

This validates executed-route timing and amount orientation. It does not reprice
the direct or alternative-vehicle counterfactual at finite size.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.block_timing import PoolView, V3DayState, load_v3_day, oriented_human
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.tables import write_exhibit, write_panel

RAW = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
UNIFIED = DATA_DIR / "unified"
OUT = OUTPUT_DIR / "exhibits" / "realised_route_timing_validation.jsonl"
OUT_PANEL = DATA_DIR / "processed" / "realised_route_timing_validation.parquet"
CODE_SOURCES = [
    "scripts/validate_realised_route_timing.py",
    "src/ddvc/analysis/block_timing.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/prices.py",
]


def available_days() -> list[str]:
    raw_days = {
        path.name.removeprefix("uniswap_v3_swaps_").removesuffix(".jsonl.gz")
        for path in RAW.glob("uniswap_v3_swaps_*.jsonl.gz")
    }
    unified_days = {path.stem for path in UNIFIED.glob("*.parquet")}
    return sorted(raw_days & unified_days)


def selected_days(requested: list[str] | None, available: list[str]) -> list[str]:
    if requested:
        missing = sorted(set(requested) - set(available))
        if missing:
            raise ValueError("requested route-timing day unavailable: " + ", ".join(missing))
        return list(dict.fromkeys(requested))
    if not available:
        return []
    indices = sorted({len(available) // 4, len(available) // 2, 3 * len(available) // 4})
    return [available[index] for index in indices]


def route_timing_observation(
    route: pd.Series,
    legs: pd.DataFrame,
    state: V3DayState,
    views: dict[str, PoolView],
) -> dict[str, object] | None:
    """Compare one realised route with strict pre-transaction and hour states."""
    transaction_id = str(route["tx_hash"]).lower()
    ordered_legs = legs.sort_values("log_index", kind="stable")
    if len(ordered_legs) != 2:
        return None
    event_refs = []
    for leg in ordered_legs.itertuples(index=False):
        event = state.events.get((transaction_id, int(leg.log_index)))
        if event is None:
            return None
        event_refs.append(event)
    blocks = {event.block for event in event_refs}
    if len(blocks) != 1:
        return None
    block = next(iter(blocks))
    first_log = state.transaction_first_log.get(transaction_id)
    if first_log is None:
        return None
    absolute_hour = int(route["timestamp_utc"]) // 3600
    own_parts: list[float] = []
    hour_parts: list[float] = []
    pools: list[str] = []
    for leg, event in zip(ordered_legs.itertuples(index=False), event_refs, strict=True):
        pool_id = event.pool_id
        view = views.get(pool_id)
        tokens = state.tokens.get(pool_id)
        decimals = state.decimals.get(pool_id)
        if view is None or tokens is None or decimals is None:
            return None
        own_price = view.before(block, first_log)
        hour_price = view.at_hour(absolute_hour)
        if own_price is None or hour_price is None:
            return None
        own_oriented = oriented_human(
            own_price,
            tokens[0],
            tokens[1],
            decimals[0],
            decimals[1],
            str(leg.token_in).lower(),
            str(leg.token_out).lower(),
        )
        hour_oriented = oriented_human(
            hour_price,
            tokens[0],
            tokens[1],
            decimals[0],
            decimals[1],
            str(leg.token_in).lower(),
            str(leg.token_out).lower(),
        )
        if own_oriented is None or hour_oriented is None:
            return None
        own_parts.append(own_oriented)
        hour_parts.append(hour_oriented)
        pools.append(pool_id)
    leg_amounts = ordered_legs[["amount_in", "amount_out"]].astype(float)
    if not np.isfinite(leg_amounts.to_numpy()).all() or not leg_amounts.gt(0).all().all():
        return None
    actual_log_rate = float(
        np.log(leg_amounts["amount_out"] / leg_amounts["amount_in"]).sum()
    )
    amount_in = float(route["realised_amount_in"])
    amount_out = float(route["realised_amount_out"])
    endpoint_output_rate = amount_out / amount_in if amount_in > 0 and amount_out > 0 else math.nan
    intermediate_out = float(leg_amounts.iloc[0]["amount_out"])
    intermediate_in = float(leg_amounts.iloc[1]["amount_in"])
    intermediate_conservation_gap = abs(intermediate_out - intermediate_in) / max(
        intermediate_out, intermediate_in
    )
    own_log_rate = sum(own_parts)
    hour_log_rate = sum(hour_parts)
    return {
        "route_id": route["route_id"],
        "tx_hash": route["tx_hash"],
        "component_id": int(route["component_id"]),
        "timestamp_utc": int(route["timestamp_utc"]),
        "block": block,
        "first_log_index": first_log,
        "src": route["src"],
        "tgt": route["tgt"],
        "vehicle": route["vehicle"],
        "hop1_pool": pools[0],
        "hop2_pool": pools[1],
        "actual_output_rate": math.exp(actual_log_rate),
        "endpoint_output_rate": endpoint_output_rate,
        "intermediate_conservation_gap": intermediate_conservation_gap,
        "own_marginal_output_rate": math.exp(own_log_rate),
        "hour_marginal_output_rate": math.exp(hour_log_rate),
        "own_state_shortfall": 1.0 - math.exp(actual_log_rate - own_log_rate),
        "hour_state_shortfall": 1.0 - math.exp(actual_log_rate - hour_log_rate),
        "marginal_state_shift_bps": 10_000.0 * (hour_log_rate - own_log_rate),
    }


def validate_day(day: str, max_routes: int) -> pd.DataFrame:
    raw_path = RAW / f"uniswap_v3_swaps_{day}.jsonl.gz"
    unified_path = UNIFIED / f"{day}.parquet"
    state = load_v3_day(raw_path)
    if not state.series:
        return pd.DataFrame()
    unified = pd.read_parquet(unified_path, columns=LINEAR_ROUTE_COLUMNS)
    routes = extract_linear_realised_routes(unified)
    routes = routes[
        routes["realised_hop1_source"].eq("uniswap_v3")
        & routes["realised_hop2_source"].eq("uniswap_v3")
    ].sort_values("route_id", kind="stable")
    if len(routes) > max_routes:
        indices = np.linspace(0, len(routes) - 1, max_routes, dtype=int)
        routes = routes.iloc[indices]
    eligible_keys = set(
        zip(routes["tx_hash"], routes["component_id"], strict=True)
    )
    legs = unified[
        unified["route_class"].eq("coherent")
        & unified["source"].eq("uniswap_v3")
    ].copy()
    legs = legs[
        [
            (tx_hash, component_id) in eligible_keys
            for tx_hash, component_id in zip(
                legs["tx_hash"], legs["component_id"], strict=True
            )
        ]
    ]
    grouped_legs = {
        key: group
        for key, group in legs.groupby(["tx_hash", "component_id"], sort=False)
    }
    views = {pool_id: PoolView(sequence) for pool_id, sequence in state.series.items()}
    rows = []
    for route in routes.to_dict("records"):
        route_series = pd.Series(route)
        key = (route["tx_hash"], route["component_id"])
        route_legs = grouped_legs.get(key)
        if route_legs is None:
            continue
        observation = route_timing_observation(route_series, route_legs, state, views)
        if observation is not None:
            observation["validation_day"] = day
            rows.append(observation)
    return pd.DataFrame(rows)


def summarise_validation(output: pd.DataFrame) -> pd.DataFrame:
    """Return one compact evidence row per day plus the pooled validation."""
    groups: list[tuple[str, pd.DataFrame]] = [("all", output)]
    groups.extend(
        (str(day), group)
        for day, group in output.groupby("validation_day", sort=True)
    )
    rows = []
    for scope, group in groups:
        shift = group["marginal_state_shift_bps"]
        conservation = group["intermediate_conservation_gap"]
        rows.append(
            {
                "validation_day": scope,
                "routes": int(len(group)),
                "negative_own_state": int(group["own_state_shortfall"].lt(0).sum()),
                "negative_own_state_share": float(group["own_state_shortfall"].lt(0).mean()),
                "own_state_shortfall_median": float(group["own_state_shortfall"].median()),
                "own_state_shortfall_p99": float(group["own_state_shortfall"].quantile(0.99)),
                "negative_hour_state_share": float(group["hour_state_shortfall"].lt(0).mean()),
                "hour_state_shortfall_median": float(group["hour_state_shortfall"].median()),
                "state_shift_median_bps": float(shift.median()),
                "state_shift_absolute_median_bps": float(shift.abs().median()),
                "state_shift_absolute_over_30bps_share": float(shift.abs().gt(30).mean()),
                "state_shift_absolute_over_100bps_share": float(shift.abs().gt(100).mean()),
                "intermediate_conservation_gap_median": float(conservation.median()),
                "intermediate_conservation_gap_p99": float(conservation.quantile(0.99)),
                "intermediate_conservation_gap_max": float(conservation.max()),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", action="append", help="repeat for strict multi-date validation")
    parser.add_argument("--max-routes", type=int, default=10_000)
    args = parser.parse_args()
    try:
        days = selected_days(args.day, available_days())
    except ValueError as error:
        print(f"error: {error}")
        return 1
    if not days:
        print("no common V3/raw unified days")
        return 1
    frames = []
    failed = []
    for day in days:
        frame = validate_day(day, max(1, args.max_routes))
        if frame.empty:
            failed.append(day)
            continue
        frames.append(frame)
        print(
            f"{day}: {len(frame):,} realised routes; "
            f"negative own-state shortfall {100 * frame.own_state_shortfall.lt(0).mean():.2f}%; "
            f"median hour shift {frame.marginal_state_shift_bps.median():+.2f} bps",
            flush=True,
        )
    if failed:
        print("no route-timing comparisons on requested day(s): " + ", ".join(failed))
        print("refusing partial multi-date validation")
        return 1
    output = pd.concat(frames, ignore_index=True)
    print(f"\n{len(output):,} realised V3 two-leg routes")
    print(
        f"  negative own-state shortfall : "
        f"{100 * output.own_state_shortfall.lt(0).mean():.2f}%"
    )
    print(f"  median own-state shortfall   : {100 * output.own_state_shortfall.median():.4f}%")
    print(f"  median hour-state shortfall  : {100 * output.hour_state_shortfall.median():.4f}%")
    print(f"  median absolute hour shift   : {output.marginal_state_shift_bps.abs().median():.2f} bps")
    inputs: list[Path] = []
    for day in days:
        inputs.extend(
            [
                RAW / f"uniswap_v3_swaps_{day}.jsonl.gz",
                UNIFIED / f"{day}.parquet",
            ]
        )
    write_panel(
        output,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="two-leg V3 realised effective rates; strict state before transaction first swap log",
    )
    summary = summarise_validation(output)
    write_exhibit(
        summary,
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes="pooled and per-day transaction-state timing validation",
    )
    print(
        f"wrote {OUT_PANEL.relative_to(DATA_DIR.parent)} and "
        f"{OUT.relative_to(OUTPUT_DIR.parent)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
