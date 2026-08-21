from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_uni_liquidity_mining_expiry import (
    EVENTS,
    REWARDED_POOL_COMPANIONS,
    REWARDED_POOL_ADDRESSES,
    WETH,
    IncentiveEvent,
    analyse_pool_events,
    event_pool_summary,
    match_pool_group,
    matched_change,
    matched_event_path,
    matched_label_reference,
    prepare_pool_panel,
)


def _address(number: int) -> str:
    return f"0x{number:040x}"


def _pool_rows(event_date: pd.Timestamp, window_days: int = 5) -> pd.DataFrame:
    pools = list(REWARDED_POOL_ADDRESSES) + [_address(10_000 + i) for i in range(10)]
    rows: list[dict[str, object]] = []
    for pool_index, pool in enumerate(pools):
        treated = pool in REWARDED_POOL_ADDRESSES
        base_log_k = 10.0 + 0.03 * pool_index
        base_log_capital = 14.0 + 0.02 * pool_index
        for relative_day in range(-window_days, window_days):
            post_effect = -0.30 if treated and relative_day >= 0 else 0.0
            log_k = base_log_k + 0.001 * relative_day + post_effect
            log_capital = base_log_capital + 0.001 * relative_day + post_effect
            day = event_date + pd.Timedelta(days=relative_day)
            rows.append(
                {
                    "venue": "uniswap_v2",
                    "day": day.strftime("%Y%m%d"),
                    "pool": pool,
                    "token0_address": WETH,
                    "token0_symbol": "WETH",
                    "token1_address": REWARDED_POOL_COMPANIONS.get(
                        pool, _address(20_000 + pool_index)
                    ),
                    "token1_symbol": f"T{pool_index}",
                    "reserve0": float(np.exp(log_k)),
                    "reserve1": float(np.exp(log_k)),
                    "capital_usd": float(np.exp(log_capital)),
                    "capital_valid": True,
                    "quantity_kind": "deposited_capital",
                    "pool_family": "full_range_constant_product",
                }
            )
    return pd.DataFrame(rows)


def test_official_reward_schedule_and_pool_set_are_fixed() -> None:
    assert [(event.event, event.timestamp_utc) for event in EVENTS] == [
        ("reward_start", "2020-09-18T00:00:00Z"),
        ("reward_expiry", "2020-11-17T00:00:00Z"),
    ]
    assert len(REWARDED_POOL_ADDRESSES) == 4
    assert len(set(REWARDED_POOL_ADDRESSES)) == 4
    assert "0xbb2b8038a1640196fbe3e38816f3e67cba72d940" in REWARDED_POOL_ADDRESSES


def test_matched_pool_first_stage_recovers_quantity_withdrawal() -> None:
    event = IncentiveEvent(
        "synthetic_expiry",
        pd.Timestamp("2020-11-17"),
        "2020-11-17T00:00:00Z",
        -1,
        "synthetic test event",
    )
    panel = prepare_pool_panel(_pool_rows(event.date))
    summary = event_pool_summary(
        panel,
        event,
        window_days=5,
        minimum_support_share=1.0,
        minimum_pre_capital_usd=100.0,
    )
    assert int(summary["eligible"].sum()) == 14
    matches = match_pool_group(
        summary,
        REWARDED_POOL_ADDRESSES,
        matches_per_treated=2,
    )
    assert len(matches) == 8
    estimate = matched_change(summary, matches, outcome="log_sqrt_k")
    assert estimate["treated_pools"] == 4
    assert estimate["matched_difference"] == pytest.approx(-0.30, abs=1e-10)
    path = matched_event_path(
        panel,
        event,
        matches,
        outcome="log_sqrt_k",
        window_days=5,
    )
    assert path.loc[path["relative_day"].lt(0), "matched_difference"].abs().max() < 1e-10
    assert path.loc[path["relative_day"].ge(0), "matched_difference"].mean() == pytest.approx(
        -0.30,
        abs=1e-10,
    )
    both_events = prepare_pool_panel(pd.concat([_pool_rows(item.date) for item in EVENTS]))
    results, support_rows = analyse_pool_events(
        both_events, window_days=5, minimum_support_share=1.0,
        minimum_pre_capital_usd=100.0, matches_per_treated=2,
        placebo_shift_days=-15, maximum_assignments=99, seed=17,
    )
    specific = results[results["record_type"].eq("wbtc_weth_pool_first_stage")]
    assert len(specific[specific["event"].eq("reward_expiry")]) == 1
    expiry_gate = support_rows[
        support_rows["record_type"].eq("pool_stop_go")
        & support_rows["event"].eq("reward_expiry")
    ].iloc[0]
    assert "wbtc_weth_signed_relevance_pass" in expiry_gate


def test_matched_label_reference_is_seed_reproducible() -> None:
    event = IncentiveEvent(
        "synthetic_expiry",
        pd.Timestamp("2020-11-17"),
        "2020-11-17T00:00:00Z",
        -1,
        "synthetic test event",
    )
    panel = prepare_pool_panel(_pool_rows(event.date))
    summary = event_pool_summary(
        panel,
        event,
        window_days=5,
        minimum_support_share=1.0,
        minimum_pre_capital_usd=100.0,
    )
    first = matched_label_reference(
        summary,
        REWARDED_POOL_ADDRESSES,
        outcome="log_sqrt_k",
        matches_per_treated=2,
        maximum_assignments=200,
        seed=117,
    )
    second = matched_label_reference(
        summary,
        REWARDED_POOL_ADDRESSES,
        outcome="log_sqrt_k",
        matches_per_treated=2,
        maximum_assignments=200,
        seed=117,
    )
    assert first == second
    assert first["reference_assignments"] == 200
    assert 0 < first["permutation_p_two_sided"] <= 1
    assert first["inference_scope"].startswith("matched-label diagnostic")
