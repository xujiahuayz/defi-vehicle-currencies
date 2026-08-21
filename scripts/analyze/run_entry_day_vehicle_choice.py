#!/usr/bin/env python3
"""Estimate vehicle selection on materially active endpoint-pair entry days.

The sample starts from each ordered endpoint pair's first day with a native or
stable vehicle route.  To keep exact transaction-state replay bounded, the
default cohort requires at least $100,000 of value-supported native-plus-stable
route activity on that day.  WETH and DAI/USDC/USDT endpoints are excluded.

For every retained entry day, the runner quotes each economically material
observed two-leg route at its pre-transaction state.  A row survives only when
the chosen route reproduces within one basis point, source/intermediary/
destination values agree within 20 percent, the input is at least $100, the
chosen route's largest leg price impact is at most 5 percent, and both a WETH
path and a DAI/USDC/USDT path are feasible under that same 5-percent support
bound.  The outcome is whether the observed vehicle is a stablecoin.

The three-column ladder uses one common sample with positive prior-calendar V2
bottleneck capital for both vehicle families: exact-output advantage only,
relative weak-leg capital only, and both jointly.  Date, source-token,
destination-token, and observed route-scope fixed effects are absorbed.  The
covariance is clustered by ordered endpoint pair and calendar date.  A broader
price-only estimate over every exact contestable entry-day route is retained as
a support check.

Reads
    data/processed/endpoint_candidate_pair_support.parquet
    data/processed/pool_capital_daily.parquet
    data/unified/*.parquet
    exact V2/V3 raw-state inputs used by run_exact_vehicle_frontier.py
Writes
    data/processed/entry_day_vehicle_choice_exact.parquet
    output/exhibits/entry_day_vehicle_choice.jsonl
    output/exhibits/entry_day_vehicle_choice_support.jsonl
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.analysis.transaction_frontier import RealisedPath
from ddvc.paths import OUTPUT_DIR, PRIMARY_REPO_ROOT, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.pricing.tick_replay import TickReplayEvent, TickReplayState, load_tick_day_events
from ddvc.pricing.v2_replay import V2ReplayDay, load_v2_replay_day
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit, write_panel
from scripts.analyze.run_contestable_vehicle_choice import (
    MAX_LINEAR_ADVANTAGE_BPS,
    QUOTED_STABLES,
    QUOTED_VEHICLES,
    QUOTED_LEG_MAX_PRICE_IMPACT,
    attach_v2_bridge_capital,
    load_lagged_v2_bridge_capital,
)
from scripts.analyze.run_exact_vehicle_frontier import (
    EXACT_VENUES,
    TICK_START,
    RouteTarget,
    _resolved_leg,
    _tick_identity,
    score_target,
)


PRIMARY_DATA_DIR = PRIMARY_REPO_ROOT / "data"
PRIMARY_RAW_ROOT = PRIMARY_DATA_DIR / "raw" / "thegraph"
PRIMARY_UNIFIED_ROOT = PRIMARY_DATA_DIR / "unified"
PAIR_SUPPORT = PRIMARY_DATA_DIR / "processed/endpoint_candidate_pair_support.parquet"
POOL_CAPITAL = PRIMARY_DATA_DIR / "processed/pool_capital_daily.parquet"
PANEL = REPO_ROOT / "data/processed/entry_day_vehicle_choice_exact.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/entry_day_vehicle_choice.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/entry_day_vehicle_choice_support.jsonl"
LOCK = SHARED_RUNTIME_DIR / "entry-day-vehicle-choice.lock"

START = "20200505"
END = "20260630"
DEFAULT_MIN_ENTRY_VALUE_USD = 100_000.0
MIN_ROUTE_INPUT_USD = 100.0
MIN_OBSERVATIONS = 100
MIN_CLUSTERS = 20
FIXED_EFFECT_COLUMNS = ("day", "token_in", "token_out", "route_scope")
CODE_SOURCES = [
    "scripts/analyze/run_entry_day_vehicle_choice.py",
    "scripts/analyze/run_exact_vehicle_frontier.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/pool_capital_daily.parquet",
    "data/unified/*.parquet",
]


def _path(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


def load_material_entries(
    path: Path,
    *,
    minimum_entry_value_usd: float = DEFAULT_MIN_ENTRY_VALUE_USD,
    start: str = START,
    end: str = END,
) -> pd.DataFrame:
    """Return first primary-vehicle days that clear the material-entry bound."""

    if minimum_entry_value_usd < MIN_ROUTE_INPUT_USD:
        raise ValueError("entry-value bound cannot be below the route-value bound")
    connection = duckdb.connect()
    try:
        entries = connection.execute(
            """
            WITH first_primary AS (
                SELECT
                    CAST(date AS DATE) AS entry_date,
                    lower(src) AS token_in,
                    lower(tgt) AS token_out,
                    primary_choice_route_count::DOUBLE AS entry_primary_routes,
                    native_choice_route_count::DOUBLE AS entry_native_routes,
                    stable_choice_route_count::DOUBLE AS entry_stable_routes,
                    (
                        native_within_20pct_routes
                        + stable_within_20pct_routes
                    )::DOUBLE AS entry_coherent_routes,
                    (
                        native_within_20pct_value_usd
                        + stable_within_20pct_value_usd
                    )::DOUBLE AS entry_coherent_value_usd,
                    row_number() OVER (
                        PARTITION BY lower(src), lower(tgt)
                        ORDER BY date
                    ) AS sequence
                FROM read_parquet(?)
                WHERE primary_choice_route_count > 0
            )
            SELECT
                strftime(entry_date, '%Y%m%d') AS day,
                entry_date,
                token_in,
                token_out,
                token_in || '>' || token_out AS ordered_pair,
                entry_primary_routes,
                entry_native_routes,
                entry_stable_routes,
                entry_stable_routes / entry_primary_routes AS entry_stable_share,
                CASE
                    WHEN entry_stable_routes > entry_native_routes THEN 1.0
                    WHEN entry_native_routes > entry_stable_routes THEN 0.0
                    ELSE NULL
                END AS entry_stable,
                entry_stable_routes = entry_native_routes AS entry_tie,
                (
                    (entry_stable_routes > 0 AND entry_native_routes = 0)
                    OR (entry_native_routes > 0 AND entry_stable_routes = 0)
                ) AS entry_exclusive,
                (
                    entry_stable_routes > 0 AND entry_native_routes > 0
                ) AS entry_mixed,
                entry_coherent_routes,
                entry_coherent_value_usd
            FROM first_primary
            WHERE sequence = 1
              AND entry_date BETWEEN strptime(?, '%Y%m%d') AND strptime(?, '%Y%m%d')
              AND entry_coherent_routes > 0
              AND entry_coherent_value_usd >= ?
              AND token_in NOT IN (?, ?, ?, ?)
              AND token_out NOT IN (?, ?, ?, ?)
            ORDER BY entry_date, token_in, token_out
            """,
            [
                str(path),
                start,
                end,
                float(minimum_entry_value_usd),
                *sorted(QUOTED_VEHICLES),
                *sorted(QUOTED_VEHICLES),
            ],
        ).fetchdf()
    finally:
        connection.close()
    if entries.empty:
        raise ValueError("material-entry cohort is empty")
    if entries.duplicated(["token_in", "token_out"]).any():
        raise ValueError("material-entry cohort contains duplicated endpoint pairs")
    return entries


def entry_route_targets(
    day: str,
    pairs: frozenset[tuple[str, str]],
    *,
    v2_replay: V2ReplayDay,
    tick_events: list[TickReplayEvent],
) -> tuple[list[RouteTarget], Counter]:
    """Resolve exact-venue routes only for the selected entry pairs."""

    path = PRIMARY_UNIFIED_ROOT / f"{day}.parquet"
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
    route_pairs = pd.Series(
        list(zip(routes["src"].astype(str).str.lower(), routes["tgt"].astype(str).str.lower(), strict=True)),
        index=routes.index,
    )
    routes = routes[route_pairs.isin(pairs)].copy()
    reasons["selected_pair_routes"] = len(routes)
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
                token_in=str(row.src).lower(),
                token_out=str(row.tgt).lower(),
                vehicle=str(row.vehicle).lower(),
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
    reasons["mapped_selected_pair_routes"] = len(out)
    return out, reasons


def score_entry_day(
    day: str,
    entries: pd.DataFrame,
    replay: TickReplayState,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Score material entry-day routes and advance replay through day close."""

    tick_events = (
        load_tick_day_events(
            None,
            day,
            venues=("uniswap_v3",),
            raw_root=PRIMARY_RAW_ROOT,
        )
        if day >= TICK_START
        else []
    )
    v2_replay = load_v2_replay_day(None, day, raw_root=PRIMARY_RAW_ROOT)
    pairs = frozenset(
        zip(entries["token_in"].astype(str), entries["token_out"].astype(str), strict=True)
    )
    targets, reasons = entry_route_targets(
        day,
        pairs,
        v2_replay=v2_replay,
        tick_events=tick_events,
    )
    entry_lookup = entries.set_index(["token_in", "token_out"]).to_dict("index")
    by_order: dict[tuple[int, int], list[RouteTarget]] = defaultdict(list)
    for target in targets:
        if (
            target.route.vehicle not in QUOTED_VEHICLES
            or target.input_usd < MIN_ROUTE_INPUT_USD
            or not target.within_20pct
        ):
            reasons["outside_route_support"] += 1
            continue
        by_order[target.order].append(target)
    reasons["economic_targets"] = sum(map(len, by_order.values()))
    reasons["economic_targets_stable_chosen"] = sum(
        target.route.vehicle in QUOTED_STABLES
        for targets_at_order in by_order.values()
        for target in targets_at_order
    )
    reasons["economic_targets_weth_chosen"] = (
        reasons["economic_targets"] - reasons["economic_targets_stable_chosen"]
    )
    event_by_order = {event.order: event for event in tick_events}
    if len(event_by_order) != len(tick_events):
        raise ValueError(f"duplicated V3 chain order on {day}")
    rows: list[dict[str, object]] = []
    for order in sorted(set(by_order) | set(event_by_order)):
        for target in by_order.get(order, []):
            result = score_target(target, replay=replay, v2_replay=v2_replay)
            if result is None:
                reasons["chosen_quote_not_reproduced"] += 1
                continue
            reasons["chosen_quote_reproduced"] += 1
            native_available = bool(
                pd.notna(result["native_public_out"])
                and float(result["native_public_out"]) > 0
            )
            stable_available = bool(
                pd.notna(result["stable_public_out"])
                and float(result["stable_public_out"]) > 0
            )
            reasons["native_path_available"] += int(native_available)
            reasons["stable_path_available"] += int(stable_available)
            reasons["both_paths_available"] += int(
                native_available and stable_available
            )
            chosen_impact_supported = (
                float(result["chosen_max_price_impact"])
                <= QUOTED_LEG_MAX_PRICE_IMPACT
            )
            reasons["chosen_impact_supported"] += int(chosen_impact_supported)
            if not native_available:
                reasons["native_path_unavailable"] += 1
            if not stable_available:
                reasons["stable_path_unavailable"] += 1
            if native_available and stable_available and not chosen_impact_supported:
                reasons["chosen_impact_above_five_percent"] += 1
            if not (
                bool(result["vehicle_families_contestable"])
                and chosen_impact_supported
            ):
                reasons["not_symmetric_common_support"] += 1
                continue
            metadata = entry_lookup[(target.route.token_in, target.route.token_out)]
            rows.append(
                {
                    **result,
                    "entry_date": metadata["entry_date"],
                    "entry_primary_routes": metadata["entry_primary_routes"],
                    "entry_native_routes": metadata["entry_native_routes"],
                    "entry_stable_routes": metadata["entry_stable_routes"],
                    "entry_stable_share": metadata["entry_stable_share"],
                    "entry_coherent_routes": metadata["entry_coherent_routes"],
                    "entry_coherent_value_usd": metadata[
                        "entry_coherent_value_usd"
                    ],
                    "ordered_pair": (
                        f"{target.route.token_in}>{target.route.token_out}"
                    ),
                    "route_scope": ">".join(target.route.venues),
                    "chosen_stable": float(
                        result["chosen_vehicle_type"] == "stable"
                    ),
                }
            )
        event = event_by_order.get(order)
        if event is not None:
            replay.apply(event)
    reasons["exact_contestable_rows"] = len(rows)
    reasons["entry_pairs"] = len(entries)
    return rows, {"day": day, **dict(reasons)}


