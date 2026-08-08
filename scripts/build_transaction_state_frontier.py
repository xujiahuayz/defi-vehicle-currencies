#!/usr/bin/env python3
"""Build and validate the strict pre-transaction V2/V3/V4 route frontier.

The frontier scores routes whose two realised legs execute on the exact-state V2,
V3, or V4 adapters and searches all supported paths at the same pre-transaction
state. Every admitted route and replay event requires block-log order. Curve,
Balancer, and Fluid remain outside the exact-state perimeter.

The 77-date audit calendar validates construction and chosen-route reproduction.
It is never an estimation sample. Only after that gate passes does
``--daily-calendar`` publish the separate full-daily analysis input used for exact
1-, 7-, 30-, and 120-calendar-day outcome links.
"""

from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.analysis.transaction_frontier import (
    MIN_CHOSEN_REPRODUCTION,
    RealisedPath,
    chosen_reproduction_share,
    chosen_output_error,
    positive_finite_amount,
    score_frontier_from_quote,
)
from ddvc.asset_types import (
    IMPORTED,
    NATIVE,
    STABLE,
    STAKED_NATIVE,
    asset_type,
    canonical_token,
)
from ddvc.calendar import nearest_day_per_month
from ddvc.data_release import (
    V4_STATIC_QUARANTINE_PANEL,
    load_v4_static_quarantine,
    require_node_d_release,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.panel_assembly import assemble_parquet_shards
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
from ddvc.provenance import cache_key, require_current_artifacts, stamp
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days
from ddvc.route_cost import MAX_PRICE_IMPACT
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.state_data import STATE_ROOT
from ddvc.source_records import block_value, transaction_id, timestamp_value
from ddvc.tables import write_exhibit, write_panel


MARKET_STATE = STATE_ROOT
UNIFIED = DATA_DIR / "unified"
AUDIT_PANEL = DATA_DIR / "processed" / "transaction_state_frontier_audit.parquet"
AUDIT_REJECTIONS = DATA_DIR / "processed" / "transaction_state_frontier_audit_rejections.parquet"
AUDIT_SUMMARY = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_audit_summary.jsonl"
AUDIT_SUPPORT = OUTPUT_DIR / "exhibits" / "transaction_state_frontier_audit_support.jsonl"
DAILY_PANEL = DATA_DIR / "processed" / "transaction_state_frontier_daily.parquet"
DAILY_REJECTIONS = DATA_DIR / "processed" / "transaction_state_frontier_daily_rejections.parquet"
DAILY_SUPPORT = DATA_DIR / "processed" / "transaction_state_frontier_daily_support.parquet"
LOCK = DATA_DIR / "processed" / ".transaction_state_frontier.lock"
TICK_VENUES = ("uniswap_v3", "uniswap_v4")
EXACT_VENUES = (*V2_VENUES, *TICK_VENUES)
REPLAY_START = "20210504"
TOKEN_DECIMALS = DATA_DIR / "processed" / "v2_token_decimals.parquet"
MIN_INPUT_USD = 100.0
VALIDATION_TOLERANCE = 0.01
INTERMEDIATE_FLOW_TOLERANCE_BPS = 0.01
CHECKPOINT_INTERVAL_DAYS = 180
CHECKPOINT_GLOB = "pre_" + "[0-9]" * 8 + ".pkl"
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
    "src/ddvc/state_data.py",
    "src/ddvc/cpquote.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/source_records.py",
    "src/ddvc/realised.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/release_calendar.py",
    "src/ddvc/prices.py",
    "src/ddvc/route_roles.py",
]
OUTPUT_CODE_SOURCES = [*CODE_SOURCES, "src/ddvc/panel_assembly.py"]
REPLAY_SOURCES = [
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/tick_state.py",
    "src/ddvc/pricing/v3pools.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/source_records.py",
    "src/ddvc/state_data.py",
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


def _cached_day_contract(
    directory: Path, day: str
) -> tuple[Path, Path, dict[str, object]] | None:
    """Validate the marker and shard row counts installed by one cached day."""
    panel_path = directory / f"{day}.parquet"
    rejection_path = directory / f"{day}.rejections.parquet"
    support_path = directory / f"{day}.support.json"
    if not support_path.exists():
        return None
    support = json.loads(support_path.read_text(encoding="utf-8"))
    if support.get("day") != day:
        raise ValueError(f"frontier day-cache marker disagrees with filename: {support_path}")
    expected = int(support.get("scored_routes", -1))
    rejected = int(support.get("rejected_routes", -1))
    if expected < 0 or rejected < 0:
        raise ValueError(f"frontier day-cache marker lacks row contracts: {support_path}")

    def require_shard(path: Path, rows: int, label: str) -> None:
        if rows == 0:
            if path.exists():
                raise ValueError(f"zero-row {label} cache should not exist: {path}")
            return
        if not path.exists():
            raise ValueError(f"frontier day-cache marker lacks {label}: {path}")
        observed = pq.ParquetFile(path).metadata.num_rows
        if observed != rows:
            raise ValueError(
                f"frontier {label} row mismatch for {day}: {observed:,} != {rows:,}"
            )
    require_shard(panel_path, expected, "panel")
    require_shard(rejection_path, rejected, "rejection panel")
    return panel_path, rejection_path, support


def load_cached_day(
    directory: Path,
    day: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]] | None:
    """Load a complete day result; the support marker is installed last."""
    contract = _cached_day_contract(directory, day)
    if contract is None:
        return None
    panel_path, rejection_path, support = contract
    panel = pd.read_parquet(panel_path) if panel_path.exists() else pd.DataFrame()
    rejections = (
        pd.read_parquet(rejection_path) if rejection_path.exists() else pd.DataFrame()
    )
    return panel, rejections, support


