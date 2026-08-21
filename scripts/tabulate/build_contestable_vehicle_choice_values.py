#!/usr/bin/env python3
"""Build paper and deck macros for contestable vehicle choice."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits" / "contestable_vehicle_choice.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "contestable_vehicle_choice_support.jsonl"
VALUES = OUTPUT_DIR / "exhibits" / "contestable_vehicle_choice_values.tex"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        if column not in selected.columns:
            raise ValueError(f"contestable-choice data lack selector column {column}")
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _signed_pp(value: float) -> str:
    return f"${value:+.2f}$ pp"


def _unsigned_pp(value: float) -> str:
    return f"${value:.2f}$ pp"


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _bp(value: float) -> str:
    return f"{value:.1f} bp"


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}".replace(",", "{,}")


def _finite(row: pd.Series, *columns: str) -> None:
    for column in columns:
        if not math.isfinite(float(row[column])):
            raise ValueError(f"contestable-choice row has non-finite {column}")


def render_contestable_vehicle_choice_values(
    estimates: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    required_estimate_fields = {
        "record_type",
        "model_id",
        "sample",
        "outcome",
        "regressor",
        "coefficient_pp",
        "standard_error_pp",
        "observations",
    }
    missing_estimate_fields = sorted(required_estimate_fields - set(estimates.columns))
    if missing_estimate_fields:
        raise ValueError(
            "contestable-choice estimates lack macro fields: "
            f"{missing_estimate_fields}"
        )
    required_support_fields = {
        "record_type",
        "sample",
        "routes",
        "incumbent_retained_share",
        "lower_output_family_share",
        "median_foregone_output_bps_if_over_1bp",
        "p90_foregone_output_bps_if_over_1bp",
        "input_value_weighted_foregone_bps",
    }
    missing_support_fields = sorted(required_support_fields - set(support.columns))
    if missing_support_fields:
        raise ValueError(
            "contestable-choice support lacks macro fields: "
            f"{missing_support_fields}"
        )

    price_leader = _single(
        estimates,
        record_type="contestable_vehicle_choice_regression",
        model_id="stable_choice_price_leader",
        sample="contestable_symmetric_common_support",
        outcome="chosen_stable",
        regressor="stable_price_leader",
    )
    challenger = _single(
        estimates,
        record_type="contestable_vehicle_choice_regression",
        model_id="exclusive_incumbent_retention_price_leader",
        sample="mature_exclusive_entry_symmetric_common_support",
        outcome="incumbent_retained",
        regressor="challenger_price_leader",
    )
    output_advantage = _single(
        estimates,
        record_type="contestable_vehicle_choice_regression",
        model_id="exclusive_retention_price_v2_capital",
        sample="mature_exclusive_entry_positive_v2_bridge_capital",
        outcome="incumbent_retained",
        regressor="incumbent_output_advantage_100bp",
    )
    capital_advantage = _single(
        estimates,
        record_type="contestable_vehicle_choice_regression",
        model_id="exclusive_retention_price_v2_capital",
        sample="mature_exclusive_entry_positive_v2_bridge_capital",
        outcome="incumbent_retained",
        regressor="incumbent_v2_capital_advantage_10pp",
    )
    incumbent_leads = _single(
        support,
        record_type="incumbent_price_relation_summary",
        sample="incumbent_price_leader",
    )
    challenger_leads = _single(
        support,
        record_type="incumbent_price_relation_summary",
        sample="challenger_price_leader",
    )
    consequence = _single(
        support,
        record_type="family_output_consequence",
        sample="contestable_symmetric_common_support",
    )

    for row in (price_leader, challenger, output_advantage, capital_advantage):
        _finite(row, "coefficient_pp", "standard_error_pp", "observations")
        if float(row["standard_error_pp"]) <= 0 or float(row["observations"]) <= 0:
            raise ValueError("contestable-choice regression support must be positive")
    for row in (incumbent_leads, challenger_leads):
        _finite(row, "incumbent_retained_share", "routes")
        if not 0 <= float(row["incumbent_retained_share"]) <= 1:
            raise ValueError("incumbent-retention share lies outside [0, 1]")
        if float(row["routes"]) <= 0:
            raise ValueError("incumbent-retention state has no routes")
    _finite(
        consequence,
        "lower_output_family_share",
        "median_foregone_output_bps_if_over_1bp",
        "p90_foregone_output_bps_if_over_1bp",
        "input_value_weighted_foregone_bps",
    )
    if not 0 <= float(consequence["lower_output_family_share"]) <= 1:
        raise ValueError("lower-output-family share lies outside [0, 1]")
    if not (
        float(consequence["p90_foregone_output_bps_if_over_1bp"])
        >= float(consequence["median_foregone_output_bps_if_over_1bp"])
        > 0
        and float(consequence["input_value_weighted_foregone_bps"]) >= 0
    ):
        raise ValueError("foregone-output statistics have invalid ordering")
    if not (
        float(price_leader["coefficient_pp"]) > 0
        and float(challenger["coefficient_pp"]) < 0
        and float(output_advantage["coefficient_pp"]) > 0
        and float(capital_advantage["coefficient_pp"]) > 0
    ):
        raise ValueError("contestable-choice coefficient directions changed")
    if int(output_advantage["observations"]) != int(capital_advantage["observations"]):
        raise ValueError("joint price-capital regressors use different samples")

    lines = [
        "% Generated by scripts/tabulate/build_contestable_vehicle_choice_values.py; do not edit.",
        f"\\newcommand{{\\ContestPriceLeaderEffect}}{{{_signed_pp(float(price_leader['coefficient_pp']))}}}",
        f"\\newcommand{{\\ContestPriceLeaderSE}}{{{_unsigned_pp(float(price_leader['standard_error_pp']))}}}",
        f"\\newcommand{{\\ContestPriceLeaderN}}{{{_integer(price_leader['observations'])}}}",
        f"\\newcommand{{\\ContestChallengerEffect}}{{{_signed_pp(float(challenger['coefficient_pp']))}}}",
        f"\\newcommand{{\\ContestChallengerSE}}{{{_unsigned_pp(float(challenger['standard_error_pp']))}}}",
        f"\\newcommand{{\\ContestChallengerN}}{{{_integer(challenger['observations'])}}}",
        f"\\newcommand{{\\ContestOutputAdvantageHundredBpEffect}}{{{_signed_pp(float(output_advantage['coefficient_pp']))}}}",
        f"\\newcommand{{\\ContestOutputAdvantageHundredBpSE}}{{{_unsigned_pp(float(output_advantage['standard_error_pp']))}}}",
        f"\\newcommand{{\\ContestOutputAdvantageHundredBpN}}{{{_integer(output_advantage['observations'])}}}",
        f"\\newcommand{{\\ContestCapitalAdvantageTenPpEffect}}{{{_signed_pp(float(capital_advantage['coefficient_pp']))}}}",
        f"\\newcommand{{\\ContestCapitalAdvantageTenPpSE}}{{{_unsigned_pp(float(capital_advantage['standard_error_pp']))}}}",
        f"\\newcommand{{\\ContestCapitalAdvantageTenPpN}}{{{_integer(capital_advantage['observations'])}}}",
        f"\\newcommand{{\\ContestIncumbentLeaderRetention}}{{{_pct(float(incumbent_leads['incumbent_retained_share']))}}}",
        f"\\newcommand{{\\ContestIncumbentLeaderN}}{{{_integer(incumbent_leads['routes'])}}}",
        f"\\newcommand{{\\ContestChallengerLeaderRetention}}{{{_pct(float(challenger_leads['incumbent_retained_share']))}}}",
        f"\\newcommand{{\\ContestChallengerLeaderN}}{{{_integer(challenger_leads['routes'])}}}",
        f"\\newcommand{{\\ContestLowerOutputFamilyShare}}{{{_pct(float(consequence['lower_output_family_share']))}}}",
        f"\\newcommand{{\\ContestForegoneMedianBps}}{{{_bp(float(consequence['median_foregone_output_bps_if_over_1bp']))}}}",
        f"\\newcommand{{\\ContestForegonePNinetyBps}}{{{_bp(float(consequence['p90_foregone_output_bps_if_over_1bp']))}}}",
        f"\\newcommand{{\\ContestForegoneInputValueWeightedBps}}{{{_bp(float(consequence['input_value_weighted_foregone_bps']))}}}",
    ]
    return "\n".join(lines) + "\n"


def run(
    *,
    estimates_path: Path = ESTIMATES,
    support_path: Path = SUPPORT,
    output_path: Path = VALUES,
) -> int:
    for path in (estimates_path, support_path):
        require_presentation_source(path)
    estimates = pd.read_json(estimates_path, lines=True)
    support = pd.read_json(support_path, lines=True)
    rendered = render_contestable_vehicle_choice_values(estimates, support)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--output", type=Path, default=VALUES)
    args = parser.parse_args()
    return run(
        estimates_path=args.estimates,
        support_path=args.support,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
