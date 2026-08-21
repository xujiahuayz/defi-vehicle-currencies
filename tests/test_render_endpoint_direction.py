from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_endpoint_direction import render_table


def test_endpoint_direction_table_reconciles_channels_and_issuer_split() -> None:
    endpoint_rows: list[dict[str, object]] = []
    channel_values = {
        "native_to_native": 0.0,
        "native_to_stable": 0.04,
        "stable_to_native": 0.05,
        "stable_to_stable": 0.01,
        "other_endpoints": 0.15,
    }
    for metric in ("count_share", "strict_intermediation_value_share"):
        for group, value in channel_values.items():
            endpoint_rows.append(
                {
                    "metric": metric,
                    "endpoint_group": group,
                    "common_calendar_days": 181,
                    "stable_share_contribution_change": value,
                    "overall_stable_share_change": 0.25,
                }
            )

    stable_rows: list[dict[str, object]] = []
    issuer_values = {
        "native": 0.02,
        "usdt": 0.06,
        "usdc": -0.01,
        "dai": 0.00,
        "other_stable": 0.00,
    }
    for metric in ("count_share", "strict_intermediation_value_share"):
        for group, value in issuer_values.items():
            stable_rows.append(
                {
                    "metric": metric,
                    "intermediary_group": group,
                    "common_calendar_days": 181,
                    "stable_share_contribution_change": value,
                }
            )

    robustness = pd.DataFrame(
        [
            {
                "metric": "strict_intermediation_value_share",
                "year": 2024,
                "common_calendar_days": 181,
                "top_decile_trimmed_mean_stable_contribution": 0.03,
                "pooled_mass_stable_contribution": 0.04,
            },
            {
                "metric": "strict_intermediation_value_share",
                "year": 2026,
                "common_calendar_days": 181,
                "top_decile_trimmed_mean_stable_contribution": 0.12,
                "pooled_mass_stable_contribution": 0.14,
            },
        ]
    )
    rendered = render_table(
        pd.DataFrame(endpoint_rows), pd.DataFrame(stable_rows), robustness
    )
    assert "One native, one stable endpoint & +9.0 & +9.0" in rendered
    assert "USDT & +6.0 & +6.0" in rendered
    assert "USDC, DAI, and other stablecoins & -1.0 & -1.0" in rendered
    assert "Top-decile-trimmed daily mean & -- & +9.0" in rendered
