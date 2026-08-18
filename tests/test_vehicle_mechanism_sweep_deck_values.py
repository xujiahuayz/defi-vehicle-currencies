from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_vehicle_mechanism_sweep_deck_values import (
    render_vehicle_mechanism_sweep_deck_values,
)


def _row(model_id: str, regressor: str, coefficient_pp: float) -> dict[str, object]:
    return {
        "claim_status": "provisional_exploratory",
        "experiment_family": "vehicle_dominance_mechanism_sweep",
        "metric": "count_share",
        "model_id": model_id,
        "regressor": regressor,
        "coefficient_pp": coefficient_pp,
        "standard_error_pp": 0.5,
        "one_sd_effect_pp": coefficient_pp / 2,
        "p_value": 0.001,
    }


def _persistence_row(scope: str, regime: str, coefficient: float) -> dict[str, object]:
    return {
        "claim_status": "provisional_exploratory",
        "experiment_family": "vehicle_dominance_mechanism_sweep",
        "metric": "count_share",
        "model_id": "regime_persistence",
        "integration_scope": scope,
        "baseline_regime": regime,
        "coefficient": coefficient,
        "standard_error_pp": 1.0,
    }


def test_vehicle_mechanism_sweep_values_render_guarded_headline() -> None:
    estimates = pd.DataFrame(
        [
            _row("turn_on_lpm", "baseline_log_market_routes", -2.6),
            _row("turn_on_lpm", "baseline_direct_route_share", 27.0),
            _row("turn_on_lpm", "baseline_complex_route_share", 20.0),
            _row("turn_on_direct_thin_interaction", "baseline_direct_x_thin", 3.1),
            _row("leader_switch_lpm", "baseline_log_market_routes", -1.1),
            _persistence_row("single_venue", "stable_majority", 0.94),
            _persistence_row("single_venue", "native_majority", 0.95),
            _persistence_row("cross_venue", "stable_majority", 0.92),
            _persistence_row("cross_venue", "native_majority", 0.96),
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_summary",
                "min_total_routes": 5,
                "year": 2024,
                "stable_route_share": 0.24,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_summary",
                "min_total_routes": 5,
                "year": 2026,
                "stable_route_share": 0.28,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_fe",
                "min_total_routes": 5,
                "regressor": "is_stable",
                "coefficient": -0.52,
                "coefficient_pp": -52.0,
                "standard_error_pp": 6.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_fe",
                "min_total_routes": 5,
                "regressor": "is_stable_x_2026",
                "coefficient": 0.04,
                "coefficient_pp": 4.0,
                "standard_error_pp": 13.0,
                "p_value": 0.75,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_centrality_fe",
                "min_total_routes": 5,
                "regressor": "is_stable",
                "coefficient": -0.22,
                "coefficient_pp": -22.0,
                "standard_error_pp": 2.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_centrality_fe",
                "min_total_routes": 5,
                "regressor": "is_stable_x_2026",
                "coefficient": 0.08,
                "coefficient_pp": 8.0,
                "standard_error_pp": 2.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_centrality_fe",
                "min_total_routes": 5,
                "regressor": "log_leaveout_candidate_pair_scopes",
                "coefficient": 0.11,
                "coefficient_pp": 11.0,
                "standard_error_pp": 1.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_lag30_reach_fe",
                "min_total_routes": 5,
                "regressor": "is_stable",
                "coefficient": -0.18,
                "coefficient_pp": -18.0,
                "standard_error_pp": 3.0,
                "p_value": 0.02,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_lag30_reach_fe",
                "min_total_routes": 5,
                "regressor": "is_stable_x_2026",
                "coefficient": 0.01,
                "coefficient_pp": 1.0,
                "standard_error_pp": 4.0,
                "p_value": 0.80,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_lag30_reach_fe",
                "min_total_routes": 5,
                "regressor": "log_lag30_candidate_pair_scopes",
                "coefficient": 0.08,
                "coefficient_pp": 8.0,
                "standard_error_pp": 2.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_issuer_reach_fe",
                "min_total_routes": 5,
                "regressor": "is_stable_x_2026",
                "coefficient": -0.40,
                "coefficient_pp": -40.0,
                "standard_error_pp": 4.0,
                "p_value": 0.01,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_issuer_reach_fe",
                "min_total_routes": 5,
                "regressor": "is_usdc_x_2026",
                "coefficient": 0.53,
                "coefficient_pp": 53.0,
                "standard_error_pp": 12.0,
                "p_value": 0.02,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "candidate_route_share",
                "model_id": "mixed_native_stable_risk_set_issuer_reach_fe",
                "min_total_routes": 5,
                "regressor": "is_usdt_x_2026",
                "coefficient": 0.88,
                "coefficient_pp": 88.0,
                "standard_error_pp": 12.0,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_decile",
                "outcome": "future_stable_turn_on",
                "regressor": "log_market_routes",
                "bottom_decile_turn_on_rate": 0.02,
                "top_decile_turn_on_rate": 0.25,
                "top_minus_bottom_pp": 23.0,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_decile",
                "outcome": "future_stable_turn_on",
                "regressor": "pair_age_log",
                "bottom_decile_turn_on_rate": 0.01,
                "top_decile_turn_on_rate": 0.41,
                "top_minus_bottom_pp": 40.0,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_fe",
                "outcome": "future_stable_turn_on",
                "regressor": "log_market_routes",
                "coefficient_pp": 3.5,
                "standard_error_pp": 0.7,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_fe",
                "outcome": "future_stable_turn_on",
                "regressor": "pair_age_log",
                "coefficient_pp": 1.6,
                "standard_error_pp": 0.2,
                "p_value": 0.001,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_summary",
                "year": 2026,
                "stable_endpoint": False,
                "weighted_turn_on_rate": 0.08,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard_summary",
                "year": 2026,
                "stable_endpoint": True,
                "weighted_turn_on_rate": 0.28,
            },
        ]
    )
    support = pd.DataFrame(
        [
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "count_share",
                "rows": 1000,
                "ordered_pairs": 50,
                "month_days": 10,
            },
            {
                "claim_status": "provisional_exploratory",
                "experiment_family": "vehicle_dominance_mechanism_sweep",
                "metric": "native_only_pair_day_stable_turn_on",
                "model_id": "stable_turn_on_hazard",
                "rows": 2000,
                "ordered_pairs": 100,
            }
        ]
    )
    rendered = render_vehicle_mechanism_sweep_deck_values(estimates, support)
    assert "\\MechanismTurnOnThinCoef" in rendered
    assert "\\MechanismTurnOnDirectThinCoef" in rendered
    assert "\\MechanismSingleStableRegimePersistence" in rendered
    assert "$-2.6$ pp" in rendered
    assert "\\MechanismScreenRows" in rendered
    assert "\\MechanismRiskSetStablePenalty" in rendered
    assert "\\MechanismRiskSetCentralityCoef" in rendered
    assert "\\MechanismRiskSetLagReachCoef" in rendered
    assert "\\MechanismRiskSetIssuerUsdtTwentySix" in rendered
    assert "\\MechanismHazardThickGap" in rendered
    assert "\\MechanismHazardRows" in rendered
