from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_bridge_lp_divergence_risk import (
    SPECIFICATIONS,
    render_bridge_lp_divergence_risk,
)


def _models() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model_index, specification in enumerate(SPECIFICATIONS):
        predictors = [
            specification.risk_regressor,
            "log_prior_candidate_routes",
        ]
        if model_index >= 2:
            predictors.append("log_prior_bridge_depth")
        for predictor_index, predictor in enumerate(predictors):
            rows.append(
                {
                    "record_type": "bridge_lp_divergence_risk_model_coefficient",
                    "table_id": "bridge_lp_divergence_risk",
                    "model_id": specification.model_id,
                    "outcome": specification.outcome,
                    "predictor": predictor,
                    "coefficient": -1.169 + model_index / 100 + predictor_index,
                    "standard_error": 0.488,
                    "p_value": 0.019,
                    "observations": 58_447,
                    "endpoint_pair_clusters": 4_254,
                    "anchor_date_clusters": 71,
                    "r_squared_within": 0.322 + model_index / 10,
                    "fixed_effects": "ordered_endpoint_pair_x_anchor_date+candidate",
                    "covariance_id": "endpoint_pair_and_anchor_date_cluster_cr1",
                    "risk_window": "days_-30_to_-1",
                }
            )
    return rows


def _support() -> list[dict[str, object]]:
    return [
        {
            "record_type": "bridge_lp_divergence_risk_sample",
            "median_native_bridge_relative_volatility": 1.2691,
            "median_stable_bridge_relative_volatility": 1.4840,
            "share_pair_dates_stable_relative_volatility_lower": 0.2942,
            "median_native_daily_divergence_loss_bps": 5.6005,
            "median_stable_daily_divergence_loss_bps": 7.6793,
            "share_pair_dates_stable_divergence_loss_lower": 0.2863,
            "minimum_risk_observations": 20,
            "minimum_prior_pair_routes": 10,
            "pool_families": "uniswap_v2+sushiswap_v2_full_range_constant_product",
            "stable_risk_conjecture_status": "not_supported_in_aggregate_bridge_comparison",
        }
    ]


def test_bridge_lp_divergence_risk_table_renders_models_and_risk_comparison() -> None:
    rendered = render_bridge_lp_divergence_risk(
        pd.DataFrame(_models()), pd.DataFrame(_support())
    )

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "Depth at $t$" in rendered
    assert "Depth at $t+30$" in rendered
    assert "Relative volatility [10 pp]" in rendered
    assert "Daily divergence loss [1 bp]" in rendered
    assert "$-0.117^{**}$" in rendered
    assert "$-1.159^{**}$" in rendered
    assert "Log initial bridge depth" in rendered
    assert "58,447" in rendered
    assert "4,254" in rendered
    assert "Pair $\\times$ date fixed effects & Yes & Yes & Yes & Yes" in rendered
    assert "Native median" in rendered
    assert r"126.9\%" in rendered
    assert "Stablecoin median" in rendered
    assert r"148.4\%" in rendered
    assert "Stablecoin has lower risk [pair-months]" in rendered
    assert r"29.4\%" in rendered
    assert r"28.6\%" in rendered


def test_bridge_lp_divergence_risk_table_rejects_missing_initial_depth() -> None:
    rows = [
        row
        for row in _models()
        if not (
            row["model_id"] == "m3_future_depth_volatility"
            and row["predictor"] == "log_prior_bridge_depth"
        )
    ]
    with pytest.raises(ValueError, match="lacks initial depth"):
        render_bridge_lp_divergence_risk(
            pd.DataFrame(rows), pd.DataFrame(_support())
        )


def test_bridge_lp_divergence_risk_table_rejects_changed_support_status() -> None:
    support = _support()
    support[0]["stable_risk_conjecture_status"] = "supported"
    with pytest.raises(ValueError, match="aggregate comparison status"):
        render_bridge_lp_divergence_risk(
            pd.DataFrame(_models()), pd.DataFrame(support)
        )
