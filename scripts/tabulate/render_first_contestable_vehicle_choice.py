#!/usr/bin/env python3
"""Render first-contestability sample facts and vehicle-choice regressions."""

from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import read_exhibit


RESULTS = OUTPUT_DIR / "exhibits" / "first_contestable_vehicle_choice.jsonl"
SUPPORT = (
    OUTPUT_DIR / "exhibits" / "first_contestable_vehicle_choice_support.jsonl"
)
VALUES = OUTPUT_DIR / "exhibits" / "first_contestable_vehicle_choice_values.tex"


@dataclass(frozen=True)
class RegressionColumn:
    model_id: str
    sample: str
    outcome: str
    heading: str


COLUMNS: tuple[RegressionColumn, ...] = (
    RegressionColumn(
        model_id="price_only_all_first_contestable",
        sample="all_first_sampled_exact_contestable_routes",
        outcome="chosen_stable",
        heading=r"\begin{tabular}{@{}c@{}}Stablecoin\\chosen\end{tabular}",
    ),
    RegressionColumn(
        model_id="r1_entry_retention_price_only",
        sample="clear_entry_family_first_contestable_positive_capital",
        outcome="entry_vehicle_retained",
        heading=r"\begin{tabular}{@{}c@{}}Entry family\\retained\end{tabular}",
    ),
    RegressionColumn(
        model_id="r3_entry_retention_price_and_capital",
        sample="clear_entry_family_first_contestable_positive_capital",
        outcome="entry_vehicle_retained",
        heading=r"\begin{tabular}{@{}c@{}}Entry family\\retained\end{tabular}",
    ),
)


REGRESSORS: tuple[tuple[str, str], ...] = (
    (
        "stable_output_advantage_100bp",
        r"Stablecoin current exact-output advantage [per 100 bp]",
    ),
    (
        "entry_vehicle_output_advantage_100bp",
        r"Entry-family current exact-output advantage [per 100 bp]",
    ),
    (
        "entry_vehicle_v2_capital_share_10pp",
        r"Entry-family prior-day V2 weak-leg capital share [per 10 pp]",
    ),
    (
        "log_input_usd",
        r"Log route input value [per log point]",
    ),
)


def _stars(p_value: object) -> str:
    value = float(p_value)
    if value < 0.01:
        return "^{***}"
    if value < 0.05:
        return "^{**}"
    if value < 0.10:
        return "^{*}"
    return ""


def _integer(value: object, *, tex: bool = False) -> str:
    rendered = f"{int(round(float(value))):,}"
    return rendered.replace(",", "{,}") if tex else rendered


def _percent(value: object, digits: int = 1) -> str:
    return f"{100.0 * float(value):.{digits}f}\\%"


def _days(value: object) -> str:
    rounded = round(float(value))
    if math.isclose(float(value), rounded, abs_tol=1e-10):
        return f"{int(rounded):,}"
    return f"{float(value):,.1f}"


def _support_row(support: pd.DataFrame, sample: str) -> pd.Series:
    selected = support[
        support["record_type"].eq("first_contestable_vehicle_choice_support")
        & support["sample"].eq(sample)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one first-contestability support row for {sample}; "
            f"found {len(selected)}"
        )
    return selected.iloc[0]


def _model_rows(results: pd.DataFrame, column: RegressionColumn) -> pd.DataFrame:
    selected = results[
        results["record_type"].eq(
            "first_contestable_vehicle_choice_regression"
        )
        & results["model_id"].eq(column.model_id)
        & results["sample"].eq(column.sample)
        & results["outcome"].eq(column.outcome)
    ].copy()
    if selected.empty:
        raise ValueError(f"missing first-contestability model {column.model_id}")
    if selected["regressor"].duplicated().any():
        raise ValueError(
            f"duplicate regressors in first-contestability model {column.model_id}"
        )
    return selected.set_index("regressor", drop=False)


