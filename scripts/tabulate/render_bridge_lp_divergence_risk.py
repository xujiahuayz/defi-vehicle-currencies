#!/usr/bin/env python3
"""Render bridge-depth regressions against prior relative-price risk."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


MODELS = OUTPUT_DIR / "exhibits" / "bridge_lp_divergence_risk_models.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "bridge_lp_divergence_risk_support.jsonl"


@dataclass(frozen=True)
class Specification:
    model_id: str
    outcome: str
    heading: str
    risk_regressor: str


SPECIFICATIONS: tuple[Specification, ...] = (
    Specification(
        model_id="m1_prior_depth_volatility",
        outcome="log_prior_bridge_depth",
        heading=r"Depth at $t$",
        risk_regressor="bridge_relative_volatility",
    ),
    Specification(
        model_id="m2_prior_depth_divergence_loss",
        outcome="log_prior_bridge_depth",
        heading=r"Depth at $t$",
        risk_regressor="bridge_daily_divergence_loss_bps",
    ),
    Specification(
        model_id="m3_future_depth_volatility",
        outcome="log_future_bridge_depth",
        heading=r"Depth at $t+30$",
        risk_regressor="bridge_relative_volatility",
    ),
    Specification(
        model_id="m4_future_depth_divergence_loss",
        outcome="log_future_bridge_depth",
        heading=r"Depth at $t+30$",
        risk_regressor="bridge_daily_divergence_loss_bps",
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


def _model_rows(models: pd.DataFrame, specification: Specification) -> pd.DataFrame:
    selected = models[
        models["record_type"].eq("bridge_lp_divergence_risk_model_coefficient")
        & models["table_id"].eq("bridge_lp_divergence_risk")
        & models["model_id"].eq(specification.model_id)
        & models["outcome"].eq(specification.outcome)
    ].copy()
    if selected.empty:
        raise ValueError(f"missing bridge-risk model {specification.model_id}")
    if selected["predictor"].duplicated().any():
        raise ValueError(f"duplicate predictors in bridge-risk model {specification.model_id}")
    selected = selected.set_index("predictor", drop=False)
    if specification.risk_regressor not in selected.index:
        raise ValueError(
            f"bridge-risk model {specification.model_id} lacks "
            f"{specification.risk_regressor}"
        )
    return selected


def _anchor(model: pd.DataFrame) -> pd.Series:
    return model.iloc[0]


def _validate_model(model: pd.DataFrame, specification: Specification) -> None:
    constant_fields = (
        "observations",
        "endpoint_pair_clusters",
        "anchor_date_clusters",
        "r_squared_within",
        "fixed_effects",
        "covariance_id",
        "risk_window",
    )
    for field in constant_fields:
        if model[field].nunique(dropna=False) != 1:
            raise ValueError(
                f"bridge-risk model {specification.model_id} has inconsistent {field}"
            )
    anchor = _anchor(model)
    if anchor["fixed_effects"] != "ordered_endpoint_pair_x_anchor_date+candidate":
        raise ValueError(f"unexpected fixed effects in {specification.model_id}")
    if anchor["covariance_id"] != "endpoint_pair_and_anchor_date_cluster_cr1":
        raise ValueError(f"unexpected covariance in {specification.model_id}")
    if anchor["risk_window"] != "days_-30_to_-1":
        raise ValueError(f"unexpected risk window in {specification.model_id}")


def _cell(model: pd.DataFrame, predictor: str, *, scale: float = 1.0) -> str:
    if predictor not in model.index:
        return ""
    row = model.loc[predictor]
    coefficient = scale * float(row["coefficient"])
    standard_error = scale * float(row["standard_error"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${coefficient:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def _support_row(support: pd.DataFrame) -> pd.Series:
    selected = support[
        support["record_type"].eq("bridge_lp_divergence_risk_sample")
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one bridge-risk support row; found {len(selected)}")
    row = selected.iloc[0]
    if row["stable_risk_conjecture_status"] != "not_supported_in_aggregate_bridge_comparison":
        raise ValueError("bridge-risk table expects the aggregate comparison status")
    return row


def render_bridge_lp_divergence_risk(
    models: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Return a compact four-column regression and sample-comparison table."""

    required_model_fields = {
        "record_type",
        "table_id",
        "model_id",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "observations",
        "endpoint_pair_clusters",
        "anchor_date_clusters",
        "r_squared_within",
        "fixed_effects",
        "covariance_id",
        "risk_window",
    }
    missing = sorted(required_model_fields - set(models.columns))
    if missing:
        raise ValueError(f"bridge-risk models lack table fields: {missing}")

    required_support_fields = {
        "record_type",
        "median_native_bridge_relative_volatility",
        "median_stable_bridge_relative_volatility",
        "share_pair_dates_stable_relative_volatility_lower",
        "median_native_daily_divergence_loss_bps",
        "median_stable_daily_divergence_loss_bps",
        "share_pair_dates_stable_divergence_loss_lower",
        "minimum_risk_observations",
        "minimum_prior_pair_routes",
        "pool_families",
        "stable_risk_conjecture_status",
    }
    missing = sorted(required_support_fields - set(support.columns))
    if missing:
        raise ValueError(f"bridge-risk support lacks table fields: {missing}")

    selected_models = [
        _model_rows(models, specification) for specification in SPECIFICATIONS
    ]
    for model, specification in zip(selected_models, SPECIFICATIONS, strict=True):
        _validate_model(model, specification)
    support_row = _support_row(support)

    for model in selected_models:
        if "log_prior_candidate_routes" not in model.index:
            raise ValueError("every bridge-risk model must control for prior route activity")
    for model, specification in zip(
        selected_models[2:], SPECIFICATIONS[2:], strict=True
    ):
        if "log_prior_bridge_depth" not in model.index:
            raise ValueError(
                f"bridge-risk model {specification.model_id} lacks initial depth"
            )

    anchors = [_anchor(model) for model in selected_models]
    volatility_scale = 0.10
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=1.58\hsize\raggedright\arraybackslash}X"
        r"*{4}{>{\hsize=0.855\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r" & (1) & (2) & (3) & (4) \\",
        "Log deposited bridge capital & "
        + " & ".join(specification.heading for specification in SPECIFICATIONS)
        + r" \\",
        r"\midrule",
        r"\multicolumn{5}{@{}l}{\textit{Panel A: Relative-price risk and bridge depth}} \\",
        "Relative volatility [10 pp] & "
        + " & ".join(
            _cell(model, "bridge_relative_volatility", scale=volatility_scale)
            for model in selected_models
        )
        + r" \\",
        "Daily divergence loss [1 bp] & "
        + " & ".join(
            _cell(model, "bridge_daily_divergence_loss_bps")
            for model in selected_models
        )
        + r" \\",
        "Log prior vehicle-route count & "
        + " & ".join(
            _cell(model, "log_prior_candidate_routes")
            for model in selected_models
        )
        + r" \\",
        "Log initial bridge depth & "
        + " & ".join(
            _cell(model, "log_prior_bridge_depth")
            for model in selected_models
        )
        + r" \\",
        r"\midrule",
        "Within $R^2$ & "
        + " & ".join(f"{float(row['r_squared_within']):.3f}" for row in anchors)
        + r" \\",
        "Observations & "
        + " & ".join(f"{int(row['observations']):,}" for row in anchors)
        + r" \\",
        "Pair clusters & "
        + " & ".join(f"{int(row['endpoint_pair_clusters']):,}" for row in anchors)
        + r" \\",
        "Date clusters & "
        + " & ".join(f"{int(row['anchor_date_clusters']):,}" for row in anchors)
        + r" \\",
        r"Pair $\times$ date fixed effects & Yes & Yes & Yes & Yes \\",
        r"Vehicle fixed effects & Yes & Yes & Yes & Yes \\",
        r"Two-way clustered s.e. & Pair, date & Pair, date & Pair, date & Pair, date \\",
        r"\addlinespace",
        r"\multicolumn{5}{@{}l}{\textit{Panel B: Native and stablecoin bridge risk}} \\",
        r" & \multicolumn{2}{c}{Relative volatility} & \multicolumn{2}{c}{Daily divergence loss} \\",
        "Native median & "
        + rf"\multicolumn{{2}}{{c}}{{{100.0 * float(support_row['median_native_bridge_relative_volatility']):.1f}\%}} & "
        + rf"\multicolumn{{2}}{{c}}{{{float(support_row['median_native_daily_divergence_loss_bps']):.2f} bp}} \\",
        "Stablecoin median & "
        + rf"\multicolumn{{2}}{{c}}{{{100.0 * float(support_row['median_stable_bridge_relative_volatility']):.1f}\%}} & "
        + rf"\multicolumn{{2}}{{c}}{{{float(support_row['median_stable_daily_divergence_loss_bps']):.2f} bp}} \\",
        "Stablecoin has lower risk [pair-months] & "
        + rf"\multicolumn{{2}}{{c}}{{{100.0 * float(support_row['share_pair_dates_stable_relative_volatility_lower']):.1f}\%}} & "
        + rf"\multicolumn{{2}}{{c}}{{{100.0 * float(support_row['share_pair_dates_stable_divergence_loss_lower']):.1f}\%}} \\",
        r"\bottomrule",
        r"\end{tabularx}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    models = pd.read_json(MODELS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "bridge_lp_divergence_risk",
        render_bridge_lp_divergence_risk(models, support),
        preview_width="8.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
