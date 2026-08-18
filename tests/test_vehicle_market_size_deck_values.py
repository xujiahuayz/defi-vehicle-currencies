from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_vehicle_market_size_deck_values import (
    render_vehicle_market_size_deck_values,
)


def test_market_size_deck_values_render_from_guarded_rows() -> None:
    rows = [
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_market_size_change",
            "estimand": "thin_1_5",
            "baseline_year": 2024,
            "comparison_year": 2026,
            "baseline_mean": 0.07,
            "comparison_mean": 0.21,
            "change": 0.14,
            "standard_error": 0.01,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_market_size_change",
            "estimand": "thick_gt100",
            "baseline_year": 2024,
            "comparison_year": 2026,
            "baseline_mean": 0.65,
            "comparison_mean": 0.74,
            "change": 0.09,
            "standard_error": 0.03,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "daily_market_size_change",
            "estimand": "thick_minus_thin",
            "baseline_year": 2024,
            "comparison_year": 2026,
            "baseline_mean": 0.58,
            "comparison_mean": 0.53,
            "change": -0.05,
            "standard_error": 0.04,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "entry_market_size_summary",
            "entry_year": 2024,
            "size_bin": "thick_gt100",
            "pairs": 20,
            "stable_count_share": 0.60,
            "entry_route_mass_share": 0.10,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "entry_market_size_summary",
            "entry_year": 2026,
            "size_bin": "thick_gt100",
            "pairs": 30,
            "stable_count_share": 0.90,
            "entry_route_mass_share": 0.22,
        },
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "entry_market_size_summary",
            "entry_year": 2026,
            "size_bin": "thin_1_5",
            "pairs": 300,
            "stable_count_share": 0.10,
            "entry_route_mass_share": 0.60,
        },
    ]
    rendered = render_vehicle_market_size_deck_values(pd.DataFrame(rows))
    assert "\\MarketSizeThinShareEnd" in rendered
    assert "\\MarketSizeThickShareEnd" in rendered
    assert "\\MarketSizeThickMinusThinEnd" in rendered
    assert "\\MarketSizeEntryThickShareEnd" in rendered
    assert "\\MarketSizeEntryThickMassEnd" in rendered
    assert "74.0\\%" in rendered
    assert "90.0\\%" in rendered
