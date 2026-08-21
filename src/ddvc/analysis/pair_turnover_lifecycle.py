"""Split one-window pair contributions by their observed panel history."""

from __future__ import annotations

import numpy as np
import pandas as pd


PAIR_KEYS = ("src", "tgt")
BASELINE_EXCLUSIVE = "baseline_exclusive"
COMPARISON_EXCLUSIVE = "comparison_exclusive"
EXCLUSIVE_STATUSES = (BASELINE_EXCLUSIVE, COMPARISON_EXCLUSIVE)

DETAIL_GROUPS = {
    "first_endpoint_pair_observed_between_windows": (
        "first_endpoint_pair_observed_after_baseline_window"
    ),
    "first_endpoint_pair_observed_in_comparison_window": (
        "first_endpoint_pair_observed_after_baseline_window"
    ),
    "vehicle_role_activated_in_continuing_endpoint_pair": (
        "vehicle_role_turnover_in_continuing_endpoint_pairs"
    ),
    "endpoint_pair_reactivated": "endpoint_pair_reactivated",
    "vehicle_role_lapsed_in_continuing_endpoint_pair": (
        "vehicle_role_turnover_in_continuing_endpoint_pairs"
    ),
    "endpoint_pair_last_observed_by_baseline_window_end": (
        "endpoint_pair_last_observed_before_comparison_window"
    ),
    "endpoint_pair_last_observed_between_windows": (
        "endpoint_pair_last_observed_before_comparison_window"
    ),
}
SUPPORT_GROUPS = {
    COMPARISON_EXCLUSIVE: "newly_active_in_comparison_window",
    BASELINE_EXCLUSIVE: "absent_in_comparison_window",
}

REQUIRED_CONTRIBUTION_COLUMNS = {
    "metric",
    "source_column",
    "reporting_scope",
    "baseline_year",
    "comparison_year",
    *PAIR_KEYS,
    "support_status",
    "contribution_share",
    "denominator_baseline",
    "denominator_comparison",
    "stable_baseline",
    "stable_comparison",
}
REQUIRED_HISTORY_COLUMNS = {
    "metric",
    "source_column",
    *PAIR_KEYS,
    "first_observed_date",
    "last_observed_date",
    "positive_days",
    "baseline_market_route_count",
    "comparison_market_route_count",
}


