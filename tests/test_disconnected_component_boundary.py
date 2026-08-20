from __future__ import annotations

import pandas as pd

from scripts.analyze.run_disconnected_component_boundary import (
    component_route_sensitivity,
    render_table,
    render_values,
)


def _legs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tx_hash": "0x1",
                "component_id": 0,
                "source": "uniswap_v3",
                "token_in": "0xa",
                "token_out": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "amount_usd": 100.0,
                "log_index": 1,
                "route_class": "tricky_independent",
                "tin_role": "source",
                "tout_role": "intermediate",
                "timestamp_utc": 1_700_000_000,
            },
            {
                "tx_hash": "0x1",
                "component_id": 0,
                "source": "uniswap_v4",
                "token_in": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "token_out": "0xb",
                "amount_usd": 100.0,
                "log_index": 2,
                "route_class": "tricky_independent",
                "tin_role": "intermediate",
                "tout_role": "sink",
                "timestamp_utc": 1_700_000_000,
            },
            {
                "tx_hash": "0x1",
                "component_id": 1,
                "source": "uniswap_v2",
                "token_in": "0xc",
                "token_out": "0xd",
                "amount_usd": 50.0,
                "log_index": 3,
                "route_class": "tricky_independent",
                "tin_role": "source",
                "tout_role": "sink",
                "timestamp_utc": 1_700_000_000,
            },
        ]
    )


def _results() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, share in ((2024, 0.008), (2025, 0.037), (2026, 0.062)):
        rows.append(
            {
                "record_type": "annual_boundary",
                "year": year,
                "disconnected_component_share": share,
            }
        )
    for year, other, v4 in ((2025, 0.027, 0.116), (2026, 0.047, 0.094)):
        for touches_v4, share in ((False, other), (True, v4)):
            rows.append(
                {
                    "record_type": "v4_boundary",
                    "year": year,
                    "touches_v4": touches_v4,
                    "disconnected_component_share": share,
                }
            )
    for rule, count, value in (
        ("principal_connected_routes", (0.169, 0.423, 0.254), (0.327, 0.765, 0.439)),
        (
            "internally_valid_component_routes",
            (0.169, 0.437, 0.268),
            (0.329, 0.773, 0.444),
        ),
    ):
        for weighting, values in (("episode", count), ("value", value)):
            rows.append(
                {
                    "record_type": "headline_sensitivity",
                    "sample_rule": rule,
                    "weighting": weighting,
                    "baseline_daily_mean": values[0],
                    "comparison_daily_mean": values[1],
                    "change": values[2],
                    "hac_standard_error": 0.01,
                }
            )
    return pd.DataFrame(rows)


def test_component_sensitivity_preserves_only_internally_valid_vehicle_route() -> None:
    routes = component_route_sensitivity(_legs())
    assert len(routes) == 1
    assert routes.iloc[0]["vehicle"] == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    assert routes.iloc[0]["legs"] == 2


def test_rendered_outputs_state_boundary_and_rotation() -> None:
    results = _results()
    values = render_values(results)
    table = render_table(results)
    assert r"\newcommand{\DisconnectedShareEnd}{6.2\%}" in values
    assert r"\newcommand{\ComponentRouteCountEnd}{43.7\%}" in values
    assert "Components touching Uniswap v4" in table
    assert "Each valid component, value" in table
    assert "$+44.4$ (1.00)" in table
