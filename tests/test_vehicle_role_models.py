from __future__ import annotations

import pandas as pd

from ddvc.asset_types import NATIVE, STABLE
from scripts.run_vehicle_role_models import (
    _finite_inference,
    build_transition_risk,
    fit_discrete_logit,
    fit_stratified_cox_sensitivity,
    prepare_candidate_panel,
    summarize_transition_support,
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
    assert risk["substitution_exit_event"].sum() == 8
    assert risk["role_disappearance_event"].sum() == 0
    assert risk["continuing_use_event"].sum() == 12
    assert risk["duration_weeks"].min() == 1


def test_pair_stratified_cox_uses_the_same_spells() -> None:
    risk = build_transition_risk(source_panel())
    result = fit_stratified_cox_sensitivity(risk, "formation")
    assert result["method"] == "cox_breslow_pair_stratified_sensitivity"
    assert result["events"] == 8
    assert result["observations"] > result["events"]


def test_role_disappearance_is_counted_once_per_at_risk_pair_week() -> None:
    # Two used candidates disappear together; a third candidate is unused throughout.
    last_two = pd.date_range("2025-02-17", periods=2, freq="7D")
    extra = []
    native = next(iter(NATIVE))
    stable, unused_stable = list(STABLE)[:2]
    for candidate, symbol, pattern in (
        (native, "ETH/WETH", (5, 0)),
        (stable, "USDC", (5, 0)),
        (unused_stable, "USDT", (0, 0)),
    ):
        for week, routes in zip(last_two, pattern, strict=True):
            extra.append(
                {
                    "week": week,
                    "src": "role-pair",
                    "sink": "role-target",
                    "vehicle": symbol,
                    "vehicle_id": candidate,
                    "total_routes": routes,
                }
            )
    source = pd.DataFrame(extra)
    panel = prepare_candidate_panel(source)
    risk = build_transition_risk(source)
    role_rows = risk[
        risk["src"].eq("role-pair") & risk["week"].eq(last_two[0])
    ]
    assert len(role_rows) == 3
    assert role_rows.loc[
        role_rows["used"].eq(1), "role_disappearance_event"
    ].eq(1).all()
    assert role_rows.loc[
        role_rows["used"].eq(0), "role_disappearance_event"
    ].eq(0).all()
    support = summarize_transition_support(source, panel, risk).iloc[0]
    assert support["role_disappearance_event_pair_weeks"] == 1
    assert support["role_disappearance_risk_pair_weeks"] == 1
    assert support["substitution_exit_risk_rows"] == 2


def test_candidate_models_reject_pair_level_role_disappearance() -> None:
    risk = build_transition_risk(source_panel())
    try:
        fit_discrete_logit(risk, "role_disappearance")
    except ValueError as exc:
        assert "unknown vehicle-role transition" in str(exc)
    else:
        raise AssertionError("pair-level disappearance was admitted as a candidate logit")
    try:
        fit_stratified_cox_sensitivity(risk, "role_disappearance")
    except ValueError as exc:
        assert "candidate-level Cox" in str(exc)
    else:
        raise AssertionError("pair-level disappearance was admitted as a candidate hazard")
