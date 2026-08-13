"""Within-cell and composition accounting for vehicle-currency rotation."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END


BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
CELL_COLUMNS = (
    "src",
    "tgt",
    "observed_reach",
    "integration_scope",
    "protocol_sequence",
)
METRICS = {
    "route_count": "route_count",
    "strict_value": "within_20pct_value_usd",
}
REQUIRED_CHOICE_COLUMNS = {
    "date",
    "src",
    "tgt",
    "candidate_address",
    "candidate_type",
    "venue_sequence",
    "integration_scope",
    "protocol_sequence",
    *METRICS.values(),
}
STATUS_ORDER = ("common", "entry", "exit")


def _observed_reach(value: object) -> str:
    venues = sorted({venue for venue in str(value).split(">") if venue})
    if not venues or len(venues) > 2:
        raise ValueError(f"vehicle-rotation choice has invalid venue sequence: {value!r}")
    return "|".join(venues)


def _common_calendar_choices(
    choices: pd.DataFrame,
    *,
    baseline_year: int,
    comparison_year: int,
) -> tuple[pd.DataFrame, str]:
    data = choices.copy()
    missing = sorted(REQUIRED_CHOICE_COLUMNS - set(data.columns))
    if missing:
        raise ValueError(f"vehicle-rotation choices lack columns: {missing}")
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data = data[data["date"].dt.year.isin((baseline_year, comparison_year))].copy()
    if set(data["date"].dt.year.unique()) != {baseline_year, comparison_year}:
        raise ValueError("vehicle-rotation decomposition requires both endpoint years")
    locked_sample_end = pd.to_datetime(RESEARCH_SAMPLE_END, format="%Y%m%d")
    comparison_end = (
        locked_sample_end
        if locked_sample_end.year == comparison_year
        else data.loc[data["date"].dt.year.eq(comparison_year), "date"].max()
    )
    if data["date"].max() > comparison_end:
        raise ValueError("vehicle-rotation choices exceed the locked sample end")
    comparison_start = pd.Timestamp(comparison_year, 1, 1)
    comparison_month_days = {
        date.strftime("%m-%d")
        for date in pd.date_range(comparison_start, comparison_end, freq="D")
    }
    data["month_day"] = data["date"].dt.strftime("%m-%d")
    data = data[data["month_day"].isin(comparison_month_days)].copy()
    data["observed_reach"] = data["venue_sequence"].map(_observed_reach)
    if data.duplicated(
        [
            "date",
            "src",
            "tgt",
            "candidate_address",
            "integration_scope",
            "venue_sequence",
        ]
    ).any():
        raise ValueError("vehicle-rotation choices contain duplicate release keys")
    if not data["candidate_type"].isin(("native", "stable")).all():
        raise ValueError("vehicle-rotation choices contain a non-primary candidate type")
    return data, comparison_end.strftime("%m-%d")


def _annual_cells(data: pd.DataFrame, *, metric_column: str) -> pd.DataFrame:
    grouped = (
        data.groupby(
            [data["date"].dt.year.rename("year"), *CELL_COLUMNS, "candidate_type"],
            as_index=False,
            sort=True,
        )[metric_column]
        .sum()
    )
    wide = grouped.pivot(
        index=["year", *CELL_COLUMNS],
        columns="candidate_type",
        values=metric_column,
    ).fillna(0.0)
    for candidate_type in ("native", "stable"):
        if candidate_type not in wide:
            wide[candidate_type] = 0.0
    wide = wide.reset_index()
    wide["denominator"] = wide["native"] + wide["stable"]
    if ~np.isfinite(wide[["native", "stable", "denominator"]]).all(
        axis=None
    ) or wide[["native", "stable"]].lt(0).any(axis=None):
        raise ValueError("vehicle-rotation cells contain invalid magnitudes")
    zero_denominator_cell_years = int(wide["denominator"].eq(0).sum())
    wide = wide[wide["denominator"].gt(0)].copy()
    if set(wide["year"].unique()) != set(data["date"].dt.year.unique()):
        raise ValueError("vehicle-rotation metric lacks positive support in an endpoint year")
    wide["stable_share"] = wide["stable"] / wide["denominator"]
    totals = wide.groupby("year")["denominator"].transform("sum")
    wide["cell_weight"] = wide["denominator"] / totals
    wide.attrs["zero_denominator_cell_years"] = zero_denominator_cell_years
    return wide


def _decompose_metric(
    annual: pd.DataFrame,
    *,
    metric: str,
    baseline_year: int,
    comparison_year: int,
    common_calendar_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline = annual[annual["year"].eq(baseline_year)].drop(columns="year")
    comparison = annual[annual["year"].eq(comparison_year)].drop(columns="year")
    merged = baseline.merge(
        comparison,
        on=list(CELL_COLUMNS),
        how="outer",
        suffixes=("_baseline", "_comparison"),
        indicator=True,
        validate="one_to_one",
    )
    merged["support_status"] = merged["_merge"].map(
        {"both": "common", "right_only": "entry", "left_only": "exit"}
    ).astype("object")
    for column in (
        "native",
        "stable",
        "denominator",
        "stable_share",
        "cell_weight",
    ):
        for suffix in ("baseline", "comparison"):
            merged[f"{column}_{suffix}"] = pd.to_numeric(
                merged[f"{column}_{suffix}"], errors="coerce"
            )
    common = merged["support_status"].eq("common")
    entry = merged["support_status"].eq("entry")
    exit_ = merged["support_status"].eq("exit")
    merged["within_cell_contribution"] = 0.0
    merged.loc[common, "within_cell_contribution"] = (
        0.5
        * (
            merged.loc[common, "cell_weight_baseline"]
            + merged.loc[common, "cell_weight_comparison"]
        )
        * (
            merged.loc[common, "stable_share_comparison"]
            - merged.loc[common, "stable_share_baseline"]
        )
    )
    merged["common_cell_reweighting_contribution"] = 0.0
    merged.loc[common, "common_cell_reweighting_contribution"] = (
        0.5
        * (
            merged.loc[common, "stable_share_baseline"]
            + merged.loc[common, "stable_share_comparison"]
        )
        * (
            merged.loc[common, "cell_weight_comparison"]
            - merged.loc[common, "cell_weight_baseline"]
        )
    )
    merged["entry_contribution"] = 0.0
    merged.loc[entry, "entry_contribution"] = (
        merged.loc[entry, "cell_weight_comparison"]
        * merged.loc[entry, "stable_share_comparison"]
    )
    merged["exit_contribution"] = 0.0
    merged.loc[exit_, "exit_contribution"] = -(
        merged.loc[exit_, "cell_weight_baseline"]
        * merged.loc[exit_, "stable_share_baseline"]
    )
    baseline_share = float(
        annual.loc[annual["year"].eq(baseline_year), "stable"].sum()
        / annual.loc[annual["year"].eq(baseline_year), "denominator"].sum()
    )
    comparison_share = float(
        annual.loc[annual["year"].eq(comparison_year), "stable"].sum()
        / annual.loc[annual["year"].eq(comparison_year), "denominator"].sum()
    )
    contributions = {
        "within_cell_contribution": float(merged["within_cell_contribution"].sum()),
        "common_cell_reweighting_contribution": float(
            merged["common_cell_reweighting_contribution"].sum()
        ),
        "entry_contribution": float(merged["entry_contribution"].sum()),
        "exit_contribution": float(merged["exit_contribution"].sum()),
    }
    total_change = comparison_share - baseline_share
    identity_error = total_change - sum(contributions.values())
    if not np.isclose(identity_error, 0.0, atol=1e-12, rtol=1e-12):
        raise RuntimeError(
            f"vehicle-rotation decomposition identity failed for {metric}: {identity_error}"
        )
    common_baseline_weight = float(
        merged.loc[common, "cell_weight_baseline"].sum()
    )
    common_comparison_weight = float(
        merged.loc[common, "cell_weight_comparison"].sum()
    )
    summary = pd.DataFrame(
        [
            {
                "metric": metric,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "common_calendar_end": common_calendar_end,
                "baseline_stable_share": baseline_share,
                "comparison_stable_share": comparison_share,
                "total_change": total_change,
                **contributions,
                "identity_error": identity_error,
                "common_support_baseline_denominator_share": common_baseline_weight,
                "common_support_comparison_denominator_share": common_comparison_weight,
                "zero_denominator_cell_years": int(
                    annual.attrs.get("zero_denominator_cell_years", 0)
                ),
                "conditioning_fields": "|".join(CELL_COLUMNS),
                "omitted_dimensions": "notional_bin|exact_search_efficiency_state",
                "estimand_scope": "fixed_pair_reach_design_pre_frontier",
                "mechanism_status": "descriptive_noncausal",
            }
        ]
    )
    support_rows: list[dict[str, object]] = []
    for status in STATUS_ORDER:
        selected = merged[merged["support_status"].eq(status)]
        support_rows.append(
            {
                "record_type": "opportunity_cell_support",
                "metric": metric,
                "unit": "ordered_endpoint_reach_design_cell",
                "support_status": status,
                "units": len(selected),
                "baseline_denominator": float(
                    selected["denominator_baseline"].fillna(0).sum()
                ),
                "comparison_denominator": float(
                    selected["denominator_comparison"].fillna(0).sum()
                ),
                "baseline_denominator_share": float(
                    selected["cell_weight_baseline"].fillna(0).sum()
                ),
                "comparison_denominator_share": float(
                    selected["cell_weight_comparison"].fillna(0).sum()
                ),
            }
        )
    support_rows.append(
        {
            "record_type": "metric_zero_denominator_support",
            "metric": metric,
            "unit": "ordered_endpoint_reach_design_cell_year",
            "support_status": "unsupported_zero_denominator",
            "units": int(annual.attrs.get("zero_denominator_cell_years", 0)),
            "baseline_denominator": 0.0,
            "comparison_denominator": 0.0,
            "baseline_denominator_share": 0.0,
            "comparison_denominator_share": 0.0,
        }
    )
    detail = merged.drop(columns="_merge").copy()
    detail.insert(0, "metric", metric)
    detail.insert(1, "baseline_year", baseline_year)
    detail.insert(2, "comparison_year", comparison_year)
    return detail, summary, pd.DataFrame(support_rows)


def _unit_support(
    data: pd.DataFrame,
    *,
    fields: Sequence[str],
    unit: str,
    baseline_year: int,
    comparison_year: int,
) -> pd.DataFrame:
    observed = (
        data.assign(year=data["date"].dt.year)
        .groupby(["year", *fields], as_index=False, sort=True)
        .agg(
            route_count=("route_count", "sum"),
            strict_value=("within_20pct_value_usd", "sum"),
        )
    )
    baseline = observed[observed["year"].eq(baseline_year)].drop(columns="year")
    comparison = observed[observed["year"].eq(comparison_year)].drop(columns="year")
    joined = baseline.merge(
        comparison,
        on=list(fields),
        how="outer",
        suffixes=("_baseline", "_comparison"),
        indicator=True,
        validate="one_to_one",
    )
    joined["support_status"] = joined["_merge"].map(
        {"both": "common", "right_only": "entry", "left_only": "exit"}
    )
    rows: list[dict[str, object]] = []
    for status in STATUS_ORDER:
        selected = joined[joined["support_status"].eq(status)]
        rows.append(
            {
                "record_type": "composition_unit_support",
                "metric": "all",
                "unit": unit,
                "support_status": status,
                "units": len(selected),
                "baseline_denominator": float(
                    selected["route_count_baseline"].fillna(0).sum()
                ),
                "comparison_denominator": float(
                    selected["route_count_comparison"].fillna(0).sum()
                ),
                "baseline_denominator_share": None,
                "comparison_denominator_share": None,
                "baseline_strict_value": float(
                    selected["strict_value_baseline"].fillna(0).sum()
                ),
                "comparison_strict_value": float(
                    selected["strict_value_comparison"].fillna(0).sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def vehicle_rotation_composition(
    choices: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return cell detail, exact share decomposition, and support geometry.

    This is deliberately a pre-frontier composition result. It fixes endpoint,
    observed venue reach, integration, and protocol sequence, but it neither
    observes a notional bin nor conditions on same-state routing regret.
    """

    data, common_calendar_end = _common_calendar_choices(
        choices,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    detail_frames: list[pd.DataFrame] = []
    summaries: list[pd.DataFrame] = []
    support_frames: list[pd.DataFrame] = []
    for metric, column in METRICS.items():
        detail, summary, support = _decompose_metric(
            _annual_cells(data, metric_column=column),
            metric=metric,
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            common_calendar_end=common_calendar_end,
        )
        detail_frames.append(detail)
        summaries.append(summary)
        support_frames.append(support)
    support_frames.extend(
        [
            _unit_support(
                data,
                fields=("src", "tgt"),
                unit="ordered_endpoint_pair",
                baseline_year=baseline_year,
                comparison_year=comparison_year,
            ),
            _unit_support(
                data,
                fields=("candidate_address",),
                unit="candidate_address",
                baseline_year=baseline_year,
                comparison_year=comparison_year,
            ),
            _unit_support(
                data,
                fields=("observed_reach", "protocol_sequence"),
                unit="venue_reach_design",
                baseline_year=baseline_year,
                comparison_year=comparison_year,
            ),
        ]
    )
    detail = pd.concat(detail_frames, ignore_index=True, sort=False)
    summary = pd.concat(summaries, ignore_index=True, sort=False)
    support = pd.concat(support_frames, ignore_index=True, sort=False)
    return detail, summary, support
