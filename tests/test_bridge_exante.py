from __future__ import annotations

import math

import pandas as pd

from ddvc.analysis.bridge_exante import (
    adoption_and_retention_summaries,
    paired_share_change_regressions,
    prepare_exante_bridge_panel,
    relative_depth_regressions,
)
from scripts.analyze.run_bridge_exante import event_support_rows
from scripts.tabulate.render_bridge_exante import (
    render_bridge_exante,
    render_bridge_exante_values,
)


def _event_panel() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event_number in range(40):
        event_date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=event_number)
        for event_time, stable_routes, native_routes, stable_depth in (
            (-1, 0.0, 10.0, 0.0),
            (0, 4.0, 6.0, 20.0 + event_number),
            (30, 5.0, 5.0, 30.0 + event_number),
        ):
            rows.append(
                {
                    "event_id": f"event-{event_number}",
                    "ordered_pair": f"src-{event_number}|tgt-{event_number}",
                    "event_date": event_date,
                    "origin_date": event_date + pd.Timedelta(days=event_time),
                    "event_time": event_time,
                    "first_supported_stable_route_date": event_date,
                    "native_routes": native_routes,
                    "stable_routes": stable_routes,
                    "native_value_usd": 100.0 * native_routes,
                    "stable_value_usd": 100.0 * stable_routes,
                    "stable_bridge_min_capital_usd": stable_depth,
                    "native_bridge_min_capital_usd": 100.0,
                }
            )
    return prepare_exante_bridge_panel(pd.DataFrame(rows))


def test_exante_adoption_retention_and_paired_changes() -> None:
    panel = _event_panel()
    summaries = adoption_and_retention_summaries(panel)
    adoption = summaries.set_index("model_id")
    assert adoption.loc["within_30_days", "estimate"] == 1.0
    assert adoption.loc["within_120_days", "estimate"] == 1.0
    assert adoption.loc["stable_route_observed_days_30_119", "estimate"] == 1.0
    assert math.isclose(
        adoption.loc["stable_route_share_days_30_119", "estimate"], 0.5
    )

    changes = paired_share_change_regressions(panel).set_index("period")
    assert math.isclose(changes.loc["post_0_29", "coefficient"], 0.4)
    assert math.isclose(changes.loc["post_30_119", "coefficient"], 0.5)
    support = event_support_rows(panel, min_stable_weak_leg_usd=100_000.0).iloc[0]
    assert support["min_stable_weak_leg_usd"] == 100_000.0


def test_exante_event_rejects_route_before_lagged_capital_threshold() -> None:
    panel = _event_panel()
    panel.loc[panel["event_id"].eq("event-0"), "first_supported_stable_route_date"] = (
        pd.Timestamp("2023-12-31")
    )
    try:
        prepare_exante_bridge_panel(panel)
    except ValueError as error:
        assert "predates" in str(error)
    else:
        raise AssertionError("pre-event route use must fail validation")


def test_relative_depth_uses_within_event_changes() -> None:
    rows: list[dict[str, object]] = []
    for event_number in range(30):
        event_date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=event_number)
        for event_time in (0, 3, 8, 15, 22, 29, 35, 50, 70, 95, 119):
            depth_share = 0.15 + 0.005 * ((event_number * 7 + event_time * 3) % 60)
            stable_share = 0.10 + 0.60 * depth_share
            total_routes = 1_000.0
            stable_depth = 100.0 * depth_share / (1.0 - depth_share)
            rows.append(
                {
                    "event_id": f"event-{event_number}",
                    "ordered_pair": f"src-{event_number}|tgt-{event_number}",
                    "event_date": event_date,
                    "origin_date": event_date + pd.Timedelta(days=event_time),
                    "event_time": event_time,
                    "first_supported_stable_route_date": event_date,
                    "native_routes": total_routes * (1.0 - stable_share),
                    "stable_routes": total_routes * stable_share,
                    "native_value_usd": total_routes * (1.0 - stable_share),
                    "stable_value_usd": total_routes * stable_share,
                    "stable_bridge_min_capital_usd": stable_depth,
                    "native_bridge_min_capital_usd": 100.0,
                }
            )
    panel = prepare_exante_bridge_panel(pd.DataFrame(rows))
    result = relative_depth_regressions(
        panel, min_observations=50, min_clusters=20
    ).set_index("period")
    assert math.isclose(result.loc["post_0_29", "coefficient"], 0.60, rel_tol=1e-7)
    assert math.isclose(
        result.loc["post_30_119", "coefficient"], 0.60, rel_tol=1e-7
    )


def test_bridge_exante_table_contains_threshold_uptake_and_post_formation_depth() -> None:
    results = pd.DataFrame(
        [
            {"record_type": "exante_bridge_support", "model_id": "lagged_capital_threshold", "min_stable_weak_leg_usd": 10_000.0, "events": 100},
            {"record_type": "exante_bridge_adoption", "model_id": "within_30_days", "estimate": 0.6, "events": 100},
            {"record_type": "exante_bridge_adoption", "model_id": "within_120_days", "estimate": 0.8, "events": 100},
            {"record_type": "exante_bridge_retention", "model_id": "stable_route_observed_days_30_119", "estimate": 0.7, "events": 60},
            {"record_type": "exante_bridge_retention", "model_id": "stable_route_share_days_30_119", "estimate": 0.4, "events": 60},
            {"record_type": "exante_bridge_paired_change", "model_id": "stable_route_share_change", "period": "post_0_29", "coefficient_pp": 8.0, "standard_error_pp": 2.0, "p_value": 0.01, "events": 90},
            {"record_type": "exante_bridge_paired_change", "model_id": "stable_route_share_change", "period": "post_30_119", "coefficient_pp": 5.0, "standard_error_pp": 2.0, "p_value": 0.04, "events": 85},
            {"record_type": "exante_bridge_relative_depth", "model_id": "stable_route_share_on_relative_depth", "period": "post_0_29", "coefficient_pp_per_10pp_depth_share": 3.0, "standard_error_pp_per_10pp_depth_share": 1.0, "p_value": 0.01, "events": 90},
            {"record_type": "exante_bridge_relative_depth", "model_id": "stable_route_share_on_relative_depth", "period": "post_30_119", "coefficient_pp_per_10pp_depth_share": 2.0, "standard_error_pp_per_10pp_depth_share": 1.0, "p_value": 0.08, "events": 85},
        ]
    )
    rendered = render_bridge_exante(results)
    assert "Route use after the lagged-capital threshold" in rendered
    assert "Prior-day weak-leg capital and route allocation" in rendered
    assert "Prior capital and first stablecoin use" not in rendered
    values = render_bridge_exante_values(results)
    assert r"\newcommand{\BridgeExanteThreshold}{\$10{,}000}" in values
    assert r"\newcommand{\BridgeExanteThresholdShort}{\$10k}" in values
    assert r"\newcommand{\BridgeExanteEvents}{100}" in values
    assert r"\newcommand{\BridgeExanteAdoptionThirty}{60.0\%}" in values
    assert (
        r"\newcommand{\BridgeExantePostShareThirty}"
        r"{8.00\%}"
    ) in values
    assert r"\BridgeExanteChangeThirty" not in values
