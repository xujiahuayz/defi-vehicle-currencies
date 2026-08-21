from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_price_rank_crossing import (
    MODEL_COLUMNS,
    render_price_rank_crossing,
    render_price_rank_crossing_values,
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dimension_index, dimension in enumerate(
        ("all_crossings", "stable_challenger", "native_challenger")
    ):
        for event_time in range(-3, 4):
            rows.append(
                {
                    "record_type": "price_rank_crossing_event_time",
                    "sample": "material_balanced_seven_month",
                    "dimension": dimension,
                    "event_time_month": event_time,
                    "mean_incumbent_route_share_pp": (
                        50.0 + dimension_index + event_time
                    ),
                    "standard_error_pp": 1.25,
                    "events": 147,
                    "ordered_pairs": 55,
                }
            )
    for model_index, model_id in enumerate(MODEL_COLUMNS[:3]):
        coefficient = (0.28, 3.70, 3.85)[model_index]
        for regressor in (
            "challenger_capital_share_10pp",
            "stable_challenger",
        ):
            rows.append(
                {
                    "record_type": "price_rank_crossing_regression",
                    "model_id": model_id,
                    "sample": "material",
                    "regressor": regressor,
                    "coefficient_pp": coefficient,
                    "standard_error_pp": 1.52,
                    "p_value": 0.018,
                    "observations": 286 + model_index,
                    "events": 286 + model_index,
                    "ordered_pairs": 122 + model_index,
                }
            )
    for regressor, coefficient in (
        ("actual_crossing", -28.98),
        ("actual_x_challenger_capital_share_10pp", 2.75),
    ):
        rows.append(
            {
                "record_type": "price_rank_crossing_regression",
                "model_id": MODEL_COLUMNS[3],
                "sample": "placebo",
                "regressor": regressor,
                "coefficient_pp": coefficient,
                "standard_error_pp": 4.71,
                "p_value": 0.001,
                "observations": 440,
                "events": 220,
                "ordered_pairs": 83,
            }
        )
    return rows


def _support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "price_rank_crossing_support",
                "material_events": 400,
                "material_event_pairs": 180,
                "material_stable_challenger_events": 200,
                "material_native_challenger_events": 200,
                "material_balanced_seven_month_events": 147,
                "price_lead_threshold_bps": 1.0,
                "material_minimum_routes_each_crossing_month": 2,
                "material_minimum_input_usd_each_crossing_month": 1_000.0,
                "event_selection_uses_future_information": False,
            }
        ]
    )


def test_price_rank_crossing_table_renders_dynamics_and_regressions() -> None:
    rendered = render_price_rank_crossing(pd.DataFrame(_rows()), _support())

    assert "Incumbent route share around an exact-price rank crossing" in rendered
    assert "Stable challenger" in rendered
    assert "Native challenger" in rendered
    assert "Challenger weak-leg capital share" in rendered
    assert "Actual crossing [vs. months -3 to -2]" in rendered
    assert "$+3.70^{**}$" in rendered
    assert "$-28.98^{***}$" in rendered
    assert "Crossing-month fixed effects & Yes & Yes & Yes & No" in rendered
    assert "Crossing-event fixed effects & No & No & No & Yes" in rendered


def test_price_rank_crossing_table_rejects_future_dated_event() -> None:
    support = _support()
    support.loc[0, "event_selection_uses_future_information"] = True
    with pytest.raises(ValueError, match="exclude future information"):
        render_price_rank_crossing(pd.DataFrame(_rows()), support)


def test_price_rank_crossing_table_requires_reverse_crossings() -> None:
    support = _support()
    support.loc[0, "material_native_challenger_events"] = 199
    with pytest.raises(ValueError, match="reverse crossing counts"):
        render_price_rank_crossing(pd.DataFrame(_rows()), support)


def test_price_rank_crossing_values_bind_promoted_results() -> None:
    rows = _rows()
    rows.extend(
        [
            {
                "record_type": "price_rank_crossing_follow_up",
                "sample": "material_crossings_with_next_month",
                "follow_up_rank": "challenger_still_ahead",
                "event_share": 0.506,
                "mean_incumbent_route_share": 0.230,
            },
            {
                "record_type": "price_rank_crossing_follow_up",
                "sample": "material_crossings_with_next_month",
                "follow_up_rank": "incumbent_ahead_again",
                "event_share": 0.465,
                "mean_incumbent_route_share": 0.734,
            },
        ]
    )
    rendered = render_price_rank_crossing_values(pd.DataFrame(rows), _support())

    assert r"\newcommand{\RankCrossingEvents}{400}" in rendered
    assert r"\newcommand{\RankCrossingCapitalPersistence}{3.70~pp}" in rendered
    assert r"\newcommand{\RankCrossingStillAhead}{50.6\%}" in rendered
