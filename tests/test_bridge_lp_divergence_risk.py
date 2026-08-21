from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_bridge_lp_divergence_risk import (
    fit_bridge_risk_models,
    support_records,
)


def _synthetic_panel() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    candidates = (
        ("WETH", "native", 0.00),
        ("DAI", "stable", 0.10),
        ("USDC", "stable", 0.12),
        ("USDT", "stable", 0.14),
    )
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2021-01-01", periods=35, freq="MS")
    for date_index, anchor_date in enumerate(dates):
        for pair_index in range(40):
            pair_effect = 8.0 + 0.02 * pair_index + 0.01 * date_index
            for candidate_index, (symbol, kind, candidate_risk) in enumerate(candidates):
                relative_risk = (
                    0.50
                    + candidate_risk
                    + 0.025 * ((pair_index + candidate_index * date_index) % 7)
                )
                divergence_bps = 3.0 * relative_risk**2
                log_routes = np.log1p(
                    2 + ((pair_index * 3 + candidate_index + date_index) % 20)
                )
                prior_log_depth = (
                    pair_effect
                    + 0.20 * candidate_index
                    - 1.50 * relative_risk
                    + 0.35 * log_routes
                    + rng.normal(0, 0.08)
                )
                future_log_depth = (
                    0.75 * prior_log_depth
                    + 0.20 * pair_effect
                    - 0.90 * relative_risk
                    + 0.15 * log_routes
                    + rng.normal(0, 0.08)
                )
                rows.append(
                    {
                        "anchor_date": anchor_date,
                        "ordered_pair": f"pair_{pair_index}",
                        "pair_date_id": f"{anchor_date:%Y%m%d}|pair_{pair_index}",
                        "candidate_symbol": symbol,
                        "candidate_type": kind,
                        "bridge_relative_volatility": relative_risk,
                        "bridge_daily_divergence_loss_bps": divergence_bps,
                        "log_prior_bridge_depth": prior_log_depth,
                        "log_future_bridge_depth": future_log_depth,
                        "log_prior_candidate_routes": log_routes,
                        "prior_bridge_depth": np.expm1(prior_log_depth),
                        "future_bridge_depth": np.expm1(future_log_depth),
                        "prior_bridge_supported": 1.0,
                        "future_bridge_supported": 1.0,
                    }
                )
    return pd.DataFrame(rows)


def test_bridge_risk_models_recover_negative_risk_depth_relation() -> None:
    result = fit_bridge_risk_models(
        _synthetic_panel(),
        min_observations=100,
        min_pair_clusters=30,
        min_date_clusters=30,
    )
    key = result[
        result["model_id"].eq("m1_prior_depth_volatility")
        & result["predictor"].eq("bridge_relative_volatility")
    ].iloc[0]

    assert key["coefficient"] < -1.0
    assert np.isfinite(key["standard_error"])
    assert key["fixed_effects"] == "ordered_endpoint_pair_x_anchor_date+candidate"
    assert key["interpretation"] == "suggestive_equilibrium_association_not_causal"


def test_support_records_report_vehicle_risk_comparison_and_missing_fees() -> None:
    support = support_records(_synthetic_panel()).iloc[0]

    assert support["median_stable_bridge_relative_volatility"] > support[
        "median_native_bridge_relative_volatility"
    ]
    assert support["share_pair_dates_stable_relative_volatility_lower"] < 0.5
    assert support["stable_risk_conjecture_status"] == (
        "not_supported_in_aggregate_bridge_comparison"
    )
    assert support["fee_control_status"].startswith("unavailable")
