from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_contestable_vehicle_choice import USDC, WETH
from scripts.analyze.run_first_contestable_vehicle_choice import (
    first_contestable_routes,
    support_results,
)


def _frontier_row(
    day: str,
    route_id: str,
    token_in: str,
    token_out: str,
    *,
    chosen_stable: bool,
    gap_bps: float,
) -> dict[str, object]:
    return {
        "day": day,
        "route_id": route_id,
        "token_in": token_in,
        "token_out": token_out,
        "chosen_vehicle": USDC if chosen_stable else WETH,
        "chosen_vehicle_type": "stable" if chosen_stable else "native",
        "input_usd": 1_000.0,
        "output_usd": 1_000.0,
        "within_20pct": True,
        "chosen_max_price_impact": 0.01,
        "vehicle_families_contestable": True,
        "stable_minus_native_bps": gap_bps,
        "native_public_out": 100.0,
        "native_public_vehicle": WETH,
        "native_public_venues": "uniswap_v2|uniswap_v3",
        "stable_public_out": 100.0 * (1 + gap_bps / 10_000.0),
        "stable_public_vehicle": USDC,
        "stable_public_venues": "uniswap_v3|uniswap_v2",
    }


def _entry(
    token_in: str,
    token_out: str,
    *,
    entry_stable: float,
) -> dict[str, object]:
    return {
        "day": "20240101",
        "entry_date": pd.Timestamp("2024-01-01"),
        "token_in": token_in,
        "token_out": token_out,
        "ordered_pair": f"{token_in}>{token_out}",
        "entry_primary_routes": 10.0,
        "entry_native_routes": 10.0 if entry_stable == 0 else 0.0,
        "entry_stable_routes": 10.0 if entry_stable == 1 else 0.0,
        "entry_stable_share": entry_stable,
        "entry_stable": entry_stable,
        "entry_tie": False,
        "entry_exclusive": True,
        "entry_mixed": False,
        "entry_coherent_routes": 10.0,
        "entry_coherent_value_usd": 100_000.0,
    }


def test_first_contestable_routes_keep_all_routes_on_first_supported_date(
    tmp_path,
) -> None:
    frontier = pd.DataFrame(
        [
            _frontier_row(
                "20240215", "first-native", "src-a", "tgt-a", chosen_stable=False, gap_bps=-5.0
            ),
            _frontier_row(
                "20240215", "first-stable", "src-a", "tgt-a", chosen_stable=True, gap_bps=5.0
            ),
            _frontier_row(
                "20240315", "later", "src-a", "tgt-a", chosen_stable=True, gap_bps=10.0
            ),
            _frontier_row(
                "20231215", "before-entry", "src-b", "tgt-b", chosen_stable=False, gap_bps=-2.0
            ),
        ]
    )
    path = tmp_path / "frontier.parquet"
    frontier.to_parquet(path, index=False)
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
        ]
    )

    result = first_contestable_routes(path, entries)

    assert set(result["route_id"]) == {"first-native", "first-stable"}
    assert result["day"].eq("20240215").all()
    assert result["entry_to_contestability_days"].eq(45).all()
    retained = result.set_index("route_id")["entry_vehicle_retained"]
    assert retained["first-native"] == 1.0
    assert retained["first-stable"] == 0.0
    assert result["route_scope"].eq(
        "uniswap_v2|uniswap_v3||uniswap_v3|uniswap_v2"
    ).all()


def test_support_distinguishes_entry_from_first_contestability() -> None:
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
            _entry("src-c", "tgt-c", entry_stable=0.0),
        ]
    )
    panel = pd.DataFrame(
        [
            {
                "ordered_pair": "src-a>tgt-a",
                "route_id": "a1",
                "day": "20240215",
                "chosen_stable": 0.0,
                "entry_stable": 0.0,
                "entry_vehicle_retained": 1.0,
                "entry_to_contestability_days": 45,
                "both_v2_bridge_capitals_positive": True,
            },
            {
                "ordered_pair": "src-a>tgt-a",
                "route_id": "a2",
                "day": "20240215",
                "chosen_stable": 0.0,
                "entry_stable": 0.0,
                "entry_vehicle_retained": 1.0,
                "entry_to_contestability_days": 45,
                "both_v2_bridge_capitals_positive": True,
            },
            {
                "ordered_pair": "src-b>tgt-b",
                "route_id": "b1",
                "day": "20240515",
                "chosen_stable": 0.0,
                "entry_stable": 1.0,
                "entry_vehicle_retained": 0.0,
                "entry_to_contestability_days": 135,
                "both_v2_bridge_capitals_positive": False,
            },
        ]
    )

    support = support_results(
        entries,
        panel,
        entry_value_threshold_usd=5_000.0,
        sampling_calendar="four_per_month",
    ).set_index("sample")

    cohort = support.loc["material_entry_cohort"]
    assert cohort["entry_pairs"] == 3
    assert cohort["pairs_reaching_sampled_contestability"] == 2
    assert cohort["contestability_coverage_share"] == pytest.approx(2 / 3)
    assert cohort["entry_value_threshold_usd"] == 5_000.0
    assert cohort["sampling_calendar"] == "four_per_month"
    survival = support.loc["entry_vehicle_survival"]
    assert survival["route_weighted_retention_share"] == pytest.approx(2 / 3)
    assert survival["equal_pair_retention_share"] == pytest.approx(0.5)
    lag = support.loc["entry_to_first_sampled_contestability_lag"]
    assert lag["median_days"] == pytest.approx(90.0)
    assert not bool(lag["monthly_sampling"])
