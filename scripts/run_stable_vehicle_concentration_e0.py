#!/usr/bin/env python3
"""E0 concentration test for stablecoins used as route intermediaries.

The economic question is whether the recent shift toward stablecoin intermediation is
broadly distributed across stablecoins or concentrated in USDT and USDC.  The current
daily intermediation owner reports every stable intermediary episode, with separate
counts for USDT, USDC, and DAI.  It does not identify every remaining stablecoin
separately.  This runner therefore reports the USDT--USDC share directly and bounds the
stablecoin Herfindahl index: the lower bound treats the residual share as atomistically
split, while the upper bound treats it as one token.  Concentration is not used to infer
succession, fragmentation, market power, or causality.

The endpoint comparison uses the same calendar days in 2024 and 2026.  Its covariance
uses endpoint-year observations only: 2025 does not enter the fit.  Newey--West
standard errors use a 30-day Bartlett bandwidth, with 7-, 14-, and 60-day sensitivity.
The closest retained crypto-finance
benchmark, Griffin and Shams (2020, Figure 4), reports the underlying account-flow shares;
we likewise keep shares visible.  Their concentration figure does not supply the HAC
design used here: serial-dependence adjustment follows from our daily comparison.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/provisional/stable_vehicle_concentration_e0.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.asset_types import STABLE, VEHICLE_CANDIDATE_SYMBOLS
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "processed" / "intermediation_by_type_daily.parquet"
OUTPUT = ROOT / "output" / "provisional" / "stable_vehicle_concentration_e0.jsonl"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAG = 30
HAC_BANDWIDTHS = (7, 14, 30, 60)
NAMED_STABLES = ("USDT", "USDC", "DAI")
MEASURES = {
    "episode_count_exact_two_leg_all_support": {
        "total": "cnt_two_leg_stable",
        "named": {symbol: f"cnt_two_leg_{symbol}" for symbol in NAMED_STABLES},
        "unit": "intermediary episodes",
        "route_scope": "exact two-leg routes without a value-agreement restriction",
    },
    "value_exact_two_leg_within_20pct": {
        "total": "usd_within_20pct_two_leg_stable",
        "named": {
            symbol: f"usd_within_20pct_two_leg_{symbol}"
            for symbol in NAMED_STABLES
        },
        "unit": "US dollars",
        "route_scope": (
            "exact two-leg routes whose source, intermediary, and destination values "
            "agree within 20 percent"
        ),
    },
}
CODE_SOURCES = [
    "scripts/run_stable_vehicle_concentration_e0.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/asset_types.py",
]


def validate_named_stable_classification() -> None:
    """Pin the named-token columns to the canonical stablecoin taxonomy."""

    stable_symbols = set(STABLE.values())
    if not set(NAMED_STABLES).issubset(stable_symbols):
        raise ValueError("named stablecoins disagree with the canonical taxonomy")
    if not set(NAMED_STABLES).issubset(VEHICLE_CANDIDATE_SYMBOLS):
        raise ValueError("named stablecoins disagree with the prespecified token columns")


def daily_concentration(
    panel: pd.DataFrame,
    *,
    measure: str = "episode_count_exact_two_leg_all_support",
) -> pd.DataFrame:
    """Construct exact shares and valid HHI bounds for each supported day."""

    validate_named_stable_classification()
    if measure not in MEASURES:
        raise ValueError(f"unknown concentration measure: {measure}")
    specification = MEASURES[measure]
    total_column = str(specification["total"])
    named_columns = dict(specification["named"])
    required = {"date", total_column, *named_columns.values()}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"intermediation panel lacks concentration fields: {missing}")
    data = panel[["date", total_column, *named_columns.values()]].copy()
    data = data.rename(
        columns={
            total_column: "stable_total",
            **{column: f"named_{symbol}" for symbol, column in named_columns.items()},
        }
    )
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    for column in ["stable_total", *(f"named_{symbol}" for symbol in NAMED_STABLES)]:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if data[column].lt(0).any():
            raise ValueError(f"intermediation panel has a negative measure: {column}")
    if data["date"].duplicated().any() or not data["date"].is_monotonic_increasing:
        raise ValueError("intermediation panel must contain one chronologically ordered row per day")

    named_total = data[[f"named_{symbol}" for symbol in NAMED_STABLES]].sum(axis=1)
    residual = data["stable_total"] - named_total
    tolerance = np.maximum(data["stable_total"].abs(), 1.0) * 1e-12
    if (residual < -tolerance).any():
        raise ValueError("named stablecoin measures exceed the all-stable total")
    data["other_stable"] = residual.clip(lower=0)
    data = data[data["stable_total"].gt(0)].copy()
    if data.empty:
        raise ValueError("intermediation panel has no supported stablecoin observations")

    denominator = data["stable_total"]
    for symbol in NAMED_STABLES:
        data[f"share_{symbol.lower()}"] = data[f"named_{symbol}"] / denominator
    residual_share = data["other_stable"] / denominator
    data["usdt_usdc_cr2"] = data["share_usdt"] + data["share_usdc"]
    named_squares = sum(data[f"share_{symbol.lower()}"] ** 2 for symbol in NAMED_STABLES)
    data["hhi_lower_bound"] = named_squares
    data["hhi_upper_bound"] = named_squares + residual_share**2
    if not (
        data["hhi_lower_bound"].between(0, 1).all()
        and data["hhi_upper_bound"].between(0, 1).all()
        and data["hhi_lower_bound"].le(data["hhi_upper_bound"] + 1e-12).all()
    ):
        raise ValueError("stablecoin concentration bounds are invalid")
    data["measure"] = measure
    return data


def _common_endpoint_sample(daily: pd.DataFrame) -> pd.DataFrame:
    sample = daily.copy()
    sample["year"] = sample["date"].dt.year
    sample = sample[sample["year"].between(BASELINE_YEAR, COMPARISON_YEAR)]
    mask = common_calendar_day_mask(
        sample["date"],
        sample["year"],
        baseline_year=BASELINE_YEAR,
        comparison_year=COMPARISON_YEAR,
    )
    sample = sample.loc[mask & sample["year"].isin([BASELINE_YEAR, COMPARISON_YEAR])].copy()
    if sample["year"].value_counts().get(BASELINE_YEAR, 0) < HAC_LAG + 1:
        raise ValueError("baseline year has too few common days for declared HAC bandwidth")
    if sample["year"].value_counts().get(COMPARISON_YEAR, 0) < HAC_LAG + 1:
        raise ValueError("comparison year has too few common days for declared HAC bandwidth")
    return sample


def concentration_results(panel: pd.DataFrame) -> pd.DataFrame:
    """Return support, aggregate magnitudes, and dependence-aware changes."""

    validate_named_stable_classification()
    rows: list[dict[str, object]] = [
        {
            "record_type": "support",
            "sample": "common month-and-day positions in 2024 and 2026",
            "baseline_year": BASELINE_YEAR,
            "comparison_year": COMPARISON_YEAR,
            "named_stablecoins": "USDT|USDC|DAI",
            "classification_authority": (
                "src/ddvc/asset_types.py; USDT, USDC, and DAI are stablecoins and "
                "prespecified named-token columns"
            ),
            "episode_denominator": (
                "stablecoin intermediary episodes on exact two-leg routes; no "
                "value-agreement restriction"
            ),
            "value_denominator": (
                "stablecoin intermediary dollars on exact two-leg routes within the "
                "20 percent source-intermediary-destination value agreement screen"
            ),
            "count_companion_status": (
                "unavailable: the current owner has exact-two-leg counts but no counts "
                "restricted by the 20 percent value-agreement flag; count and value "
                "results are different universes and are not compared as companions"
            ),
            "cr2_definition": (
                "prespecified USDT plus USDC share of the stated stablecoin denominator; "
                "not a rank-selected top-two statistic"
            ),
            "cr2_hhi_distinction": (
                "CR2 records the combined share of USDT and USDC; HHI records how shares "
                "are distributed. A rising CR2 is not called rising concentration and can "
                "coexist with flat or falling HHI when USDT and USDC become more balanced"
            ),
            "hhi_lower_definition": "sum of squared named-token shares; residual stable share atomistically split",
            "hhi_upper_definition": "sum of squared named-token shares plus squared residual stable share",
            "residual_use": (
                "the unidentified residual stablecoin share enters only the HHI bounds; "
                "it is not reported or interpreted as a separate result"
            ),
            "inference": (
                "endpoint-year-only Newey-West Bartlett covariance on equal-weighted "
                "daily observations; 2025 is excluded"
            ),
            "hac_lag_days": HAC_LAG,
            "hac_bandwidth_sensitivity_days": "7|14|30|60",
            "empirical_finance_benchmark": (
                "Griffin and Shams (2020, Journal of Finance), Figure 4 reports underlying "
                "account-flow shares; it supports keeping shares visible, not this HHI or "
                "HAC specification"
            ),
            "claim_limit": (
                "descriptive concentration; does not identify succession, fragmentation, "
                "market power, or causality; residual stablecoin identities are unavailable"
            ),
        }
    ]

    metrics = (
        "usdt_usdc_cr2",
        "hhi_lower_bound",
        "hhi_upper_bound",
    )
    for measure, specification in MEASURES.items():
        daily = daily_concentration(panel, measure=measure)
        sample = _common_endpoint_sample(daily)
        rows.append(
            {
                "record_type": "measure_support",
                "measure": measure,
                "unit": specification["unit"],
                "route_scope": specification["route_scope"],
                "baseline_days": int(sample["year"].eq(BASELINE_YEAR).sum()),
                "comparison_days": int(sample["year"].eq(COMPARISON_YEAR).sum()),
                "hac_lag_days": HAC_LAG,
                "covariance_years": "2024|2026",
                "intervening_year_in_covariance": False,
                "hac_bandwidth_sensitivity_days": "7|14|30|60",
                "inference_weighting": "equal-weighted daily concentration",
                "magnitude_weighting": "pooled within endpoint year",
            }
        )
        for year in (BASELINE_YEAR, COMPARISON_YEAR):
            group = sample[sample["year"].eq(year)]
            total = float(group["stable_total"].sum())
            token_totals = {
                symbol: float(group[f"named_{symbol}"].sum())
                for symbol in NAMED_STABLES
            }
            residual = float(group["other_stable"].sum())
            shares = {symbol: value / total for symbol, value in token_totals.items()}
            residual_share = residual / total
            lower = sum(value**2 for value in shares.values())
            rows.append(
                {
                    "record_type": "aggregate_magnitude",
                    "measure": measure,
                    "unit": specification["unit"],
                    "route_scope": specification["route_scope"],
                    "year": year,
                    "days": int(len(group)),
                    "stable_measure_total": total,
                    "usdt_share": shares["USDT"],
                    "usdc_share": shares["USDC"],
                    "dai_share": shares["DAI"],
                    "usdt_usdc_cr2": shares["USDT"] + shares["USDC"],
                    "hhi_lower_bound": lower,
                    "hhi_upper_bound": lower + residual_share**2,
                    "weighting": "pooled within endpoint year",
                }
            )

        inference_rows: list[dict[str, object]] = []
        for hac_lag in HAC_BANDWIDTHS:
            for metric in metrics:
                estimate = year_endpoint_change(
                    sample[metric],
                    sample["year"],
                    baseline_year=BASELINE_YEAR,
                    comparison_year=COMPARISON_YEAR,
                    hac_lag=hac_lag,
                    dates=sample["date"],
                )
                inference_rows.append(
                    {
                        "record_type": "endpoint_change",
                        "measure": measure,
                        "unit": specification["unit"],
                        "route_scope": specification["route_scope"],
                        "metric": metric,
                        "baseline_daily_mean": estimate.baseline_mean,
                        "comparison_daily_mean": estimate.comparison_mean,
                        "change": estimate.change,
                        "hac_standard_error": estimate.standard_error,
                        "t_statistic": estimate.t_statistic,
                        "p_value": estimate.p_value,
                        "days": estimate.n_observations,
                        "hac_lag_days": hac_lag,
                        "primary_bandwidth": hac_lag == HAC_LAG,
                        "covariance_years": "2024|2026",
                        "intervening_year_in_covariance": False,
                        "weighting": "equal-weighted daily concentration",
                    }
                )
        inference = pd.DataFrame(inference_rows)
        inference["p_value_holm"] = inference.groupby(
            "hac_lag_days", sort=False
        )["p_value"].transform(holm_adjusted_pvalues)
        rows.extend(inference.to_dict("records"))
    return pd.DataFrame(rows)


def main() -> int:
    try:
        with current_artifacts([INPUT], consumer="stable-vehicle concentration E0"):
            panel = pd.read_parquet(INPUT)
            results = concentration_results(panel)
            write_exhibit(
                results,
                OUTPUT,
                code_sources=CODE_SOURCES,
                inputs=[INPUT],
                notes=(
                    "E0 only; stablecoin intermediary CR2 and HHI bounds; endpoint-year-only "
                    "daily HAC inference with bandwidth sensitivity; residual identities withheld"
                ),
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"stable-vehicle concentration E0 blocked: {error}", file=sys.stderr)
        return 2

    display = results[
        results["record_type"].eq("endpoint_change")
        & results["primary_bandwidth"].fillna(False)
    ]
    print(display[["measure", "metric", "baseline_daily_mean", "comparison_daily_mean", "change", "hac_standard_error", "p_value_holm"]].to_string(index=False))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
