from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_contestable_vehicle_choice import (
    SPECIFICATIONS,
    render_contestable_vehicle_choice,
)


REGRESSORS = {
    "stable_choice_price_leader": (
        "stable_price_leader",
        "log_input_usd",
    ),
    "exclusive_incumbent_retention_price_leader": (
        "challenger_price_leader",
        "challenger_price_leader_x_entry_stable",
        "log_input_usd",
    ),
    "exclusive_retention_price_only_positive_v2_capital": (
        "incumbent_output_advantage_100bp",
        "log_input_usd",
    ),
    "exclusive_retention_price_v2_capital": (
        "incumbent_output_advantage_100bp",
        "incumbent_v2_capital_advantage_10pp",
        "log_input_usd",
    ),
}


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model_index, specification in enumerate(SPECIFICATIONS):
        sample_index = min(model_index, 2)
        for regressor_index, regressor in enumerate(REGRESSORS[specification.model_id]):
            rows.append(
                {
                    "record_type": "contestable_vehicle_choice_regression",
                    "model_id": specification.model_id,
                    "sample": specification.sample,
                    "outcome": specification.outcome,
                    "regressor": regressor,
                    "coefficient_pp": 10.125 + model_index + regressor_index / 10,
                    "standard_error_pp": 0.765,
                    "p_value": 0.005,
                    "observations": 49_212 - sample_index * 10_000,
                    "ordered_pair_clusters": 2_596 - sample_index * 500,
                    "date_clusters": 73,
                    "fixed_effects": "ordered_endpoint_pair+calendar_date",
                    "covariance": "two_way_ordered_pair_calendar_date_cr1",
                    "within_r_squared": 0.372 - model_index / 10,
                    "dependent_mean": 0.265 + sample_index / 10,
                    "price_lead_threshold_bps": 1.0,
                    "linear_price_advantage_cap_bps": 1000.0,
                }
            )
    return rows


def test_contestable_choice_table_renders_joint_economic_models() -> None:
    rendered = render_contestable_vehicle_choice(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "Stablecoin chosen" in rendered
    assert rendered.count("Incumbent retained") == 3
    assert "Outcome; estimates [pp]" in rendered
    assert "Stablecoin route has higher exact output" in rendered
    assert "Challenger route has higher exact output" in rendered
    assert "Incumbent exact-output advantage [100 bp]" in rendered
    assert "Incumbent lagged full-range capital-share advantage [10 pp]" in rendered
    assert "$+10.12^{***}$" in rendered
    assert "49,212" in rendered
    assert "Pair fixed effects & Yes & Yes & Yes & Yes" in rendered
    assert (
        "Two-way clustered s.e. & Pair, date & Pair, date & Pair, date & Pair, date"
        in rendered
    )
    assert (
        "Prior-day full-range capital positive, both vehicles & No & No & Yes & Yes"
        in rendered
    )
    assert "Minimum absolute output difference [bp] & 1 & 1 & 1 & 1" in rendered
    assert "Continuous output gap cap [bp] &  &  & 1,000 & 1,000" in rendered


def test_contestable_choice_table_rejects_missing_primary_regressor() -> None:
    rows = [
        row for row in _complete_rows()
        if not (
            row["model_id"] == "exclusive_retention_price_v2_capital"
            and row["regressor"] == "incumbent_v2_capital_advantage_10pp"
        )
    ]
    with pytest.raises(ValueError, match="lacks regressor"):
        render_contestable_vehicle_choice(pd.DataFrame(rows))


def test_contestable_choice_table_rejects_inconsistent_model_metadata() -> None:
    rows = _complete_rows()
    rows[1]["date_clusters"] = 72
    with pytest.raises(ValueError, match="inconsistent date_clusters"):
        render_contestable_vehicle_choice(pd.DataFrame(rows))


def test_contestable_choice_table_rejects_different_nested_samples() -> None:
    rows = _complete_rows()
    for row in rows:
        if row["model_id"] == "exclusive_retention_price_v2_capital":
            row["observations"] = int(row["observations"]) - 1
    with pytest.raises(ValueError, match="use different samples"):
        render_contestable_vehicle_choice(pd.DataFrame(rows))
