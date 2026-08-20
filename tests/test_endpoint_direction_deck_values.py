from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_endpoint_direction_deck_values import (
    render_endpoint_direction_values,
)


def _results() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    contributions = {
        "native_to_native": 0.0,
        "native_to_stable": 0.04,
        "stable_to_native": 0.05,
        "stable_to_stable": 0.01,
        "other_endpoints": 0.15,
    }
    for metric in ("count_share", "strict_intermediation_value_share"):
        for group, change in contributions.items():
            rows.append(
                {
                    "metric": metric,
                    "endpoint_group": group,
                    "common_calendar_days": 181,
                    "stable_share_contribution_change": change,
                    "share_of_total_stable_change": change / 0.25,
                    "overall_stable_share_baseline": 0.15,
                    "overall_stable_share_comparison": 0.40,
                    "overall_stable_share_change": 0.25,
                }
            )
    return pd.DataFrame(rows)


def test_endpoint_direction_values_combine_opposite_native_stable_directions() -> None:
    rendered = render_endpoint_direction_values(_results())
    assert r"\newcommand{\EndpointNativeStableCountContribution}{$+9.0$ pp}" in rendered
    assert r"\newcommand{\EndpointOtherValueShare}{60.0\%}" in rendered
    assert r"\newcommand{\EndpointCountChangeNumber}{25.0}" in rendered


def test_endpoint_direction_values_require_full_calendar() -> None:
    results = _results()
    results.loc[0, "common_calendar_days"] = 180
    with pytest.raises(ValueError, match="181 common days"):
        render_endpoint_direction_values(results)
