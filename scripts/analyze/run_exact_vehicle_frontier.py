#!/usr/bin/env python3
"""Measure whether vehicle choice survives an exact pre-transaction price test.

The bounded research calendar uses the fifteenth day of every month.  For each
coherent two-leg route executed on Uniswap V2, SushiSwap V2, or Uniswap V3, the
chosen path must reproduce realised output within one basis point.  The search
then holds source, destination, input amount, and pre-transaction state fixed
while widening the opportunity set in three nested steps: the same vehicle on
the observed venues, the same vehicle on every admitted venue, and every named
vehicle plus the direct route on every admitted venue.

The exercise is deliberately smaller than the retired daily route-cost grid.
It prices executed notionals at exact transaction state and answers the economic
question directly: how much realised vehicle use reflects venue reach, vehicle
choice, or the absence of a direct route?
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.transaction_frontier import (
    MAX_CHOSEN_REPRODUCTION_ERROR,
    RealisedPath,
    score_frontier,
)
from ddvc.asset_types import asset_type, canonical_token
from ddvc.datasets import route_partitions, validate_before_install
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.pricing.mixed_frontier import (
    MixedFrontierState,
    mixed_leg_quotes,
    quote_mixed_path,
)
from ddvc.pricing.path_frontier import PathQuote, best_vehicle_path
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    load_tick_day_events,
)
from ddvc.pricing.v2_replay import V2ReplayDay, V2_VENUES, load_v2_replay_day
from ddvc.realised import (
    LINEAR_ROUTE_COLUMNS,
    extract_linear_realised_routes,
)
from ddvc.route_cost import MAX_PRICE_IMPACT
from ddvc.source_records import transaction_id
from ddvc.tables import write_exhibit, write_panel


UNIFIED = DATA_DIR / "unified"
PANEL = DATA_DIR / "processed" / "exact_vehicle_frontier_monthly.parquet"
SUMMARY = OUTPUT_DIR / "exhibits" / "exact_vehicle_frontier_monthly.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "exact_vehicle_frontier_monthly_support.jsonl"
START = "20200615"
END = "20260615"
TICK_START = "20210504"
MIN_ECONOMIC_INPUT_USD = 100.0
MIN_ECONOMIC_GAIN_BPS = 1.0
MAX_STANDARD_QUOTE_GAIN_BPS = 10_000.0
EXACT_VENUES = (*V2_VENUES, "uniswap_v3")
VEHICLES = tuple(
    canonical_token(address)
    for address in (
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
        "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
        "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
    )
)
NATIVE_VEHICLES = VEHICLES[:1]
STABLE_VEHICLES = VEHICLES[1:4]
CODE_SOURCES = [
    "scripts/analyze/run_exact_vehicle_frontier.py",
    "src/ddvc/analysis/transaction_frontier.py",
    "src/ddvc/pricing/mixed_frontier.py",
    "src/ddvc/pricing/path_frontier.py",
    "src/ddvc/pricing/tick_frontier.py",
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/tick_quote.py",
    "src/ddvc/pricing/tick_state.py",
    "src/ddvc/pricing/v2_frontier.py",
    "src/ddvc/pricing/v2_replay.py",
    "src/ddvc/route_cost.py",
]


@dataclass(frozen=True)
class RouteTarget:
    day: str
    route_id: str
    order: tuple[int, int]
    timestamp: int
    route: RealisedPath
    input_usd: float
    output_usd: float
    within_20pct: bool


def monthly_days(start: str = START, end: str = END) -> list[str]:
    """Return every fifteenth-of-month date in the inclusive bounds."""

    lo, hi = pd.to_datetime(start, format="%Y%m%d"), pd.to_datetime(
        end, format="%Y%m%d"
    )
    dates = pd.date_range(lo.replace(day=1), hi.replace(day=1), freq="MS")
    return [
        date.replace(day=15).strftime("%Y%m%d")
        for date in dates
        if lo <= date.replace(day=15) <= hi
    ]


def _tick_identity(event: TickReplayEvent) -> tuple[str, str, int] | None:
    tx_hash = str(transaction_id(event.row) or "").lower()
    raw_index = event.row.get("logIndex")
    try:
        log_index = int(raw_index)
    except (TypeError, ValueError):
        return None
    return (event.venue, tx_hash, log_index) if tx_hash else None


def _resolved_leg(
    source: str,
    tx_hash: str,
    log_index: int,
    *,
    v2_replay: V2ReplayDay,
    tick_by_identity: dict[tuple[str, str, int], TickReplayEvent],
) -> tuple[str, tuple[int, int]] | None:
    key = (source, tx_hash.lower(), int(log_index))
    if source in V2_VENUES:
        event = v2_replay.swaps_by_identity.get(key)
        return (event.pool, event.order) if event is not None else None
    event = tick_by_identity.get(key)
    if event is None:
        return None
    pool = str((event.row.get("pool") or {}).get("id") or "").lower()
    return (pool, event.order) if pool else None


def route_targets(
    day: str,
    *,
    v2_replay: V2ReplayDay,
    tick_events: list[TickReplayEvent],
) -> tuple[list[RouteTarget], Counter]:
    """Resolve eligible unified two-leg routes to exact pool and chain identity."""

    path = UNIFIED / f"{day}.parquet"
    reasons: Counter = Counter()
    if not path.is_file():
        reasons["missing_unified_day"] += 1
        return [], reasons
    legs = pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
    routes = extract_linear_realised_routes(legs)
    reasons["linear_routes"] = len(routes)
    routes = routes[
        routes["realised_hop1_source"].isin(EXACT_VENUES)
        & routes["realised_hop2_source"].isin(EXACT_VENUES)
    ].copy()
    reasons["exact_venue_routes"] = len(routes)
    if routes.empty:
        return [], reasons

    keys = ["tx_hash", "component_id"]
    selected = legs.merge(routes[keys + ["route_id"]], on=keys, how="inner")
    selected = selected.sort_values(keys + ["log_index"], kind="stable")
    first = selected.drop_duplicates(keys, keep="first")[
        keys + ["source", "log_index"]
    ].rename(columns={"source": "source1", "log_index": "log_index1"})
    second = selected.drop_duplicates(keys, keep="last")[
        keys + ["source", "log_index"]
    ].rename(columns={"source": "source2", "log_index": "log_index2"})
    routes = routes.merge(first, on=keys, how="inner").merge(
        second, on=keys, how="inner"
    )
    tick_by_identity = {
        identity: event
        for event in tick_events
        if event.kind == "swap"
        and (identity := _tick_identity(event)) is not None
    }
    out: list[RouteTarget] = []
    for row in routes.itertuples(index=False):
        first_leg = _resolved_leg(
            str(row.source1),
            str(row.tx_hash),
            int(row.log_index1),
            v2_replay=v2_replay,
            tick_by_identity=tick_by_identity,
        )
        second_leg = _resolved_leg(
            str(row.source2),
            str(row.tx_hash),
            int(row.log_index2),
            v2_replay=v2_replay,
            tick_by_identity=tick_by_identity,
        )
        if first_leg is None or second_leg is None:
            reasons["unresolved_pool_identity"] += 1
            continue
        if first_leg[1] >= second_leg[1]:
            reasons["nonsequential_chain_order"] += 1
            continue
        try:
            realised = RealisedPath(
                token_in=str(row.src),
                token_out=str(row.tgt),
                vehicle=str(row.vehicle),
                amount_in=float(row.realised_amount_in),
                amount_out=float(row.realised_amount_out),
                venues=(str(row.source1), str(row.source2)),
                pools=(first_leg[0], second_leg[0]),
            )
            target = RouteTarget(
                day=day,
                route_id=str(row.route_id),
                order=first_leg[1],
                timestamp=int(row.timestamp_utc),
                route=realised,
                input_usd=float(row.input_usd),
                output_usd=float(row.output_usd),
                within_20pct=bool(row.within_20pct),
            )
        except (TypeError, ValueError):
            reasons["invalid_route_quantity"] += 1
            continue
        if min(
            realised.amount_in,
            realised.amount_out,
            target.input_usd,
            target.output_usd,
        ) <= 0:
            reasons["invalid_route_quantity"] += 1
            continue
        out.append(target)
    reasons["mapped_routes"] = len(out)
    return out, reasons


def vehicle_class(token: str | None) -> str:
    if token is None:
        return "direct"
    kind = asset_type(str(token))
    return "native" if kind == "staked_native" else str(kind or "other")


def best_family_path(
    token_in: str,
    token_out: str,
    vehicles: tuple[str, ...],
    amount_in: float,
    *,
    quote_legs,
) -> PathQuote | None:
    """Return the best feasible two-leg quote within one vehicle family."""

    best: PathQuote | None = None
    for vehicle in vehicles:
        candidate = best_vehicle_path(
            token_in,
            token_out,
            vehicle,
            amount_in,
            quote_legs=quote_legs,
        )
        if candidate is not None and (
            best is None or candidate.amount_out > best.amount_out
        ):
            best = candidate
    return best


def _path_fields(prefix: str, quote: PathQuote | None) -> dict[str, object]:
    return {
        f"{prefix}_public_out": quote.amount_out if quote is not None else None,
        f"{prefix}_public_vehicle": quote.vehicle if quote is not None else None,
        f"{prefix}_public_max_leg_price_impact": (
            max(quote.price_impacts) if quote is not None else None
        ),
        f"{prefix}_public_venues": (
            "|".join(quote.venues) if quote is not None else None
        ),
        f"{prefix}_public_pools": (
            "|".join(quote.pools) if quote is not None else None
        ),
    }


def score_target(
    target: RouteTarget,
    *,
    replay: TickReplayState,
    v2_replay: V2ReplayDay,
) -> dict[str, object] | None:
    state = MixedFrontierState(
        tick_pool_index=replay.pool_index,
        tick_states_by_venue=replay.states_by_venue,
        tick_ticks_by_venue=replay.ticks_by_venue,
        tick_quote_indexes_by_venue=replay.quote_indexes_by_venue,
        v2_replay=v2_replay,
        v2_hour=target.timestamp - target.timestamp % 3600,
        v2_order=target.order,
    )
    quote_legs = partial(
        mixed_leg_quotes,
        state=state,
        allowed_venues=None,
        max_support=MAX_PRICE_IMPACT,
    )

    def quote_chosen(route: RealisedPath):
        return quote_mixed_path(
            route.token_in,
            route.token_out,
            route.vehicle,
            route.amount_in,
            venues=route.venues,
            pools=route.pools,
            state=state,
            max_support=None,
        )

    scored = score_frontier(
        target.route,
        vehicles=tuple(value for value in VEHICLES if value is not None),
        quote_legs=quote_legs,
        quote_chosen=quote_chosen,
        validation_tolerance=MAX_CHOSEN_REPRODUCTION_ERROR,
    )
    if scored is None:
        return None
    native_quote = best_family_path(
        target.route.token_in,
        target.route.token_out,
        NATIVE_VEHICLES,
        target.route.amount_in,
        quote_legs=quote_legs,
    )
    stable_quote = best_family_path(
        target.route.token_in,
        target.route.token_out,
        STABLE_VEHICLES,
        target.route.amount_in,
        quote_legs=quote_legs,
    )
    contestable = native_quote is not None and stable_quote is not None
    stable_minus_native_bps = (
        10_000.0
        * (stable_quote.amount_out - native_quote.amount_out)
        / native_quote.amount_out
        if contestable and native_quote.amount_out > 0
        else None
    )
    public_vehicle = scored["public_path_vehicle"]
    gain_bps = float(scored["public_path_regret_bps"])
    return {
        "day": target.day,
        "year": int(target.day[:4]),
        "route_id": target.route_id,
        "tx_hash": target.route_id.split(":", 1)[0],
        "token_in": target.route.token_in,
        "token_out": target.route.token_out,
        "chosen_vehicle": target.route.vehicle,
        "chosen_vehicle_type": vehicle_class(target.route.vehicle),
        "public_vehicle": public_vehicle,
        "public_vehicle_type": vehicle_class(
            None if public_vehicle is None else str(public_vehicle)
        ),
        "input_usd": target.input_usd,
        "output_usd": target.output_usd,
        "within_20pct": target.within_20pct,
        "chosen_validation_error_bps": scored["chosen_validation_error_bps"],
        "chosen_max_price_impact": scored["chosen_max_price_impact"],
        "direct_available": scored["direct_public_out"] is not None,
        "direct_improvement_bps": scored["direct_omission_bps"],
        "within_reach_regret_bps": scored["within_reach_search_regret_bps"],
        "reach_increment_bps": scored["reach_increment_bps"],
        "vehicle_choice_increment_bps": scored["path_choice_increment_bps"],
        "public_path_regret_bps": gain_bps,
        "public_gain_usd": target.output_usd * gain_bps / 10_000.0,
        "public_path_venues": scored["public_path_venues"],
        "public_path_pools": scored["public_path_pools"],
        "vehicle_families_contestable": contestable,
        "stable_minus_native_bps": stable_minus_native_bps,
        **_path_fields("native", native_quote),
        **_path_fields("stable", stable_quote),
    }


def score_day(
    day: str,
    replay: TickReplayState,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Score one target date and advance the V3 replay through its close."""

    tick_events = (
        load_tick_day_events(None, day, venues=("uniswap_v3",))
        if day >= TICK_START
        else []
    )
    v2_replay = load_v2_replay_day(None, day)
    targets, reasons = route_targets(
        day, v2_replay=v2_replay, tick_events=tick_events
    )
    by_order: dict[tuple[int, int], list[RouteTarget]] = defaultdict(list)
    for target in targets:
        by_order[target.order].append(target)
    event_by_order = {event.order: event for event in tick_events}
    if len(event_by_order) != len(tick_events):
        raise ValueError(f"duplicated V3 chain order on {day}")
    rows: list[dict[str, object]] = []
    for order in sorted(set(by_order) | set(event_by_order)):
        for target in by_order.get(order, []):
            result = score_target(target, replay=replay, v2_replay=v2_replay)
            if result is None:
                reasons["chosen_quote_not_reproduced"] += 1
            else:
                rows.append(result)
        event = event_by_order.get(order)
        if event is not None:
            replay.apply(event)
    reasons["scored_routes"] = len(rows)
    return rows, {"day": day, **dict(reasons)}


