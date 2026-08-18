from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_route_gas_economics_deck_values import (
    render_route_gas_economics_deck_values,
)


def test_route_gas_macros_render_guarded_headline() -> None:
    rows = [
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "extra_hop_gas_hurdle",
            "route_class": "stable_vehicle",
            "year": 2024,
            "extra_gas_units": 100_000,
            "extra_gas_units_pct_of_direct": 1.0,
            "extra_gas_cost_usd_at_year_medians": 3.2,
            "notional_for_extra_gas_1bp_usd": 32_000,
            "notional_for_extra_gas_10bp_usd": 3_200,
            "route_median_notional_usd": 800,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "extra_hop_gas_hurdle",
            "route_class": "stable_vehicle",
            "year": 2026,
            "extra_gas_units": 200_000,
            "extra_gas_units_pct_of_direct": 1.5,
            "extra_gas_cost_usd_at_year_medians": 0.08,
            "notional_for_extra_gas_1bp_usd": 800,
            "notional_for_extra_gas_10bp_usd": 80,
            "route_median_notional_usd": 82,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "endpoint_extra_hop_hurdle_change",
            "route_class": "stable_vehicle",
            "one_bp_notional_ratio": 0.025,
        },
    ]
    rendered = render_route_gas_economics_deck_values(pd.DataFrame(rows))
    assert "\\GasStableExtraGasUnitsEnd" in rendered
    assert "\\GasStableOneBpNotionalBase" in rendered
    assert "\\$0.08" in rendered
    assert "\\$800" in rendered
