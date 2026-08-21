#!/usr/bin/env python3
"""Follow vehicle choice when the exact-output price ranking changes.

The monthly exact-price panel quotes the best public WETH route and the best
public DAI, USDC, or USDT route at each observed input amount. This analysis
collapses those quotes to an ordered endpoint-pair and month. The pair-month
price ranking is the median stable-minus-WETH exact-output gap, and the route
share is the fraction of common-support routes that use a stablecoin.

An event occurs in month zero when the prior month put one vehicle family at
least one basis point ahead and the current month puts the other family at
least one basis point ahead. Event dating uses only the prior and current
quote panels. The primary material sample requires at least two quotes and at
least $1,000 of observed input value in both crossing months. The unrestricted
sample is retained as a sensitivity check.

Weak-leg capital is the V2/Sushi V2 bottleneck measure already used by the
contestable-choice analysis. It is observed on the prior calendar day of the
crossing month. The estimates ask separately whether capital changes the
immediate route-share response and whether it predicts that the new price
ranking lasts through the next monthly observation.

Reads
    data/processed/exact_vehicle_frontier_monthly.parquet
    data/processed/pool_capital_daily.parquet
Writes
    output/exhibits/price_rank_crossing.jsonl
    output/exhibits/price_rank_crossing_support.jsonl
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit
from scripts.analyze.run_contestable_vehicle_choice import (
    FRONTIER_COLUMNS,
    attach_v2_bridge_capital,
    load_lagged_v2_bridge_capital,
    prepare_frontier,
)


FRONTIER = DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
POOL_CAPITAL = DATA_DIR / "processed/pool_capital_daily.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/price_rank_crossing.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/price_rank_crossing_support.jsonl"
LOCK = SHARED_RUNTIME_DIR / "price-rank-crossing.lock"

PRICE_LEAD_THRESHOLD_BPS = 1.0
PRIMARY_MIN_ROUTES = 2
PRIMARY_MIN_INPUT_USD = 1_000.0
EVENT_TIMES = tuple(range(-3, 4))
MAX_GAP_BPS_FOR_CONTROLS = 1_000.0
CAPITAL_SPLIT = 0.50
CODE_SOURCES = [
    "scripts/analyze/run_price_rank_crossing.py",
    "scripts/analyze/run_contestable_vehicle_choice.py",
]
INPUTS = [
    "data/processed/exact_vehicle_frontier_monthly.parquet",
    "data/processed/pool_capital_daily.parquet",
]


def _path(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


def build_pair_month_panel(routes: pd.DataFrame) -> pd.DataFrame:
    """Collapse common-support exact quotes to ordered-pair months."""

    required = {
        "ordered_pair",
        "day",
        "date",
        "route_id",
        "token_in",
        "token_out",
        "chosen_stable",
        "stable_minus_native_bps",
        "input_usd",
        "symmetric_common_support",
        "stable_v2_capital_share",
    }
    missing = sorted(required - set(routes.columns))
    if missing:
        raise ValueError(f"contestable route panel lacks crossing fields: {missing}")
    data = routes[routes["symmetric_common_support"].astype(bool)].copy()
    if data.empty:
        raise ValueError("price-rank crossing sample has no common-support routes")
    data["chosen_stable"] = data["chosen_stable"].astype(float)
    for column in (
        "stable_minus_native_bps",
        "input_usd",
        "stable_v2_capital_share",
    ):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["stable_minus_native_bps", "input_usd"]
    )
    monthly = (
        data.groupby(
            ["ordered_pair", "day", "date", "token_in", "token_out"],
            as_index=False,
            sort=True,
        )
        .agg(
            route_count=("route_id", "size"),
            observed_input_usd=("input_usd", "sum"),
            stable_route_share=("chosen_stable", "mean"),
            median_stable_minus_native_bps=(
                "stable_minus_native_bps",
                "median",
            ),
            event_eve_stable_v2_capital_share=(
                "stable_v2_capital_share",
                "median",
            ),
            capital_quote_count=("stable_v2_capital_share", "count"),
        )
        .sort_values(["ordered_pair", "date"], kind="stable")
        .reset_index(drop=True)
    )
    if monthly.duplicated(["ordered_pair", "day"]).any():
        raise ValueError("pair-month exact-price panel is not unique")
    monthly["month_index"] = (
        monthly["date"].dt.year * 12 + monthly["date"].dt.month
    ).astype(int)
    gap = monthly["median_stable_minus_native_bps"]
    monthly["price_state"] = np.select(
        [
            gap.ge(PRICE_LEAD_THRESHOLD_BPS),
            gap.le(-PRICE_LEAD_THRESHOLD_BPS),
        ],
        [1, -1],
        default=0,
    ).astype(int)
    return monthly


def identify_crossings(
    monthly: pd.DataFrame,
    *,
    minimum_routes: int,
    minimum_input_usd: float,
    sample: str,
) -> pd.DataFrame:
    """Date consecutive-month price-rank changes without future confirmation."""

    required = {
        "ordered_pair",
        "day",
        "date",
        "month_index",
        "price_state",
        "route_count",
        "observed_input_usd",
        "stable_route_share",
        "median_stable_minus_native_bps",
        "event_eve_stable_v2_capital_share",
    }
    missing = sorted(required - set(monthly.columns))
    if missing:
        raise ValueError(f"pair-month panel lacks crossing fields: {missing}")
    ordered = monthly.sort_values(
        ["ordered_pair", "month_index"], kind="stable"
    ).reset_index(drop=True)
    previous = (
        ordered.groupby("ordered_pair", sort=False)
        .shift(1)
        .add_prefix("previous_")
    )
    data = pd.concat([ordered, previous], axis=1)
    consecutive = data["month_index"].sub(data["previous_month_index"]).eq(1)
    material = (
        data["route_count"].ge(minimum_routes)
        & data["previous_route_count"].ge(minimum_routes)
        & data["observed_input_usd"].ge(minimum_input_usd)
        & data["previous_observed_input_usd"].ge(minimum_input_usd)
    )
    stable_crossing = (
        consecutive
        & material
        & data["previous_price_state"].eq(-1)
        & data["price_state"].eq(1)
    )
    native_crossing = (
        consecutive
        & material
        & data["previous_price_state"].eq(1)
        & data["price_state"].eq(-1)
    )
    events = data[stable_crossing | native_crossing].copy()
    if events.empty:
        raise ValueError(f"price-rank crossing sample {sample} is empty")
    events["direction"] = np.where(
        stable_crossing.loc[events.index],
        "stable_challenger",
        "native_challenger",
    )
    events["stable_challenger"] = events["direction"].eq(
        "stable_challenger"
    ).astype(float)
    events["event_id"] = events["ordered_pair"].astype(str) + ":" + events[
        "day"
    ].astype(str)
    if events["event_id"].duplicated().any():
        raise ValueError("price-rank crossing event ids are duplicated")
    events["event_month"] = events["day"].astype(str)
    events["event_eve_challenger_v2_capital_share"] = np.where(
        events["direction"].eq("stable_challenger"),
        events["event_eve_stable_v2_capital_share"],
        1.0 - events["event_eve_stable_v2_capital_share"],
    )
    events["challenger_capital_share_10pp"] = (
        events["event_eve_challenger_v2_capital_share"] - CAPITAL_SPLIT
    ) / 0.10
    events["capital_group"] = np.select(
        [
            events["event_eve_challenger_v2_capital_share"].lt(CAPITAL_SPLIT),
            events["event_eve_challenger_v2_capital_share"].ge(CAPITAL_SPLIT),
        ],
        ["challenger_capital_below_half", "challenger_capital_at_least_half"],
        default="capital_unavailable",
    )
    stable_challenger = events["direction"].eq("stable_challenger")
    events["prior_incumbent_route_share"] = np.where(
        stable_challenger,
        1.0 - events["previous_stable_route_share"],
        events["previous_stable_route_share"],
    )
    events["current_incumbent_route_share"] = np.where(
        stable_challenger,
        1.0 - events["stable_route_share"],
        events["stable_route_share"],
    )
    events["incumbent_route_share_change"] = (
        events["current_incumbent_route_share"]
        - events["prior_incumbent_route_share"]
    )
    events["prior_incumbent_route_share_centered"] = (
        events["prior_incumbent_route_share"] - 0.5
    )
    events["crossing_gap_100bp"] = np.minimum(
        events["median_stable_minus_native_bps"].abs(),
        MAX_GAP_BPS_FOR_CONTROLS,
    ) / 100.0
    events["prior_gap_100bp"] = np.minimum(
        events["previous_median_stable_minus_native_bps"].abs(),
        MAX_GAP_BPS_FOR_CONTROLS,
    ) / 100.0
    events["log_crossing_window_routes"] = np.log1p(
        events["route_count"] + events["previous_route_count"]
    )
    events["sample"] = sample
    events["minimum_pair_month_routes"] = int(minimum_routes)
    events["minimum_pair_month_input_usd"] = float(minimum_input_usd)
    events["event_selection_uses_future_information"] = False
    keep = [
        "event_id",
        "sample",
        "ordered_pair",
        "token_in",
        "token_out",
        "day",
        "date",
        "month_index",
        "event_month",
        "direction",
        "stable_challenger",
        "route_count",
        "previous_route_count",
        "observed_input_usd",
        "previous_observed_input_usd",
        "median_stable_minus_native_bps",
        "previous_median_stable_minus_native_bps",
        "event_eve_challenger_v2_capital_share",
        "challenger_capital_share_10pp",
        "capital_group",
        "prior_incumbent_route_share",
        "current_incumbent_route_share",
        "incumbent_route_share_change",
        "prior_incumbent_route_share_centered",
        "crossing_gap_100bp",
        "prior_gap_100bp",
        "log_crossing_window_routes",
        "minimum_pair_month_routes",
        "minimum_pair_month_input_usd",
        "event_selection_uses_future_information",
    ]
    return events.loc[:, keep].reset_index(drop=True)


def build_event_panel(monthly: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Stack available pair-months from event time -3 through +3."""

    request = events[
        [
            "event_id",
            "sample",
            "ordered_pair",
            "month_index",
            "direction",
            "stable_challenger",
            "capital_group",
            "event_eve_challenger_v2_capital_share",
        ]
    ].copy()
    request = request.merge(
        pd.DataFrame({"event_time": EVENT_TIMES}), how="cross"
    )
    request["requested_month_index"] = (
        request["month_index"] + request["event_time"]
    )
    lookup = monthly[
        [
            "ordered_pair",
            "month_index",
            "day",
            "stable_route_share",
            "median_stable_minus_native_bps",
            "route_count",
        ]
    ].rename(columns={"month_index": "requested_month_index"})
    panel = request.merge(
        lookup,
        on=["ordered_pair", "requested_month_index"],
        how="left",
        validate="many_to_one",
    )
    panel["observed"] = panel["day"].notna()
    balanced = (
        panel.groupby("event_id")["observed"]
        .sum()
        .eq(len(EVENT_TIMES))
        .rename("balanced_seven_month_window")
    )
    panel = panel.merge(balanced, on="event_id", validate="many_to_one")
    panel = panel[panel["observed"]].copy()
    stable_challenger = panel["direction"].eq("stable_challenger")
    panel["incumbent_route_share"] = np.where(
        stable_challenger,
        1.0 - panel["stable_route_share"],
        panel["stable_route_share"],
    )
    panel["challenger_price_gap_bps"] = np.where(
        stable_challenger,
        panel["median_stable_minus_native_bps"],
        -panel["median_stable_minus_native_bps"],
    )
    panel["challenger_is_price_leader"] = panel[
        "challenger_price_gap_bps"
    ].ge(PRICE_LEAD_THRESHOLD_BPS)
    panel["incumbent_is_price_leader"] = panel[
        "challenger_price_gap_bps"
    ].le(-PRICE_LEAD_THRESHOLD_BPS)
    return panel.reset_index(drop=True)


