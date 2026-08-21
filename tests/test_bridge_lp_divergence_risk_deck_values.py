from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.build_bridge_lp_divergence_risk_deck_values import (
    render_bridge_lp_divergence_risk_deck_values,
)


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "output/exhibits/bridge_lp_divergence_risk_models.jsonl"
SUPPORT = ROOT / "output/exhibits/bridge_lp_divergence_risk_support.jsonl"
VALUES = ROOT / "output/exhibits/bridge_lp_divergence_risk_deck_values.tex"


def _render() -> str:
    return render_bridge_lp_divergence_risk_deck_values(
        pd.read_json(MODELS, lines=True),
        pd.read_json(SUPPORT, lines=True),
    )


def test_checked_in_bridge_risk_deck_values_equal_renderer() -> None:
    assert VALUES.read_text(encoding="utf-8") == _render()


def test_bridge_risk_deck_values_render_key_macros() -> None:
    rendered = _render()
    expected = (
        r"\newcommand{\BridgeRiskCurrentVolEffect}{$-0.117$}",
        r"\newcommand{\BridgeRiskCurrentVolSE}{$0.049$}",
        r"\newcommand{\BridgeRiskFutureVolEffect}{$-0.093$}",
        r"\newcommand{\BridgeRiskFutureVolSE}{$0.029$}",
        r"\newcommand{\BridgeRiskNativeMedianVol}{126.9\%}",
        r"\newcommand{\BridgeRiskStableMedianVol}{148.4\%}",
        r"\newcommand{\BridgeRiskStableLowerShare}{29.4\%}",
        r"\newcommand{\BridgeRiskObservations}{58{,}447}",
        r"\newcommand{\BridgeRiskPairClusters}{4{,}254}",
        r"\newcommand{\BridgeRiskDateClusters}{71}",
    )
    for macro in expected:
        assert macro in rendered
    assert rendered.count(r"\newcommand{") == len(expected)


def test_bridge_risk_deck_values_reject_direction_change() -> None:
    models = pd.read_json(MODELS, lines=True)
    mask = (
        models["model_id"].eq("m1_prior_depth_volatility")
        & models["predictor"].eq("bridge_relative_volatility")
    )
    models.loc[mask, "effect_log_points_per_10pp_volatility"] = 0.1
    with pytest.raises(ValueError, match="coefficient direction"):
        render_bridge_lp_divergence_risk_deck_values(
            models,
            pd.read_json(SUPPORT, lines=True),
        )