def _model_row(
    results: pd.DataFrame, model_id: str, outcome: str, regressor: str
) -> pd.Series:
    selected = results[
        results["record_type"].eq(
            "first_contestable_vehicle_choice_regression"
        )
        & results["model_id"].eq(model_id)
        & results["outcome"].eq(outcome)
        & results["regressor"].eq(regressor)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {regressor} row for {model_id}; found {len(selected)}"
        )
    return selected.iloc[0]


def _validate(results: pd.DataFrame, support: pd.DataFrame) -> None:
    required_results = {
        "record_type",
        "model_id",
        "sample",
        "outcome",
        "regressor",
        "coefficient_pp",
        "standard_error_pp",
        "p_value",
        "observations",
        "ordered_pairs",
        "dates",
        "ordered_pair_clusters",
        "date_clusters",
        "fixed_effects",
        "covariance",
        "within_r_squared",
        "dependent_mean",
        "choice_timing",
        "capital_timing",
        "entry_value_threshold_usd",
        "minimum_route_input_usd",
        "maximum_leg_price_impact",
        "value_agreement_threshold",
    }
    required_support = {
        "record_type",
        "sample",
        "entry_pairs",
        "entry_dates",
        "entry_value_threshold_usd",
        "pairs_reaching_sampled_contestability",
        "contestability_coverage_share",
        "routes",
        "ordered_pairs",
        "dates",
        "pairs",
        "median_days",
        "p25_days",
        "p75_days",
        "p90_days",
        "within_120_days_share",
        "route_weighted_retention_share",
        "route_weighted_routes",
        "equal_pair_retention_share",
        "equal_pair_pairs",
    }
    missing_results = sorted(required_results - set(results.columns))
    missing_support = sorted(required_support - set(support.columns))
    if missing_results:
        raise ValueError(f"first-contestability results lack fields: {missing_results}")
    if missing_support:
        raise ValueError(f"first-contestability support lacks fields: {missing_support}")

    entry = _support_row(support, "material_entry_cohort")
    first = _support_row(support, "first_sampled_exact_contestable_routes")
    lag = _support_row(support, "entry_to_first_sampled_contestability_lag")
    survival = _support_row(support, "entry_vehicle_survival")
    capital = _support_row(support, "positive_both_family_prior_v2_capital")

    if not (
        float(entry["entry_pairs"])
        > float(entry["pairs_reaching_sampled_contestability"])
        > 0
    ):
        raise ValueError("sampled contestability must be a subset of original entry")
    implied_coverage = float(entry["pairs_reaching_sampled_contestability"]) / float(
        entry["entry_pairs"]
    )
    if not math.isclose(
        implied_coverage,
        float(entry["contestability_coverage_share"]),
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ValueError("contestability coverage is inconsistent with pair counts")
    if not (
        float(lag["p25_days"])
        <= float(lag["median_days"])
        <= float(lag["p75_days"])
        <= float(lag["p90_days"])
    ):
        raise ValueError("entry-to-contestability lag quantiles are unordered")
    for field in (
        "within_120_days_share",
        "route_weighted_retention_share",
        "equal_pair_retention_share",
    ):
        owner = lag if field == "within_120_days_share" else survival
        if not 0 <= float(owner[field]) <= 1:
            raise ValueError(f"{field} lies outside [0, 1]")
    if int(first["ordered_pairs"]) != int(lag["pairs"]):
        raise ValueError("first-contest route and lag panels disagree on pair count")
    if int(first["routes"]) <= int(capital["routes"]):
        raise ValueError("positive-capital routes must be a strict subsample")

    models = [_model_rows(results, column) for column in COLUMNS]
    required_by_model = (
        ("stable_output_advantage_100bp", "log_input_usd"),
        ("entry_vehicle_output_advantage_100bp", "log_input_usd"),
        (
            "entry_vehicle_output_advantage_100bp",
            "entry_vehicle_v2_capital_share_10pp",
            "log_input_usd",
        ),
    )
    for model, column, required in zip(models, COLUMNS, required_by_model, strict=True):
        for regressor in required:
            if regressor not in model.index:
                raise ValueError(
                    f"first-contestability model {column.model_id} lacks {regressor}"
                )
        for field in (
            "observations",
            "ordered_pairs",
            "dates",
            "ordered_pair_clusters",
            "date_clusters",
            "fixed_effects",
            "covariance",
            "within_r_squared",
            "dependent_mean",
            "choice_timing",
            "capital_timing",
            "entry_value_threshold_usd",
            "minimum_route_input_usd",
            "maximum_leg_price_impact",
            "value_agreement_threshold",
        ):
            if model[field].nunique(dropna=False) != 1:
                raise ValueError(
                    f"first-contestability model {column.model_id} has inconsistent {field}"
                )
        anchor = model.iloc[0]
        if anchor["choice_timing"] != (
            "first_sampled_exact_contestable_date_after_entry"
        ):
            raise ValueError("regression date is not the first sampled exact contest")
        if anchor["capital_timing"] != "exact_prior_calendar_day":
            raise ValueError("capital must precede the sampled contest")
        if anchor["fixed_effects"] != (
            "calendar_date+source_token+destination_token+observed_route_scope"
        ):
            raise ValueError("unexpected fixed effects in first-contestability model")
        if anchor["covariance"] != "two_way_ordered_pair_calendar_date_cr1":
            raise ValueError("unexpected covariance in first-contestability model")

    broad, retention_output, retention_joint = [model.iloc[0] for model in models]
    if int(broad["observations"]) != int(first["routes"]):
        raise ValueError("broad price model and first-contest routes disagree")
    for field in (
        "observations",
        "ordered_pairs",
        "dates",
        "ordered_pair_clusters",
        "date_clusters",
        "dependent_mean",
    ):
        if not math.isclose(
            float(retention_output[field]),
            float(retention_joint[field]),
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("nested retention models use different samples")


def _effect_cell(model: pd.DataFrame, regressor: str) -> str:
    if regressor not in model.index:
        return ""
    row = model.loc[regressor]
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['coefficient_pp']):+.2f}{_stars(row['p_value'])}$"
        r"\\"
        f"$({float(row['standard_error_pp']):.2f})$"
        r"\end{tabular}"
    )