def _clustered_mean(values: pd.Series, clusters: pd.Series) -> tuple[float, float]:
    data = pd.DataFrame({"value": values, "cluster": clusters}).dropna()
    if data.empty:
        return np.nan, np.nan
    mean = float(data["value"].mean())
    group_sums = (data["value"] - mean).groupby(data["cluster"]).sum()
    group_count = len(group_sums)
    if group_count < 2:
        return mean, np.nan
    variance = (
        group_count
        / (group_count - 1)
        * float(np.square(group_sums).sum())
        / float(len(data) ** 2)
    )
    return mean, float(np.sqrt(max(variance, 0.0)))


def event_time_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize normalized incumbent share over the event window."""

    rows: list[dict[str, object]] = []
    samples = (
        (
            "material_balanced_seven_month",
            panel[panel["balanced_seven_month_window"]],
        ),
        ("material_all_available_months", panel),
    )
    for sample, sample_frame in samples:
        dimensions = (
            ("all_crossings", sample_frame),
            (
                "stable_challenger",
                sample_frame[sample_frame["direction"].eq("stable_challenger")],
            ),
            (
                "native_challenger",
                sample_frame[sample_frame["direction"].eq("native_challenger")],
            ),
        )
        for dimension, frame in dimensions:
            for event_time, cell in frame.groupby("event_time", sort=True):
                mean, standard_error = _clustered_mean(
                    cell["incumbent_route_share"], cell["ordered_pair"]
                )
                rows.append(
                    {
                        "record_type": "price_rank_crossing_event_time",
                        "sample": sample,
                        "dimension": dimension,
                        "event_time_month": int(event_time),
                        "mean_incumbent_route_share": mean,
                        "mean_incumbent_route_share_pp": 100.0 * mean,
                        "standard_error": standard_error,
                        "standard_error_pp": 100.0 * standard_error,
                        "events": int(cell["event_id"].nunique()),
                        "ordered_pairs": int(cell["ordered_pair"].nunique()),
                        "calendar_months": int(cell["day"].nunique()),
                        "weighting": "equal_event",
                        "covariance": "ordered_pair_cluster_cr1",
                    }
                )
    return pd.DataFrame(rows)


CONTROL_PREDICTORS = (
    "stable_challenger",
    "crossing_gap_100bp",
    "prior_gap_100bp",
    "prior_incumbent_route_share_centered",
    "log_crossing_window_routes",
)


def _fit_date_fe_model(
    frame: pd.DataFrame,
    *,
    model_id: str,
    outcome: str,
    predictors: tuple[str, ...],
    sample: str,
) -> pd.DataFrame:
    columns = [outcome, *predictors, "event_id", "ordered_pair", "event_month"]
    data = frame.loc[:, columns].replace([np.inf, -np.inf], np.nan).dropna()
    if (
        len(data) < 50
        or data["ordered_pair"].nunique() < 10
        or data["event_month"].nunique() < 10
    ):
        raise ValueError(f"price-rank model {model_id} has insufficient support")
    transformed = absorb_fixed_effects(
        data[[outcome, *predictors]], data["event_month"]
    )
    fit = ols_clustered(
        transformed[outcome],
        transformed[list(predictors)],
        data["ordered_pair"],
        add_constant=False,
        absorbed_groups=(data["event_month"],),
        additional_clusters=(data["event_month"],),
        min_observations=50,
        min_clusters=10,
    )
    rows = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "record_type": "price_rank_crossing_regression",
                "model_id": model_id,
                "sample": sample,
                "outcome": outcome,
                "regressor": predictor,
                "coefficient": float(coefficient),
                "coefficient_pp": 100.0 * float(coefficient),
                "standard_error": float(standard_error),
                "standard_error_pp": 100.0 * float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "events": int(data["event_id"].nunique()),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "calendar_months": int(data["event_month"].nunique()),
                "fixed_effects": "crossing_calendar_month",
                "covariance": "two_way_ordered_pair_calendar_month_cr1",
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data[outcome].mean()),
                "inference_status": "descriptive_association",
            }
        )
    return pd.DataFrame(rows)


def attach_next_month_outcome(
    events: pd.DataFrame, event_panel: pd.DataFrame
) -> pd.DataFrame:
    """Attach next-month rank persistence and normalized route share."""

    next_month = event_panel[event_panel["event_time"].eq(1)][
        [
            "event_id",
            "challenger_is_price_leader",
            "incumbent_is_price_leader",
            "incumbent_route_share",
            "challenger_price_gap_bps",
        ]
    ].rename(
        columns={
            "challenger_is_price_leader": "challenger_leads_next_month",
            "incumbent_is_price_leader": "incumbent_leads_next_month",
            "incumbent_route_share": "incumbent_route_share_next_month",
            "challenger_price_gap_bps": "challenger_gap_next_month_bps",
        }
    )
    return events.merge(next_month, on="event_id", how="inner", validate="one_to_one")


def follow_up_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Show route share when the new price rank lasts or reverses."""

    category = np.select(
        [
            frame["challenger_leads_next_month"].astype(bool),
            frame["incumbent_leads_next_month"].astype(bool),
        ],
        ["challenger_still_ahead", "incumbent_ahead_again"],
        default="within_one_basis_point",
    )
    data = frame.assign(follow_up_rank=category)
    rows = []
    for rank, cell in data.groupby("follow_up_rank", sort=True):
        mean, standard_error = _clustered_mean(
            cell["incumbent_route_share_next_month"], cell["ordered_pair"]
        )
        rows.append(
            {
                "record_type": "price_rank_crossing_follow_up",
                "sample": "material_crossings_with_next_month",
                "follow_up_rank": rank,
                "events": int(len(cell)),
                "ordered_pairs": int(cell["ordered_pair"].nunique()),
                "event_share": float(len(cell) / len(data)),
                "mean_incumbent_route_share": mean,
                "mean_incumbent_route_share_pp": 100.0 * mean,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
                "weighting": "equal_event",
                "covariance": "ordered_pair_cluster_cr1",
            }
        )
    return pd.DataFrame(rows)


