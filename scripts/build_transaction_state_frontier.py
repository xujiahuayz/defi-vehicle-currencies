#!/usr/bin/env python3
"""Build the strict pre-transaction V2/V3/V4 route frontier for node F.

The frontier scores routes whose two realised legs execute on the exact-state V2,
V3, or V4 adapters and searches all supported paths at the same pre-transaction
state. Pure V4 routes lack a block number in the raw source, so their opportunity
set remains V3/V4-only; that bound is explicit in the support funnel. Curve,
Balancer, and Fluid remain outside the exact-state perimeter.
"""

from __future__ import annotations

import argparse
import pickle
from collections import defaultdict
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.transaction_frontier import RealisedPath, score_frontier
from ddvc.asset_types import (
    IMPORTED,
    NATIVE,
    STABLE,
    STAKED_NATIVE,
    asset_type,
    canonical_token,
)
from ddvc.calendar import nearest_monthly_days
from ddvc.fetch.raw import block_value, transaction_id, timestamp_value
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.pricing.mixed_frontier import (
    MixedFrontierState,
    mixed_leg_quotes,
    quote_mixed_path,
)
from ddvc.pricing.path_frontier import PathQuote
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    load_tick_day_events,
    warm_tick_day,
)
from ddvc.pricing.v3pools import load_token_decimals
from ddvc.pricing.v2_replay import V2ReplayDay, V2_VENUES, load_v2_replay_day
from ddvc.provenance import cache_key
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.route_cost import MAX_PRICE_IMPACT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit, write_panel


RAW = DATA_DIR / "raw" / "thegraph"
UNIFIED = DATA_DIR / "unified"
OUT_PANEL = DATA_DIR / "processed" / "transaction_state_frontier.parquet"
OUT_SUMMARY = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_summary.jsonl"
OUT_SUPPORT = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_support.jsonl"
TICK_VENUES = ("uniswap_v3", "uniswap_v4")
EXACT_VENUES = (*V2_VENUES, *TICK_VENUES)
REPLAY_START = "20210504"
TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"
MIN_INPUT_USD = 100.0
VALIDATION_TOLERANCE = 0.01
CHECKPOINT_INTERVAL_DAYS = 180
CHECKPOINT_GLOB = "pre_" + "[0-9]" * 8 + ".pkl"
PILOT_DAYS = ("20220615", "20240615", "20250615", "20260615")
CODE_SOURCES = [
    "scripts/build_transaction_state_frontier.py",
    "src/ddvc/analysis/transaction_frontier.py",
    "src/ddvc/pricing/path_frontier.py",
    "src/ddvc/pricing/mixed_frontier.py",
    "src/ddvc/pricing/tick_frontier.py",
    "src/ddvc/pricing/tick_quote.py",
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/tick_state.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/pricing/v3quote.py",
    "src/ddvc/pricing/v2_frontier.py",
    "src/ddvc/pricing/v2_replay.py",
    "src/ddvc/cpquote.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/realised.py",
    "src/ddvc/prices.py",
    "src/ddvc/route_roles.py",
]
REPLAY_SOURCES = [
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/tick_state.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/fetch/raw.py",
]


def candidate_vehicles() -> tuple[str, ...]:
    addresses = set().union(NATIVE, STAKED_NATIVE, STABLE, IMPORTED)
    return tuple(
        sorted(
            {
                canonical
                for address in addresses
                if (canonical := canonical_token(address)) is not None
            }
        )
    )


