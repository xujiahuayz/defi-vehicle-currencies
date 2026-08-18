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


def test_vehicle_mechanism_sweep_values_render_guarded_headline() -> None:
    estimates = pd.DataFrame(
        [
            _row("turn_on_lpm", "baseline_log_market_routes", -2.6),
            _row("turn_on_lpm", "baseline_direct_route_share", 27.0),
            _row("turn_on_lpm", "baseline_complex_route_share", 20.0),
            _row("leader_switch_lpm", "baseline_log_market_routes", -1.1),
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
            }
        ]
    )
    rendered = render_vehicle_mechanism_sweep_deck_values(estimates, support)
    assert "\\MechanismTurnOnThinCoef" in rendered
    assert "$-2.6$ pp" in rendered
    assert "\\MechanismScreenRows" in rendered