def transition_cell_rows(events: pd.DataFrame) -> pd.DataFrame:
    """Report direction-by-capital cells without pooling level differences."""

    data = events[events["capital_group"].ne("capital_unavailable")].copy()
    rows = []
    for (direction, capital_group), cell in data.groupby(
        ["direction", "capital_group"], sort=True
    ):
        mean, standard_error = _clustered_mean(
            cell["incumbent_route_share_change"], cell["ordered_pair"]
        )
        rows.append(
            {
                "record_type": "price_rank_crossing_transition_cell",
                "sample": "material_crossings",
                "direction": direction,
                "capital_group": capital_group,
                "events": int(len(cell)),
                "ordered_pairs": int(cell["ordered_pair"].nunique()),
                "mean_challenger_capital_share": float(
                    cell["event_eve_challenger_v2_capital_share"].mean()
                ),
                "mean_incumbent_route_share_change": mean,
                "mean_incumbent_route_share_change_pp": 100.0 * mean,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
                "weighting": "equal_event",
                "covariance": "ordered_pair_cluster_cr1",
            }
        )
    return pd.DataFrame(rows)


def placebo_rows(
    events: pd.DataFrame, event_panel: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare the month -1 to 0 change with the month -3 to -2 change."""

    shares = event_panel.pivot(
        index="event_id", columns="event_time", values="incumbent_route_share"
    )
    complete_ids = shares.dropna(subset=[-3, -2, -1, 0]).index
    complete = events[events["event_id"].isin(complete_ids)].copy()
    transitions = []
    for row in complete.itertuples(index=False):
        transitions.extend(
            [
                {
                    "event_id": row.event_id,
                    "ordered_pair": row.ordered_pair,
                    "actual_crossing": 1.0,
                    "route_share_change": float(
                        shares.loc[row.event_id, 0] - shares.loc[row.event_id, -1]
                    ),
                    "challenger_capital_share_10pp": row.challenger_capital_share_10pp,
                    "stable_challenger_centered": row.stable_challenger - 0.5,
                },
                {
                    "event_id": row.event_id,
                    "ordered_pair": row.ordered_pair,
                    "actual_crossing": 0.0,
                    "route_share_change": float(
                        shares.loc[row.event_id, -2] - shares.loc[row.event_id, -3]
                    ),
                    "challenger_capital_share_10pp": row.challenger_capital_share_10pp,
                    "stable_challenger_centered": row.stable_challenger - 0.5,
                },
            ]
        )
    stack = pd.DataFrame(transitions)
    stack["actual_x_challenger_capital_share_10pp"] = (
        stack["actual_crossing"] * stack["challenger_capital_share_10pp"]
    )
    stack["actual_x_stable_challenger_centered"] = (
        stack["actual_crossing"] * stack["stable_challenger_centered"]
    )
    predictors = (
        "actual_crossing",
        "actual_x_challenger_capital_share_10pp",
        "actual_x_stable_challenger_centered",
    )
    columns = [
        "route_share_change",
        *predictors,
        "event_id",
        "ordered_pair",
    ]
    data = stack.loc[:, columns].replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 50 or data["ordered_pair"].nunique() < 10:
        raise ValueError("price-rank placebo comparison has insufficient support")
    transformed = absorb_fixed_effects(
        data[["route_share_change", *predictors]], data["event_id"]
    )
    fit = ols_clustered(
        transformed["route_share_change"],
        transformed[list(predictors)],
        data["ordered_pair"],
        add_constant=False,
        absorbed_groups=(data["event_id"],),
        min_observations=50,
        min_clusters=10,
    )
    model_rows = []
    for predictor, coefficient, standard_error, statistic, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        model_rows.append(
            {
                "record_type": "price_rank_crossing_regression",
                "model_id": "actual_crossing_vs_pre_event_placebo",
                "sample": "material_crossings_with_months_minus3_to_zero",
                "outcome": "route_share_change",
                "regressor": predictor,
                "coefficient": float(coefficient),
                "coefficient_pp": 100.0 * float(coefficient),
                "standard_error": float(standard_error),
                "standard_error_pp": 100.0 * float(standard_error),
                "t_statistic": float(statistic),
                "p_value": float(p_value),
                "observations": int(fit.n_observations),
                "events": int(data["event_id"].nunique()),
                "ordered_pairs": int(data["ordered_pair"].nunique()),
                "calendar_months": np.nan,
                "fixed_effects": "crossing_event",
                "covariance": "ordered_pair_cluster_cr1",
                "within_r_squared": float(fit.r_squared),
                "dependent_mean": float(data["route_share_change"].mean()),
                "inference_status": "descriptive_association",
            }
        )
    summary = []
    for actual, cell in data.groupby("actual_crossing"):
        mean, standard_error = _clustered_mean(
            cell["route_share_change"], cell["ordered_pair"]
        )
        summary.append(
            {
                "record_type": "price_rank_crossing_placebo_summary",
                "sample": "material_crossings_with_months_minus3_to_zero",
                "transition": (
                    "actual_minus1_to_zero"
                    if actual
                    else "placebo_minus3_to_minus2"
                ),
                "events": int(cell["event_id"].nunique()),
                "ordered_pairs": int(cell["ordered_pair"].nunique()),
                "mean_route_share_change": mean,
                "mean_route_share_change_pp": 100.0 * mean,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
            }
        )
    return pd.DataFrame(model_rows), pd.DataFrame(summary)


def regression_rows(
    material_events: pd.DataFrame,
    material_panel: pd.DataFrame,
    broad_events: pd.DataFrame,
    broad_panel: pd.DataFrame,
) -> pd.DataFrame:
    """Estimate immediate response, rank durability, and timing comparisons."""

    predictors = ("challenger_capital_share_10pp", *CONTROL_PREDICTORS)
    material_follow_up = attach_next_month_outcome(material_events, material_panel)
    broad_follow_up = attach_next_month_outcome(broad_events, broad_panel)
    rows = [
        _fit_date_fe_model(
            material_events,
            model_id="material_immediate_route_share_change",
            outcome="incumbent_route_share_change",
            predictors=predictors,
            sample="material_crossings",
        ),
        _fit_date_fe_model(
            material_follow_up,
            model_id="material_next_month_price_rank_persistence",
            outcome="challenger_leads_next_month",
            predictors=predictors,
            sample="material_crossings_with_next_month",
        ),
        _fit_date_fe_model(
            broad_follow_up,
            model_id="all_next_month_price_rank_persistence",
            outcome="challenger_leads_next_month",
            predictors=predictors,
            sample="all_crossings_with_next_month",
        ),
    ]
    placebo_model, _ = placebo_rows(material_events, material_panel)
    rows.append(placebo_model)
    return pd.concat(rows, ignore_index=True, sort=False)


def support_rows(
    monthly: pd.DataFrame,
    material_events: pd.DataFrame,
    material_panel: pd.DataFrame,
    broad_events: pd.DataFrame,
    broad_panel: pd.DataFrame,
    *,
    common_support_routes: int,
) -> pd.DataFrame:
    """Record the exact input, event, and runtime perimeter."""

    material_follow = attach_next_month_outcome(material_events, material_panel)
    broad_follow = attach_next_month_outcome(broad_events, broad_panel)
    return pd.DataFrame(
        [
            {
                "record_type": "price_rank_crossing_support",
                "common_support_routes": int(common_support_routes),
                "pair_months": int(len(monthly)),
                "ordered_pairs": int(monthly["ordered_pair"].nunique()),
                "calendar_months": int(monthly["day"].nunique()),
                "first_month": str(monthly["day"].min()),
                "last_month": str(monthly["day"].max()),
                "material_events": int(len(material_events)),
                "material_stable_challenger_events": int(
                    material_events["direction"].eq("stable_challenger").sum()
                ),
                "material_native_challenger_events": int(
                    material_events["direction"].eq("native_challenger").sum()
                ),
                "material_event_pairs": int(
                    material_events["ordered_pair"].nunique()
                ),
                "material_capital_observed_events": int(
                    material_events[
                        "event_eve_challenger_v2_capital_share"
                    ].notna().sum()
                ),
                "material_balanced_seven_month_events": int(
                    material_panel[
                        material_panel["balanced_seven_month_window"]
                    ]["event_id"].nunique()
                ),
                "material_next_month_events": int(len(material_follow)),
                "all_events": int(len(broad_events)),
                "all_event_pairs": int(broad_events["ordered_pair"].nunique()),
                "all_next_month_events": int(len(broad_follow)),
                "price_lead_threshold_bps": PRICE_LEAD_THRESHOLD_BPS,
                "material_minimum_routes_each_crossing_month": PRIMARY_MIN_ROUTES,
                "material_minimum_input_usd_each_crossing_month": (
                    PRIMARY_MIN_INPUT_USD
                ),
                "pair_month_gap_aggregation": (
                    "route_count_median_exact_output_gap_bps"
                ),
                "pair_month_route_share_aggregation": (
                    "equal_common_support_route"
                ),
                "event_time_aggregation": "equal_event",
                "capital_measure": "v2_sushiv2_weak_leg_share",
                "capital_timing": "prior_calendar_day_of_crossing_month",
                "event_selection_uses_future_information": False,
                "frontier_input": INPUTS[0],
                "capital_input": INPUTS[1],
            }
        ]
    )


def run(
    *,
    root: Path = REPO_ROOT,
    frontier_path: Path = FRONTIER,
    pool_capital_path: Path = POOL_CAPITAL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT,
) -> int:
    started = time.perf_counter()
    frontier_path = _path(frontier_path, root)
    pool_capital_path = _path(pool_capital_path, root)
    output_path = _path(output_path, root)
    support_path = _path(support_path, root)
    for path in (frontier_path, pool_capital_path):
        if not path.is_file():
            raise FileNotFoundError(f"price-rank crossing input is missing: {path}")
    raw = pd.read_parquet(frontier_path, columns=list(FRONTIER_COLUMNS))
    frontier, _ = prepare_frontier(raw)
    common = frontier[frontier["symmetric_common_support"]].copy()
    capital = load_lagged_v2_bridge_capital(common, pool_capital_path)
    routes = attach_v2_bridge_capital(common, capital)
    monthly = build_pair_month_panel(routes)
    material_events = identify_crossings(
        monthly,
        minimum_routes=PRIMARY_MIN_ROUTES,
        minimum_input_usd=PRIMARY_MIN_INPUT_USD,
        sample="material_crossings",
    )
    broad_events = identify_crossings(
        monthly,
        minimum_routes=1,
        minimum_input_usd=0.0,
        sample="all_crossings",
    )
    material_panel = build_event_panel(monthly, material_events)
    broad_panel = build_event_panel(monthly, broad_events)
    regressions = regression_rows(
        material_events,
        material_panel,
        broad_events,
        broad_panel,
    )
    material_follow = attach_next_month_outcome(material_events, material_panel)
    _, placebo_summary = placebo_rows(material_events, material_panel)
    results = pd.concat(
        [
            event_time_rows(material_panel),
            transition_cell_rows(material_events),
            follow_up_summary(material_follow),
            placebo_summary,
            regressions,
        ],
        ignore_index=True,
        sort=False,
    )
    runtime_seconds = time.perf_counter() - started
    support = support_rows(
        monthly,
        material_events,
        material_panel,
        broad_events,
        broad_panel,
        common_support_routes=len(common),
    )
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(
        f"wrote {len(results):,} result rows for {len(material_events):,} "
        f"material crossings in {runtime_seconds:.1f} seconds"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--pool-capital", type=Path, default=POOL_CAPITAL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    arguments = parser.parse_args()
    return run(
        frontier_path=arguments.frontier,
        pool_capital_path=arguments.pool_capital,
        output_path=arguments.output,
        support_path=arguments.support,
    )


if __name__ == "__main__":
    with exclusive_job(LOCK, job="price-rank crossing"):
        raise SystemExit(main())