def save_replay_checkpoint(path: Path, replay: TickReplayState) -> None:
    with atomic_output(path) as temporary:
        with temporary.open("wb") as handle:
            pickle.dump(replay, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_replay_checkpoint(path: Path) -> TickReplayState:
    with path.open("rb") as handle:
        replay = pickle.load(handle)
    if not isinstance(replay, TickReplayState):
        raise TypeError(f"invalid tick replay checkpoint: {path}")
    return replay


def checkpoint_day(path: Path) -> str:
    name = path.stem
    if not name.startswith("pre_") or len(name) != 12 or not name[4:].isdigit():
        raise ValueError(f"invalid replay checkpoint name: {path.name}")
    return name[4:]


def latest_replay_checkpoint(directory: Path, target_day: str) -> Path | None:
    candidates = [
        path
        for path in directory.glob(CHECKPOINT_GLOB)
        if checkpoint_day(path) <= target_day
    ]
    return max(candidates, key=checkpoint_day) if candidates else None


def available_days() -> list[str]:
    return sorted(path.stem for path in UNIFIED.glob("[0-9]" * 8 + ".parquet"))


def select_days(
    available: list[str],
    *,
    explicit: list[str] | None,
    monthly: bool,
) -> list[str]:
    if explicit:
        selected = list(dict.fromkeys(day.replace("-", "") for day in explicit))
    elif monthly:
        selected = nearest_monthly_days(available)
    else:
        selected = [day for day in PILOT_DAYS if day in set(available)]
    missing = sorted(set(selected) - set(available))
    if missing:
        raise ValueError("requested frontier day unavailable: " + ", ".join(missing))
    if not selected:
        raise ValueError("no transaction-state frontier days selected")
    return sorted(selected)


def _event_key(event: TickReplayEvent) -> tuple[str, str, int] | None:
    if event.kind != "swap":
        return None
    tx_hash = transaction_id(event.row)
    try:
        log_index = int(event.row.get("logIndex") or 0)
    except (TypeError, ValueError):
        return None
    if not tx_hash:
        return None
    return event.venue, str(tx_hash).lower(), log_index


def load_target_routes(
    day: str,
    events: list[TickReplayEvent],
    v2_replay: V2ReplayDay,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    path = UNIFIED / f"{day}.parquet"
    legs = pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
    all_routes = extract_linear_realised_routes(legs)
    exact_routes = all_routes[
        all_routes["realised_hop1_source"].isin(EXACT_VENUES)
        & all_routes["realised_hop2_source"].isin(EXACT_VENUES)
    ].copy()
    route_keys = {
        (str(tx_hash).lower(), int(component_id))
        for tx_hash, component_id in zip(
            exact_routes["tx_hash"], exact_routes["component_id"], strict=True
        )
    }
    route_legs = legs[
        legs["route_class"].eq("coherent") & legs["source"].isin(EXACT_VENUES)
    ].copy()
    route_legs = route_legs[
        [
            (str(tx_hash).lower(), int(component_id)) in route_keys
            for tx_hash, component_id in zip(
                route_legs["tx_hash"], route_legs["component_id"], strict=True
            )
        ]
    ]
    grouped_legs = {
        (str(key[0]).lower(), int(key[1])): group.sort_values(
            "log_index", kind="stable"
        )
        for key, group in route_legs.groupby(["tx_hash", "component_id"], sort=False)
    }
    raw_tick_events: dict[tuple[str, str, int], TickReplayEvent] = {}
    for event in events:
        key = _event_key(event)
        if key is None:
            continue
        prior = raw_tick_events.get(key)
        if prior is not None and prior.row != event.row:
            raise ValueError(f"conflicting raw tick swap identity: {key}")
        raw_tick_events[key] = event

    targets: list[dict[str, object]] = []
    mapped = 0
    above_minimum = 0
    block_order_unavailable = 0
    for route in exact_routes.to_dict("records"):
        tx_hash = str(route["tx_hash"]).lower()
        component_id = int(route["component_id"])
        selected_legs = grouped_legs.get((tx_hash, component_id))
        if selected_legs is None or len(selected_legs) != 2:
            continue
        matched_events: list[dict[str, object]] = []
        for leg in selected_legs.itertuples(index=False):
            try:
                log_index = int(leg.log_index)
            except (TypeError, ValueError):
                matched_events = []
                break
            venue = str(leg.source)
            if venue in V2_VENUES:
                event = v2_replay.swaps_by_identity.get((venue, tx_hash, log_index))
                if event is None:
                    matched_events = []
                    break
                matched_events.append(
                    {
                        "venue": venue,
                        "pool": event.pool,
                        "timestamp": event.timestamp,
                        "log_index": log_index,
                        "block": event.order[0],
                    }
                )
            else:
                event = raw_tick_events.get((venue, tx_hash, log_index))
                if event is None:
                    matched_events = []
                    break
                pool = str((event.row.get("pool") or {}).get("id") or "").lower()
                try:
                    timestamp = int(timestamp_value(event.row) or 0)
                    block = block_value(event.row)
                    block_number = int(block) if block is not None else None
                except (TypeError, ValueError):
                    matched_events = []
                    break
                if not pool or timestamp <= 0:
                    matched_events = []
                    break
                matched_events.append(
                    {
                        "venue": venue,
                        "pool": pool,
                        "timestamp": timestamp,
                        "log_index": log_index,
                        "block": block_number,
                    }
                )
        if len(matched_events) != 2:
            continue
        mapped += 1
        input_usd = float(route["input_usd"])
        if not np.isfinite(input_usd) or input_usd < MIN_INPUT_USD:
            continue
        above_minimum += 1
        pools = tuple(str(event["pool"]) for event in matched_events)
        venues = tuple(str(event["venue"]) for event in matched_events)
        target_order = min(
            (int(event["timestamp"]), int(event["log_index"]))
            for event in matched_events
        )
        blocks = {
            int(event["block"])
            for event in matched_events
            if event["block"] is not None
        }
        if len(blocks) > 1:
            raise ValueError(f"route legs disagree on block number: {route['route_id']}")
        v2_order = (
            (blocks.pop(), min(int(event["log_index"]) for event in matched_events))
            if blocks
            else None
        )
        if v2_order is None:
            block_order_unavailable += 1
        targets.append(
            {
                **route,
                "day": day,
                "tx_hash": tx_hash,
                "target_order": target_order,
                "v2_hour": int(target_order[0]) - int(target_order[0]) % 3600,
                "v2_order": v2_order,
                "realised_venues": venues,
                "realised_pools": pools,
                "vehicle_type": asset_type(str(route["vehicle"])),
            }
        )
    targets.sort(key=lambda row: (row["target_order"], row["route_id"]))
    tick_only = exact_routes[
        exact_routes["realised_hop1_source"].isin(TICK_VENUES)
        & exact_routes["realised_hop2_source"].isin(TICK_VENUES)
    ]
    v2_only = exact_routes[
        exact_routes["realised_hop1_source"].isin(V2_VENUES)
        & exact_routes["realised_hop2_source"].isin(V2_VENUES)
    ]
    support = {
        "day": day,
        "all_exact_two_leg_routes": int(len(all_routes)),
        "exact_venue_two_leg_routes": int(len(exact_routes)),
        "exact_venue_share": float(len(exact_routes) / len(all_routes)) if len(all_routes) else None,
        "tick_venue_exact_two_leg_routes": int(len(tick_only)),
        "v2_venue_exact_two_leg_routes": int(len(v2_only)),
        "mixed_family_exact_two_leg_routes": int(len(exact_routes) - len(tick_only) - len(v2_only)),
        "block_order_unavailable_routes": block_order_unavailable,
        "raw_tx_log_mapped_routes": mapped,
        "routes_at_least_100usd": above_minimum,
        "scored_routes": 0,
        "chosen_state_unavailable": 0,
        "chosen_output_mismatch": 0,
        "quarantined_tick_pools": 0,
        "clean_v2_pool_hours": int(len(v2_replay.pool_hour_events)),
    }
    return targets, support


def validation_error_diagnostics(errors_bps: list[float]) -> dict[str, object]:
    """Summarise every available chosen-route quote, including rejected tails."""
    absolute = pd.Series(errors_bps, dtype=float).abs()
    mismatch = absolute[absolute.gt(10_000 * VALIDATION_TOLERANCE)]

    def quantile(values: pd.Series, probability: float) -> float | None:
        return float(values.quantile(probability)) if not values.empty else None

    return {
        "quote_available": int(len(absolute)),
        "output_mismatch": int(len(mismatch)),
        "validation_abs_median_bps": quantile(absolute, 0.5),
        "validation_abs_p90_bps": quantile(absolute, 0.9),
        "validation_abs_p99_bps": quantile(absolute, 0.99),
        "validation_abs_max_bps": quantile(absolute, 1.0),
        "validation_within_tolerance_share": (
            float(absolute.le(10_000 * VALIDATION_TOLERANCE).mean())
            if not absolute.empty
            else None
        ),
        "mismatch_abs_min_bps": quantile(mismatch, 0.0),
        "mismatch_abs_median_bps": quantile(mismatch, 0.5),
        "mismatch_abs_p90_bps": quantile(mismatch, 0.9),
        "mismatch_abs_max_bps": quantile(mismatch, 1.0),
    }


def score_day(
    day: str,
    events: list[TickReplayEvent],
    replay: TickReplayState,
    v2_replay: V2ReplayDay,
    vehicles: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, object]]:
    targets, support = load_target_routes(day, events, v2_replay)
    by_order: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for target in targets:
        by_order[target["target_order"]].append(target)
    rows: list[dict[str, object]] = []
    validation_errors_bps: list[float] = []
    coherent_validation_errors_bps: list[float] = []
    cursor = 0
    for order in sorted(by_order):
        while cursor < len(events) and events[cursor].order < order:
            replay.apply(events[cursor])
            cursor += 1
        for target in by_order[order]:
            route = RealisedPath(
                token_in=str(target["src"]),
                token_out=str(target["tgt"]),
                vehicle=str(target["vehicle"]),
                amount_in=float(target["realised_amount_in"]),
                amount_out=float(target["realised_amount_out"]),
                venues=target["realised_venues"],
                pools=target["realised_pools"],
            )
            frontier_state = MixedFrontierState(
                tick_pool_index=replay.pool_index,
                tick_states_by_venue=replay.states_by_venue,
                tick_ticks_by_venue=replay.ticks_by_venue,
                tick_quote_indexes_by_venue=replay.quote_indexes_by_venue,
                v2_replay=v2_replay,
                v2_hour=int(target["v2_hour"]),
                v2_order=target["v2_order"],
            )

            def quote_chosen(chosen_route: RealisedPath) -> PathQuote | None:
                return quote_mixed_path(
                    chosen_route.token_in,
                    chosen_route.token_out,
                    chosen_route.vehicle,
                    chosen_route.amount_in,
                    venues=chosen_route.venues,
                    pools=chosen_route.pools,
                    state=frontier_state,
                    max_support=None,
                )

            quote_legs = partial(
                mixed_leg_quotes,
                state=frontier_state,
                allowed_venues=None,
                max_support=MAX_PRICE_IMPACT,
            )
            chosen = quote_chosen(route)
            if chosen is None:
                support["chosen_state_unavailable"] += 1
                continue
            validation_error = abs(chosen.amount_out - route.amount_out) / route.amount_out
            validation_errors_bps.append(
                10_000 * (chosen.amount_out - route.amount_out) / route.amount_out
            )
            if bool(target["within_20pct"]):
                coherent_validation_errors_bps.append(validation_errors_bps[-1])
            if validation_error > VALIDATION_TOLERANCE:
                support["chosen_output_mismatch"] += 1
                continue
            score = score_frontier(
                route,
                vehicles=vehicles,
                quote_legs=quote_legs,
                quote_chosen=quote_chosen,
                validation_tolerance=VALIDATION_TOLERANCE,
            )
            if score is None:
                raise AssertionError("validated chosen path was rejected during frontier scoring")
            realised_out = route.amount_out
            target_price = float(target["output_usd"]) / realised_out
            public_gain_usd = max(
                0.0,
                (float(score["public_path_out"]) - realised_out) * target_price,
            )
            rows.append(
                {
                    "date": pd.to_datetime(day, format="%Y%m%d"),
                    "day": day,
                    "route_id": target["route_id"],
                    "tx_hash": target["tx_hash"],
                    "component_id": int(target["component_id"]),
                    "timestamp_utc": int(target["timestamp_utc"]),
                    "first_log_index": int(order[1]),
                    "v2_block_order_available": target["v2_order"] is not None,
                    "src": route.token_in,
                    "tgt": route.token_out,
                    "vehicle": route.vehicle,
                    "vehicle_type": target["vehicle_type"],
                    "input_usd": float(target["input_usd"]),
                    "output_usd": float(target["output_usd"]),
                    "within_20pct": bool(target["within_20pct"]),
                    "cross_venue": bool(target["cross_venue"]),
                    "realised_amount_in": route.amount_in,
                    "realised_amount_out": route.amount_out,
                    "realised_venues": "|".join(route.venues),
                    "realised_pools": "|".join(route.pools),
                    "public_gain_usd": public_gain_usd,
                    **score,
                }
            )
        while cursor < len(events) and events[cursor].order == order:
            replay.apply(events[cursor])
            cursor += 1
    replay.apply_all(events[cursor:])
    support["scored_routes"] = len(rows)
    support["quarantined_tick_pools"] = sum(
        len(pools) for pools in replay.quarantined_pools.values()
    )
    diagnostics = validation_error_diagnostics(validation_errors_bps)
    support.update({f"chosen_{key}": value for key, value in diagnostics.items()})
    coherent_diagnostics = validation_error_diagnostics(coherent_validation_errors_bps)
    support.update(
        {
            f"within_20pct_chosen_{key}": value
            for key, value in coherent_diagnostics.items()
        }
    )
    return pd.DataFrame(rows), support


def _concentration(values: pd.Series) -> float | None:
    positive = values[np.isfinite(values) & values.gt(0)].sort_values(ascending=False)
    if positive.empty:
        return None
    count = max(1, int(np.ceil(0.01 * len(positive))))
    return float(positive.iloc[:count].sum() / positive.sum())


def summarise(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    groups: list[tuple[str, str, pd.DataFrame]] = []
    for label, frame in (("all", panel), ("within_20pct", panel[panel["within_20pct"]])):
        groups.append(("pooled", label, frame))
        groups.extend(
            (str(day), label, day_frame)
            for day, day_frame in frame.groupby("day", sort=True)
        )
    for day, sample, frame in groups:
        if frame.empty:
            continue
        regret = frame["public_path_regret_bps"].astype(float)
        direct = pd.to_numeric(frame["direct_omission_bps"], errors="coerce")
        gain = frame["public_gain_usd"].astype(float)
        rows.append(
            {
                "day": day,
                "sample": sample,
                "routes": int(len(frame)),
                "input_usd": float(frame["input_usd"].sum()),
                "chosen_validation_abs_median_bps": float(
                    frame["chosen_validation_error_bps"].abs().median()
                ),
                "within_reach_regret_positive_share": float(
                    frame["within_reach_search_regret_bps"].gt(0).mean()
                ),
                "public_reach_regret_positive_share": float(
                    frame["public_reach_same_vehicle_regret_bps"].gt(0).mean()
                ),
                "public_path_regret_positive_share": float(regret.gt(0).mean()),
                "public_path_regret_over_0p01bps_share": float(regret.gt(0.01).mean()),
                "public_path_regret_over_1bps_share": float(regret.gt(1.0).mean()),
                "public_path_regret_over_10bps_share": float(regret.gt(10).mean()),
                "public_path_regret_median_bps": float(regret.median()),
                "public_path_regret_p90_bps": float(regret.quantile(0.9)),
                "within_reach_increment_mean_bps": float(
                    frame["within_reach_search_regret_bps"].mean()
                ),
                "within_reach_regret_over_0p01bps_share": float(
                    frame["within_reach_search_regret_bps"].gt(0.01).mean()
                ),
                "within_reach_regret_over_1bps_share": float(
                    frame["within_reach_search_regret_bps"].gt(1.0).mean()
                ),
                "reach_increment_mean_bps": float(frame["reach_increment_bps"].mean()),
                "reach_increment_over_0p01bps_share": float(
                    frame["reach_increment_bps"].gt(0.01).mean()
                ),
                "reach_increment_over_1bps_share": float(
                    frame["reach_increment_bps"].gt(1.0).mean()
                ),
                "path_choice_increment_mean_bps": float(
                    frame["path_choice_increment_bps"].mean()
                ),
                "path_choice_increment_over_0p01bps_share": float(
                    frame["path_choice_increment_bps"].gt(0.01).mean()
                ),
                "path_choice_increment_over_1bps_share": float(
                    frame["path_choice_increment_bps"].gt(1.0).mean()
                ),
                "direct_available_share": float(direct.notna().mean()),
                "direct_omission_positive_share": float(direct.fillna(0).gt(0).mean()),
                "aggregate_public_gain_usd": float(gain.sum()),
                "median_public_gain_usd": float(gain.median()),
                "public_gain_top_1pct_share": _concentration(gain),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", action="append", help="repeat for explicit YYYYMMDD days")
    parser.add_argument("--monthly", action="store_true", help="use the fixed nearest-15th calendar")
    args = parser.parse_args()
    try:
        selected = select_days(available_days(), explicit=args.day, monthly=args.monthly)
    except ValueError as error:
        print(f"error: {error}")
        return 1
    vehicles = candidate_vehicles()
    selected_set = set(selected)
    frames: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    replay_generation = cache_key(
        REPLAY_SOURCES,
        inputs=[RAW / "uniswap_v3", RAW / "uniswap_v4", TOKEN_DECIMALS],
    )
    checkpoint_dir = (
        DATA_DIR
        / "empirical"
        / "_tick_replay_checkpoints"
        / f"engine_{replay_generation}"
    )
    resume_checkpoint = latest_replay_checkpoint(checkpoint_dir, selected[0])
    if resume_checkpoint is not None:
        replay = load_replay_checkpoint(resume_checkpoint)
        replay_start = checkpoint_day(resume_checkpoint)
        print(f"loaded replay checkpoint before {replay_start}", flush=True)
    else:
        replay = TickReplayState(token_decimals=load_token_decimals(TOKEN_DECIMALS))
        replay_start = min(REPLAY_START, selected[0])
    calendar = pd.date_range(
        pd.to_datetime(replay_start, format="%Y%m%d"),
        pd.to_datetime(max(selected), format="%Y%m%d"),
        freq="D",
    )
    for index, observed in enumerate(calendar, 1):
        day = observed.strftime("%Y%m%d")
        checkpoint = checkpoint_dir / f"pre_{day}.pkl"
        if day in selected_set or (index - 1) % CHECKPOINT_INTERVAL_DAYS == 0:
            if not checkpoint.exists():
                save_replay_checkpoint(checkpoint, replay)
                print(f"wrote replay checkpoint before {day}", flush=True)
        if day in selected_set:
            events = load_tick_day_events(RAW, day)
            v2_replay = load_v2_replay_day(RAW, day)
            frame, support = score_day(day, events, replay, v2_replay, vehicles)
            frames.append(frame)
            support_rows.append(support)
            print(
                f"{day}: {support['all_exact_two_leg_routes']:,} exact two-leg; "
                f"{support['exact_venue_two_leg_routes']:,} V2/V3/V4; "
                f"{support['scored_routes']:,} exact-state scored",
                flush=True,
            )
        else:
            warm_tick_day(RAW, day, replay)
        if index % 180 == 0:
            print(f"replayed through {day} ({index:,}/{len(calendar):,} days)", flush=True)
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if panel.empty:
        print("no transaction-state frontier routes survived validation")
        return 1
    support = pd.DataFrame(support_rows)
    summary = summarise(panel)
    inputs = [
        UNIFIED,
        *(RAW / venue for venue in EXACT_VENUES),
        TOKEN_DECIMALS,
    ]
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="strict pre-transaction V2/V3/V4 realised and public-path frontier",
    )
    write_exhibit(
        summary,
        OUT_SUMMARY,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes="route and dollar magnitudes for nested V2/V3/V4 exact-state frontiers",
    )
    write_exhibit(
        support,
        OUT_SUPPORT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="explicit V2/V3/V4 exact-state support funnel; V2 alternatives excluded when block order is unavailable",
    )
    pooled = summary[
        (summary["day"] == "pooled") & (summary["sample"] == "within_20pct")
    ].iloc[0]
    print(
        f"pooled coherent: {int(pooled.routes):,} routes; public regret >1 bp "
        f"{100 * pooled.public_path_regret_over_1bps_share:.2f}%, >10 bp "
        f"{100 * pooled.public_path_regret_over_10bps_share:.2f}%; "
        f"median {pooled.public_path_regret_median_bps:.2f} bps; "
        f"aggregate gain ${pooled.aggregate_public_gain_usd:,.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
