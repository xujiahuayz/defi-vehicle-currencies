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
                "positive_stable_depth_pair_weeks": 5_000,
                "adoptions_with_zero_stable_depth": adoptions - 100,
                "adoptions_with_positive_stable_depth": 110,
            }
        )
        definitions = (
            (
                "m5_any_preweek_stable_support",
                "positive_stable_support",
                1.75 * scale,
                0.60,
                0.004,
                pair_weeks,
                None,
                None,
            ),
            (
                "m6_positive_support_log_depth_advantage",
                "log_depth_advantage",
                0.42 * scale,
                0.18,
                0.020,
                pair_weeks // 20,
                0.97 * scale,
                0.41,
            ),
            (
                "m1_preweek_relative_depth",
                "stable_depth_share_10pp",
                3.60 * scale,
                1.30,
                0.006,
                pair_weeks,
                None,
                None,
            ),
            (
                "m3_future_depth_time_reversal",
                "lead_stable_depth_share_10pp",
                5.01 * scale,
                1.39,
                0.0004,
                pair_weeks - 7_000,
                None,
                None,
            ),
            (
                "m4_preweek_and_future_depth",
                "stable_depth_share_10pp",
                2.94 * scale,
                1.21,
                0.016,
                pair_weeks - 7_000,
                None,
                None,
            ),
            (
                "m4_preweek_and_future_depth",
                "lead_stable_depth_share_10pp",
                4.58 * scale,
                1.32,
                0.0006,
                pair_weeks - 7_000,
                None,
                None,
            ),
        )
        for (
            model_id,
            predictor,
            coefficient_pp,
            se_pp,
            p_value,
            model_n,
            coefficient_pp_per_10x,
            standard_error_pp_per_10x,
        ) in definitions:
            rows.append(
                {
                    "sample_id": sample_id,
                    "record_type": "bridge_adoption_risk_model",
                    "model_id": model_id,
                    "predictor": predictor,
                    "coefficient_pp": coefficient_pp,
                    "standard_error_pp": se_pp,
                    "coefficient_pp_per_10x": coefficient_pp_per_10x,
                    "standard_error_pp_per_10x": standard_error_pp_per_10x,
                    "p_value": p_value,
                    "pair_weeks": model_n,
                    "pairs": pairs,
                    "adoptions": adoptions,
                }
            )
    return pd.DataFrame(rows)


def test_bridge_adoption_risk_table_labels_the_future_capital_comparison() -> None:
    rendered = render_bridge_adoption_risk_set(_results())
    assert r"(1)\\Any\\support" in rendered
    assert r"(2)\\Capital\\ratio" in rendered
    assert r"(5)\\Joint\\timing" in rendered
    assert "Any measured V2 stable bridge capital before the week" in rendered
    assert "positive-support weeks" in rendered
    assert "Next-week stable share of joint weak-leg capital" in rendered
    assert "Panel A. Prior 28 days: at least 10 WETH routes on three days" in rendered
    assert "Panel B. Prior 28 days: at least 50 WETH routes on five days" in rendered
    assert "$+1.75^{***}$" in rendered
    assert "$+0.97^{**}$" in rendered
    assert "$+3.60^{***}$" in rendered
    assert "$+5.01^{***}$" in rendered
    assert "325,448" in rendered
    assert "318,448" in rendered
    assert "measure next-week association" in rendered
    assert "capital adjustments following adoption" in rendered
    assert "at least two positive-support weeks" in rendered
    assert "time reversal" not in rendered
    assert "diagnostic" not in rendered


def test_bridge_adoption_risk_values_share_the_table_rows() -> None:
    values = render_bridge_adoption_risk_set_values(_results())
    assert r"\newcommand{\BridgeAdoptionRiskPairWeeks}{330{,}448}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPositiveDepthWeeks}{5{,}000}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPositiveDepthAdoptions}{110}" in values
    assert r"\newcommand{\BridgeAdoptionRiskIntensivePairWeeks}{16{,}272}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweek}{$+3.60$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweekSE}{$1.30$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskPreweekP}{$p=0.006$}" in values
    assert r"\newcommand{\BridgeAdoptionRiskFuture}{$+5.01$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskFutureP}{$p<0.001$}" in values
    assert r"\newcommand{\BridgeAdoptionRiskStrictPreweek}{$+2.88$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskAnySupport}{$+1.75$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskAnySupportP}{$p=0.004$}" in values
    assert r"\newcommand{\BridgeAdoptionRiskIntensiveTenfold}{$+0.97$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskIntensiveTenfoldSE}{$0.41$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskStrictAnySupport}{$+1.40$ pp}" in values
    assert r"\newcommand{\BridgeAdoptionRiskStrictIntensiveTenfold}{$+0.78$ pp}" in values