def _sample_panel(support: pd.DataFrame) -> str:
    entry = _support_row(support, "material_entry_cohort")
    first = _support_row(support, "first_sampled_exact_contestable_routes")
    lag = _support_row(support, "entry_to_first_sampled_contestability_lag")
    survival = _support_row(support, "entry_vehicle_survival")
    capital = _support_row(support, "positive_both_family_prior_v2_capital")
    return "\n".join(
        [
            r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr@{}}",
            r"\toprule",
            r"\multicolumn{3}{@{}l}{\textit{Panel A. From original pair entry to the first sampled exact contest}} \\",
            r"Quantity & Primary value & Additional detail \\",
            r"\midrule",
            "Original pair-entry cohort & "
            + _integer(entry["entry_pairs"])
            + " pairs & "
            + _integer(entry["entry_dates"])
            + " entry dates; \\$"
            + _integer(entry["entry_value_threshold_usd"])
            + r" minimum \\",
            "First sampled exact contest & "
            + _integer(first["ordered_pairs"])
            + " pairs & "
            + _integer(first["routes"])
            + r" routes \\",
            "Entry pairs reaching a sampled contest & "
            + _percent(entry["contestability_coverage_share"])
            + r" & \\",
            "Entry-to-contest lag [days] & "
            + _days(lag["median_days"])
            + " median & "
            + _days(lag["p25_days"])
            + "--"
            + _days(lag["p75_days"])
            + r" interquartile range \\",
            "Contest reached within 120 days & "
            + _percent(lag["within_120_days_share"])
            + r" & \\",
            "Entry family retained, clear comparisons & "
            + _percent(survival["route_weighted_retention_share"])
            + " of routes & "
            + _percent(survival["equal_pair_retention_share"])
            + r" of pairs \\",
            "Positive prior-day V2 capital for both families & "
            + _integer(capital["routes"])
            + " routes & "
            + _integer(capital["ordered_pairs"])
            + r" pairs \\",
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    )


