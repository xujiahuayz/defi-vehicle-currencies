from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_stable_stable_vehicle_values import (
    render_stable_stable_vehicle_values,
)


def _results() -> pd.DataFrame:
    changes = {
        "native": 0.02,
        "usdt": 0.14,
        "usdc": -0.01,
        "dai": -0.005,
        "other_stable": 0.005,
    }
    return pd.DataFrame(
        [
            {
                "metric": "strict_intermediation_value_share",
                "intermediary_group": group,
                "common_calendar_days": 181,
                "stable_share_contribution_baseline": 0.01,
                "stable_share_contribution_comparison": 0.01 + change,
                "stable_share_contribution_change": change,
            }
            for group, change in changes.items()
        ]
    )


def _robustness() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "strict_intermediation_value_share",
                "year": year,
                "common_calendar_days": 181,
                "active_days": 181,
                "top_decile_trimmed_mean_stable_contribution": value,
                "pooled_mass_stable_contribution": value + 0.01,
            }
            for year, value in ((2024, 0.05), (2026, 0.17))
        ]
    )


def test_stable_stable_vehicle_values_reconcile_usdt_and_other_issuers() -> None:
    rendered = render_stable_stable_vehicle_values(_results(), _robustness())
    assert r"\newcommand{\StableStableUsdtValueContribution}{$+14.0$ pp}" in rendered
    assert r"\newcommand{\StableStableOtherValueContribution}{$-1.0$ pp}" in rendered
    assert r"\newcommand{\StableStableValueContribution}{$+13.0$ pp}" in rendered
    assert r"\newcommand{\StableStableTrimmedValueChange}{$+12.0$ pp}" in rendered


def test_stable_stable_vehicle_values_require_daily_support() -> None:
    robustness = _robustness()
    robustness.loc[0, "active_days"] = 180
    with pytest.raises(ValueError, match="not active on all common days"):
        render_stable_stable_vehicle_values(_results(), robustness)
