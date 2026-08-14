#!/usr/bin/env python3
"""Measure leadership and persistence within stablecoin vehicle activity.

The E0 distinguishes USDT replacing USDC from convergence toward a balanced
USDT--USDC split and from unstable day-to-day leadership.  It uses exact
two-leg intermediary activity only.  Counts use all reconstructed support;
value uses the project's strict 20 percent route-value support.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/provisional/stable_vehicle_leadership_e0.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit


INPUT = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUTPUT = OUTPUT_DIR / "provisional" / "stable_vehicle_leadership_e0.jsonl"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAGS = (7, 14, 30, 60)
PRIMARY_HAC_LAG = 30
METRICS = {
    "exact_two_leg_count_all_support": {
        "denominator": "cnt_two_leg_stable",
        "USDT": "cnt_two_leg_USDT",
        "USDC": "cnt_two_leg_USDC",
        "DAI": "cnt_two_leg_DAI",
        "unit": "route_intermediary_episodes",
    },
    "exact_two_leg_value_strict_20pct": {
        "denominator": "usd_within_20pct_two_leg_stable",
        "USDT": "usd_within_20pct_two_leg_USDT",
        "USDC": "usd_within_20pct_two_leg_USDC",
        "DAI": "usd_within_20pct_two_leg_DAI",
        "unit": "strict_supported_routed_usd",
    },
}
CODE_SOURCES = [
    "scripts/run_stable_vehicle_leadership_e0.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]


def required_columns() -> set[str]:
    columns = {"date"}
    for definition in METRICS.values():
        columns.update(
            str(definition[key]) for key in ("denominator", "USDT", "USDC", "DAI")
        )
    return columns


def matched_endpoint_sample(
    panel: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    """Keep month-days observed in both endpoint years."""

    missing = sorted(required_columns() - set(panel.columns))
    if missing:
        raise ValueError(f"intermediation panel is missing columns: {missing}")
    data = panel[list(required_columns())].copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["year"] = data["date"].dt.year
    data = data[data["year"].isin((baseline_year, comparison_year))].copy()
    mask = common_calendar_day_mask(
        data["date"],
        data["year"],
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    data = data.loc[mask].sort_values("date", kind="stable").reset_index(drop=True)
    data["month_day"] = data["date"].dt.strftime("%m-%d")
    counts = data.groupby("month_day")["year"].nunique()
    if data["date"].duplicated().any() or not counts.eq(2).all():
        raise ValueError("endpoint sample is not one matched observation per month-day and year")
    return data


def _leader(amounts: pd.DataFrame) -> pd.Series:
    maximum = amounts.max(axis=1)
    ties = amounts.eq(maximum, axis=0).sum(axis=1).gt(1)
    leader = amounts.idxmax(axis=1).astype(object)
    leader.loc[ties] = "tie"
    return leader.astype(str)


def daily_leadership(panel: pd.DataFrame) -> pd.DataFrame:
    """Construct daily within-stablecoin shares for the two declared metrics."""

    data = matched_endpoint_sample(panel)
    rows: list[pd.DataFrame] = []
    for metric, definition in METRICS.items():
        columns = {
            token: pd.to_numeric(data[str(definition[token])], errors="coerce")
            for token in ("USDT", "USDC", "DAI")
        }
        denominator = pd.to_numeric(
            data[str(definition["denominator"])], errors="coerce"
        )
        frame = data[["date", "year", "month_day"]].copy()
        frame["metric"] = metric
        frame["unit"] = definition["unit"]
        frame["stable_activity"] = denominator
        for token, values in columns.items():
            frame[f"{token.lower()}_activity"] = values
        frame["residual_activity"] = denominator - sum(columns.values())
        tolerance = np.maximum(1.0, denominator.abs()) * 1e-10
        if (frame["residual_activity"] < -tolerance).any():
            raise ValueError(f"{metric} named stablecoin activity exceeds stable total")
        frame["residual_activity"] = frame["residual_activity"].clip(lower=0.0)
        frame = frame[frame["stable_activity"].gt(0)].copy()
        for name in ("usdt", "usdc", "dai", "residual"):
            frame[f"{name}_share"] = (
                frame[f"{name}_activity"] / frame["stable_activity"]
            )
        share_sum = frame[
            ["usdt_share", "usdc_share", "dai_share", "residual_share"]
        ].sum(axis=1)
        if not np.allclose(share_sum, 1.0, atol=1e-9, rtol=0):
            raise RuntimeError(f"{metric} within-stable shares do not sum to one")
        frame["usdt_minus_usdc_share"] = frame["usdt_share"] - frame["usdc_share"]
        frame["usdt_usdc_combined_share"] = frame["usdt_share"] + frame["usdc_share"]
        frame["usdt_usdc_absolute_gap"] = frame["usdt_minus_usdc_share"].abs()
        frame["leader"] = _leader(
            frame[["usdt_activity", "usdc_activity", "dai_activity", "residual_activity"]]
            .rename(
                columns={
                    "usdt_activity": "USDT",
                    "usdc_activity": "USDC",
                    "dai_activity": "DAI",
                    "residual_activity": "residual_stablecoins",
                }
            )
        )
        frame["usdt_leader"] = frame["leader"].eq("USDT")
        frame["usdc_leader"] = frame["leader"].eq("USDC")
        rows.append(frame)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["metric", "date"], kind="stable"
    )


def _newey_west_mean(values: np.ndarray, lag: int) -> dict[str, float | int]:
    observations = len(values)
    if observations < 4:
        raise ValueError("paired-month-day HAC requires at least four observations")
    effective_lag = min(lag, observations - 1)
    estimate = float(values.mean())
    centered = values - estimate
    long_run_variance = float(centered @ centered / observations)
    for offset in range(1, effective_lag + 1):
        covariance = float(centered[offset:] @ centered[:-offset] / observations)
        long_run_variance += 2 * (1 - offset / (effective_lag + 1)) * covariance
    standard_error = float(np.sqrt(max(long_run_variance, 0.0) / observations))
    statistic = estimate / standard_error if standard_error > 0 else np.nan
    p_value = (
        float(2 * stats.t.sf(abs(statistic), observations - 1))
        if np.isfinite(statistic)
        else np.nan
    )
    critical = float(stats.t.ppf(0.975, observations - 1))
    return {
        "baseline_mean": np.nan,
        "comparison_mean": np.nan,
        "change": estimate,
        "standard_error": standard_error,
        "t_statistic": float(statistic),
        "p_value": p_value,
        "confidence_interval_lower": estimate - critical * standard_error,
        "confidence_interval_upper": estimate + critical * standard_error,
        "observations": observations,
    }


def gap_inference(daily: pd.DataFrame) -> pd.DataFrame:
    """Estimate USDT-minus-USDC gap changes under both declared HAC clocks."""

    rows: list[dict[str, object]] = []
    for metric, sample in daily.groupby("metric", sort=True):
        sample = sample.sort_values("date", kind="stable")
        wide = sample.pivot(
            index="month_day", columns="year", values="usdt_minus_usdc_share"
        ).sort_index()
        if wide[[BASELINE_YEAR, COMPARISON_YEAR]].isna().any().any():
            raise RuntimeError(f"{metric} gap inference lost matched month-days")
        paired = (
            wide[COMPARISON_YEAR] - wide[BASELINE_YEAR]
        ).to_numpy(dtype=float)
        for lag in HAC_LAGS:
            endpoint = year_endpoint_change(
                sample["usdt_minus_usdc_share"],
                sample["year"],
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                hac_lag=lag,
                dates=sample["date"],
            )
            critical = float(stats.t.ppf(0.975, endpoint.degrees_freedom))
            rows.append(
                {
                    "row_type": "gap_inference",
                    "metric": metric,
                    "method": "endpoint_year_actual_calendar_hac",
                    "hac_lag_days": lag,
                    "primary_inference": lag == PRIMARY_HAC_LAG,
                    "baseline_mean": endpoint.baseline_mean,
                    "comparison_mean": endpoint.comparison_mean,
                    "change": endpoint.change,
                    "standard_error": endpoint.standard_error,
                    "t_statistic": endpoint.t_statistic,
                    "p_value": endpoint.p_value,
                    "confidence_interval_lower": endpoint.change
                    - critical * endpoint.standard_error,
                    "confidence_interval_upper": endpoint.change
                    + critical * endpoint.standard_error,
                    "observations": endpoint.n_observations,
                    "estimand": "change_in_daily_USDT_minus_USDC_share_within_stable_intermediary_activity",
                    "interpretation_boundary": "descriptive_within_stablecoin_leadership_not_overall_vehicle_dominance",
                }
            )
            rows.append(
                {
                    "row_type": "gap_inference",
                    "metric": metric,
                    "method": "paired_month_day_difference_hac_sensitivity",
                    "hac_lag_days": lag,
                    "primary_inference": False,
                    **_newey_west_mean(paired, lag),
                    "estimand": "mean_matched_month_day_change_in_USDT_minus_USDC_share",
                    "interpretation_boundary": "sensitivity_permitting_cross_year_matched_day_covariance",
                }
            )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = np.nan
    for (_method, _lag), index in result.groupby(
        ["method", "hac_lag_days"], sort=False
    ).groups.items():
        result.loc[index, "p_value_holm"] = holm_adjusted_pvalues(
            result.loc[index, "p_value"]
        )
    return result


def transition_summaries(daily: pd.DataFrame) -> pd.DataFrame:
    """Report levels that distinguish replacement, balance and residual growth."""

    variables = (
        "usdt_share",
        "usdc_share",
        "usdt_minus_usdc_share",
        "usdt_usdc_absolute_gap",
        "usdt_usdc_combined_share",
        "dai_share",
        "residual_share",
    )
    rows: list[dict[str, object]] = []
    for metric, sample in daily.groupby("metric", sort=True):
        for variable in variables:
            means = sample.groupby("year")[variable].mean()
            rows.append(
                {
                    "row_type": "transition_summary",
                    "metric": metric,
                    "measure": variable,
                    "baseline_mean": float(means.loc[BASELINE_YEAR]),
                    "comparison_mean": float(means.loc[COMPARISON_YEAR]),
                    "change": float(means.loc[COMPARISON_YEAR] - means.loc[BASELINE_YEAR]),
                    "matched_month_days": int(sample["month_day"].nunique()),
                    "weighting": "equal_weighted_daily_share",
                }
            )
        for year, year_sample in sample.groupby("year", sort=True):
            total = float(year_sample["stable_activity"].sum())
            rows.append(
                {
                    "row_type": "transition_summary",
                    "metric": metric,
                    "measure": "pooled_USDT_minus_USDC_share",
                    "year": int(year),
                    "level": float(
                        (year_sample["usdt_activity"].sum() - year_sample["usdc_activity"].sum())
                        / total
                    ),
                    "stable_activity_support": total,
                    "weighting": "activity_weighted_pooled_share",
                }
            )
    return pd.DataFrame(rows)


def persistence_summaries(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarize adjacent-day retention without comparing censored spell lengths."""

    rows: list[dict[str, object]] = []
    for (metric, year), sample in daily.groupby(["metric", "year"], sort=True):
        sample = sample.sort_values("date", kind="stable").reset_index(drop=True)
        adjacent = sample["date"].diff().dt.days.eq(1)
        same = sample["leader"].eq(sample["leader"].shift()) & adjacent
        pairs = int(adjacent.sum())
        changes = sample["leader"].ne(sample["leader"].shift())
        spell_count = int(changes.sum())
        leader_shares = sample["leader"].value_counts(normalize=True)
        rows.append(
            {
                "row_type": "persistence_summary",
                "metric": metric,
                "year": int(year),
                "days": int(len(sample)),
                "adjacent_calendar_day_pairs": pairs,
                "same_leader_rate": float(same.sum() / pairs) if pairs else np.nan,
                "switch_rate": float((adjacent & ~same).sum() / pairs) if pairs else np.nan,
                "usdt_leader_day_share": float(leader_shares.get("USDT", 0.0)),
                "usdc_leader_day_share": float(leader_shares.get("USDC", 0.0)),
                "dai_leader_day_share": float(leader_shares.get("DAI", 0.0)),
                "residual_leader_day_share": float(
                    leader_shares.get("residual_stablecoins", 0.0)
                ),
                "tie_day_share": float(leader_shares.get("tie", 0.0)),
                "observed_spells": spell_count,
                "left_censored_spells": int(spell_count > 0),
                "right_censored_spells": int(spell_count > 0),
                "fully_observed_internal_spells": max(spell_count - 2, 0),
                "spell_length_comparison": "not_reported_endpoint_spells_are_censored",
            }
        )
    return pd.DataFrame(rows)


