from __future__ import annotations

import pandas as pd

from scripts.tabulate.build_vehicle_formation_deck_values import (
    render_vehicle_formation_deck_values,
)


def test_vehicle_formation_deck_values_render_key_macros() -> None:
    estimates = pd.DataFrame(
        [
            {
                "record_type": "entry_cohort",
                "entry_year": 2024,
                "pairs": 10,
                "primary_routes": 100,
                "stable_share": 0.05,
            },
            {
                "record_type": "entry_cohort",
                "entry_year": 2026,
                "pairs": 20,
                "primary_routes": 200,
                "stable_share": 0.25,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_type": "native_only_entry",
                "pairs": 18,
                "primary_routes": 180,
                "stable_share": 0.005,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 30,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.975,
            },
            {
                "record_type": "entry_persistence_contrast",
                "horizon_days": 30,
                "entry_year": 2026,
                "primary_routes": 200,
                "stable_share": None,
                "coefficient": 0.97,
                "standard_error": 0.02,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 120,
                "entry_year": 2024,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.98,
            },
            {
                "record_type": "entry_persistence",
                "horizon_days": 120,
                "entry_year": 2026,
                "entry_type": "stable_dominant_entry",
                "pairs": 2,
                "primary_routes": 20,
                "stable_share": 0.99,
            },
        ]
    )
    rendered = render_vehicle_formation_deck_values(estimates)
    assert "\\FormationEntryStableShareBase" in rendered
    assert "5.0\\%" in rendered
    assert "$+97.0$ pp" in rendered
