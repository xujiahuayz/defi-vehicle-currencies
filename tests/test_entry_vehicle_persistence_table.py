from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_entry_vehicle_persistence import (
    MAIN_COLUMNS,
    RETRADE_COLUMNS,
    ROBUSTNESS_COLUMNS,
    render_entry_vehicle_persistence,
    render_entry_vehicle_persistence_robustness,
)


def _model_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    declared = (*MAIN_COLUMNS, *RETRADE_COLUMNS, *ROBUSTNESS_COLUMNS)
    for index, column in enumerate(declared):
        retrade_model = column.model_id.startswith("r")
        late = column.window_id == "days_31_120"
        robustness = "_min" in column.model_id
        if "_min10" in column.model_id:
            minimum_routes = 10
        elif "_min5" in column.model_id:
            minimum_routes = 5
        else:
            minimum_routes = 1
        eligible = 775 if minimum_routes == 10 else 2_192 if minimum_routes == 5 else 157_262
        main_retrading_pairs = 19_405 if late else 30_547
        observations = (
            eligible
            if retrade_model
            else 452
            if late and minimum_routes == 10
            else 30_547 - index
        )
        weighting = "post_entry_route_activity" if column.activity_weighted else "equal_pair"
        rows.append(
            {
                "record_type": (
                    "post_entry_retrade_model_coefficient"
                    if retrade_model
                    else "post_entry_persistence_model_coefficient"
                ),
                "table_id": (
                    "post_entry_retrade_probability"
                    if retrade_model
                    else "post_entry_stable_share"
                ),
                "model_id": column.model_id,
                "window_id": column.window_id,
                "predictor": "entry_stable_share",
                "effect_pp_per_10pp": 8.90 + index / 100,
                "standard_error_pp_per_10pp": 0.14 + index / 100,
                "p_value": 0.005 if index != 1 else 0.03,
                "observations": observations,
                "entry_date_clusters": 123 - int(robustness),
                "r_squared": 0.80 + index / 1000,
                "dependent_mean": 0.12 if retrade_model else 0.04,
                "weighting": weighting,
                "minimum_entry_routes": minimum_routes,
                "controls_included": column.controls,
                "covariance_id": "entry_date_cluster_cr1",
                "eligible_pairs": eligible,
                "retrading_pairs": (
                    main_retrading_pairs
                    if minimum_routes == 1
                    else observations
                ),
                "retrade_rate": (
                    main_retrading_pairs / 157_262
                    if minimum_routes == 1
                    else observations / eligible
                ),
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "entry_day_excluded": True,
                "retrading_required": not retrade_model,
                "complete_through_day": 120,
                "inference_status": "provisional_descriptive",
            }
        )
    return rows


def _support_rows() -> list[dict[str, object]]:
    return [
        {
            "record_type": "post_entry_persistence_support",
            "window_id": window_id,
            "entry_year": "all",
            "eligible_pairs": 157_262,
            "retrading_pairs": retrading_pairs,
            "retrade_rate": retrading_pairs / 157_262,
            "common_entry_calendar_cutoff_mm_dd": "03-02",
            "entry_day_excluded": True,
            "complete_through_day": 120,
        }
        for window_id, retrading_pairs in (
            ("days_1_30", 30_547),
            ("days_31_120", 19_405),
        )
    ]


def test_persistence_table_separates_outcomes_and_reports_design() -> None:
    main = render_entry_vehicle_persistence(
        pd.DataFrame(_model_rows()),
        pd.DataFrame(_support_rows()),
    )
    robustness = render_entry_vehicle_persistence_robustness(
        pd.DataFrame(_model_rows()),
        pd.DataFrame(_support_rows()),
    )

    assert main.count(r"\begin{tabularx}{\linewidth}") == 2
    assert r"Panel A. Stablecoin route share among pairs that trade again [\%]" in main
    assert r"Panel B. Subsequent-trading incidence among all entrants [\%]" in main
    assert "greater first-day activity" not in main
    assert "Days 1--30" in main
    assert "Days 31--120" in main
    assert "Entry stablecoin share [10 pp]" in main
    assert r"Mean stablecoin share [\%]" in main
    assert r"Mean retrading rate [\%]" in main
    assert "effect pp per 10 pp" not in main
    assert "$+8.90^{***}$" in main
    assert "$(0.14)$" in main
    assert "$+8.91^{**}$" in main
    assert "Route-activity weights" in main
    assert "Observations (pairs)" in main
    assert "Entry-date clusters" in main

    assert robustness.count(r"\begin{tabularx}{\linewidth}") == 1
    assert (
        r"Stablecoin route share among entrants with greater first-day activity [\%]"
        in robustness
    )
    assert "Panel A." not in robustness
    assert "Panel B." not in robustness
    assert "Minimum first-day routes & 5 & 10 & 5 & 10" in robustness
    assert "$+9.00^{***}$" in robustness

    combined = main + robustness
    assert "Sample and inference" not in combined
    assert "March 2 in each cohort year" not in combined
    assert "entry day excluded from later outcomes" not in combined
    assert "Descriptive associations" not in combined
    assert "candidate" not in combined.lower()
    assert "screen" not in combined.lower()
    assert "claim" not in combined.lower()
    assert "rather than" not in combined.lower()


def test_persistence_table_rejects_missing_model() -> None:
    rows = [
        row
        for row in _model_rows()
        if row["model_id"] != "m6_late_activity_controls"
    ]
    with pytest.raises(ValueError, match="expected one entry-stable-share row"):
        render_entry_vehicle_persistence(
            pd.DataFrame(rows),
            pd.DataFrame(_support_rows()),
        )


def test_persistence_robustness_table_rejects_missing_model() -> None:
    rows = _model_rows()[:-1]
    with pytest.raises(ValueError, match="expected one entry-stable-share row"):
        render_entry_vehicle_persistence_robustness(
            pd.DataFrame(rows),
            pd.DataFrame(_support_rows()),
        )


def test_persistence_table_rejects_entry_day_in_followup() -> None:
    rows = _model_rows()
    rows[0]["entry_day_excluded"] = False
    with pytest.raises(ValueError, match="exclude the entry day"):
        render_entry_vehicle_persistence(
            pd.DataFrame(rows),
            pd.DataFrame(_support_rows()),
        )