def _clustered_mean(
    outcome: pd.Series,
    day: pd.Series,
    *,
    weights: pd.Series | None = None,
) -> tuple[float, float, float]:
    values = pd.to_numeric(outcome, errors="coerce")
    groups = day.astype(str)
    valid = values.notna()
    if weights is not None:
        numeric_weights = pd.to_numeric(weights, errors="coerce")
        valid &= numeric_weights.gt(0) & np.isfinite(numeric_weights)
    if valid.sum() < 2 or groups[valid].nunique() < 2:
        return float("nan"), float("nan"), float("nan")
    y = values[valid].to_numpy(dtype=float)
    group = groups[valid].to_numpy()
    weight = (
        np.ones(len(y), dtype=float)
        if weights is None
        else numeric_weights[valid].to_numpy(dtype=float)
    )
    coefficient = float(np.average(y, weights=weight))
    residual = y - coefficient
    cluster_scores = np.array(
        [float(np.sum(weight[group == label] * residual[group == label]))
         for label in np.unique(group)]
    )
    clusters = len(cluster_scores)
    variance = (
        clusters / (clusters - 1)
        * float(np.sum(cluster_scores**2))
        / float(np.sum(weight) ** 2)
    )
    standard_error = float(np.sqrt(max(0.0, variance)))
    statistic = coefficient / standard_error if standard_error > 0 else float("nan")
    p_value = float(2 * stats.t.sf(abs(statistic), clusters - 1))
    return coefficient, standard_error, p_value


