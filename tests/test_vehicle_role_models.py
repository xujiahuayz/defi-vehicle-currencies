from __future__ import annotations

import pandas as pd

from ddvc.asset_types import NATIVE, STABLE
from scripts.run_vehicle_role_models import (
    _finite_inference,
    build_transition_risk,
    fit_stratified_cox_sensitivity,
    prepare_candidate_panel,
)


def test_model_inference_fails_closed_on_nonfinite_standard_error() -> None:
    row = pd.Series({"Estimate": 0.1, "Std. Error": float("nan"), "Pr(>|t|)": 0.5})
    try:
        _finite_inference(row, model_name="synthetic logit")
    except ValueError as exc:
        assert "unidentified or numerically unstable" in str(exc)
    else:
        raise AssertionError("non-finite inference was admitted")


def source_panel() -> pd.DataFrame:
    native = next(iter(NATIVE))
    stable = next(iter(STABLE))
    rows = []
    for pair_index in range(4):
        for candidate, symbol, pattern in (
            (native, "ETH/WETH", [1, 1, 0, 0, 1, 1]),
            (stable, "USDC", [0, 0, 1, 1, 0, 0]),
        ):
            for week, used in zip(pd.date_range("2025-01-06", periods=6, freq="7D"), pattern, strict=True):
                rows.append(
                    {
                        "week": week,
                        "src": f"s{pair_index}",
                        "sink": f"t{pair_index}",
                        "vehicle": symbol,
                        "vehicle_id": candidate,
                        "total_routes": 5 * used,
                    }
                )
    return pd.DataFrame(rows)


def test_prepare_candidate_panel_preserves_explicit_zero_rows() -> None:
    panel = prepare_candidate_panel(source_panel())
    assert len(panel) == 48
    assert panel["total_routes"].eq(0).sum() == 24
    assert set(panel["candidate_type"]) == {"stable", "native"}


def test_transition_risk_uses_only_consecutive_pair_active_weeks() -> None:
    risk = build_transition_risk(source_panel())
    assert len(risk) == 40
    assert risk["formation_event"].sum() == 8
    assert risk["loss_event"].sum() == 8
    assert risk["duration_weeks"].min() == 1


def test_pair_stratified_cox_uses_the_same_spells() -> None:
    risk = build_transition_risk(source_panel())
    result = fit_stratified_cox_sensitivity(risk, "formation")
    assert result["method"] == "cox_breslow_pair_stratified_sensitivity"
    assert result["events"] == 8
    assert result["observations"] > result["events"]
