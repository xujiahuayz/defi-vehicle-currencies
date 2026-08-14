from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_v4_route_composition_probe import (
    estimate_composition,
    matched_pair_weeks,
    support_record,
)


def _aggregate() -> pd.DataFrame:
    rows = []
    weeks = pd.date_range("2025-01-06", periods=12, freq="7D")
    for pair_index in range(12):
        src, sink = f"S{pair_index}", f"T{pair_index}"
        for week_index, week in enumerate(weeks):
            for dex, stable, native in (
                ("uniswap_v3", 4, 6),
                ("uniswap_v4", 7, 3),
            ):
                scale = pair_index + week_index + 1
                rows.append(
                    {
                        "week": week,
                        "src": src,
                        "sink": sink,
                        "dex": dex,
                        "routes": 10,
                        "route_usd": 100.0 * scale,
                        "stable_routes": stable,
                        "stable_route_usd": stable * 10.0 * scale,
                        "native_routes": native,
                        "native_route_usd": native * 10.0 * scale,
                    }
                )
    return pd.DataFrame(rows)


def test_matched_pair_weeks_builds_declared_shares() -> None:
    matched = matched_pair_weeks(_aggregate(), min_routes=5)
    assert len(matched) == 144
    assert np.allclose(matched["stable_count_share_uniswap_v3"], 0.4)
    assert np.allclose(matched["stable_count_share_uniswap_v4"], 0.7)
    assert np.allclose(matched["native_value_share_uniswap_v3"], 0.6)
    assert np.allclose(matched["native_value_share_uniswap_v4"], 0.3)


def test_estimator_uses_paired_difference_and_two_way_clusters() -> None:
    matched = matched_pair_weeks(_aggregate(), min_routes=5)
    # Add non-degenerate pair/week variation while preserving a positive mean.
    variation = (
        matched["src"].str.extract(r"(\d+)")[0].astype(int).to_numpy() % 3 - 1
    ) * 0.01
    matched["stable_count_share_uniswap_v4"] += variation
    results = estimate_composition(matched)
    stable = results.set_index("outcome").loc["stable_count_share"]
    assert np.isclose(stable["v4_minus_v3"], 0.3)
    assert stable["ordered_pair_clusters"] == 12
    assert stable["calendar_week_clusters"] == 12
    assert stable["covariance"] == "two_way_ordered_pair_calendar_week_cr1"
    assert np.isfinite(stable["standard_error"])


def test_support_names_scope_and_omitted_dimensions() -> None:
    matched = matched_pair_weeks(_aggregate(), min_routes=5)
    support = support_record(matched, min_routes=5).iloc[0]
    assert support["comparison"] == "same_ordered_source_destination_and_calendar_week"
    assert support["stable_vehicles"] == "USDC|USDT|DAI"
    assert "selection_into_v4" in support["omitted_dimensions"]