def load_cached_day_support(directory: Path, day: str) -> dict[str, object] | None:
    """Validate a complete cached day without loading either route-level shard."""
    contract = _cached_day_contract(directory, day)
    if contract is None:
        return None
    return contract[2]


def write_cached_day(
    directory: Path,
    day: str,
    panel: pd.DataFrame,
    rejections: pd.DataFrame,
    support: dict[str, object],
) -> None:
    """Atomically cache one scored audit day, installing its marker last."""
    if str(support.get("day")) != day:
        raise ValueError("frontier support day disagrees with cache key")
    if int(support.get("scored_routes", -1)) != len(panel):
        raise ValueError("frontier support count disagrees with cached panel")
    if int(support.get("rejected_routes", -1)) != len(rejections):
        raise ValueError("frontier support count disagrees with cached rejections")
    directory.mkdir(parents=True, exist_ok=True)
    for frame, path in (
        (panel, directory / f"{day}.parquet"),
        (rejections, directory / f"{day}.rejections.parquet"),
    ):
        if frame.empty:
            path.unlink(missing_ok=True)
            continue
        with atomic_output(path) as temporary:
            frame.to_parquet(temporary, index=False)
    serialisable = {
        key: value.item() if isinstance(value, np.generic) else value
        for key, value in support.items()
    }
    with atomic_output(directory / f"{day}.support.json") as temporary:
        temporary.write_text(
            json.dumps(serialisable, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def latest_replay_checkpoint(directory: Path, target_day: str) -> Path | None:
    candidates = [
        path
        for path in directory.glob(CHECKPOINT_GLOB)
        if checkpoint_day(path) <= target_day
    ]
    return max(candidates, key=checkpoint_day) if candidates else None


def replay_checkpoint_due(
    *, day: str, index: int, selected_days: set[str], daily_mode: bool
) -> bool:
    """Keep audit selections resumable without checkpointing every daily target."""
    return (not daily_mode and day in selected_days) or (
        (index - 1) % CHECKPOINT_INTERVAL_DAYS == 0
    )


def available_days(*, nonempty: bool = False) -> list[str]:
    return released_route_days(UNIFIED_QUALITY_PANEL, nonempty=nonempty)


def select_days(
    available: list[str],
    *,
    explicit: list[str] | None,
    audit_calendar: bool,
    daily_calendar: bool = False,
) -> list[str]:
    if explicit:
        selected = list(dict.fromkeys(day.replace("-", "") for day in explicit))
    elif audit_calendar:
        selected = nearest_day_per_month(available)
    elif daily_calendar:
        selected = available
    else:
        raise ValueError("select explicit, audit, or full daily frontier dates")
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


def strict_route_order(
    matched_events: list[dict[str, object]],
) -> tuple[int, int] | None:
    """Return one transaction's exact block-log order or reject incomplete order."""
    blocks = [event.get("block") for event in matched_events]
    if any(block is None for block in blocks):
        return None
    unique_blocks = {int(block) for block in blocks if block is not None}
    if len(unique_blocks) != 1:
        raise ValueError("route legs disagree on block number")
    return unique_blocks.pop(), min(int(event["log_index"]) for event in matched_events)


def rejection_record(
    day: str,
    route: dict[str, object],
    reason: str,
    *,
    reason_detail: str | None = None,
    causal_order: tuple[int, int] | None = None,
    venues: tuple[str, ...] | None = None,
    pools: tuple[str, ...] | None = None,
    chosen_quote_out: float | None = None,
    signed_validation_error_bps: float | None = None,
) -> dict[str, object]:
    """Preserve the economic and causal identity of every excluded exact route."""
    realised_venues = venues or tuple(
        str(route.get(column) or "")
        for column in ("realised_hop1_source", "realised_hop2_source")
    )
    realised_pools = pools or ()
    return {
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "day": day,
        "route_id": str(route.get("route_id") or ""),
        "tx_hash": str(route.get("tx_hash") or "").lower(),
        "component_id": int(route.get("component_id") or 0),
        "timestamp_utc": int(route.get("timestamp_utc") or 0),
        "block_number": causal_order[0] if causal_order is not None else None,
        "first_log_index": causal_order[1] if causal_order is not None else None,
        "src": str(route.get("src") or ""),
        "tgt": str(route.get("tgt") or ""),
        "vehicle": str(route.get("vehicle") or ""),
        "vehicle_type": asset_type(str(route.get("vehicle") or "")),
        "input_usd": float(route.get("input_usd") or 0.0),
        "output_usd": float(route.get("output_usd") or 0.0),
        "within_20pct": bool(route.get("within_20pct")),
        "cross_venue": bool(route.get("cross_venue")),
        "realised_amount_in": float(route.get("realised_amount_in") or 0.0),
        "realised_amount_out": float(route.get("realised_amount_out") or 0.0),
        "realised_leg1_output": route.get("realised_leg1_output"),
        "realised_leg2_input": route.get("realised_leg2_input"),
        "intermediate_amount_gap_bps": route.get("intermediate_amount_gap_bps"),
        "realised_venues": "|".join(value for value in realised_venues if value),
        "realised_pools": "|".join(value for value in realised_pools if value),
        "reason": reason,
        "reason_detail": reason_detail,
        "chosen_quote_out": chosen_quote_out,
        "signed_validation_error_bps": signed_validation_error_bps,
        "validation_tolerance_bps": 10_000 * VALIDATION_TOLERANCE,
    }


def intermediate_amount_gap_bps(
    leg1_output: object, leg2_input: object
) -> float | None:
    """Token-unit discontinuity between the two claimed legs of one route."""
    try:
        first = float(leg1_output)
        second = float(leg2_input)
    except (TypeError, ValueError):
        return None
    if not positive_finite_amount(first) or not positive_finite_amount(second):
        return None
    return 10_000 * (second / first - 1.0)


def load_target_routes(
    day: str,
    events: list[TickReplayEvent],
    v2_replay: V2ReplayDay,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
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
    route_mask = pd.Series(
        [
            (str(tx_hash).lower(), int(component_id)) in route_keys
            for tx_hash, component_id in zip(
                route_legs["tx_hash"], route_legs["component_id"], strict=True
            )
        ],
        index=route_legs.index,
        dtype=bool,
    )
    route_legs = route_legs.loc[route_mask].copy()
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
    rejections: list[dict[str, object]] = []
    mapped = 0
    above_minimum = 0
    block_order_unavailable = 0
    intermediate_amount_coherent = 0
    intermediate_amount_incoherent = 0
    for route in exact_routes.to_dict("records"):
        tx_hash = str(route["tx_hash"]).lower()
        component_id = int(route["component_id"])
        selected_legs = grouped_legs.get((tx_hash, component_id))
        if selected_legs is None or len(selected_legs) != 2:
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "route_leg_identity_unavailable",
                    reason_detail=(
                        "missing"
                        if selected_legs is None
                        else f"observed_legs={len(selected_legs)}"
                    ),
                )
            )
            continue
        first_leg, second_leg = tuple(selected_legs.itertuples(index=False))
        flow_gap = intermediate_amount_gap_bps(
            first_leg.amount_out, second_leg.amount_in
        )
        route = {
            **route,
            "realised_leg1_output": first_leg.amount_out,
            "realised_leg2_input": second_leg.amount_in,
            "intermediate_amount_gap_bps": flow_gap,
        }
        if flow_gap is None or abs(flow_gap) > INTERMEDIATE_FLOW_TOLERANCE_BPS:
            intermediate_amount_incoherent += 1
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "intermediate_amount_incoherent",
                    reason_detail=(
                        "nonpositive_or_missing"
                        if flow_gap is None
                        else f"gap_bps={flow_gap}"
                    ),
                )
            )
            continue
        intermediate_amount_coherent += 1
        matched_events: list[dict[str, object]] = []
        rejection_reason: str | None = None
        rejection_detail: str | None = None
        for leg in selected_legs.itertuples(index=False):
            try:
                log_index = int(leg.log_index)
            except (TypeError, ValueError):
                rejection_reason = "invalid_log_index"
                rejection_detail = str(leg.log_index)
                break
            venue = str(leg.source)
            if venue in V2_VENUES:
                event = v2_replay.swaps_by_identity.get((venue, tx_hash, log_index))
                if event is None:
                    rejection_reason = "raw_swap_identity_unavailable"
                    rejection_detail = f"{venue}:{log_index}"
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
                    rejection_reason = "raw_swap_identity_unavailable"
                    rejection_detail = f"{venue}:{log_index}"
                    break
                pool = str((event.row.get("pool") or {}).get("id") or "").lower()
                try:
                    timestamp = int(timestamp_value(event.row) or 0)
                    block = block_value(event.row)
                    block_number = int(block) if block is not None else None
                except (TypeError, ValueError):
                    rejection_reason = "raw_swap_payload_invalid"
                    rejection_detail = f"{venue}:{log_index}"
                    break
                if not pool or timestamp <= 0:
                    rejection_reason = "raw_swap_payload_invalid"
                    rejection_detail = f"{venue}:{log_index}"
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
            rejections.append(
                rejection_record(
                    day,
                    route,
                    rejection_reason or "raw_swap_mapping_incomplete",
                    reason_detail=rejection_detail,
                    venues=tuple(str(event["venue"]) for event in matched_events),
                    pools=tuple(str(event["pool"]) for event in matched_events),
                )
            )
            continue
        mapped += 1
        input_usd = float(route["input_usd"])
        if not np.isfinite(input_usd) or input_usd < MIN_INPUT_USD:
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "realised_input_below_minimum",
                    reason_detail=f"input_usd={input_usd}",
                    venues=tuple(str(event["venue"]) for event in matched_events),
                    pools=tuple(str(event["pool"]) for event in matched_events),
                )
            )
            continue
        above_minimum += 1
        pools = tuple(str(event["pool"]) for event in matched_events)
        venues = tuple(str(event["venue"]) for event in matched_events)
        try:
            target_order = strict_route_order(matched_events)
        except ValueError as error:
            raise ValueError(f"{error}: {route['route_id']}") from error
        if target_order is None:
            block_order_unavailable += 1
            rejections.append(
                rejection_record(
                    day,
                    route,
                    "block_order_unavailable",
                    venues=venues,
                    pools=pools,
                )
            )
            continue
        target_timestamp = min(int(event["timestamp"]) for event in matched_events)
        targets.append(
            {
                **route,
                "day": day,
                "tx_hash": tx_hash,
                "target_order": target_order,
                "v2_hour": target_timestamp - target_timestamp % 3600,
                "v2_order": target_order,
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
        "intermediate_amount_coherent_routes": intermediate_amount_coherent,
        "intermediate_amount_incoherent_routes": int(
            intermediate_amount_incoherent
        ),
        "intermediate_flow_tolerance_bps": INTERMEDIATE_FLOW_TOLERANCE_BPS,
        "routes_at_least_100usd": above_minimum,
        "scored_routes": 0,
        "rejected_routes": len(rejections),
        "invalid_realised_input": 0,
        "invalid_realised_output": 0,
        "invalid_chosen_output": 0,
        "chosen_state_unavailable": 0,
        "chosen_output_mismatch": 0,
        "quarantined_tick_pools": 0,
        "clean_v2_pool_hours": int(len(v2_replay.pool_hour_events)),
    }
    return targets, rejections, support


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
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    targets, rejection_rows, support = load_target_routes(day, events, v2_replay)
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
            if not positive_finite_amount(route.amount_in):
                support["invalid_realised_input"] += 1
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "invalid_realised_input",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                    )
                )
                continue

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
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "chosen_state_unavailable",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                    )
                )
                continue
            signed_validation_error = chosen_output_error(route, chosen)
            if signed_validation_error is None:
                if not positive_finite_amount(route.amount_out):
                    support["invalid_realised_output"] += 1
                    reason = "invalid_realised_output"
                else:
                    support["invalid_chosen_output"] += 1
                    reason = "invalid_chosen_output"
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        reason,
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                        chosen_quote_out=float(chosen.amount_out),
                    )
                )
                continue
            validation_error = abs(signed_validation_error)
            validation_errors_bps.append(10_000 * signed_validation_error)
            if bool(target["within_20pct"]):
                coherent_validation_errors_bps.append(validation_errors_bps[-1])
            if validation_error > VALIDATION_TOLERANCE:
                support["chosen_output_mismatch"] += 1
                rejection_rows.append(
                    rejection_record(
                        day,
                        target,
                        "chosen_output_mismatch",
                        causal_order=order,
                        venues=route.venues,
                        pools=route.pools,
                        chosen_quote_out=float(chosen.amount_out),
                        signed_validation_error_bps=10_000 * signed_validation_error,
                    )
                )
                continue
            score = score_frontier_from_quote(
                route,
                chosen=chosen,
                vehicles=vehicles,
                quote_legs=quote_legs,
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
                    "realised_leg1_output": target["realised_leg1_output"],
                    "realised_leg2_input": target["realised_leg2_input"],
                    "intermediate_amount_gap_bps": target[
                        "intermediate_amount_gap_bps"
                    ],
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
    support["rejected_routes"] = len(rejection_rows)
    if len(rows) + len(rejection_rows) != int(support["exact_venue_two_leg_routes"]):
        raise AssertionError("frontier route ledger does not reconcile to exact support")
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
    return pd.DataFrame(rows), pd.DataFrame(rejection_rows), support


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


def assemble_cached_output(
    day_cache: Path,
    support_rows: list[dict[str, object]],
    *,
    suffix: str,
    count_column: str,
    output: Path,
    inputs: list[Path],
    notes: str,
) -> int:
    """Assemble a full-daily route ledger from validated day shards out of core."""
    expected = sum(int(row[count_column]) for row in support_rows)
    files = [
        day_cache / f"{row['day']}{suffix}"
        for row in support_rows
        if int(row[count_column]) > 0
    ]
    if expected == 0:
        raise RuntimeError(f"no rows available for {output.name}")

    def progress(index: int, total: int, rows: int) -> None:
        if index % 180 == 0 or index == total:
            print(
                f"  assembled {output.name} [{index:,}/{total:,}] rows={rows:,}",
                flush=True,
            )

    result = assemble_parquet_shards(
        files,
        output,
        progress=progress,
        unique_keys=("day", "route_id"),
    )
    if result.rows != expected:
        raise RuntimeError(
            f"assembled {output.name} row mismatch: {result.rows:,} != {expected:,}"
        )
    stamp(
        output,
        code_sources=OUTPUT_CODE_SOURCES,
        inputs=[*inputs, day_cache],
        rows=result.rows,
        notes=notes,
    )
    return result.rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--day", action="append", help="repeat for an unpublished explicit-date diagnostic"
    )
    selection.add_argument(
        "--audit-calendar",
        action="store_true",
        help="audit one exact daily snapshot per calendar month, nearest the 15th",
    )
    selection.add_argument(
        "--daily-calendar",
        action="store_true",
        help="materialise the distinct full-daily estimation frontier after the audit passes",
    )
    args = parser.parse_args()
    require_node_d_release(routes=True, market_state=True)
    require_current_artifacts(
        [TOKEN_DECIMALS], consumer="transaction-state frontier"
    )
    try:
        selected = select_days(
            available_days(nonempty=args.audit_calendar),
            explicit=args.day,
            audit_calendar=args.audit_calendar,
            daily_calendar=args.daily_calendar,
        )
    except ValueError as error:
        print(f"error: {error}")
        return 1
    vehicles = candidate_vehicles()
    selected_set = set(selected)
    daily_mode = bool(args.daily_calendar)
    frames: list[pd.DataFrame] = []
    rejection_frames: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    inputs = [
        UNIFIED,
        UNIFIED_QUALITY_PANEL,
        *(
            MARKET_STATE
            / ("constant_product" if venue in V2_VENUES else "tick")
            / venue
            for venue in EXACT_VENUES
        ),
        TOKEN_DECIMALS,
        V4_STATIC_QUARANTINE_PANEL,
    ]
    frontier_generation = cache_key(CODE_SOURCES, inputs=inputs)
    day_cache = (
        DATA_DIR
        / "empirical"
        / "_transaction_state_frontier_day_cache"
        / f"engine_{frontier_generation}"
    )
    cached_days = {
        day: (
            load_cached_day_support(day_cache, day)
            if daily_mode
            else load_cached_day(day_cache, day)
        )
        for day in selected
    }
    uncached_days = [day for day in selected if cached_days[day] is None]
    replay_generation = cache_key(
        REPLAY_SOURCES,
        inputs=[
            MARKET_STATE / "tick" / "uniswap_v3",
            MARKET_STATE / "tick" / "uniswap_v4",
            TOKEN_DECIMALS,
            V4_STATIC_QUARANTINE_PANEL,
        ],
    )
    checkpoint_dir = (
        DATA_DIR
        / "empirical"
        / "_tick_replay_checkpoints"
        / f"engine_{replay_generation}"
    )
    replay_start: str | None = None
    replay: TickReplayState | None = None
    if uncached_days:
        resume_checkpoint = latest_replay_checkpoint(checkpoint_dir, uncached_days[0])
        if resume_checkpoint is not None:
            replay = load_replay_checkpoint(resume_checkpoint)
            replay_start = checkpoint_day(resume_checkpoint)
            print(f"loaded replay checkpoint before {replay_start}", flush=True)
        else:
            replay = TickReplayState(
                token_decimals=load_token_decimals(TOKEN_DECIMALS),
                quarantined_pools={
                    "uniswap_v4": load_v4_static_quarantine()
                },
            )
            replay_start = min(REPLAY_START, uncached_days[0])
    for day in selected:
        if replay_start is not None and day >= replay_start:
            break
        cached = cached_days[day]
        if cached is None:
            raise RuntimeError(f"uncached frontier day precedes replay start: {day}")
        if daily_mode:
            support = cached
        else:
            frame, rejections, support = cached
            frames.append(frame)
            rejection_frames.append(rejections)
        support_rows.append(support)
    calendar = (
        pd.date_range(
            pd.to_datetime(replay_start, format="%Y%m%d"),
            pd.to_datetime(max(selected), format="%Y%m%d"),
            freq="D",
        )
        if replay_start is not None
        else []
    )
    for index, observed in enumerate(calendar, 1):
        assert replay is not None
        day = observed.strftime("%Y%m%d")
        checkpoint = checkpoint_dir / f"pre_{day}.pkl"
        if replay_checkpoint_due(
            day=day,
            index=index,
            selected_days=selected_set,
            daily_mode=daily_mode,
        ):
            if not checkpoint.exists():
                save_replay_checkpoint(checkpoint, replay)
                print(f"wrote replay checkpoint before {day}", flush=True)
        if day in selected_set:
            cached = cached_days[day]
            if cached is not None:
                if daily_mode:
                    support = cached
                else:
                    frame, rejections, support = cached
                warm_tick_day(MARKET_STATE, day, replay)
                cache_note = " [cached]"
            else:
                events = load_tick_day_events(MARKET_STATE, day)
                v2_replay = load_v2_replay_day(MARKET_STATE, day)
                frame, rejections, support = score_day(
                    day, events, replay, v2_replay, vehicles
                )
                write_cached_day(day_cache, day, frame, rejections, support)
                cache_note = ""
            if not daily_mode:
                frames.append(frame)
                rejection_frames.append(rejections)
            support_rows.append(support)
            print(
                f"{day}: {support['all_exact_two_leg_routes']:,} exact two-leg; "
                f"{support['exact_venue_two_leg_routes']:,} V2/V3/V4; "
                f"{support['scored_routes']:,} exact-state scored{cache_note}",
                flush=True,
            )
        else:
            warm_tick_day(MARKET_STATE, day, replay)
        if index % 180 == 0:
            print(f"replayed through {day} ({index:,}/{len(calendar):,} days)", flush=True)
    support = pd.DataFrame(support_rows)
    if daily_mode:
        panel_rows = assemble_cached_output(
            day_cache,
            support_rows,
            suffix=".parquet",
            count_column="scored_routes",
            output=DAILY_PANEL,
            inputs=inputs,
            notes="full-daily strict pre-transaction V2/V3/V4 realised and public-path frontier; distinct from the construction audit",
        )
        rejection_rows = assemble_cached_output(
            day_cache,
            support_rows,
            suffix=".rejections.parquet",
            count_column="rejected_routes",
            output=DAILY_REJECTIONS,
            inputs=inputs,
            notes="full-daily route-level exclusion and chosen-route reproduction ledger",
        )
        write_panel(
            support,
            DAILY_SUPPORT,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes="daily V2/V3/V4 exact-state support funnel for the full estimation frontier",
        )
        print(
            f"wrote full-daily frontier on {len(selected):,} calendar days: "
            f"{panel_rows:,} scored and {rejection_rows:,} rejected routes"
        )
        return 0

    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    rejections = (
        pd.concat(rejection_frames, ignore_index=True)
        if rejection_frames
        else pd.DataFrame()
    )
    if panel.empty:
        print("no transaction-state frontier routes survived validation")
        return 1
    if args.day:
        print(
            f"explicit diagnostic complete: {len(selected):,} day(s), "
            f"{len(panel):,} scored and {len(rejections):,} rejected routes; "
            "canonical outputs unchanged"
        )
        return 0

    summary = summarise(panel)
    write_panel(
        panel,
        AUDIT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="77-date construction audit of the strict pre-transaction V2/V3/V4 frontier",
    )
    write_panel(
        rejections,
        AUDIT_REJECTIONS,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="77-date route-level exclusion and chosen-route reproduction ledger",
    )
    write_exhibit(
        summary,
        AUDIT_SUMMARY,
        code_sources=CODE_SOURCES,
        inputs=[AUDIT_PANEL],
        notes="construction-audit route and dollar magnitudes; not an estimation sample",
    )
    write_exhibit(
        support,
        AUDIT_SUPPORT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="77-date V2/V3/V4 exact-state support and chosen-route reproduction gate",
    )
    coherent_available = int(support["within_20pct_chosen_quote_available"].sum())
    coherent_mismatches = int(
        support["within_20pct_chosen_output_mismatch"].sum()
    )
    reproduction = chosen_reproduction_share(
        coherent_available, coherent_mismatches
    )
    print(
        f"chosen-route reproduction: {reproduction:.2%} "
        f"({coherent_available - coherent_mismatches:,}/{coherent_available:,})"
    )
    if reproduction < MIN_CHOSEN_REPRODUCTION:
        print(
            f"FAILED: chosen-route reproduction is below the "
            f"{MIN_CHOSEN_REPRODUCTION:.0%} gate"
        )
        return 1
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
    with exclusive_job(LOCK, job="transaction-state frontier"):
        raise SystemExit(main())
