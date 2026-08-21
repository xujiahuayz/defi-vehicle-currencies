#!/usr/bin/env python3
"""Render exact-output consequences of observed vehicle-family choice."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


SUPPORT = OUTPUT_DIR / "exhibits" / "contestable_vehicle_choice_support.jsonl"

POOLED_SAMPLE = "contestable_symmetric_common_support"
RETAINED_SAMPLE = (
    "mature_exclusive_entry_symmetric_common_support:incumbent_retained"
)
AGE_SAMPLES: tuple[tuple[str, str, str], ...] = (
    (
        "0_to_89_days",
        "contestable_symmetric_common_support:0_to_89_days",
        r"Pairs aged 0--89 days",
    ),
    (
        "90_to_364_days",
        "contestable_symmetric_common_support:90_to_364_days",
        r"Pairs aged 90--364 days",
    ),
    (
        "365_plus_days",
        "contestable_symmetric_common_support:365_plus_days",
        r"Pairs aged at least 365 days",
    ),
)


def _select_row(
    support: pd.DataFrame,
    *,
    record_type: str,
    sample: str,
    split_dimension: str,
    split_category: str,
) -> pd.Series:
    selected = support[
        support["record_type"].eq(record_type)
        & support["sample"].eq(sample)
        & support["split_dimension"].eq(split_dimension)
        & support["split_category"].eq(split_category)
    ]
    if len(selected) != 1:
        raise ValueError(
            "expected one vehicle-consequence row for "
            f"{sample}; found {len(selected)}"
        )
    return selected.iloc[0]


def _validate_row(row: pd.Series, *, sample: str) -> None:
    expected = {
        "comparison": (
            "best exact public route in the observed vehicle family versus the "
            "best exact public route in the rival vehicle family"
        ),
        "exact_venue_scope": "uniswap_v2+sushiswap_v2+uniswap_v3",
        "quoted_vehicle_universe": "WETH+DAI+USDC+USDT",
        "loss_bps_denominator": "exact output from observed vehicle family",
        "weighting": "observed_route_input_value_usd",
        "output_difference_rule": "strictly_greater_than_threshold",
    }
    for field, value in expected.items():
        if row[field] != value:
            raise ValueError(f"unexpected {field} for vehicle-consequence sample {sample}")

    numeric_expected = {
        "minimum_output_difference_bps": 1.0,
        "quoted_alternative_max_leg_price_impact": 0.05,
        "weighted_loss_below_threshold_bps": 0.0,
    }
    for field, value in numeric_expected.items():
        if float(row[field]) != value:
            raise ValueError(f"unexpected {field} for vehicle-consequence sample {sample}")

    if not bool(row["cell_meets_minimum_support"]):
        raise ValueError(f"vehicle-consequence sample {sample} lacks minimum support")
    if not bool(row["conditional_loss_meets_minimum_support"]):
        raise ValueError(
            f"vehicle-consequence sample {sample} lacks conditional-loss support"
        )
    if bool(row["gas_consequence_reported"]):
        raise ValueError(f"vehicle-consequence sample {sample} unexpectedly includes gas")
    if bool(row["causal_interpretation"]):
        raise ValueError(f"vehicle-consequence sample {sample} is marked causal")
    if int(row["routes"]) <= 0 or int(row["lower_output_family_routes"]) <= 0:
        raise ValueError(f"vehicle-consequence sample {sample} has no usable routes")


def _percent(value: object) -> str:
    return rf"{100.0 * float(value):.1f}\%"


def _basis_points(value: object) -> str:
    return f"{float(value):.1f}"


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def render_contestable_vehicle_consequences(support: pd.DataFrame) -> str:
    """Return a compact table of route-level output shortfalls."""

    required = {
        "record_type",
        "sample",
        "split_dimension",
        "split_category",
        "comparison",
        "exact_venue_scope",
        "quoted_vehicle_universe",
        "loss_bps_denominator",
        "weighting",
        "output_difference_rule",
        "minimum_output_difference_bps",
        "quoted_alternative_max_leg_price_impact",
        "weighted_loss_below_threshold_bps",
        "cell_meets_minimum_support",
        "conditional_loss_meets_minimum_support",
        "gas_consequence_reported",
        "causal_interpretation",
        "routes",
        "lower_output_family_routes",
        "lower_output_family_share",
        "median_foregone_output_bps_if_over_1bp",
        "p90_foregone_output_bps_if_over_1bp",
        "input_value_weighted_foregone_bps",
        "split_categories_exhaustive_within_parent_sample",
        "split_categories_mutually_exclusive",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        raise ValueError(f"vehicle-consequence support lacks table fields: {missing}")

    pooled = _select_row(
        support,
        record_type="family_output_consequence",
        sample=POOLED_SAMPLE,
        split_dimension="all",
        split_category="all",
    )
    retained = _select_row(
        support,
        record_type="family_output_consequence_split",
        sample=RETAINED_SAMPLE,
        split_dimension="mature_exclusive_route_choice",
        split_category="incumbent_retained",
    )
    age_rows: list[tuple[str, pd.Series]] = []
    for category, sample, label in AGE_SAMPLES:
        age_rows.append(
            (
                label,
                _select_row(
                    support,
                    record_type="family_output_consequence_split",
                    sample=sample,
                    split_dimension="pair_age",
                    split_category=category,
                ),
            )
        )

    for sample, row in ((POOLED_SAMPLE, pooled), (RETAINED_SAMPLE, retained)):
        _validate_row(row, sample=sample)
    for (_, sample, _), (_, row) in zip(AGE_SAMPLES, age_rows, strict=True):
        _validate_row(row, sample=sample)
        if not bool(row["split_categories_exhaustive_within_parent_sample"]):
            raise ValueError("pair-age consequence categories must be exhaustive")
        if not bool(row["split_categories_mutually_exclusive"]):
            raise ValueError("pair-age consequence categories must be mutually exclusive")
    if sum(int(row["routes"]) for _, row in age_rows) != int(pooled["routes"]):
        raise ValueError("pair-age consequence rows do not partition the pooled sample")

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xr@{\hspace{1.6em}}r@{}}",
        r"\toprule",
        r"Measure & Estimate & Routes \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. All contestable routes}} \\",
        r"Observed family has an exact-output shortfall above 1 bp [\%] & "
        + _percent(pooled["lower_output_family_share"])
        + " & "
        + _integer(pooled["routes"])
        + r" \\",
        "Conditional median shortfall [bp] & "
        + _basis_points(pooled["median_foregone_output_bps_if_over_1bp"])
        + " & "
        + _integer(pooled["lower_output_family_routes"])
        + r" \\",
        "Conditional 90th-percentile shortfall [bp] & "
        + _basis_points(pooled["p90_foregone_output_bps_if_over_1bp"])
        + " & "
        + _integer(pooled["lower_output_family_routes"])
        + r" \\",
        "Input-value-weighted mean shortfall [bp] & "
        + _basis_points(pooled["input_value_weighted_foregone_bps"])
        + " & "
        + _integer(pooled["routes"])
        + r" \\",
        r"\addlinespace",
        r"\multicolumn{3}{@{}l}{\textit{Panel B. Routes retaining a mature exclusive incumbent}} \\",
        r"Observed family has an exact-output shortfall above 1 bp [\%] & "
        + _percent(retained["lower_output_family_share"])
        + " & "
        + _integer(retained["routes"])
        + r" \\",
        "Conditional median shortfall [bp] & "
        + _basis_points(retained["median_foregone_output_bps_if_over_1bp"])
        + " & "
        + _integer(retained["lower_output_family_routes"])
        + r" \\",
        "Input-value-weighted mean shortfall [bp] & "
        + _basis_points(retained["input_value_weighted_foregone_bps"])
        + " & "
        + _integer(retained["routes"])
        + r" \\",
        r"\addlinespace",
        r"\multicolumn{3}{@{}l}{\textit{Panel C. Input-value-weighted mean shortfall by pair age}} \\",
    ]
    for label, row in age_rows:
        lines.append(
            label
            + " [bp] & "
            + _basis_points(row["input_value_weighted_foregone_bps"])
            + " & "
            + _integer(row["routes"])
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def main() -> int:
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "contestable_vehicle_consequences",
        render_contestable_vehicle_consequences(support),
        preview_width="8.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
