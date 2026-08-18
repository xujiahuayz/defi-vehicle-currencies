from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_vehicle_formation_deck_values import (
    render_vehicle_formation_deck_values,
)


def test_vehicle_formation_deck_values_render_key_macros() -> None:
    estimates = pd.DataFrame(
        [
            {
                "record_type": "entry_cohort",
                "entry_year": 2024,
                "pairs": 10,
                "primary_routes": 100,
                "stable_share": 0.05,
            },
            {
                "record_type": "entry_cohort",
                "entry_year": 2026,
                "pairs": 20,
                "primary_routes": 200,
                "stable_share": 0.25,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_type": "native_only_entry",
                "pairs": 18,
                "primary_routes": 180,
                "stable_share": 0.005,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.975,
            },
            {
                "record_type": "entry_persistence_contrast",
                "horizon_days": 30,
                "entry_year": 2026,
                "primary_routes": 200,
                "stable_share": None,
                "coefficient": 0.97,
                "standard_error": 0.02,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 120,
                "entry_year": 2024,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.98,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 120,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.99,
            },
            {
                "record_type": "entry_persistence_contrast",
                "horizon_days": 120,
                "entry_year": 2026,
                "primary_routes": 200,
                "stable_share": None,
                "coefficient": 0.98,
                "standard_error": 0.01,
            },
            {
                "record_type": "entry_regime_hysteresis",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 20,
                "pairs_trading_again": 18,
                "primary_routes": 1,
                "stable_share": 0.0,
                "never_left_share_retrade": 0.92,
                "mean_stable_majority_day_share": 0.99,
            },
            {
                "record_type": "entry_regime_hysteresis",
                "horizon_days": 120,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 20,
                "pairs_trading_again": 18,
                "primary_routes": 1,
                "stable_share": 0.0,
                "never_left_share_retrade": 0.95,
                "mean_stable_majority_day_share": 0.99,
            },
            {
                "record_type": "entry_endpoint_class",
                "entry_year": 2024,
                "endpoint_class": "non_weth_endpoint",
                "primary_routes": 90,
                "stable_share": 0.01,
                "route_mass_share": 0.90,
            },
            {
                "record_type": "entry_endpoint_class",
                "entry_year": 2026,
                "endpoint_class": "non_weth_endpoint",
                "primary_routes": 80,
                "stable_share": 0.08,
                "route_mass_share": 0.80,
            },
            {
                "record_type": "entry_endpoint_class",
                "entry_year": 2026,
                "endpoint_class": "weth_endpoint",
                "primary_routes": 20,
                "stable_share": 1.0,
                "route_mass_share": 0.20,
            },
            {
                "record_type": "entry_stable_candidate",
                "entry_year": 2026,
                "candidate_symbol": "USDC",
                "primary_routes": None,
                "stable_share": None,
                "stable_entry_route_share": 0.738,
            },
            {
                "record_type": "entry_stable_candidate",
                "entry_year": 2026,
                "candidate_symbol": "USDT",
                "primary_routes": None,
                "stable_share": None,
                "stable_entry_route_share": 0.258,
            },
            {
                "record_type": "entry_stable_candidate_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_candidate_symbol": "USDC",
                "primary_routes": None,
                "stable_share": None,
                "own_candidate_followup_share": 0.873,
            },
            {
                "record_type": "entry_stable_candidate_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_candidate_symbol": "USDT",
                "primary_routes": None,
                "stable_share": None,
                "own_candidate_followup_share": 0.946,
            },
            {
                "record_type": "entry_stable_candidate_persistence",
                "horizon_days": 120,
                "entry_year": 2026,
                "entry_candidate_symbol": "USDC",
                "primary_routes": None,
                "stable_share": None,
                "own_candidate_followup_share": 0.883,
            },
            {
                "record_type": "entry_stable_candidate_persistence",
                "horizon_days": 120,
                "entry_year": 2026,
                "entry_candidate_symbol": "USDT",
                "primary_routes": None,
                "stable_share": None,
                "own_candidate_followup_share": 0.877,
            },
            {
                "record_type": "entry_driver_regression",
                "endpoint_class": "non_weth_endpoint",
                "outcome": "stable_share",
                "predictor": "is_2026",
                "coefficient": 0.043,
                "standard_error": 0.004,
                "primary_routes": None,
                "stable_share": None,
            },
            {
                "record_type": "entry_driver_regression",
                "endpoint_class": "non_weth_endpoint",
                "outcome": "stable_share",
                "predictor": "is_2026_x_stable_endpoint",
                "coefficient": 0.057,
                "standard_error": 0.013,
                "primary_routes": None,
                "stable_share": None,
            },
        ]
    )
    rendered = render_vehicle_formation_deck_values(estimates)
    assert "\\FormationEntryStableShareBase" in rendered
    assert "5.0\\%" in rendered
    assert "$+97.0$ pp" in rendered
    assert "$+98.0$ pp" in rendered
    assert "\\FormationNonWethEntryStableShareEnd" in rendered
    assert "\\FormationStableEntryTopTwoShareEnd" in rendered
    assert "99.6\\%" in rendered
    assert "\\FormationUSDCEntryOwnThirty" in rendered
    assert "\\FormationStableHysteresisThirtyRetrade" in rendered
    assert "94.6\\%" in rendered
    assert "\\FormationNonWethYearDriver" in rendered
