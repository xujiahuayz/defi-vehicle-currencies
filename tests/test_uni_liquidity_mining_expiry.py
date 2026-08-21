from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_uni_liquidity_mining_expiry import (
    ALL_STABLES,
    CORE_STABLES,
    EVENTS,
    REWARDED_POOL_ADDRESSES,
    WBTC,
    WETH,
    IncentiveEvent,
    event_pool_summary,
    match_pool_group,
    matched_change,
    matched_event_path,
    matched_label_reference,
    prepare_pool_panel,
    prepare_wbtc_routes,
    wbtc_pair_support,
    wbtc_route_response,
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
                    "token1_address": _address(20_000 + pool_index),
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


def _route_rows(event_date: pd.Timestamp, pairs: int = 4) -> pd.DataFrame:
    stable = sorted(CORE_STABLES)[0]
    noncore_stable = sorted(ALL_STABLES - CORE_STABLES)[0]
    rows: list[dict[str, object]] = []
    for pair_index in range(pairs):
        other = _address(30_000 + pair_index)
        wbtc_first = pair_index % 2 == 0
        src, tgt = (WBTC, other) if wbtc_first else (other, WBTC)
        for relative_day in range(-5, 5):
            date = event_date + pd.Timedelta(days=relative_day)
            native_routes = 8 if relative_day < 0 else 4
            stable_routes = 2 if relative_day < 0 else 6
            rows.extend(
                [
                    {
                        "date": date,
                        "src": src,
                        "tgt": tgt,
                        "candidate_address": WETH,
                        "candidate_type": "native",
                        "candidate_symbol": "WETH",
                        "integration_scope": "single_venue",
                        "hop1_venue": "uniswap_v2",
                        "hop2_venue": "uniswap_v2",
                        "route_count": native_routes,
                    },
                    {
                        "date": date,
                        "src": src,
                        "tgt": tgt,
                        "candidate_address": stable,
                        "candidate_type": "stable",
                        "candidate_symbol": "stable",
                        "integration_scope": "single_venue",
                        "hop1_venue": "uniswap_v2",
                        "hop2_venue": "uniswap_v2",
                        "route_count": stable_routes,
                    },
                ]
            )
    rows.append(
        {
            "date": event_date,
            "src": WBTC,
            "tgt": stable,
            "candidate_address": WETH,
            "candidate_type": "native",
            "candidate_symbol": "WETH",
            "integration_scope": "single_venue",
            "hop1_venue": "uniswap_v2",
            "hop2_venue": "uniswap_v2",
            "route_count": 1,
        }
    )
    rows.append(
        {
            "date": event_date,
            "src": WBTC,
            "tgt": noncore_stable,
            "candidate_address": WETH,
            "candidate_type": "native",
            "candidate_symbol": "WETH",
            "integration_scope": "single_venue",
            "hop1_venue": "uniswap_v2",
            "hop2_venue": "uniswap_v2",
            "route_count": 1,
        }
    )
    return pd.DataFrame(rows)


def test_wbtc_route_response_is_preselected_and_narrow() -> None:
    event_date = pd.Timestamp("2020-11-17")
    routes = prepare_wbtc_routes(_route_rows(event_date))
    assert not routes["other_endpoint"].isin(ALL_STABLES | {WETH, WBTC}).any()
    support = wbtc_pair_support(
        routes,
        event_date,
        window_days=5,
        minimum_pre_routes=5,
        minimum_pre_exposure=0.80,
    )
    assert int(support["selected"].sum()) == 4
    assert support.loc[support["selected"], "pre_treated_leg_exposure"].eq(1.0).all()
    response, diagnostics = wbtc_route_response(
        support,
        sign_flip_draws=1_000,
        seed=17,
    )
    aggregate = response[
        response["estimate"].eq("route_weighted_stable_share_change")
    ].iloc[0]
    assert aggregate["pre_value"] == pytest.approx(0.20)
    assert aggregate["post_value"] == pytest.approx(0.60)
    assert aggregate["value"] == pytest.approx(0.40)
    assert diagnostics["selected_pairs"] == 4
    assert diagnostics["post_active_pairs"] == 4
