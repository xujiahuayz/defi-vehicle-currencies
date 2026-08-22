from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_bridge_adoption_risk_set import (
    PRIMARY_SAMPLE,
    STRICT_SAMPLE,
    render_bridge_adoption_risk_set,
    render_bridge_adoption_risk_set_values,
)


def _results() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sample_id, pair_weeks, pairs, adoptions, scale in (
        (PRIMARY_SAMPLE, 325_448, 57_344, 697, 1.0),
        (STRICT_SAMPLE, 120_000, 20_000, 400, 0.8),
    ):
        rows.append(
            {
                "sample_id": sample_id,
                "record_type": "bridge_adoption_risk_support",
                "model_id": f"{sample_id}_risk_set",
                "pair_weeks": pair_weeks + 5_000,
                "pairs": pairs + 1_000,
                "adopting_pairs": adoptions + 10,
                "zero_stable_depth_pair_weeks": pair_weeks - 5_000,
            }
        )
        definitions = (
            (
                "m1_preweek_relative_depth",
                "stable_depth_share_10pp",
                3.60 * scale,
                1.30,
                0.006,
                pair_weeks,
            ),
            (
                "m3_future_depth_time_reversal",
                "lead_stable_depth_share_10pp",
                5.01 * scale,
                1.39,
                0.0004,
                pair_weeks - 7_000,
            ),
            (
                "m4_preweek_and_future_depth",
                "stable_depth_share_10pp",
                2.94 * scale,
                1.21,
                0.016,
                pair_weeks - 7_000,
            ),
            (
                "m4_preweek_and_future_depth",
                "lead_stable_depth_share_10pp",
                4.58 * scale,
                1.32,
                0.0006,
                pair_weeks - 7_000,
            ),
        )
        for model_id, predictor, coefficient_pp, se_pp, p_value, model_n in definitions:
            rows.append(
                {
                    "sample_id": sample_id,
                    "record_type": "bridge_adoption_risk_model",
                    "model_id": model_id,
                    "predictor": predictor,
                    "coefficient_pp": coefficient_pp,
                    "standard_error_pp": se_pp,
                    "p_value": p_value,
                    "pair_weeks": model_n,
                    "pairs": pairs,
                    "adoptions": adoptions,
                }
            )
    return pd.DataFrame(rows)


def test_bridge_adoption_risk_table_labels_the_future_capital_comparison() -> None:
    rendered = render_bridge_adoption_risk_set(_results())
    assert "(1) Preweek & (2) Next week & (3) Joint timing" in rendered
    assert "Next-week stable share of joint weak-leg capital" in rendered
    assert "Panel A. At least 10 WETH routes on three days" in rendered
    assert "Panel B. At least 50 WETH routes on five days" in rendered
    assert "$+3.60^{***}$" in rendered
    assert "$+5.01^{***}$" in rendered
    assert "325,448" in rendered
    assert "318,448" in rendered
    assert "future capital conditional on preweek capital" in rendered
    assert "does not establish that capital precedes use" in rendered
    assert "time reversal" not in rendered
    assert "diagnostic" not in rendered


def test_bridge_adoption_risk_values_share_the_table_rows() -> None:
    values = render_bridge_adoption_risk_set_values(_results())
    assert r"\newcommand{\BridgeAdoptionRiskPairWeeks}{330{,}448}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweek}{$+3.60$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweekSE}{$1.30$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweekP}{$p=0.006$}" in values
    assert r"\newcommand{\BridgeAdoptionRiskFuture}{$+5.01$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskFutureP}{$p<0.001$}" in values
    assert r"\newcommand{\BridgeAdoptionRiskStrictPreweek}{$+2.88$ pp}" in values