def _validate_inputs(
    contributions: pd.DataFrame,
    histories: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    missing = sorted(REQUIRED_CONTRIBUTION_COLUMNS - set(contributions.columns))
    if missing:
        raise ValueError("pair contributions lack columns: " + ", ".join(missing))
    missing = sorted(REQUIRED_HISTORY_COLUMNS - set(histories.columns))
    if missing:
        raise ValueError("pair histories lack columns: " + ", ".join(missing))

    ledger = contributions.copy()
    if set(ledger["reporting_scope"].unique()) != {"pooled"}:
        raise ValueError("pair lifecycle split requires pooled contributions only")
    if not ledger["support_status"].isin(EXCLUSIVE_STATUSES).all():
        raise ValueError("pair lifecycle split received a common-pair contribution")
    if ledger.duplicated(["metric", *PAIR_KEYS]).any():
        raise ValueError("pair lifecycle split contains duplicate metric-pair rows")
    years = ledger[["baseline_year", "comparison_year"]].drop_duplicates()
    if len(years) != 1:
        raise ValueError("pair lifecycle split requires one comparison")
    baseline_year, comparison_year = map(int, years.iloc[0])
    if comparison_year <= baseline_year:
        raise ValueError("pair lifecycle comparison years are not ordered")
    for column in (
        "contribution_share",
        "denominator_baseline",
        "denominator_comparison",
        "stable_baseline",
        "stable_comparison",
    ):
        ledger[column] = pd.to_numeric(ledger[column], errors="raise")
        if not np.isfinite(ledger[column]).all():
            raise ValueError(f"pair lifecycle split contains nonfinite {column}")

    history = histories.copy()
    if history.duplicated(["metric", *PAIR_KEYS]).any():
        raise ValueError("pair histories contain duplicate metric-pair rows")
    for column in ("first_observed_date", "last_observed_date"):
        history[column] = pd.to_datetime(history[column], errors="raise").dt.normalize()
    history["positive_days"] = pd.to_numeric(
        history["positive_days"], errors="raise"
    ).astype(int)
    for column in ("baseline_market_route_count", "comparison_market_route_count"):
        history[column] = pd.to_numeric(history[column], errors="raise")
        if not np.isfinite(history[column]).all() or history[column].lt(0).any():
            raise ValueError(f"pair histories contain invalid {column}")
    if history[["first_observed_date", "last_observed_date"]].isna().any().any():
        raise ValueError("pair histories contain a missing observation boundary")
    if (history["last_observed_date"] < history["first_observed_date"]).any():
        raise ValueError("pair histories end before they begin")
    if history["positive_days"].le(0).any():
        raise ValueError("pair histories require at least one positive day")
    return ledger, history, baseline_year, comparison_year


def _aggregate(
    classified: pd.DataFrame,
    *,
    aggregation_level: str,
    category_column: str,
) -> pd.DataFrame:
    result = (
        classified.groupby(
            ["metric", "source_column", category_column],
            as_index=False,
            sort=False,
        )
        .agg(
            pair_count=("src", "size"),
            contribution_share=("contribution_share", "sum"),
            baseline_denominator=("denominator_baseline", "sum"),
            comparison_denominator=("denominator_comparison", "sum"),
            baseline_stable_mass=("stable_baseline", "sum"),
            comparison_stable_mass=("stable_comparison", "sum"),
            earliest_first_observation=("first_observed_date", "min"),
            latest_first_observation=("first_observed_date", "max"),
            earliest_last_observation=("last_observed_date", "min"),
            latest_last_observation=("last_observed_date", "max"),
        )
        .rename(columns={category_column: "lifecycle_category"})
    )
    result.insert(2, "aggregation_level", aggregation_level)
    result["contribution_pp"] = 100.0 * result["contribution_share"]
    return result


def summarize_pair_turnover_lifecycle(
    contributions: pd.DataFrame,
    histories: pd.DataFrame,
) -> pd.DataFrame:
    """Return an exhaustive history split of the exclusive-pair contribution.

    Pair entry and exit use any observed route for the endpoint pair. Separate
    categories capture a primary native-or-stable vehicle role appearing or
    disappearing while the endpoint pair itself remains active. First observed
    means first positive observation in the available route panel. Exit remains
    right-censored at the panel end.
    """

    ledger, history, baseline_year, comparison_year = _validate_inputs(
        contributions, histories
    )
    data = ledger.merge(
        history,
        on=["metric", "source_column", *PAIR_KEYS],
        how="left",
        validate="one_to_one",
    )
    if data["first_observed_date"].isna().any():
        raise ValueError(
            f"pair lifecycle split lacks history for "
            f"{int(data['first_observed_date'].isna().sum())} pairs"
        )

    baseline_end = pd.Timestamp(f"{baseline_year}-06-30")
    comparison_start = pd.Timestamp(f"{comparison_year}-01-01")
    is_comparison = data["support_status"].eq(COMPARISON_EXCLUSIVE)
    is_baseline = data["support_status"].eq(BASELINE_EXCLUSIVE)
    if (
        is_comparison & data["comparison_market_route_count"].le(0)
    ).any() or (is_baseline & data["baseline_market_route_count"].le(0)).any():
        raise ValueError("exclusive vehicle-role support lacks its endpoint market")
    data["detail_category"] = np.select(
        [
            is_comparison
            & data["first_observed_date"].gt(baseline_end)
            & data["first_observed_date"].lt(comparison_start),
            is_comparison & data["first_observed_date"].ge(comparison_start),
            is_comparison & data["baseline_market_route_count"].gt(0),
            is_comparison
            & data["first_observed_date"].le(baseline_end)
            & data["baseline_market_route_count"].eq(0),
            is_baseline & data["comparison_market_route_count"].gt(0),
            is_baseline & data["last_observed_date"].le(baseline_end),
            is_baseline
            & data["last_observed_date"].gt(baseline_end)
            & data["last_observed_date"].lt(comparison_start),
        ],
        tuple(DETAIL_GROUPS),
        default="unclassified",
    )
    if data["detail_category"].eq("unclassified").any():
        raise ValueError(
            "pair lifecycle split contains histories inconsistent with endpoint support"
        )
    data["lifecycle_group"] = data["detail_category"].map(DETAIL_GROUPS)
    data["support_group"] = data["support_status"].map(SUPPORT_GROUPS)
    data["total_group"] = "one_window_only_total"

    result = pd.concat(
        [
            _aggregate(
                data,
                aggregation_level="detail",
                category_column="detail_category",
            ),
            _aggregate(
                data,
                aggregation_level="lifecycle_group",
                category_column="lifecycle_group",
            ),
            _aggregate(
                data,
                aggregation_level="endpoint_support",
                category_column="support_group",
            ),
            _aggregate(
                data,
                aggregation_level="exclusive_total",
                category_column="total_group",
            ),
        ],
        ignore_index=True,
    )
    result["baseline_year"] = baseline_year
    result["comparison_year"] = comparison_year
    result["baseline_window_end"] = baseline_end
    result["comparison_window_start"] = comparison_start
    result["formula_id"] = "endpoint_pair_history_split_of_exclusive_contribution_v1"

    for metric, rows in result.groupby("metric", sort=False):
        totals = [
            float(
                rows.loc[
                    rows["aggregation_level"].eq(level), "contribution_share"
                ].sum()
            )
            for level in ("detail", "lifecycle_group", "endpoint_support")
        ]
        exclusive = rows[rows["aggregation_level"].eq("exclusive_total")]
        if len(exclusive) != 1:
            raise RuntimeError(f"pair lifecycle split lacks one {metric} total")
        expected = float(exclusive.iloc[0]["contribution_share"])
        if not all(
            np.isclose(value, expected, atol=1e-12, rtol=0.0) for value in totals
        ):
            raise RuntimeError(f"pair lifecycle rollups do not reconcile for {metric}")
    return result.sort_values(
        ["metric", "aggregation_level", "lifecycle_category"], kind="stable"
    ).reset_index(drop=True)


def validate_exclusive_totals(
    lifecycle: pd.DataFrame,
    decomposition: pd.DataFrame,
) -> None:
    """Require the history split to reproduce the registered exclusive term."""

    totals = lifecycle[lifecycle["aggregation_level"].eq("exclusive_total")]
    registered = decomposition[
        decomposition["reporting_scope"].eq("pooled")
        & decomposition["formula_id"].eq("midpoint_common_exclusive_support_v1")
    ][["metric", "exclusive_pair_contribution"]]
    checked = totals.merge(registered, on="metric", how="left", validate="one_to_one")
    if checked["exclusive_pair_contribution"].isna().any():
        raise ValueError("registered decomposition lacks a lifecycle metric")
    residual = checked["contribution_share"] - checked["exclusive_pair_contribution"]
    if not np.allclose(residual, 0.0, atol=1e-12, rtol=0.0):
        raise RuntimeError("pair lifecycle split does not reproduce the exclusive term")
