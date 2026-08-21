from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_v2_protocol_fee_switch import (
    ACTIVATION_BLOCK,
    ACTIVATION_TIMESTAMP_UTC,
    FIRST_POST_WEEK,
    OUTCOMES,
    PARTIAL_WEEK,
    estimate_fee_switch,
    prepare_pair_week_panel,
    select_balanced_pairs,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def _address(number: int) -> str:
    return f"0x{number:040x}"


def _synthetic_daily(pairs: int = 6) -> pd.DataFrame:
    weeks = list(pd.date_range("2025-09-29", periods=13, freq="7D")) + list(
        pd.date_range("2025-12-29", periods=12, freq="7D")
    )
    rows: list[dict[str, object]] = []
    for pair_index in range(pairs):
        token0 = USDC if pair_index < 3 else WETH
        token1 = _address(100 + pair_index)
        for venue_index, venue in enumerate(("uniswap_v2", "sushiswap_v2")):
            pool = _address(1_000 + 100 * venue_index + pair_index)
            for week in weeks:
                for day_offset in range(7):
                    partial = week == PARTIAL_WEEK
                    post = week >= FIRST_POST_WEEK
                    base_rate = 0.10 + 0.002 * pair_index
                    add_rate = base_rate
                    if venue == "uniswap_v2" and post:
                        add_rate -= 0.04
                    if partial and venue == "uniswap_v2":
                        add_rate = 9.0
                    remove_rate = 0.03
                    capital = 100_000.0 + 1_000 * pair_index
                    add = add_rate * capital / 7.0
                    remove = remove_rate * capital / 7.0
                    rows.append(
                        {
                            "venue": venue,
                            "origin_date": week + pd.Timedelta(days=day_offset),
                            "pool": pool,
                            "token0_address": token0,
                            "token1_address": token1,
                            "v2_add_lp_flow_usd": add,
                            "v2_remove_lp_flow_usd": remove,
                            "v2_gross_lp_flow_usd": add + remove,
                            "v2_net_add_lp_flow_usd": add - remove,
                            "v2_add_liquidity": add / 100,
                            "v2_remove_liquidity": remove / 100,
                            "v2_gross_liquidity": (add + remove) / 100,
                            "v2_net_add_liquidity": (add - remove) / 100,
                            "v2_raw_add_events": 1,
                            "v2_raw_remove_events": 1,
                            "v2_add_events_valued": 1,
                            "v2_remove_events_valued": 1,
                            "v2_missing_invalid_liquidity_events": 0,
                            "v2_needs_complete_events": 0,
                            "v2_volume_usd": 1_000_000.0,
                            "v2_lagged_capital_usd": capital,
                            "v2_lagged_sqrt_k": capital / 100,
                            "v2_capital_usd": capital,
                            "v2_exact_lag_valid": True,
                            "v2_capital_valid": True,
                        }
                    )
    return pd.DataFrame(rows)


def test_fee_switch_boundary_uses_first_complete_week() -> None:
    assert ACTIVATION_TIMESTAMP_UTC == "2025-12-27T20:33:11Z"
    assert ACTIVATION_BLOCK == 24_106_378
    panel = prepare_pair_week_panel(_synthetic_daily())
    assert PARTIAL_WEEK not in set(panel["origin_week"])
    assert set(panel["relative_week"]) == set(range(-12, 0)) | set(range(12))


def test_matched_pair_did_recovers_lower_uniswap_additions() -> None:
    panel = prepare_pair_week_panel(_synthetic_daily())
    selected = select_balanced_pairs(
        panel,
        outcome="asinh_add_flow_rate",
        min_pre_capital_usd=10_000,
    )
    assert len(selected) == 6
    results, support = estimate_fee_switch(panel, min_pre_capital_usd=10_000)
    main = results[
        results["record_type"].eq("difference_in_differences")
        & results["window"].eq("12_pre_12_post_weeks")
        & results["outcome"].eq("asinh_add_flow_rate")
        & results["sample"].eq("all_matched_pairs")
    ].iloc[0]
    base_rates = 0.10 + 0.002 * np.arange(6)
    expected = float(np.mean(np.arcsinh(base_rates - 0.04) - np.arcsinh(base_rates)))
    assert main["estimate"] == pytest.approx(expected, abs=1e-12)
    assert main["estimate"] < 0
    pretrend = results[
        results["record_type"].eq("pretrend")
        & results["outcome"].eq("asinh_add_flow_rate")
        & results["sample"].eq("all_matched_pairs")
    ].iloc[0]
    assert pretrend["estimate"] == pytest.approx(0.0, abs=1e-12)
    placebos = results[
        results["record_type"].eq("placebo_date")
        & results["outcome"].eq("asinh_add_flow_rate")
        & results["sample"].eq("all_matched_pairs")
    ]
    assert len(placebos) == 5
    assert placebos["estimate"].abs().max() < 1e-12
    assert support["assignment_unit"].eq(
        "one_uniswap_v2_venue_by_activation_time"
    ).all()


def test_incomplete_usd_valuation_drops_only_usd_flow_outcomes() -> None:
    daily = _synthetic_daily()
    target = (
        daily["venue"].eq("uniswap_v2")
        & daily["origin_date"].eq(pd.Timestamp("2026-01-05"))
    )
    daily.loc[target, "v2_add_events_valued"] = 0
    panel = prepare_pair_week_panel(daily)
    usd_pairs = select_balanced_pairs(
        panel,
        outcome="asinh_add_flow_rate",
        min_pre_capital_usd=0,
    )
    capital_pairs = select_balanced_pairs(
        panel,
        outcome="log_capital_usd",
        min_pre_capital_usd=0,
    )
    assert len(usd_pairs) == 0
    assert len(capital_pairs) == 6
    assert {outcome.name for outcome in OUTCOMES}.issuperset(
        {"asinh_add_flow_rate", "log_capital_usd"}
    )