def run_exact_entry_days(entries: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay the exact-state calendar and score only selected entry days."""

    selected_days = sorted(entries["day"].astype(str).unique())
    replay = TickReplayState()
    by_day = {day: frame.copy() for day, frame in entries.groupby("day", sort=True)}
    first, last = selected_days[0], selected_days[-1]
    replay_start = min(first, TICK_START)
    all_rows: list[dict[str, object]] = []
    support_rows: list[dict[str, object]] = []
    calendar = pd.date_range(
        pd.to_datetime(replay_start, format="%Y%m%d"),
        pd.to_datetime(last, format="%Y%m%d"),
        freq="D",
    )
    started = perf_counter()
    for index, observed in enumerate(calendar, 1):
        day = observed.strftime("%Y%m%d")
        if day < TICK_START:
            if day in by_day:
                rows, support = score_entry_day(day, by_day[day], replay)
                all_rows.extend(rows)
                support_rows.append(support)
                print(
                    f"{day}: pairs={support.get('entry_pairs', 0):,} "
                    f"targets={support.get('economic_targets', 0):,} "
                    f"contestable={support.get('exact_contestable_rows', 0):,}",
                    flush=True,
                )
            continue
        if day in by_day:
            rows, support = score_entry_day(day, by_day[day], replay)
            all_rows.extend(rows)
            support_rows.append(support)
            print(
                f"{day}: pairs={support.get('entry_pairs', 0):,} "
                f"targets={support.get('economic_targets', 0):,} "
                f"contestable={support.get('exact_contestable_rows', 0):,}",
                flush=True,
            )
        else:
            replay.apply_all(
                load_tick_day_events(
                    None,
                    day,
                    venues=("uniswap_v3",),
                    raw_root=PRIMARY_RAW_ROOT,
                )
            )
        if index % 180 == 0:
            elapsed = perf_counter() - started
            print(
                f"replayed through {day}; elapsed={elapsed / 60:.1f} minutes",
                flush=True,
            )
    return pd.DataFrame(all_rows), pd.DataFrame(support_rows)


def attach_entry_capital(panel: pd.DataFrame, capital_path: Path) -> pd.DataFrame:
    """Attach prior-day V2 bottleneck capital and scaled exact-price variables."""

    capital = load_lagged_v2_bridge_capital(panel, capital_path)
    data = attach_v2_bridge_capital(panel, capital)
    data["stable_output_advantage_100bp"] = (
        pd.to_numeric(data["stable_minus_native_bps"], errors="coerce")
        .clip(-MAX_LINEAR_ADVANTAGE_BPS, MAX_LINEAR_ADVANTAGE_BPS)
        / 100.0
    )
    data["stable_v2_capital_share_10pp"] = (
        data["stable_v2_capital_share"] - 0.5
    ) / 0.10
    data["log_input_usd"] = np.log(
        pd.to_numeric(data["input_usd"], errors="coerce")
    )
    return data


def _fit_entry_model(
    frame: pd.DataFrame,
    *,
    model_id: str,
    predictors: tuple[str, ...],
    sample: str,
    outcome: str = "chosen_stable",
    choice_timing: str = "original_pair_entry_day",
    record_type: str = "entry_day_vehicle_choice_regression",
    entry_value_threshold_usd: float | None = None,
) -> pd.DataFrame:
    """Fit one entry-choice column with four absorbed controls."""

    columns = [
        outcome,
        *predictors,
        "log_input_usd",
        "ordered_pair",
        *FIXED_EFFECT_COLUMNS,
    ]
    data = frame.loc[:, columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    regressors = [*predictors, "log_input_usd"]
    if (
        len(data) < MIN_OBSERVATIONS
        or data["ordered_pair"].nunique() < MIN_CLUSTERS
        or data["day"].nunique() < MIN_CLUSTERS
    ):
        raise ValueError(f"entry-choice model {model_id} has insufficient support")
    stacked = data[[outcome, *regressors]]
    fixed_effects = tuple(data[column] for column in FIXED_EFFECT_COLUMNS)
    transformed = absorb_fixed_effects(stacked, *fixed_effects)
    # With more than two absorbed dimensions, the shared covariance helper takes
    # a declared finite-sample degree-of-freedom count.  Summing level counts
    # minus one per dimension is conservative when the partitions are disconnected.
    k_absorbed = sum(data[column].nunique() - 1 for column in FIXED_EFFECT_COLUMNS)
    fit = ols_clustered(
        transformed[outcome],
        transformed[regressors],
        data["ordered_pair"],
        add_constant=False,
        k_absorbed=int(k_absorbed),
        additional_clusters=(data["day"],),
        min_observations=MIN_OBSERVATIONS,
        min_clusters=MIN_CLUSTERS,
    )
    if not np.isfinite(fit.beta).all() or not np.isfinite(fit.standard_errors).all():
        raise ValueError(f"entry-choice model {model_id} is not estimable")
    rows: list[dict[str, object]] = []
    for regressor, coefficient, standard_error, statistic, p_value in zip(
        regressors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": record_type,
                "model_id": model_id,
                "sample": sample,
                "outcome": outcome,
                "regressor": regressor,
                "coefficient": float(coefficient),
                "coefficient_pp": 100.0 * float(coefficient),
                "standard_error": float(standard_error),
                "standard_error_pp": 100.0 * float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "dates": int(data["day"].nunique()),
                "route_scopes": int(data["route_scope"].nunique()),
                "source_tokens": int(data["token_in"].nunique()),
                "destination_tokens": int(data["token_out"].nunique()),
                "ordered_pair_clusters": int(fit.cluster_counts[0]),
                "date_clusters": int(fit.cluster_counts[1]),
                "fixed_effects": (
                    "calendar_date+source_token+destination_token+observed_route_scope"
                ),
                "covariance": "two_way_ordered_pair_calendar_date_cr1",
                "absorbed_degrees_of_freedom": int(fit.absorbed_degrees_of_freedom),
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data[outcome].mean()),
                "minimum_entry_value_usd": float(
                    frame["entry_coherent_value_usd"].min()
                ),
                "entry_value_threshold_usd": (
                    float(entry_value_threshold_usd)
                    if entry_value_threshold_usd is not None
                    else float(frame["entry_coherent_value_usd"].min())
                ),
                "minimum_route_input_usd": MIN_ROUTE_INPUT_USD,
                "maximum_leg_price_impact": QUOTED_LEG_MAX_PRICE_IMPACT,
                "value_agreement_threshold": 0.20,
                "capital_timing": "exact_prior_calendar_day",
                "choice_timing": choice_timing,
                "interpretation": (
                    "descriptive_selection_inside_exact_two_family_opportunity_set"
                ),
            }
        )
    return pd.DataFrame(rows)


def regression_results(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the common-sample three-column ladder and broad price check."""

    complete_capital = panel[panel["both_v2_bridge_capitals_positive"]].copy()
    rows = [
        _fit_entry_model(
            panel,
            model_id="price_only_all_exact_contestable",
            predictors=("stable_output_advantage_100bp",),
            sample="all_exact_contestable_entry_day_routes",
        ),
        _fit_entry_model(
            complete_capital,
            model_id="m1_price_only_common_capital_sample",
            predictors=("stable_output_advantage_100bp",),
            sample="positive_both_family_prior_v2_capital",
        ),
        _fit_entry_model(
            complete_capital,
            model_id="m2_capital_only_common_sample",
            predictors=("stable_v2_capital_share_10pp",),
            sample="positive_both_family_prior_v2_capital",
        ),
        _fit_entry_model(
            complete_capital,
            model_id="m3_price_and_capital_common_sample",
            predictors=(
                "stable_output_advantage_100bp",
                "stable_v2_capital_share_10pp",
            ),
            sample="positive_both_family_prior_v2_capital",
        ),
    ]
    return pd.concat(rows, ignore_index=True, sort=False)


def support_results(
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    day_support: pd.DataFrame,
    *,
    minimum_entry_value_usd: float,
    elapsed_seconds: float,
) -> pd.DataFrame:
    """Summarize cohort attrition and the exact contestable estimation sample."""

    complete = panel[panel["both_v2_bridge_capitals_positive"]]
    return pd.DataFrame(
        [
            {
                "record_type": "entry_day_vehicle_choice_support",
                "sample": "material_entry_cohort",
                "entry_pairs": int(len(entries)),
                "entry_dates": int(entries["day"].nunique()),
                "entry_primary_routes": float(entries["entry_primary_routes"].sum()),
                "entry_coherent_value_usd": float(
                    entries["entry_coherent_value_usd"].sum()
                ),
                "minimum_entry_value_usd": float(minimum_entry_value_usd),
                "minimum_route_input_usd": MIN_ROUTE_INPUT_USD,
                "maximum_leg_price_impact": QUOTED_LEG_MAX_PRICE_IMPACT,
                "value_agreement_threshold": 0.20,
                "weth_or_stable_endpoints_excluded": True,
                "elapsed_seconds": float(elapsed_seconds),
            },
            {
                "record_type": "entry_day_vehicle_choice_support",
                "sample": "exact_contestable_entry_day_routes",
                "routes": int(len(panel)),
                "ordered_pairs": int(panel["ordered_pair"].nunique()),
                "dates": int(panel["day"].nunique()),
                "stable_choice_share": float(panel["chosen_stable"].mean()),
                "entry_pairs_with_exact_contestable_route_share": float(
                    panel["ordered_pair"].nunique() / len(entries)
                ),
                "both_positive_prior_v2_capital_share": float(
                    panel["both_v2_bridge_capitals_positive"].mean()
                ),
                "minimum_entry_value_usd": float(minimum_entry_value_usd),
                "elapsed_seconds": float(elapsed_seconds),
            },
            {
                "record_type": "entry_day_vehicle_choice_support",
                "sample": "positive_both_family_prior_v2_capital",
                "routes": int(len(complete)),
                "ordered_pairs": int(complete["ordered_pair"].nunique()),
                "dates": int(complete["day"].nunique()),
                "stable_choice_share": float(complete["chosen_stable"].mean()),
                "minimum_entry_value_usd": float(minimum_entry_value_usd),
                "elapsed_seconds": float(elapsed_seconds),
            },
            {
                "record_type": "entry_day_vehicle_choice_support",
                "sample": "exact_replay_day_totals",
                "target_days": int(len(day_support)),
                "selected_pair_routes": int(
                    day_support.get("selected_pair_routes", pd.Series(dtype=float))
                    .fillna(0)
                    .sum()
                ),
                "mapped_selected_pair_routes": int(
                    day_support.get(
                        "mapped_selected_pair_routes", pd.Series(dtype=float)
                    )
                    .fillna(0)
                    .sum()
                ),
                "economic_targets": int(
                    day_support.get("economic_targets", pd.Series(dtype=float))
                    .fillna(0)
                    .sum()
                ),
                "exact_contestable_rows": int(
                    day_support.get(
                        "exact_contestable_rows", pd.Series(dtype=float)
                    )
                    .fillna(0)
                    .sum()
                ),
                "minimum_entry_value_usd": float(minimum_entry_value_usd),
                "elapsed_seconds": float(elapsed_seconds),
            },
        ]
    )


def run(
    *,
    root: Path = REPO_ROOT,
    pair_support_path: Path = PAIR_SUPPORT,
    pool_capital_path: Path = POOL_CAPITAL,
    panel_path: Path = PANEL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
    minimum_entry_value_usd: float = DEFAULT_MIN_ENTRY_VALUE_USD,
    start: str = START,
    end: str = END,
    maximum_target_days: int | None = None,
    targets_only: bool = False,
    score_only: bool = False,
    estimate_only: bool = False,
) -> int:
    if sum((targets_only, score_only, estimate_only)) > 1:
        raise ValueError(
            "targets-only, score-only, and estimate-only are mutually exclusive"
        )
    pair_support_path = _path(pair_support_path, root)
    pool_capital_path = _path(pool_capital_path, root)
    panel_path = _path(panel_path, root)
    output_path = _path(output_path, root)
    support_path = _path(support_path, root)
    entries = load_material_entries(
        pair_support_path,
        minimum_entry_value_usd=minimum_entry_value_usd,
        start=start,
        end=end,
    )
    if maximum_target_days is not None:
        if maximum_target_days < 1:
            raise ValueError("maximum target days must be positive")
        retained_days = sorted(entries["day"].unique())[:maximum_target_days]
        entries = entries[entries["day"].isin(retained_days)].copy()
    print(
        f"material-entry cohort: {len(entries):,} pairs over "
        f"{entries['day'].nunique():,} dates",
        flush=True,
    )
    if targets_only:
        return 0
    started = perf_counter()
    if estimate_only:
        if not panel_path.is_file():
            raise FileNotFoundError(f"entry-choice panel is missing: {panel_path}")
        exact_panel = pd.read_parquet(panel_path)
        day_support = pd.DataFrame()
    else:
        exact_panel, day_support = run_exact_entry_days(entries)
        if score_only:
            elapsed = perf_counter() - started
            print(
                f"score-only result: {len(exact_panel):,} routes, "
                f"{exact_panel.get('ordered_pair', pd.Series(dtype=str)).nunique():,} pairs, "
                f"{exact_panel.get('day', pd.Series(dtype=str)).nunique():,} dates, "
                f"{elapsed:.1f} seconds",
                flush=True,
            )
            print(day_support.to_string(index=False), flush=True)
            return 0
        if exact_panel.empty:
            raise ValueError("material entry cohort has no exact contestable routes")
        exact_panel = exact_panel.sort_values(
            ["day", "ordered_pair", "route_id"], kind="stable"
        ).reset_index(drop=True)
    panel = attach_entry_capital(exact_panel, pool_capital_path)
    results = regression_results(panel)
    elapsed = perf_counter() - started
    support = support_results(
        entries,
        panel,
        day_support,
        minimum_entry_value_usd=minimum_entry_value_usd,
        elapsed_seconds=elapsed,
    )
    if not estimate_only:
        write_panel(
            exact_panel,
            panel_path,
            code_sources=CODE_SOURCES,
        )
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(results.to_string(index=False), flush=True)
    print(support.to_string(index=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--panel", type=Path, default=PANEL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument(
        "--minimum-entry-value-usd",
        type=float,
        default=DEFAULT_MIN_ENTRY_VALUE_USD,
    )
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--maximum-target-days", type=int)
    parser.add_argument("--targets-only", action="store_true")
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="time exact replay without writing canonical panel or estimates",
    )
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    return run(
        pair_support_path=args.pair_support,
        pool_capital_path=args.pool_capital,
        panel_path=args.panel,
        output_path=args.output,
        support_path=args.support,
        minimum_entry_value_usd=args.minimum_entry_value_usd,
        start=args.start.replace("-", ""),
        end=args.end.replace("-", ""),
        maximum_target_days=args.maximum_target_days,
        targets_only=args.targets_only,
        score_only=args.score_only,
        estimate_only=args.estimate_only,
    )


if __name__ == "__main__":
    with exclusive_job(LOCK, job="entry-day vehicle choice"):
        raise SystemExit(main())
