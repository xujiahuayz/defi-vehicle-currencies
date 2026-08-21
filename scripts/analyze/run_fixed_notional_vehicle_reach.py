#!/usr/bin/env python3
"""Measure executable vehicle reach at fixed USD notionals.

The existing exact vehicle frontier prices realised endpoint-pair trades at
their own transaction sizes.  It therefore cannot measure whether one vehicle
has a broader executable spoke network at a common size.  This companion
exercise takes end-of-day snapshots on the same fifteenth-of-month calendar
and asks a narrower question: from each named vehicle, how many priced endpoint
tokens can be reached in one pool with $10,000 or $100,000 of input?

Uniswap V2 and SushiSwap V2 use their last validated hourly reserve snapshot.
Uniswap V3 uses the causally replayed post-final-event state.  A leg is
executable only when the existing exact-frontier 5% own-leg support bound is
met.  The output-token price converts the quoted amount back to USD, producing
an all-in quoted-output shortfall alongside the quoter's finite-size impact.

This is a descriptive network-state panel.  It does not replace the existing
unweighted betweenness measure, infer an LP motive, or use realised route
choice.  Its endpoint-level rows are deliberately retained so a later LP-flow
test can lag the snapshot and remove the focal endpoint before constructing
vehicle reach.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from functools import partial
from itertools import chain
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import classify
from ddvc.capital_validation import validated_capital_prices
from ddvc.cpquote import Pool, quote_one_hop
from ddvc.paths import DATA_DIR, OUTPUT_DIR, TOKEN_PRICE_DAILY_PANEL
from ddvc.pricing.path_frontier import LegQuote
from ddvc.pricing.tick_frontier import PoolIndex, tick_leg_quotes
from ddvc.pricing.tick_replay import (
    TickReplayState,
    load_tick_day_events,
)
from ddvc.prices import load_canonical_token_prices
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_exact_vehicle_frontier import (
    MAX_PRICE_IMPACT,
    NATIVE_VEHICLES,
    STABLE_VEHICLES,
    TICK_START,
    monthly_days,
)


CAPITAL_INPUT = DATA_DIR / "processed/pool_capital_daily.parquet"
PRICE_INPUT = TOKEN_PRICE_DAILY_PANEL
PANEL_OUTPUT = DATA_DIR / "processed/fixed_notional_vehicle_reach_monthly.parquet"
SUMMARY_OUTPUT = OUTPUT_DIR / "exhibits/fixed_notional_vehicle_reach_monthly.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/fixed_notional_vehicle_reach_support.jsonl"

VEHICLES = tuple((*NATIVE_VEHICLES, *STABLE_VEHICLES))
VEHICLE_SET = frozenset(VEHICLES)
NOTIONALS_USD = (10_000.0, 100_000.0)
V2_VENUES = frozenset({"uniswap_v2", "sushiswap_v2"})
VALID_RESERVE_STATUS = "validated_last_hourly_reserve_snapshot"
VALID_IDENTITY_STATUS = "exact_identity_and_decimals_passed"
CODE_SOURCES = [
    "scripts/analyze/run_fixed_notional_vehicle_reach.py",
    "scripts/analyze/run_exact_vehicle_frontier.py",
    "src/ddvc/pricing/tick_frontier.py",
    "src/ddvc/pricing/tick_quote.py",
    "src/ddvc/cpquote.py",
]


def _normalise_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"day", "token", "price_usd"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"fixed-notional reach prices lack columns: {missing}")
    frame = prices.loc[:, ["day", "token", "price_usd"]].copy()
    frame["day"] = frame["day"].astype(str)
    frame["token"] = frame["token"].astype(str).str.lower()
    frame["price_usd"] = pd.to_numeric(frame["price_usd"], errors="coerce")
    valid = (
        frame["day"].str.fullmatch(r"\d{8}")
        & frame["token"].str.fullmatch(r"0x[0-9a-f]{40}")
        & np.isfinite(frame["price_usd"])
        & frame["price_usd"].gt(0)
    )
    frame = frame.loc[valid].copy()
    if frame.duplicated(["day", "token"]).any():
        raise ValueError("fixed-notional reach prices duplicate an address-day")
    return frame.reset_index(drop=True)


def _valid_v2_rows(rows: pd.DataFrame) -> pd.DataFrame:
    required = {
        "venue",
        "day",
        "pool",
        "token0_address",
        "token1_address",
        "reserve0",
        "reserve1",
        "reserve_validation_status",
        "identity_validation_status",
        "capital_valid",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"fixed-notional reach V2 state lacks columns: {missing}")
    frame = rows.copy()
    for column in ("venue", "day", "pool", "token0_address", "token1_address"):
        frame[column] = frame[column].astype(str).str.lower()
    frame["reserve0"] = pd.to_numeric(frame["reserve0"], errors="coerce")
    frame["reserve1"] = pd.to_numeric(frame["reserve1"], errors="coerce")
    valid = (
        frame["venue"].isin(V2_VENUES)
        & frame["capital_valid"].fillna(False).astype(bool)
        & frame["reserve_validation_status"].eq(VALID_RESERVE_STATUS)
        & frame["identity_validation_status"].eq(VALID_IDENTITY_STATUS)
        & frame["token0_address"].str.fullmatch(r"0x[0-9a-f]{40}")
        & frame["token1_address"].str.fullmatch(r"0x[0-9a-f]{40}")
        & np.isfinite(frame["reserve0"])
        & np.isfinite(frame["reserve1"])
        & frame["reserve0"].gt(0)
        & frame["reserve1"].gt(0)
    )
    frame = frame.loc[valid].copy()
    if frame.duplicated(["venue", "day", "pool"]).any():
        raise ValueError("fixed-notional reach V2 state duplicates a venue-pool-day")
    return frame.reset_index(drop=True)


def v2_pool_index(rows: pd.DataFrame) -> dict[frozenset[str], list[Pool]]:
    """Index validated closing V2 reserves by canonical token pair."""

    frame = _valid_v2_rows(rows)
    result: dict[frozenset[str], list[Pool]] = {}
    for row in frame.itertuples(index=False):
        pool = Pool(
            pool_id=str(row.pool),
            token0=str(row.token0_address),
            token1=str(row.token1_address),
            reserve0=Decimal(str(row.reserve0)),
            reserve1=Decimal(str(row.reserve1)),
            venue=str(row.venue),
        )
        result.setdefault(
            frozenset((pool.token0, pool.token1)), []
        ).append(pool)
    for pools in result.values():
        pools.sort(key=lambda item: (item.venue, item.pool_id))
    return result


def v2_leg_quotes(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    pools: Mapping[frozenset[str], Iterable[Pool]],
    max_support: float = MAX_PRICE_IMPACT,
) -> list[LegQuote]:
    """Quote every validated closing V2 pool under the frontier support rule."""

    amount = Decimal(str(amount_in))
    quotes: list[LegQuote] = []
    for pool in pools.get(frozenset((token_in, token_out)), ()):
        reserves = pool.reserves_for(token_in)
        if reserves is None or reserves[0] <= 0:
            continue
        reserve_in, reserve_out = reserves
        if float(amount / reserve_in) > max_support:
            continue
        output = quote_one_hop(pool, token_in, amount)
        if output is None or output <= 0 or reserve_out <= 0:
            continue
        spot_output = amount * reserve_out / reserve_in
        if spot_output <= 0:
            continue
        quotes.append(
            LegQuote(
                amount_out=float(output),
                venue=pool.venue,
                pool=pool.pool_id,
                price_impact=max(0.0, 1.0 - float(output / spot_output)),
            )
        )
    return quotes


def _candidate_linked_endpoints(
    v2_pairs: Iterable[frozenset[str]],
    tick_pairs: Iterable[frozenset[str]],
) -> set[str]:
    endpoints: set[str] = set()
    for pair in chain(v2_pairs, tick_pairs):
        tokens = set(pair)
        if len(tokens) != 2 or not (tokens & VEHICLE_SET):
            continue
        endpoints.update(tokens)
    return endpoints


def _endpoint_scope(candidate: str, endpoint: str) -> str:
    if endpoint not in VEHICLE_SET:
        return "noncandidate_spoke"
    if candidate in STABLE_VEHICLES and endpoint in STABLE_VEHICLES:
        return "stable_stable_core"
    return "vehicle_core"


TickLegEnumerator = Callable[[str, str, float], Iterable[LegQuote]]


def snapshot_frontier(
    day: str,
    v2_rows: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    tick_pool_index: PoolIndex | None = None,
    tick_quote_legs: TickLegEnumerator | None = None,
    notionals_usd: tuple[float, ...] = NOTIONALS_USD,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build one fixed-notional candidate-to-endpoint closing-state frontier."""

    if not notionals_usd or any(value <= 0 for value in notionals_usd):
        raise ValueError("fixed-notional reach requires positive USD notionals")
    if len(set(notionals_usd)) != len(notionals_usd):
        raise ValueError("fixed-notional reach notionals must be unique")
    day = str(day)
    day_prices = _normalise_prices(prices)
    day_prices = day_prices.loc[day_prices["day"].eq(day)].copy()
    if day_prices.empty:
        raise ValueError(f"fixed-notional reach has no validated prices on {day}")
    price_lookup = dict(
        zip(day_prices["token"], day_prices["price_usd"], strict=True)
    )
    v2_rows = _valid_v2_rows(v2_rows)
    v2_rows = v2_rows.loc[v2_rows["day"].eq(day)].copy()
    pools = v2_pool_index(v2_rows)
    tick_pool_index = tick_pool_index or {}
    endpoints = sorted(
        token
        for token in _candidate_linked_endpoints(pools, tick_pool_index)
        if token in price_lookup
    )
    rows: list[dict[str, object]] = []
    present_candidates = [token for token in VEHICLES if token in price_lookup]
    for candidate in present_candidates:
        candidate_symbol, candidate_type = classify(candidate)
        candidate_price = float(price_lookup[candidate])
        for endpoint in endpoints:
            if endpoint == candidate:
                continue
            endpoint_symbol, endpoint_type = classify(endpoint)
            endpoint_price = float(price_lookup[endpoint])
            for notional in sorted(notionals_usd):
                input_amount = float(notional / candidate_price)
                quotes = v2_leg_quotes(
                    candidate,
                    endpoint,
                    input_amount,
                    pools=pools,
                )
                if tick_quote_legs is not None:
                    quotes.extend(
                        tick_quote_legs(candidate, endpoint, input_amount)
                    )
                best = max(
                    quotes,
                    key=lambda item: (item.amount_out, item.venue, item.pool),
                    default=None,
                )
                output_amount = best.amount_out if best is not None else None
                output_usd = (
                    float(output_amount * endpoint_price)
                    if output_amount is not None
                    else None
                )
                rows.append(
                    {
                        "day": day,
                        "candidate_address": candidate,
                        "candidate_symbol": candidate_symbol,
                        "candidate_type": candidate_type,
                        "endpoint_address": endpoint,
                        "endpoint_symbol": endpoint_symbol,
                        "endpoint_type": endpoint_type,
                        "endpoint_scope": _endpoint_scope(candidate, endpoint),
                        "notional_usd": float(notional),
                        "candidate_price_usd": candidate_price,
                        "endpoint_price_usd": endpoint_price,
                        "input_amount": input_amount,
                        "executable": best is not None,
                        "best_output_amount": output_amount,
                        "best_output_usd": output_usd,
                        "all_in_cost_bps": (
                            10_000.0 * (1.0 - output_usd / notional)
                            if output_usd is not None
                            else None
                        ),
                        "best_price_impact_bps": (
                            10_000.0 * best.price_impact
                            if best is not None
                            else None
                        ),
                        "best_venue": best.venue if best is not None else None,
                        "best_pool": best.pool if best is not None else None,
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError(f"fixed-notional reach has no candidate-endpoint rows on {day}")
    keys = ["day", "candidate_address", "endpoint_address", "notional_usd"]
    if result.duplicated(keys).any():
        raise ValueError("fixed-notional reach duplicates a candidate-endpoint-notional")
    support = {
        "record_type": "fixed_notional_vehicle_reach_support",
        "day": day,
        "priced_tokens": int(len(price_lookup)),
        "priced_candidate_linked_endpoints": int(len(endpoints)),
        "priced_vehicle_candidates": int(len(present_candidates)),
        "missing_vehicle_candidates": "|".join(
            classify(token)[0] for token in VEHICLES if token not in price_lookup
        ),
        "validated_v2_pools": int(sum(map(len, pools.values()))),
        "supported_v3_pools": int(
            sum(len(values) for values in tick_pool_index.values())
        ),
        "frontier_rows": int(len(result)),
        "snapshot_timing": (
            "target_day_close_v2_last_validated_hourly_snapshot_"
            "v3_post_final_event"
        ),
        "notionals_usd": "|".join(f"{value:.0f}" for value in notionals_usd),
        "support_bound": "maximum_own_leg_price_impact_5pct",
    }
    return result.sort_values(keys).reset_index(drop=True), support


def summarize_reach(panel: pd.DataFrame) -> pd.DataFrame:
    """Aggregate executable breadth and quoted cost without hiding the endpoint rows."""

    required = {
        "day",
        "candidate_address",
        "candidate_symbol",
        "candidate_type",
        "endpoint_address",
        "endpoint_scope",
        "notional_usd",
        "executable",
        "all_in_cost_bps",
        "best_price_impact_bps",
        "best_venue",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"fixed-notional reach panel lacks columns: {missing}")
    scopes = {
        "all_priced_endpoints": panel,
        "noncandidate_spokes": panel.loc[
            panel["endpoint_scope"].eq("noncandidate_spoke")
        ],
        "candidate_core": panel.loc[
            panel["endpoint_scope"].ne("noncandidate_spoke")
        ],
        "stable_stable_core": panel.loc[
            panel["endpoint_scope"].eq("stable_stable_core")
        ],
    }
    rows: list[dict[str, object]] = []
    group_columns = [
        "day",
        "candidate_address",
        "candidate_symbol",
        "candidate_type",
        "notional_usd",
    ]
    for scope, scoped in scopes.items():
        for keys, group in scoped.groupby(group_columns, sort=True):
            executable = group.loc[group["executable"].astype(bool)]
            rows.append(
                {
                    "record_type": "fixed_notional_vehicle_reach",
                    "scope": scope,
                    **dict(zip(group_columns, keys, strict=True)),
                    "priced_endpoints": int(group["endpoint_address"].nunique()),
                    "executable_endpoints": int(
                        executable["endpoint_address"].nunique()
                    ),
                    "executable_coverage_share": float(group["executable"].mean()),
                    "mean_all_in_cost_bps": float(
                        executable["all_in_cost_bps"].mean()
                    ),
                    "median_all_in_cost_bps": float(
                        executable["all_in_cost_bps"].median()
                    ),
                    "median_price_impact_bps": float(
                        executable["best_price_impact_bps"].median()
                    ),
                    "v3_best_quote_share": float(
                        executable["best_venue"].eq("uniswap_v3").mean()
                    ),
                    "quantity": (
                        "priced_candidate_linked_endpoint_tokens_reachable_"
                        "in_one_pool_at_fixed_candidate_input_usd"
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("fixed-notional reach summary is empty")
    return result.sort_values(
        ["day", "scope", "candidate_address", "notional_usd"]
    ).reset_index(drop=True)


def _capital_day(path: Path, day: str) -> pd.DataFrame:
    columns = [
        "venue",
        "day",
        "pool",
        "token0_address",
        "token1_address",
        "reserve0",
        "reserve1",
        "reserve_validation_status",
        "identity_validation_status",
        "capital_valid",
    ]
    return pd.read_parquet(path, columns=columns, filters=[("day", "=", day)])


def run(
    selected: list[str],
    *,
    capital_path: Path = CAPITAL_INPUT,
    price_path: Path = PRICE_INPUT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Replay V3 once and collect closing fixed-notional snapshots."""

    if not capital_path.is_file():
        raise FileNotFoundError(capital_path)
    prices = load_canonical_token_prices(
        price_path,
        columns=("day", "token", "price_usd"),
    )
    # The full canonical panel defines the priced endpoint perimeter.  For the
    # four input vehicles, retain the tighter rolling and peg sanity checks used
    # by the deposited-capital analyses.
    anchor_prices = validated_capital_prices(price_path).loc[
        lambda frame: frame["token"].isin(VEHICLE_SET),
        ["day", "token", "price_usd"],
    ]
    prices = pd.concat(
        [prices.loc[~prices["token"].isin(VEHICLE_SET)], anchor_prices],
        ignore_index=True,
    )
    prices = _normalise_prices(prices)
    selected_set = set(selected)
    first, last = min(selected), max(selected)
    replay_start = min(first, TICK_START)
    replay = TickReplayState()
    panels: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    calendar = pd.date_range(
        pd.to_datetime(replay_start, format="%Y%m%d"),
        pd.to_datetime(last, format="%Y%m%d"),
        freq="D",
    )
    for index, observed in enumerate(calendar, 1):
        day = observed.strftime("%Y%m%d")
        if day >= TICK_START:
            replay.apply_all(
                load_tick_day_events(None, day, venues=("uniswap_v3",))
            )
        if day not in selected_set:
            if index % 180 == 0:
                print(f"replayed V3 through {day}", flush=True)
            continue
        tick_quotes = partial(
            tick_leg_quotes,
            pool_index=replay.pool_index,
            states_by_venue=replay.states_by_venue,
            ticks_by_venue=replay.ticks_by_venue,
            allowed_venues={"uniswap_v3"},
            max_price_impact=MAX_PRICE_IMPACT,
            quote_indexes_by_venue=replay.quote_indexes_by_venue,
        )
        panel, support = snapshot_frontier(
            day,
            _capital_day(capital_path, day),
            prices.loc[prices["day"].eq(day)],
            tick_pool_index=replay.pool_index,
            tick_quote_legs=tick_quotes,
        )
        panels.append(panel)
        support_rows.append(support)
        print(
            f"{day}: endpoints={support['priced_candidate_linked_endpoints']:,} "
            f"rows={support['frontier_rows']:,}",
            flush=True,
        )
    combined = pd.concat(panels, ignore_index=True)
    summary = summarize_reach(combined)
    support = pd.DataFrame(support_rows)
    return combined, summary, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="20200615")
    parser.add_argument("--end", default="20260615")
    parser.add_argument("--capital", type=Path, default=CAPITAL_INPUT)
    parser.add_argument("--prices", type=Path, default=PRICE_INPUT)
    parser.add_argument(
        "--pilot-day",
        help="build one date and print summaries without changing canonical outputs",
    )
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="rebuild the summary from the existing endpoint-level panel",
    )
    args = parser.parse_args()
    if args.summarize_only:
        if not PANEL_OUTPUT.is_file():
            parser.error("--summarize-only requires the endpoint-level panel")
        summary = summarize_reach(pd.read_parquet(PANEL_OUTPUT))
        write_exhibit(
            summary,
            SUMMARY_OUTPUT,
            code_sources=CODE_SOURCES,
            inputs=[PANEL_OUTPUT],
        )
        return 0
    selected = (
        [args.pilot_day.replace("-", "")]
        if args.pilot_day
        else monthly_days(args.start.replace("-", ""), args.end.replace("-", ""))
    )
    panel, summary, support = run(
        selected,
        capital_path=args.capital,
        price_path=args.prices,
    )
    print(summary.to_string(index=False), flush=True)
    if args.pilot_day:
        return 0
    write_panel(
        panel,
        PANEL_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[args.capital, args.prices],
        notes=(
            "Endpoint-level fixed-notional vehicle reach at monthly closing "
            "state; retained for strict lagging and focal-endpoint removal."
        ),
    )
    write_exhibit(
        summary,
        SUMMARY_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL_OUTPUT],
    )
    write_exhibit(
        support,
        SUPPORT_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL_OUTPUT],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