def result_frame(panel: pd.DataFrame) -> pd.DataFrame:
    daily = daily_leadership(panel)
    daily_rows = daily.copy()
    daily_rows.insert(0, "row_type", "daily_leadership")
    return pd.concat(
        [
            daily_rows,
            transition_summaries(daily),
            persistence_summaries(daily),
            gap_inference(daily),
        ],
        ignore_index=True,
        sort=False,
    )


def run(input_path: Path = INPUT, output_path: Path = OUTPUT) -> Path:
    with current_artifacts([input_path], consumer="stable vehicle leadership E0"):
        panel = pd.read_parquet(input_path)
        result = result_frame(panel)
        return write_exhibit(
            result,
            output_path,
            code_sources=CODE_SOURCES,
            inputs=[input_path],
            notes=(
                "exact two-leg within-stablecoin leadership; count uses all route support; "
                "value requires source/intermediary/destination agreement within 20 percent; "
                "2024 and 2026 first-half month-days matched; actual-calendar NW30 primary; "
                "venue choice and leadership are descriptive; Somogyi (2026), raw PDF pp. "
                "16-18, motivates market-specific rather than universal currency leadership"
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        path = run(args.input, args.output)
    except RuntimeError as exc:
        print(f"INPUT BLOCKED: {exc}")
        return 2
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
