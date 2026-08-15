from __future__ import annotations

import pandas as pd
import pytest

from scripts.build_liquidity_capital_v2_deck_values import (
    DIRECTIONS,
    LONG_HORIZON,
    MEASURE_PAIRS,
    PRIMARY_HORIZONS,
    render_liquidity_capital_v2_deck_values,
)


def _row(
    pair_id: str,
    direction: str,
    horizon: int,
    *,
    coefficient: float = 0.001,
    p_value: float = 0.60,
) -> dict[str, object]:
    primary = horizon in PRIMARY_HORIZONS
    return {
        "perimeter": "full_v2_calendar",
        "horizon_days": horizon,
        "primary_horizon": primary,
        "direction": direction,
        "measure_pair_id": pair_id,
        "capital_measure": pair_id.split("__")[1],
        "coefficient": coefficient,
        "standard_error": 0.002,
        "p_value": p_value,
        "p_value_holm": min(1.0, p_value * 2) if primary else float("nan"),
        "month_block_bootstrap_p_value": 0.5,
        "candidate_clusters": 5,
        "calendar_span_days": 2238 - horizon,
        "fixed_effects": "candidate_and_origin_date",
        "interpretation": "temporally_ordered_predictability_not_causal_feedback",
        "analysis_role": (
            "primary_adjudication" if primary else "long_horizon_sensitivity"
        ),
        "reciprocal_pair_pass": False,
        "claim_decision_pass": False,
    }


def _estimates() -> pd.DataFrame:
    rows = []
    for pair_id in MEASURE_PAIRS:
        for direction in DIRECTIONS:
            for horizon in (*PRIMARY_HORIZONS, LONG_HORIZON):
                coefficient = 0.001
                p_value = 0.60
                if horizon == LONG_HORIZON and direction == "capital_to_route" and (
                    pair_id.startswith("intermediary_episode_share__")
                ):
                    coefficient = -0.022
                    p_value = 0.001
                rows.append(
                    _row(
                        pair_id,
                        direction,
                        horizon,
                        coefficient=coefficient,
                        p_value=p_value,
                    )
                )
    return pd.DataFrame(rows)


def test_renders_all_frame_macros() -> None:
    rendered = render_liquidity_capital_v2_deck_values(_estimates())
    for name in (
        "LiqPredCapRouteDayCoef",
        "LiqPredCapRouteDaySE",
        "LiqPredCapRouteMonthCoef",
        "LiqPredCapRouteMonthSE",
        "LiqPredRouteCapDayCoef",
        "LiqPredRouteCapDaySE",
        "LiqPredRouteCapMonthCoef",
        "LiqPredRouteCapMonthSE",
        "LiqPredLongCapRouteCoef",
        "LiqPredLongCapRouteSE",
        "LiqPredMinHolm",
        "LiqPredSpanDays",
    ):
        assert f"\\newcommand{{\\{name}}}" in rendered
    assert "\\newcommand{\\LiqPredSpanDays}{2{,}237}" in rendered


def test_refuses_a_passing_reciprocal_pair() -> None:
    estimates = _estimates()
    estimates.loc[estimates.index[:1], "claim_decision_pass"] = True
    with pytest.raises(ValueError, match="rewrite the deck frame"):
        render_liquidity_capital_v2_deck_values(estimates)


def test_refuses_a_holm_significant_adjudicated_cell() -> None:
    estimates = _estimates()
    primary = estimates["primary_horizon"]
    estimates.loc[estimates.index[primary][:1], "p_value_holm"] = 0.01
    with pytest.raises(ValueError, match="Holm-significant"):
        render_liquidity_capital_v2_deck_values(estimates)


def test_refuses_a_vanished_long_horizon_pattern() -> None:
    estimates = _estimates()
    long_negative = (
        estimates["horizon_days"].eq(LONG_HORIZON)
        & estimates["direction"].eq("capital_to_route")
        & estimates["measure_pair_id"].str.startswith(
            "intermediary_episode_share__"
        )
    )
    estimates.loc[long_negative, "p_value"] = 0.50
    with pytest.raises(ValueError, match="no longer holds"):
        render_liquidity_capital_v2_deck_values(estimates)


def test_refuses_missing_adjudicated_cells() -> None:
    estimates = _estimates()
    trimmed = estimates.drop(estimates.index[:1])
    with pytest.raises(ValueError, match="adjudicated"):
        render_liquidity_capital_v2_deck_values(trimmed)
