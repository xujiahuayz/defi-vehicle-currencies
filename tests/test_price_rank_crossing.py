from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_price_rank_crossing import (
    attach_next_month_outcome,
    build_event_panel,
    build_pair_month_panel,
    identify_crossings,
)


def _route(
    *,
    route_id: str,
    day: str,
    gap: float,
    stable: bool,
    capital_share: float,
    pair: str = "a>b",
    input_usd: float = 600.0,
) -> dict[str, object]:
    token_in, token_out = pair.split(">")
    return {
        "ordered_pair": pair,
        "day": day,
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "route_id": route_id,
        "token_in": token_in,
        "token_out": token_out,
        "chosen_stable": stable,
        "stable_minus_native_bps": gap,
        "input_usd": input_usd,
        "symmetric_common_support": True,
        "stable_v2_capital_share": capital_share,
    }


def test_pair_month_median_and_crossing_use_current_and_prior_months() -> None:
    routes = pd.DataFrame(
        [
            _route(
                route_id="jan-1",
                day="20240115",
                gap=-3.0,
                stable=False,
                capital_share=0.2,
            ),
            _route(
                route_id="jan-2",
                day="20240115",
                gap=-1.0,
                stable=True,
                capital_share=0.4,
            ),
            _route(
                route_id="feb-1",
                day="20240215",
                gap=1.0,
                stable=True,
                capital_share=0.6,
            ),
            _route(
                route_id="feb-2",
                day="20240215",
                gap=5.0,
                stable=True,
                capital_share=0.8,
            ),
            _route(
                route_id="mar-1",
                day="20240315",
                gap=-2.0,
                stable=False,
                capital_share=0.4,
            ),
            _route(
                route_id="mar-2",
                day="20240315",
                gap=-4.0,
                stable=False,
                capital_share=0.4,
            ),
        ]
    )
    monthly = build_pair_month_panel(routes)
    january = monthly.set_index("day").loc["20240115"]
    assert january["median_stable_minus_native_bps"] == pytest.approx(-2.0)
    assert january["stable_route_share"] == pytest.approx(0.5)
    assert january["event_eve_stable_v2_capital_share"] == pytest.approx(0.3)
    assert january["price_state"] == -1

    events = identify_crossings(
        monthly,
        minimum_routes=2,
        minimum_input_usd=1_000.0,
        sample="material",
    )
    february = events.set_index("day").loc["20240215"]
    assert february["direction"] == "stable_challenger"
    assert february["event_eve_challenger_v2_capital_share"] == pytest.approx(0.7)
    assert february["prior_incumbent_route_share"] == pytest.approx(0.5)
    assert february["current_incumbent_route_share"] == pytest.approx(0.0)
    assert not bool(february["event_selection_uses_future_information"])
    assert "20240315" in set(events["day"])


def test_crossing_requires_consecutive_months_and_both_material_cells() -> None:
    monthly = pd.DataFrame(
        [
            {
                "ordered_pair": "a>b",
                "day": "20240115",
                "date": pd.Timestamp("2024-01-15"),
                "month_index": 2024 * 12 + 1,
                "price_state": -1,
                "route_count": 2,
                "observed_input_usd": 1_200.0,
                "stable_route_share": 0.0,
                "median_stable_minus_native_bps": -2.0,
                "event_eve_stable_v2_capital_share": 0.2,
                "token_in": "a",
                "token_out": "b",
            },
            {
                "ordered_pair": "a>b",
                "day": "20240315",
                "date": pd.Timestamp("2024-03-15"),
                "month_index": 2024 * 12 + 3,
                "price_state": 1,
                "route_count": 2,
                "observed_input_usd": 1_200.0,
                "stable_route_share": 1.0,
                "median_stable_minus_native_bps": 2.0,
                "event_eve_stable_v2_capital_share": 0.8,
                "token_in": "a",
                "token_out": "b",
            },
        ]
    )
    with pytest.raises(ValueError, match="sample material is empty"):
        identify_crossings(
            monthly,
            minimum_routes=2,
            minimum_input_usd=1_000.0,
            sample="material",
        )


def test_event_panel_normalizes_stable_and_native_challengers() -> None:
    rows = []
    for pair, stable_share in (("a>b", 0.8), ("c>d", 0.3)):
        token_in, token_out = pair.split(">")
        for offset in range(-3, 4):
            date = pd.Timestamp("2024-04-15") + pd.DateOffset(months=offset)
            rows.append(
                {
                    "ordered_pair": pair,
                    "day": date.strftime("%Y%m%d"),
                    "date": date,
                    "month_index": date.year * 12 + date.month,
                    "stable_route_share": stable_share,
                    "median_stable_minus_native_bps": float(offset),
                    "route_count": 2,
                    "token_in": token_in,
                    "token_out": token_out,
                }
            )
    events = pd.DataFrame(
        [
            {
                "event_id": "a>b:20240415",
                "sample": "material",
                "ordered_pair": "a>b",
                "month_index": 2024 * 12 + 4,
                "direction": "stable_challenger",
                "stable_challenger": 1.0,
                "capital_group": "challenger_capital_below_half",
                "event_eve_challenger_v2_capital_share": 0.2,
            },
            {
                "event_id": "c>d:20240415",
                "sample": "material",
                "ordered_pair": "c>d",
                "month_index": 2024 * 12 + 4,
                "direction": "native_challenger",
                "stable_challenger": 0.0,
                "capital_group": "challenger_capital_at_least_half",
                "event_eve_challenger_v2_capital_share": 0.8,
            },
        ]
    )
    panel = build_event_panel(pd.DataFrame(rows), events)
    at_zero = panel[panel["event_time"].eq(0)].set_index("event_id")
    assert at_zero.loc["a>b:20240415", "incumbent_route_share"] == pytest.approx(0.2)
    assert at_zero.loc["c>d:20240415", "incumbent_route_share"] == pytest.approx(0.3)
    assert panel.groupby("event_id")["balanced_seven_month_window"].all().all()

    follow = attach_next_month_outcome(events, panel).set_index("event_id")
    assert bool(follow.loc["a>b:20240415", "challenger_leads_next_month"])
    assert not bool(follow.loc["c>d:20240415", "challenger_leads_next_month"])


def test_pair_month_excludes_non_common_support_route() -> None:
    rows = [
        _route(
            route_id="kept",
            day="20240115",
            gap=-2.0,
            stable=False,
            capital_share=0.3,
        ),
        _route(
            route_id="dropped",
            day="20240115",
            gap=100.0,
            stable=True,
            capital_share=0.9,
        ),
    ]
    rows[1]["symmetric_common_support"] = False
    monthly = build_pair_month_panel(pd.DataFrame(rows))
    assert len(monthly) == 1
    assert monthly.iloc[0]["route_count"] == 1
    assert monthly.iloc[0]["median_stable_minus_native_bps"] == pytest.approx(-2.0)