def _holm(p_values: list[float]) -> list[float]:
    adjusted = np.full(len(p_values), np.nan, dtype=float)
    finite = np.flatnonzero(np.isfinite(p_values))
    if not len(finite):
        return adjusted.tolist()
    order = finite[np.argsort(np.asarray(p_values, dtype=float)[finite])]
    running = 0.0
    total = len(order)
    for rank, position in enumerate(order):
        running = max(running, (total - rank) * float(p_values[position]))
        adjusted[position] = min(1.0, running)
    return adjusted.tolist()


def summarize(panel: pd.DataFrame) -> pd.DataFrame:
    """Return compact economic summaries, transitions, and paired inference."""

    rows: list[dict[str, object]] = []

    def add_summary(scope: str, label: str, frame: pd.DataFrame) -> None:
        gain = pd.to_numeric(frame["public_path_regret_bps"], errors="coerce")
        direct = pd.to_numeric(frame["direct_improvement_bps"], errors="coerce")
        within = pd.to_numeric(
            frame["within_reach_regret_bps"], errors="coerce"
        )
        reach = pd.to_numeric(frame["reach_increment_bps"], errors="coerce")
        same_vehicle_public = within + reach
        effective_public = frame["public_vehicle_type"].where(
            gain.gt(MIN_ECONOMIC_GAIN_BPS), frame["chosen_vehicle_type"]
        )
        positive = gain[
            gain.gt(MIN_ECONOMIC_GAIN_BPS)
            & gain.le(MAX_STANDARD_QUOTE_GAIN_BPS)
        ]
        rows.append(
            {
                "record_type": "frontier_summary",
                "scope": scope,
                "label": label,
                "routes": len(frame),
                "dates": frame["day"].nunique(),
                "input_usd": frame["input_usd"].sum(),
                "minimum_input_usd": MIN_ECONOMIC_INPUT_USD,
                "gain_threshold_bps": MIN_ECONOMIC_GAIN_BPS,
                "max_price_impact": MAX_PRICE_IMPACT,
                "chosen_stable_share": frame["chosen_vehicle_type"].eq("stable").mean(),
                "public_stable_share": effective_public.eq("stable").mean(),
                "public_direct_share": effective_public.eq("direct").mean(),
                "gain_over_1bp_share": gain.gt(MIN_ECONOMIC_GAIN_BPS).mean(),
                "direct_improvement_over_1bp_share": direct.gt(
                    MIN_ECONOMIC_GAIN_BPS
                ).mean(),
                "within_reach_regret_over_1bp_share": within.gt(
                    MIN_ECONOMIC_GAIN_BPS
                ).mean(),
                "same_vehicle_public_regret_over_1bp_share": same_vehicle_public.gt(
                    MIN_ECONOMIC_GAIN_BPS
                ).mean(),
                "reach_increment_over_1bp_share": pd.to_numeric(
                    frame["reach_increment_bps"], errors="coerce"
                ).gt(MIN_ECONOMIC_GAIN_BPS).mean(),
                "vehicle_choice_increment_over_1bp_share": pd.to_numeric(
                    frame["vehicle_choice_increment_bps"], errors="coerce"
                ).gt(MIN_ECONOMIC_GAIN_BPS).mean(),
                "median_gain_bps_if_over_1bp": positive.median(),
                "p90_gain_bps": gain.quantile(0.9),
                "gain_over_100pct_routes": gain.gt(
                    MAX_STANDARD_QUOTE_GAIN_BPS
                ).sum(),
            }
        )

    add_summary("pooled", "all", panel)
    add_summary(
        "pooled",
        "at_least_100usd",
        panel[panel["input_usd"].ge(MIN_ECONOMIC_INPUT_USD)],
    )
    add_summary("pooled", "within_20pct", panel[panel["within_20pct"]])
    coherent = panel[
        panel["within_20pct"]
        & panel["input_usd"].ge(MIN_ECONOMIC_INPUT_USD)
    ]
    add_summary("pooled", "within_20pct_at_least_100usd", coherent)
    main = coherent[
        pd.to_numeric(
            coherent["chosen_max_price_impact"], errors="coerce"
        ).le(MAX_PRICE_IMPACT)
    ]
    add_summary("pooled", "common_support", main)
    standard_quote = main[
        pd.to_numeric(main["public_path_regret_bps"], errors="coerce").le(
            MAX_STANDARD_QUOTE_GAIN_BPS
        )
    ]
    add_summary("pooled", "common_support_standard_quote", standard_quote)
    high_notional = main[main["input_usd"].ge(10_000.0)]
    add_summary("pooled", "common_support_at_least_10000usd", high_notional)
    for kind, group in panel.groupby("chosen_vehicle_type", sort=True):
        add_summary("chosen_vehicle_type", str(kind), group)
    for year, group in panel.groupby("year", sort=True):
        add_summary("year", str(year), group)
    for year, group in main.groupby("year", sort=True):
        add_summary("year_common_support", str(year), group)

    for sample, frame in (("all", panel), ("main", main)):
        switched = frame[
            frame["public_path_regret_bps"].gt(MIN_ECONOMIC_GAIN_BPS)
        ]
        for (chosen, public), group in switched.groupby(
            ["chosen_vehicle_type", "public_vehicle_type"], sort=True
        ):
            rows.append(
                {
                    "record_type": "vehicle_transition",
                    "scope": sample,
                    "label": f"{chosen}_to_{public}",
                    "routes": len(group),
                    "dates": group["day"].nunique(),
                    "route_share": len(group) / len(frame),
                    "median_gain_bps": group["public_path_regret_bps"].median(),
                }
            )

    inference: list[dict[str, object]] = []
    inference_samples = (
        ("all", panel),
        ("coherent_100usd", coherent),
        ("common_support", main),
        ("common_support_standard_quote", standard_quote),
        ("common_support_at_least_10000usd", high_notional),
    )
    for sample, frame in inference_samples:
        gain = pd.to_numeric(frame["public_path_regret_bps"], errors="coerce")
        effective_public = frame["public_vehicle_type"].where(
            gain.gt(MIN_ECONOMIC_GAIN_BPS), frame["chosen_vehicle_type"]
        )
        difference = (
            effective_public.eq("stable").astype(float)
            - frame["chosen_vehicle_type"].eq("stable").astype(float)
        )
        for weighting, weights in (
            ("route", None),
            ("input_value", frame["input_usd"]),
        ):
            coefficient, standard_error, p_value = _clustered_mean(
                difference, frame["day"], weights=weights
            )
            inference.append(
                {
                    "record_type": "stable_share_inference",
                    "scope": sample,
                    "label": weighting,
                    "routes": len(frame),
                    "dates": frame["day"].nunique(),
                    "change_pp": 100 * coefficient,
                    "standard_error_pp": 100 * standard_error,
                    "p_value": p_value,
                }
            )
    adjusted = _holm([row["p_value"] for row in inference])
    for row, p_holm in zip(inference, adjusted, strict=True):
        row["p_value_holm"] = float(p_holm)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_support(support: pd.DataFrame) -> pd.DataFrame:
    """Aggregate exact-venue reach and chosen-path reproduction by period."""

    frame = support.copy()
    frame["year"] = frame["day"].astype(str).str[:4]
    rows: list[dict[str, object]] = []
    groups = [("pooled", frame), *frame.groupby("year", sort=True)]
    for label, group in groups:
        linear = int(group["linear_routes"].sum())
        exact = int(group["exact_venue_routes"].sum())
        mapped = int(group["mapped_routes"].sum())
        scored = int(group["scored_routes"].sum())
        rows.append(
            {
                "record_type": "frontier_support",
                "scope": "period",
                "label": str(label),
                "dates": group["day"].nunique(),
                "linear_routes": linear,
                "exact_venue_routes": exact,
                "mapped_routes": mapped,
                "scored_routes": scored,
                "exact_venue_share": exact / linear if linear else float("nan"),
                "mapping_share": mapped / exact if exact else float("nan"),
                "chosen_reproduction_share": scored / mapped if mapped else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def run(selected: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    replay = TickReplayState()
    target_set = set(selected)
    first, last = min(selected), max(selected)
    replay_start = min(first, TICK_START)
    all_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    calendar = pd.date_range(
        pd.to_datetime(replay_start, format="%Y%m%d"),
        pd.to_datetime(last, format="%Y%m%d"),
        freq="D",
    )
    for index, observed in enumerate(calendar, 1):
        day = observed.strftime("%Y%m%d")
        if day < TICK_START:
            if day in target_set:
                rows, support = score_day(day, replay)
                all_rows.extend(rows)
                support_rows.append(support)
                print(
                    f"{day}: mapped={support.get('mapped_routes', 0):,} "
                    f"scored={support.get('scored_routes', 0):,}",
                    flush=True,
                )
            continue
        if day in target_set:
            rows, support = score_day(day, replay)
            all_rows.extend(rows)
            support_rows.append(support)
            print(
                f"{day}: mapped={support.get('mapped_routes', 0):,} "
                f"scored={support.get('scored_routes', 0):,}",
                flush=True,
            )
        else:
            replay.apply_all(
                load_tick_day_events(None, day, venues=("uniswap_v3",))
            )
        if index % 180 == 0:
            print(f"replayed through {day}", flush=True)
    return pd.DataFrame(all_rows), pd.DataFrame(support_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument(
        "--pilot-day",
        help="score one date and print only; canonical outputs are unchanged",
    )
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="rebuild summaries from the existing canonical panel and support rows",
    )
    args = parser.parse_args()
    if args.summarize_only:
        if not PANEL.is_file() or not SUPPORT.is_file():
            parser.error("--summarize-only requires the canonical panel and support rows")
        panel = pd.read_parquet(PANEL)
        support = pd.read_json(SUPPORT, lines=True)
        summary = pd.concat(
            [summarize(panel), summarize_support(support)],
            ignore_index=True,
            sort=False,
        )
        print(summary.to_string(index=False), flush=True)
        write_exhibit(
            summary,
            SUMMARY,
            code_sources=CODE_SOURCES,
            inputs=[PANEL, SUPPORT],
        )
        return 0
    selected = (
        [args.pilot_day.replace("-", "")]
        if args.pilot_day
        else monthly_days(args.start.replace("-", ""), args.end.replace("-", ""))
    )
    route_release = route_partitions(LINEAR_ROUTE_COLUMNS, nonempty=False)
    panel, support = run(selected)
    if panel.empty:
        print("no routes cleared exact chosen-path reproduction", flush=True)
        return 1
    summary = pd.concat(
        [summarize(panel), summarize_support(support)],
        ignore_index=True,
        sort=False,
    )
    print(summary.to_string(index=False), flush=True)
    print(support.to_string(index=False), flush=True)
    if args.pilot_day:
        return 0
    write_panel(
        panel.sort_values(["day", "route_id"], kind="stable").reset_index(drop=True),
        PANEL,
        code_sources=CODE_SOURCES,
        preinstall_validator=validate_before_install(route_release),
    )
    write_exhibit(support, SUPPORT, code_sources=CODE_SOURCES, inputs=[PANEL])
    write_exhibit(
        summary,
        SUMMARY,
        code_sources=CODE_SOURCES,
        inputs=[PANEL, SUPPORT],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
