#!/usr/bin/env python3
"""Fit route-only functional-form and distributional robustness designs.

The grouped-binomial model uses the same matched pair x month-day x realised
integration-scope support as the current denominator-weighted share regression.
Counts stay grouped.  The fixed effects are profiled cell by cell, and inference
uses pair and calendar-date score clusters.  The ECDF comparison preserves the
matched cells and uses pair-by-month-day cluster sign randomisation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit

from ddvc.model_artifacts import attach_spec_ids, model_artifact_context, write_model_exhibit
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


PAIR_PANEL = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.parquet"
RESULTS = OUTPUT_DIR / "exhibits" / "route_methodology_robustness.jsonl"
RESAMPLING = OUTPUT_DIR / "exhibits" / "route_methodology_distribution_resampling.jsonl"
CODE_SOURCES = [
    "scripts/run_route_methodology_robustness.py",
    "src/ddvc/model_artifacts.py",
]
COUNT_METRICS = ("count_share", "matched_strict_count_share")
GROUP_KEYS = ("src", "tgt", "month_day", "integration_scope")


def _cluster_meat(scores: np.ndarray, labels: pd.Series) -> tuple[float, int]:
    frame = pd.DataFrame({"score": scores, "cluster": labels.astype(str).to_numpy()})
    sums = frame.groupby("cluster", sort=False, observed=True)["score"].sum().to_numpy()
    groups = len(sums)
    correction = groups / (groups - 1) if groups > 1 else np.nan
    return float(correction * np.square(sums).sum()), groups


def _matched_metric(panel: pd.DataFrame, metric: str) -> pd.DataFrame:
    required = {
        "metric", "year", "date", *GROUP_KEYS, "native", "stable", "denominator",
        "stable_share",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"route methodology panel lacks columns: {missing}")
    data = panel[panel["metric"].eq(metric)].copy()
    if data.empty:
        raise ValueError(f"route methodology panel lacks metric {metric}")
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    if not data["year"].isin((2024, 2026)).all():
        raise ValueError("route methodology panel contains an unexpected year")
    for column in ("native", "stable", "denominator"):
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"route methodology panel has invalid {column}")
    if not np.allclose(data["native"] + data["stable"], data["denominator"]):
        raise ValueError("route methodology grouped counts do not reconcile")
    if not np.allclose(data[["native", "stable"]], np.rint(data[["native", "stable"]])):
        raise ValueError("grouped-binomial route counts must be integer valued")
    counts = data.groupby(list(GROUP_KEYS), observed=True)["year"].agg(["size", "nunique"])
    if not counts.eq(2).all().all():
        raise ValueError(f"{metric} does not have exactly two endpoint years per matched cell")
    return data.sort_values([*GROUP_KEYS, "year"], kind="stable").reset_index(drop=True)


def _profile_probabilities(
    beta: float,
    n0: np.ndarray,
    n1: np.ndarray,
    total_successes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    overall = total_successes / (n0 + n1)
    alpha = np.log(overall / (1.0 - overall)) - beta * n1 / (n0 + n1)
    for _ in range(60):
        p0 = expit(alpha)
        p1 = expit(alpha + beta)
        residual = n0 * p0 + n1 * p1 - total_successes
        derivative = n0 * p0 * (1.0 - p0) + n1 * p1 * (1.0 - p1)
        step = residual / derivative
        alpha -= step
        if np.max(np.abs(step)) < 1e-12:
            break
    p0 = expit(alpha)
    p1 = expit(alpha + beta)
    w0 = n0 * p0 * (1.0 - p0)
    w1 = n1 * p1 * (1.0 - p1)
    return p0, p1, w0, w1


def grouped_binomial_fixed_effects(panel: pd.DataFrame, metric: str) -> dict[str, object]:
    """Profile matched-cell intercepts and cluster the efficient score twice."""

    data = _matched_metric(panel, metric)
    wide = data.pivot(index=list(GROUP_KEYS), columns="year", values=["stable", "denominator", "date"])
    n0 = wide[("denominator", 2024)].to_numpy(float)
    n1 = wide[("denominator", 2026)].to_numpy(float)
    y0 = wide[("stable", 2024)].to_numpy(float)
    y1 = wide[("stable", 2026)].to_numpy(float)
    total = y0 + y1
    informative = (total > 0) & (total < n0 + n1)
    separated = int((~informative).sum())
    wide = wide.loc[informative].copy()
    n0, n1, y0, y1, total = (value[informative] for value in (n0, n1, y0, y1, total))
    if len(wide) < 4:
        raise ValueError(f"{metric} has too few informative grouped-binomial cells")

    beta = 0.0
    for _ in range(100):
        p0, p1, w0, w1 = _profile_probabilities(beta, n0, n1, total)
        score = float(np.sum(y1 - n1 * p1))
        information = float(np.sum(w0 * w1 / (w0 + w1)))
        step = score / information
        beta += step
        if abs(step) < 1e-11:
            break
    else:
        raise RuntimeError(f"{metric} grouped-binomial profile did not converge")

    p0, p1, w0, w1 = _profile_probabilities(beta, n0, n1, total)
    residual1 = y1 - n1 * p1
    denom = w0 + w1
    score0 = (w1 / denom) * residual1
    score1 = (w0 / denom) * residual1
    pair = pd.Series([f"{src}|{tgt}" for src, tgt, _day, _scope in wide.index])
    date0 = pd.Series(pd.to_datetime(wide[("date", 2024)].to_numpy()))
    date1 = pd.Series(pd.to_datetime(wide[("date", 2026)].to_numpy()))
    pair_scores = residual1
    date_scores = np.concatenate([score0, score1])
    date_labels = pd.concat([date0, date1], ignore_index=True)
    intersection_scores = np.concatenate([score0, score1])
    intersection_labels = pd.Series(
        [f"{p}|{d.date()}" for p, d in zip(pair, date0, strict=True)]
        + [f"{p}|{d.date()}" for p, d in zip(pair, date1, strict=True)]
    )
    meat_pair, pair_clusters = _cluster_meat(pair_scores, pair)
    meat_date, date_clusters = _cluster_meat(date_scores, date_labels)
    meat_intersection, intersection_clusters = _cluster_meat(
        intersection_scores, intersection_labels
    )
    information = float(np.sum(w0 * w1 / denom))
    variance = (meat_pair + meat_date - meat_intersection) / information**2
    if not np.isfinite(variance) or variance <= 0:
        raise RuntimeError(f"{metric} two-way grouped-binomial covariance is nonpositive")
    standard_error = float(np.sqrt(variance))
    degrees_freedom = min(pair_clusters, date_clusters) - 1
    t_statistic = beta / standard_error
    p_value = float(2.0 * stats.t.sf(abs(t_statistic), degrees_freedom))

    predicted0 = n0 * p0
    predicted1 = n1 * p1
    pearson = np.sum(
        np.square(y0 - predicted0) / (n0 * p0 * (1.0 - p0))
        + np.square(y1 - predicted1) / (n1 * p1 * (1.0 - p1))
    )
    dispersion_df = len(wide) - 1
    return {
        "method": "grouped_binomial_profile_fixed_effects",
        "metric": metric,
        "coefficient": float(beta),
        "odds_ratio": float(np.exp(beta)),
        "standard_error": standard_error,
        "t_statistic": float(t_statistic),
        "p_value": p_value,
        "observations": int(2 * len(wide)),
        "matched_cells": int(len(wide)),
        "separated_cells_excluded": separated,
        "ordered_pair_clusters": pair_clusters,
        "calendar_date_clusters": date_clusters,
        "pair_date_intersection_clusters": intersection_clusters,
        "pearson_dispersion": float(pearson / dispersion_df),
        "fixed_effects": "ordered_endpoint_pair_x_month_day_x_integration_scope",
        "covariance": "two_way_ordered_pair_calendar_date_cluster_score_sandwich",
        "estimand": "2026-versus-2024 stable odds within matched realised-route cells",
        "interpretation": "functional_form_robustness_for_realised_stable_share_noncausal",
        "falsifier": "odds_change_reverses_or_is_economically_negligible_on_locked_support",
    }


def paired_calendar_comparison(panel: pd.DataFrame, metric: str, *, hac_lag: int = 30) -> list[dict[str, object]]:
    """Compare ratios of totals after aggregating matched cells by calendar day."""

    data = _matched_metric(panel, metric)
    daily = data.groupby(["year", "month_day"], observed=True)[["stable", "denominator"]].sum()
    daily["share"] = daily["stable"] / daily["denominator"]
    wide = daily["share"].unstack("year").dropna(subset=[2024, 2026]).sort_index()
    change = (wide[2026] - wide[2024]).to_numpy(float)
    n = len(change)
    estimate = float(change.mean())
    ordinary_se = float(change.std(ddof=1) / np.sqrt(n))
    centered = change - estimate
    gamma0 = float(centered @ centered / n)
    long_run = gamma0
    for lag in range(1, min(hac_lag, n - 1) + 1):
        covariance = float(centered[lag:] @ centered[:-lag] / n)
        long_run += 2.0 * (1.0 - lag / (hac_lag + 1.0)) * covariance
    hac_se = float(np.sqrt(max(long_run, 0.0) / n))
    rows = []
    for method, standard_error, covariance in (
        ("paired_calendar_t", ordinary_se, "iid_calendar_day_diagnostic"),
        ("paired_calendar_hac_t", hac_se, f"newey_west_calendar_day_lag_{hac_lag}"),
    ):
        statistic = estimate / standard_error
        p_value = float(2.0 * stats.t.sf(abs(statistic), n - 1))
        rows.append(
            {
                "method": method,
                "metric": metric,
                "coefficient": estimate,
                "standard_error": standard_error,
                "t_statistic": float(statistic),
                "p_value": p_value,
                "observations": n,
                "matched_cells": int(len(data) // 2),
                "fixed_effects": "paired_month_day",
                "covariance": covariance,
                "estimand": (
                    "mean 2026-versus-2024 change in the calendar-day ratio of total stable "
                    "routes to total stable-plus-native routes across matched cells"
                ),
                "interpretation": (
                    "serial_dependence_diagnostic_only_allows_activity_reallocation_across_cells"
                    if method == "paired_calendar_t" else
                    "calendar_dependence_robust_noncausal_change_allows_activity_reallocation_across_cells"
                ),
                "falsifier": "paired_calendar_mean_change_is_zero_or_reverses",
            }
        )
    return rows


def conventional_ks_rejection(panel: pd.DataFrame, metric: str) -> dict[str, object]:
    """Calculate the familiar statistic while rejecting its iid reference law."""

    data = _matched_metric(panel, metric)
    wide = data.pivot(index=list(GROUP_KEYS), columns="year", values="stable_share")
    statistic, iid_p_value = stats.ks_2samp(
        wide[2024].to_numpy(float), wide[2026].to_numpy(float), method="asymp"
    )
    return {
        "method": "conventional_two_sample_ks_rejected",
        "metric": metric,
        "coefficient": float(statistic),
        "p_value": float(iid_p_value),
        "observations": int(2 * len(wide)),
        "matched_cells": int(len(wide)),
        "fixed_effects": "none",
        "covariance": "iid_reference_law_invalid_for_matched_pair_date_cells",
        "estimand": "maximum empirical-CDF gap under an iid two-sample reference law",
        "interpretation": "rejected_inference_diagnostic_statistic_only",
        "falsifier": "not_applicable_because_dependence_invalidates_reference_distribution",
        "rejection_reason": (
            "the two years are paired within cells and observations share ordered pairs "
            "and calendar dates; use the cluster sign-randomised analogue"
        ),
    }


def clustered_ecdf_randomisation(
    panel: pd.DataFrame,
    metric: str,
    *,
    weighting: str = "equal_cell",
    replications: int = 999,
    seed: int = 1863,
) -> tuple[dict[str, object], pd.DataFrame]:
    """Paired ECDF maximum gap with two-way cluster sign randomisation."""

    data = _matched_metric(panel, metric)
    wide = data.pivot(
        index=list(GROUP_KEYS), columns="year", values=["stable_share", "denominator"]
    )
    if weighting not in {"equal_cell", "symmetric_denominator_mass"}:
        raise ValueError(f"unknown ECDF weighting: {weighting}")
    before = wide[("stable_share", 2024)].to_numpy(float)
    after = wide[("stable_share", 2026)].to_numpy(float)
    if weighting == "equal_cell":
        weights = np.ones(len(wide), dtype=float)
    else:
        mass0 = wide[("denominator", 2024)].to_numpy(float)
        mass1 = wide[("denominator", 2026)].to_numpy(float)
        weights = mass0 * mass1 / (mass0 + mass1)

    def weighted_cdf(values: np.ndarray, evaluation: np.ndarray) -> np.ndarray:
        order = np.argsort(values, kind="stable")
        sorted_values = values[order]
        cumulative = np.cumsum(weights[order])
        positions = np.searchsorted(sorted_values, evaluation, side="right")
        output = np.zeros(len(evaluation), dtype=float)
        positive = positions > 0
        output[positive] = cumulative[positions[positive] - 1]
        return output / cumulative[-1]

    grid = np.unique(np.concatenate([before, after]))
    before_cdf = weighted_cdf(before, grid)
    after_cdf = weighted_cdf(after, grid)
    gap = after_cdf - before_cdf
    maximum = float(np.max(np.abs(gap)))
    location = float(grid[np.argmax(np.abs(gap))])

    pairs = pd.Categorical([f"{src}|{tgt}" for src, tgt, _day, _scope in wide.index])
    days = pd.Categorical([day for _src, _tgt, day, _scope in wide.index])
    rng = np.random.default_rng(seed)
    null_maxima = np.empty(replications, dtype=float)
    rows: list[dict[str, object]] = []
    evaluation_grid = np.linspace(0.0, 1.0, 201)
    for draw in range(replications):
        pair_sign = rng.choice(np.array([-1, 1], dtype=np.int8), size=len(pairs.categories))
        day_sign = rng.choice(np.array([-1, 1], dtype=np.int8), size=len(days.categories))
        swap = pair_sign[pairs.codes] * day_sign[days.codes] < 0
        null_before = np.where(swap, after, before)
        null_after = np.where(swap, before, after)
        cdf0 = weighted_cdf(null_before, evaluation_grid)
        cdf1 = weighted_cdf(null_after, evaluation_grid)
        null_maxima[draw] = np.max(np.abs(cdf1 - cdf0))
        rows.append(
            {
                "spec_id": (
                    f"route-methodology-distribution.{metric}.{weighting}."
                    f"draw-{draw + 1:04d}"
                ),
                "metric": metric,
                "weighting": weighting,
                "draw": draw + 1,
                "maximum_ecdf_gap_under_cluster_swap": null_maxima[draw],
                "seed": seed,
            }
        )
    p_value = float((1 + np.sum(null_maxima >= maximum)) / (replications + 1))
    result = {
        "method": "paired_ecdf_two_way_cluster_sign_randomisation",
        "metric": metric,
        "distribution_weighting": weighting,
        "coefficient": maximum,
        "ecdf_gap_at_location": float(gap[np.argmax(np.abs(gap))]),
        "ecdf_gap_location": location,
        "p_value": p_value,
        "observations": int(2 * len(wide)),
        "matched_cells": int(len(wide)),
        "ordered_pair_clusters": int(len(pairs.categories)),
        "month_day_clusters": int(len(days.categories)),
        "replications": replications,
        "fixed_effects": "matched_cell_pairing",
        "covariance": "ordered_pair_x_month_day_cluster_sign_randomisation",
        "estimand": "maximum change in the matched-cell distribution of realised stable shares",
        "interpretation": "distributional_shift_on_matched_realised_route_cells_noncausal",
        "falsifier": "matched_share_distribution_is_invariant_across_endpoint_years",
    }
    return result, pd.DataFrame(rows)


def run(
    *,
    panel_path: Path = PAIR_PANEL,
    result_path: Path = RESULTS,
    resampling_path: Path = RESAMPLING,
    replications: int = 999,
    root: Path = REPO_ROOT,
    environment=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_parquet(panel_path)
    rows: list[dict[str, object]] = []
    resampling = []
    for metric in COUNT_METRICS:
        rows.append(grouped_binomial_fixed_effects(panel, metric))
        rows.extend(paired_calendar_comparison(panel, metric))
        rows.append(conventional_ks_rejection(panel, metric))
        for weighting in ("equal_cell", "symmetric_denominator_mass"):
            distribution, draws = clustered_ecdf_randomisation(
                panel, metric, weighting=weighting, replications=replications
            )
            rows.append(distribution)
            resampling.append(draws)
    results = attach_spec_ids(
        pd.DataFrame(rows),
        prefix="route_methodology_robustness",
        columns=("method", "metric", "distribution_weighting"),
    )
    draws = pd.concat(resampling, ignore_index=True)
    context = model_artifact_context(root=root, environment=environment)
    write_model_exhibit(
        results,
        result_path,
        role="diagnostic",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[panel_path],
        notes=(
            "grouped-binomial, paired-calendar mean, and cluster-randomised ECDF "
            "robustness on the locked matched realised-route support; no opportunity-set "
            "or causal interpretation"
        ),
    )
    write_model_exhibit(
        draws,
        resampling_path,
        role="resampling",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[panel_path],
        notes="two-way ordered-pair and month-day cluster sign-randomisation draws",
    )
    return results, draws


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PAIR_PANEL)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--resampling", type=Path, default=RESAMPLING)
    parser.add_argument("--replications", type=int, default=999)
    args = parser.parse_args()
    results, _draws = run(
        panel_path=args.panel,
        result_path=args.results,
        resampling_path=args.resampling,
        replications=args.replications,
    )
    print(results.to_json(orient="records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
