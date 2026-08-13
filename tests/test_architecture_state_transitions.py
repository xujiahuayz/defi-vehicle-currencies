from __future__ import annotations

import pandas as pd

from scripts.run_architecture_state_transitions import (
    build_full_risk_panel,
    event_contrasts,
    summarize_transition_support,
    transition_events,
)
from scripts.run_v4_settlement_identification import _exclusive_architecture


def _routes() -> pd.DataFrame:
    rows = []
    for week_index, week in enumerate(pd.date_range("2025-01-06", periods=44, freq="7D")):
        v4 = 0 if week_index < 10 or week_index >= 30 else 4
        v3 = 4 if v4 == 0 else 0
        for dex, count in (("uniswap_v3", v3), ("uniswap_v4", v4)):
            rows.extend(
                {
                    "week": week,
                    "src": "A",
                    "sink": "B",
                    "vehicle": "USDC",
                    "dex": dex,
                    "route_usd": 100.0,
                }
                for _ in range(count)
            )
        # A second vehicle makes vehicle_route_share a distinct outcome from V4 share.
        rows.extend(
            {
                "week": week,
                "src": "A",
                "sink": "B",
                "vehicle": "WETH",
                "dex": "uniswap_v3",
                "route_usd": 100.0,
            }
            for _ in range(4)
        )
    return pd.DataFrame(rows)


def test_full_risk_panel_keeps_one_architecture_cells_and_fills_other_side_zero() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    usdc = panel[panel.vehicle.eq("USDC")]
    assert (usdc.routes_uniswap_v4.iloc[:10] == 0).all()
    assert (usdc.routes_uniswap_v3.iloc[10:30] == 0).all()
    assert len(usdc) == 44


def test_mixed_route_is_not_relabelled_as_a_pure_architecture() -> None:
    mixed = pd.DataFrame({"source": ["uniswap_v3", "uniswap_v4"]})
    pure = pd.DataFrame({"source": ["uniswap_v4", "uniswap_v4"]})
    assert _exclusive_architecture(mixed) is None
    assert _exclusive_architecture(pure) == "uniswap_v4"


def test_sustained_entry_and_exit_are_both_detected() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    events = transition_events(panel, threshold=0.10, confirmation_weeks=3)
    usdc = events[events.vehicle.eq("USDC")]
    assert usdc.kind.tolist() == ["entry", "exit"]
    assert set(usdc.transition_margin) == {"within_observed_vehicle_cell"}
    assert usdc.event_week.dt.strftime("%Y-%m-%d").tolist() == ["2025-03-17", "2025-08-04"]


def test_calendar_gap_does_not_create_a_transition() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    panel = panel[~panel.week.eq(pd.Timestamp("2025-03-10"))]
    events = transition_events(panel, threshold=0.10, confirmation_weeks=3)
    assert not ((events.vehicle.eq("USDC")) & events.kind.eq("entry")).any()


def test_event_outcome_is_overall_vehicle_use_not_architecture_share() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    events = transition_events(panel, threshold=0.10, confirmation_weeks=3)
    contrasts = event_contrasts(panel, events)
    assert set(contrasts.outcome) == {
        "pair-week-adjusted overall V3+V4 vehicle route share"
    }
    assert set(contrasts.status) == {"usable"}
    assert (contrasts.immediate_change == 0).all()


def test_pair_week_adjustment_removes_common_pair_week_change() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    assert panel.groupby(["week", "src", "sink"])[
        "pair_week_adjusted_vehicle_share"
    ].sum().abs().lt(1e-12).all()


def test_low_support_peer_remains_in_pair_week_denominator_before_filtering() -> None:
    routes = _routes()
    extra = pd.DataFrame(
        [
            {
                "week": week,
                "src": "A",
                "sink": "B",
                "vehicle": "DAI",
                "dex": "uniswap_v3",
                "route_usd": 100.0,
            }
            for week in routes.week.unique()
        ]
    )
    panel = build_full_risk_panel(pd.concat([routes, extra]), min_total_routes=2)
    first = panel[(panel.week.eq(panel.week.min())) & panel.vehicle.eq("USDC")].iloc[0]
    assert first.vehicle_route_share == 4 / 9
    assert first.pair_week_candidate_count == 3
    assert not (panel.vehicle == "DAI").any()


def test_nearby_reversal_marks_event_windows_as_contaminated() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    usdc = panel[panel.vehicle.eq("USDC")].copy()
    usdc.loc[usdc.week.ge(pd.Timestamp("2025-05-12")), "v4_route_share"] = 0.0
    events = transition_events(usdc, threshold=0.10, confirmation_weeks=3)
    contrasts = event_contrasts(usdc, events)
    assert events.kind.tolist() == ["entry", "exit"]
    assert set(contrasts.status) == {"overlapping_transition"}
    assert contrasts.immediate_change.isna().all()


def test_changing_peer_set_marks_only_affected_event_window_as_contaminated() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    events = transition_events(panel, threshold=0.10, confirmation_weeks=3)
    changed_week = pd.Timestamp("2025-02-17")
    panel.loc[
        panel.week.eq(changed_week), "pair_week_vehicle_set_sha256"
    ] = "changed"
    contrasts = event_contrasts(panel, events)
    usdc = contrasts[contrasts.vehicle.eq("USDC")]
    assert usdc.status.tolist() == ["composition_shift", "usable"]


def test_support_summary_keeps_zero_event_threshold_kind_cells() -> None:
    panel = build_full_risk_panel(_routes(), min_total_routes=1)
    events = transition_events(panel, threshold=0.10, confirmation_weeks=3)
    contrasts = event_contrasts(panel, events)
    support = summarize_transition_support(contrasts, thresholds=[0.10, 0.25])

    assert support[["threshold", "kind"]].to_records(index=False).tolist() == [
        (0.10, "entry"),
        (0.10, "exit"),
        (0.25, "entry"),
        (0.25, "exit"),
    ]
    assert support.detected_events.tolist() == [1, 1, 0, 0]
    assert set(support.transition_margin) == {"within_observed_vehicle_cell"}
    assert support.usable_events.tolist() == [1, 1, 0, 0]
    assert support.mean_immediate_change.iloc[:2].eq(0).all()
    assert support.mean_immediate_change.iloc[2:].isna().all()