def _regression_panel(results: pd.DataFrame) -> str:
    models = [_model_rows(results, column) for column in COLUMNS]
    anchors = [model.iloc[0] for model in models]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.55\hsize\raggedright\arraybackslash}X*{3}{>{\hsize=.82\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{4}{@{}l}{\textit{Panel B. Route choice at the first sampled exact contest}} \\",
        r" & (1) & (2) & (3) \\",
        "Outcome; effects [pp] & "
        + " & ".join(column.heading for column in COLUMNS)
        + r" \\",
        r"\midrule",
    ]
    for regressor, label in REGRESSORS:
        lines.append(
            label
            + " & "
            + " & ".join(_effect_cell(model, regressor) for model in models)
            + r" \\"
        )
    lines.extend(
        [
            r"\addlinespace",
            "Dependent mean [\\%] & "
            + " & ".join(
                f"{100.0 * float(anchor['dependent_mean']):.1f}"
                for anchor in anchors
            )
            + r" \\",
            "Within $R^2$ & "
            + " & ".join(
                f"{float(anchor['within_r_squared']):.3f}" for anchor in anchors
            )
            + r" \\",
            "Observations (routes) & "
            + " & ".join(_integer(anchor["observations"]) for anchor in anchors)
            + r" \\",
            "Ordered endpoint pairs & "
            + " & ".join(_integer(anchor["ordered_pairs"]) for anchor in anchors)
            + r" \\",
            "Dates & "
            + " & ".join(_integer(anchor["dates"]) for anchor in anchors)
            + r" \\",
            r"Prior-day V2 capital positive for both families & No & Yes & Yes \\",
            r"Date, source, destination, and route-scope fixed effects & Yes & Yes & Yes \\",
            r"Pair- and date-clustered s.e. & Yes & Yes & Yes \\",
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    )
    return "\n".join(lines)


def render_first_contestable_vehicle_choice(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return compact sample and regression panels as a TeX fragment."""

    _validate(results, support)
    return (
        _sample_panel(support)
        + "\n\n"
        + r"\vspace{0.65em}"
        + "\n\n"
        + _regression_panel(results)
        + "\n"
        + "% Paper note: Original pair entry is the first material observed "
        "activity for an ordered endpoint pair. The first sampled exact contest "
        "is the first monthly exact-state date after entry on which both a WETH "
        "path and a DAI, USDC, or USDT path are feasible for an observed route "
        "under common quote rules. Exact output is measured from the "
        "pre-transaction state and its advantage is capped at 1,000 bp in "
        "absolute value. Capital is prior-calendar-day V2 full-range deposited "
        "capital on the weaker route leg; the regressor is the entry family's "
        "share of the two families' capital, centered at 50 percent. All models "
        "include log input value and date, source-asset, destination-asset, and "
        "observed-route-scope fixed effects. Standard errors are clustered by "
        "ordered endpoint pair and date. Asterisks *, **, and *** denote "
        "statistical significance at the 10 percent, 5 percent, and 1 percent "
        "levels, respectively.\n"
    )


def render_first_contestable_vehicle_choice_values(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return generated values from the same rows as the table."""

    _validate(results, support)
    entry = _support_row(support, "material_entry_cohort")
    first = _support_row(support, "first_sampled_exact_contestable_routes")
    lag = _support_row(support, "entry_to_first_sampled_contestability_lag")
    survival = _support_row(support, "entry_vehicle_survival")
    capital = _support_row(support, "positive_both_family_prior_v2_capital")
    stable_output = _model_row(
        results,
        "price_only_all_first_contestable",
        "chosen_stable",
        "stable_output_advantage_100bp",
    )
    retention_output = _model_row(
        results,
        "r1_entry_retention_price_only",
        "entry_vehicle_retained",
        "entry_vehicle_output_advantage_100bp",
    )
    retention_joint_output = _model_row(
        results,
        "r3_entry_retention_price_and_capital",
        "entry_vehicle_retained",
        "entry_vehicle_output_advantage_100bp",
    )
    retention_joint_capital = _model_row(
        results,
        "r3_entry_retention_price_and_capital",
        "entry_vehicle_retained",
        "entry_vehicle_v2_capital_share_10pp",
    )

    def signed_pp(value: object) -> str:
        return f"${float(value):+.2f}$ pp"

    def unsigned_pp(value: object) -> str:
        return f"${abs(float(value)):.2f}$ pp"

    lines = [
        "% Generated by scripts/tabulate/render_first_contestable_vehicle_choice.py; do not edit.",
        f"\\newcommand{{\\FirstContestEntryPairs}}{{{_integer(entry['entry_pairs'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestEntryDates}}{{{_integer(entry['entry_dates'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestEntryValueThreshold}}{{\\${_integer(entry['entry_value_threshold_usd'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestPairs}}{{{_integer(first['ordered_pairs'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestRoutes}}{{{_integer(first['routes'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestDates}}{{{_integer(first['dates'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestCoverage}}{{{_percent(entry['contestability_coverage_share'])}}}",
        f"\\newcommand{{\\FirstContestMedianLagDays}}{{{_days(lag['median_days'])}}}",
        f"\\newcommand{{\\FirstContestLagPQuarterDays}}{{{_days(lag['p25_days'])}}}",
        f"\\newcommand{{\\FirstContestLagPThreeQuarterDays}}{{{_days(lag['p75_days'])}}}",
        f"\\newcommand{{\\FirstContestWithinOneTwenty}}{{{_percent(lag['within_120_days_share'])}}}",
        f"\\newcommand{{\\FirstContestRouteRetention}}{{{_percent(survival['route_weighted_retention_share'])}}}",
        f"\\newcommand{{\\FirstContestPairRetention}}{{{_percent(survival['equal_pair_retention_share'])}}}",
        f"\\newcommand{{\\FirstContestRetentionSupportRoutes}}{{{_integer(survival['route_weighted_routes'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestRetentionSupportPairs}}{{{_integer(survival['equal_pair_pairs'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestCapitalRoutes}}{{{_integer(capital['routes'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestCapitalPairs}}{{{_integer(capital['ordered_pairs'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestStableOutputEffect}}{{{signed_pp(stable_output['coefficient_pp'])}}}",
        f"\\newcommand{{\\FirstContestStableOutputSE}}{{{unsigned_pp(stable_output['standard_error_pp'])}}}",
        f"\\newcommand{{\\FirstContestStableOutputN}}{{{_integer(stable_output['observations'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestRetentionOutputOnlyEffect}}{{{signed_pp(retention_output['coefficient_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionOutputOnlySE}}{{{unsigned_pp(retention_output['standard_error_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionJointOutputEffect}}{{{signed_pp(retention_joint_output['coefficient_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionJointOutputSE}}{{{unsigned_pp(retention_joint_output['standard_error_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionJointCapitalEffect}}{{{signed_pp(retention_joint_capital['coefficient_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionJointCapitalSE}}{{{unsigned_pp(retention_joint_capital['standard_error_pp'])}}}",
        f"\\newcommand{{\\FirstContestRetentionRegressionN}}{{{_integer(retention_joint_output['observations'], tex=True)}}}",
        f"\\newcommand{{\\FirstContestRetentionRegressionPairs}}{{{_integer(retention_joint_output['ordered_pairs'], tex=True)}}}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    results = read_exhibit(RESULTS)
    support = read_exhibit(SUPPORT)
    write_table_artifacts(
        "first_contestable_vehicle_choice",
        render_first_contestable_vehicle_choice(results, support),
        preview_width="8.25in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(
            render_first_contestable_vehicle_choice_values(results, support),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
