#!/usr/bin/env python3
"""Render exact-price, incumbency, and bridge-capital regressions."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "contestable_vehicle_choice.jsonl"


@dataclass(frozen=True)
class Specification:
    model_id: str
    sample: str
    outcome: str
    heading: str


SPECIFICATIONS: tuple[Specification, ...] = (
    Specification(
        model_id="stable_choice_price_leader",
        sample="contestable_symmetric_common_support",
        outcome="chosen_stable",
        heading=r"Stablecoin chosen",
    ),
    Specification(
        model_id="exclusive_incumbent_retention_price_leader",
        sample="mature_exclusive_entry_symmetric_common_support",
        outcome="incumbent_retained",
        heading=r"Incumbent retained",
    ),
    Specification(
        model_id="exclusive_retention_price_v2_capital",
        sample="mature_exclusive_entry_positive_v2_bridge_capital",
        outcome="incumbent_retained",
        heading=r"Incumbent retained",
    ),
    Specification(
        model_id="exclusive_retention_price_v2_capital_interaction",
        sample="mature_exclusive_entry_positive_v2_bridge_capital",
        outcome="incumbent_retained",
        heading=r"Incumbent retained",
    ),
)


REGRESSORS: tuple[tuple[str, str], ...] = (
    (
        "stable_price_leader",
        r"Stablecoin route has higher exact output",
    ),
    (
        "challenger_price_leader",
        r"Challenger route has higher exact output",
    ),
    (
        "challenger_price_leader_x_entry_stable",
        r"Challenger output lead $\times$ stable incumbent",
    ),
    (
        "incumbent_output_advantage_100bp",
        r"Incumbent exact-output advantage [100 bp]",
    ),
    (
        "incumbent_v2_capital_advantage_10pp",
        r"Incumbent lagged full-range capital-share advantage [10 pp]",
    ),
    (
        "price_x_incumbent_v2_capital",
        r"Output advantage $\times$ capital-share advantage [100 bp $\times$ 10 pp]",
    ),
    (
        "log_input_usd",
        r"Log input value [USD]",
    ),
)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _model_rows(results: pd.DataFrame, specification: Specification) -> pd.DataFrame:
    selected = results[
        results["record_type"].eq("contestable_vehicle_choice_regression")
        & results["model_id"].eq(specification.model_id)
        & results["sample"].eq(specification.sample)
        & results["outcome"].eq(specification.outcome)
    ].copy()
    if selected.empty:
        raise ValueError(f"missing contestable-choice model {specification.model_id}")
    if selected["regressor"].duplicated().any():
        raise ValueError(
            f"duplicate regressors in contestable-choice model {specification.model_id}"
        )
    return selected.set_index("regressor", drop=False)


def _require_regressor(model: pd.DataFrame, regressor: str, model_id: str) -> None:
    if regressor not in model.index:
        raise ValueError(
            f"contestable-choice model {model_id} lacks regressor {regressor}"
        )


def _effect_cell(model: pd.DataFrame, regressor: str) -> str:
    if regressor not in model.index:
        return ""
    row = model.loc[regressor]
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['coefficient_pp']):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({float(row['standard_error_pp']):.2f})$"
        r"\end{tabular}"
    )


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def _anchor(model: pd.DataFrame) -> pd.Series:
    return model.iloc[0]


def _validate_model_metadata(model: pd.DataFrame, specification: Specification) -> None:
    constant_fields = (
        "observations",
        "ordered_pair_clusters",
        "date_clusters",
        "fixed_effects",
        "covariance",
        "within_r_squared",
        "dependent_mean",
        "price_lead_threshold_bps",
        "linear_price_advantage_cap_bps",
    )
    for field in constant_fields:
        if model[field].nunique(dropna=False) != 1:
            raise ValueError(
                f"contestable-choice model {specification.model_id} has inconsistent {field}"
            )
    anchor = _anchor(model)
    if anchor["fixed_effects"] != "ordered_endpoint_pair+calendar_date":
        raise ValueError(
            f"unexpected fixed effects in contestable-choice model {specification.model_id}"
        )
    if anchor["covariance"] != "two_way_ordered_pair_calendar_date_cr1":
        raise ValueError(
            f"unexpected covariance in contestable-choice model {specification.model_id}"
        )


def render_contestable_vehicle_choice(results: pd.DataFrame) -> str:
    """Return a compact four-column regression table."""

    required = {
        "record_type",
        "model_id",
        "sample",
        "outcome",
        "regressor",
        "coefficient_pp",
        "standard_error_pp",
        "p_value",
        "observations",
        "ordered_pair_clusters",
        "date_clusters",
        "fixed_effects",
        "covariance",
        "within_r_squared",
        "dependent_mean",
        "price_lead_threshold_bps",
        "linear_price_advantage_cap_bps",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"contestable-choice results lack table fields: {missing}")

    models = [
        _model_rows(results, specification) for specification in SPECIFICATIONS
    ]
    for model, specification in zip(models, SPECIFICATIONS, strict=True):
        _validate_model_metadata(model, specification)

    required_by_model = (
        ("stable_price_leader", "log_input_usd"),
        (
            "challenger_price_leader",
            "challenger_price_leader_x_entry_stable",
            "log_input_usd",
        ),
        (
            "incumbent_output_advantage_100bp",
            "incumbent_v2_capital_advantage_10pp",
            "log_input_usd",
        ),
        (
            "incumbent_output_advantage_100bp",
            "incumbent_v2_capital_advantage_10pp",
            "price_x_incumbent_v2_capital",
            "log_input_usd",
        ),
    )
    for model, specification, regressors in zip(
        models, SPECIFICATIONS, required_by_model, strict=True
    ):
        for regressor in regressors:
            _require_regressor(model, regressor, specification.model_id)

    anchors = [_anchor(model) for model in models]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=1.64\hsize\raggedright\arraybackslash}X"
        r"*{4}{>{\hsize=0.84\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r" & (1) & (2) & (3) & (4) \\",
        "Outcome; estimates [pp] & "
        + " & ".join(spec.heading for spec in SPECIFICATIONS)
        + r" \\",
        r"\midrule",
    ]
    for regressor, label in REGRESSORS:
        cells = [_effect_cell(model, regressor) for model in models]
        lines.append(label + " & " + " & ".join(cells) + r" \\")

    lines.extend(
        [
            r"\midrule",
            r"Dependent mean [\%] & "
            + " & ".join(f"{100.0 * float(row['dependent_mean']):.1f}" for row in anchors)
            + r" \\",
            "Within $R^2$ & "
            + " & ".join(f"{float(row['within_r_squared']):.3f}" for row in anchors)
            + r" \\",
            "Observations & "
            + " & ".join(_integer(row["observations"]) for row in anchors)
            + r" \\",
            "Pair clusters & "
            + " & ".join(_integer(row["ordered_pair_clusters"]) for row in anchors)
            + r" \\",
            "Date clusters & "
            + " & ".join(_integer(row["date_clusters"]) for row in anchors)
            + r" \\",
            r"Pair fixed effects & Yes & Yes & Yes & Yes \\",
            r"Date fixed effects & Yes & Yes & Yes & Yes \\",
            r"Two-way clustered s.e. & Pair, date & Pair, date & Pair, date & Pair, date \\",
            r"Exclusive entry, age $\geq 30$ days & No & Yes & Yes & Yes \\",
            r"Prior-day full-range capital positive, both vehicles & No & No & Yes & Yes \\",
            "Minimum absolute output difference [bp] & "
            + " & ".join(
                f"{float(row['price_lead_threshold_bps']):.0f}" for row in anchors
            )
            + r" \\",
            "Continuous output gap cap [bp] &  &  & "
            + f"{float(anchors[2]['linear_price_advantage_cap_bps']):,.0f}"
            + " & "
            + f"{float(anchors[3]['linear_price_advantage_cap_bps']):,.0f}"
            + r" \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "contestable_vehicle_choice",
        render_contestable_vehicle_choice(results),
        preview_width="8.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
