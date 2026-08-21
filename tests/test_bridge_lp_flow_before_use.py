from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_bridge_lp_flow_before_use import (
    EVENT_DAYS,
    aggregate_event_days,
    bridge_adoption_events,
    build_event_pool_days,
    estimate_lp_flow_timing,
    load_exact_support_pools,
    load_relevant_v2_family_flows,
    select_first_used_supported_stablecoin,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"


def _address(number: int) -> str:
    return f"0x{number:040x}"


def _bridge_panel(*, first_use: str = "2026-01-29") -> pd.DataFrame:
    src = _address(1)
    tgt = _address(2)
    rows = []
    for day in pd.date_range("2026-01-14", periods=3):
        rows.append(
            {
                "event_id": "event-1",
                "ordered_pair": f"{src}|{tgt}",
                "event_date": pd.Timestamp("2026-01-15"),
                "first_stable_route_date": pd.Timestamp(first_use),
                "src": src,
                "tgt": tgt,
                "integration_scope": "all_integrations",
                "event_stablecoin_addresses": f"{DAI},{USDC}",
                "origin_date": day,
            }
        )
    return pd.DataFrame(rows)


def _selected_event(*, first_use: str = "2026-01-29") -> pd.DataFrame:
    events = bridge_adoption_events(_bridge_panel(first_use=first_use))
    choices = pd.DataFrame(
        [
            {
                "event_id": "event-1",
                "date": first_use,
                "src": _address(1),
                "tgt": _address(2),
                "integration_scope": "all_integrations",
                "candidate_address": DAI,
                "candidate_symbol": "DAI",
                "route_count": 2,
            },
            {
                "event_id": "event-1",
                "date": first_use,
                "src": _address(1),
                "tgt": _address(2),
                "integration_scope": "all_integrations",
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
                "route_count": 7,
            },
            {
                "event_id": "event-1",
                "date": first_use,
                "src": _address(1),
                "tgt": _address(2),
                "integration_scope": "all_integrations",
                "candidate_address": _address(999),
                "candidate_symbol": "OTHER",
                "route_count": 100,
            },
        ]
    )
    return select_first_used_supported_stablecoin(events, choices)


def _flow_row(
    *,
    day: str,
    pool: str,
    token0: str,
    token1: str,
    add: float = 0.0,
    remove: float = 0.0,
    current_capital: float = 10_000.0,
    lagged_capital: float = 10_000.0,
    raw_add: int | None = None,
    valued_add: int | None = None,
    venue: str = "uniswap_v2",
) -> dict[str, object]:
    raw_add = int(add > 0) if raw_add is None else raw_add
    valued_add = raw_add if valued_add is None else valued_add
    raw_remove = int(remove > 0)
    return {
        "venue": venue,
        "origin_date": pd.Timestamp(day),
        "pool": pool,
        "token0_address": token0,
        "token1_address": token1,
        "v2_add_lp_flow_usd": add,
        "v2_remove_lp_flow_usd": remove,
        "v2_gross_lp_flow_usd": add + remove,
        "v2_net_add_lp_flow_usd": add - remove,
        "v2_add_liquidity": add / 100,
        "v2_remove_liquidity": remove / 100,
        "v2_raw_add_events": raw_add,
        "v2_raw_remove_events": raw_remove,
        "v2_add_events_valued": valued_add,
        "v2_remove_events_valued": raw_remove,
        "v2_lagged_capital_usd": lagged_capital,
        "v2_capital_usd": current_capital,
        "v2_exact_lag_valid": lagged_capital > 0,
        "v2_capital_valid": current_capital > 0,
    }


def _two_leg_flows(*, target_seed_day: str = "2026-01-25") -> pd.DataFrame:
    src = _address(1)
    tgt = _address(2)
    source_pool = _address(101)
    target_pool = _address(102)
    unrelated_pool = _address(103)
    return pd.DataFrame(
        [
            _flow_row(
                day="2026-01-01",
                pool=source_pool,
                token0=src,
                token1=USDC,
                add=500,
                lagged_capital=0,
            ),
            _flow_row(
                day="2026-01-20",
                pool=source_pool,
                token0=src,
                token1=USDC,
                add=100,
                remove=20,
            ),
            _flow_row(
                day=target_seed_day,
                pool=target_pool,
                token0=USDC,
                token1=tgt,
                add=200,
                lagged_capital=0,
            ),
            _flow_row(
                day="2026-01-29",
                pool=source_pool,
                token0=src,
                token1=USDC,
                add=300,
            ),
            _flow_row(
                day="2026-01-20",
                pool=unrelated_pool,
                token0=USDC,
                token1=_address(3),
                add=999,
            ),
        ]
    )


def _support_pools(*, target_prior: bool = True) -> pd.DataFrame:
    src = _address(1)
    tgt = _address(2)
    rows = [
        {
            "event_id": "event-1",
            "leg": "source",
            "token_a": min(src, USDC),
            "token_b": max(src, USDC),
            "venue": "uniswap_v2",
            "pool": _address(101),
            "prior_capital_usd": 10_000.0,
            "same_day_capital_usd": 10_000.0,
        },
        {
            "event_id": "event-1",
            "leg": "target",
            "token_a": min(tgt, USDC),
            "token_b": max(tgt, USDC),
            "venue": "uniswap_v2",
            "pool": _address(102),
            "prior_capital_usd": 10_000.0 if target_prior else 0.0,
            "same_day_capital_usd": 10_000.0,
        },
    ]
    return pd.DataFrame(rows)


def test_supported_candidate_is_fixed_on_exact_first_use_date() -> None:
    selected = _selected_event()
    assert len(selected) == 1
    assert selected.iloc[0]["candidate_address"] == USDC
    assert selected.iloc[0]["candidate_symbol"] == "USDC"
    assert selected.iloc[0]["route_count"] == 7
    assert selected.iloc[0]["adoption_lag_days"] == 14


def test_exact_two_legs_split_seeding_from_existing_pool_additions() -> None:
    pool_days, coverage = build_event_pool_days(
        _selected_event(), _two_leg_flows(), _support_pools()
    )
    event_days = aggregate_event_days(pool_days)
    assert set(pool_days["pool"]) == {_address(101), _address(102)}
    assert coverage.iloc[0]["covered_legs_by_first_use"] == 2
    assert coverage.iloc[0]["covered_legs_strictly_before_first_use"] == 2
    existing = event_days[event_days["relative_day"].eq(-9)].iloc[0]
    assert existing["strict_add_flow_usd"] == pytest.approx(100)
    assert existing["strict_existing_add_flow_usd"] == pytest.approx(100)
    assert existing["strict_seed_add_flow_usd"] == pytest.approx(0)
    assert existing["strict_remove_flow_usd"] == pytest.approx(20)
    seed = event_days[event_days["relative_day"].eq(-4)].iloc[0]
    assert seed["strict_add_flow_usd"] == pytest.approx(200)
    assert seed["strict_seed_add_flow_usd"] == pytest.approx(200)
    assert seed["strict_existing_add_flow_usd"] == pytest.approx(0)
    use_day = event_days[event_days["relative_day"].eq(0)].iloc[0]
    assert use_day["strict_existing_add_flow_usd"] == pytest.approx(300)


def test_same_day_seed_is_not_strictly_prior_support() -> None:
    pool_days, coverage = build_event_pool_days(
        _selected_event(),
        _two_leg_flows(target_seed_day="2026-01-29"),
        _support_pools(target_prior=False),
    )
    assert bool(coverage.iloc[0]["both_legs_by_first_use"])
    assert not bool(coverage.iloc[0]["both_legs_strictly_before_first_use"])
    target = pool_days[
        pool_days["pool"].eq(_address(102)) & pool_days["relative_day"].eq(0)
    ].iloc[0]
    assert bool(target["seed_day"])
    assert target["seed_add_flow_usd"] == pytest.approx(200)
    assert not pool_days.loc[
        pool_days["pool"].eq(_address(102)) & pool_days["relative_day"].lt(0),
        "v2_add_lp_flow_usd",
    ].any()


def test_pool_capital_loader_recovers_exact_support_pool_ids(tmp_path) -> None:
    events = _selected_event()
    capital = pd.DataFrame(
        [
            {
                "day": 20260129,
                "venue": "uniswap_v2",
                "pool": _address(101),
                "token0_address": _address(1),
                "token1_address": USDC,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
                "exact_lag_valid": True,
                "capital_usd_lagged": 10_000.0,
                "capital_valid": True,
                "capital_usd": 12_000.0,
            },
            {
                "day": 20260129,
                "venue": "sushiswap_v2",
                "pool": _address(202),
                "token0_address": USDC,
                "token1_address": _address(2),
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
                "exact_lag_valid": True,
                "capital_usd_lagged": 20_000.0,
                "capital_valid": True,
                "capital_usd": 21_000.0,
            },
            {
                "day": 20260129,
                "venue": "uniswap_v3",
                "pool": _address(303),
                "token0_address": _address(1),
                "token1_address": USDC,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
                "exact_lag_valid": True,
                "capital_usd_lagged": 999_000.0,
                "capital_valid": True,
                "capital_usd": 999_000.0,
            },
            {
                "day": 20260129,
                "venue": "uniswap_v2",
                "pool": _address(404),
                "token0_address": _address(1),
                "token1_address": USDC,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_current",
                "exact_lag_valid": False,
                "capital_usd_lagged": None,
                "capital_valid": True,
                "capital_usd": 5_000.0,
            },
        ]
    )
    capital_path = tmp_path / "capital.parquet"
    capital.to_parquet(capital_path, index=False)
    pools = load_exact_support_pools(events, capital_path)
    assert set(zip(pools["venue"], pools["pool"], strict=True)) == {
        ("uniswap_v2", _address(101)),
        ("uniswap_v2", _address(404)),
        ("sushiswap_v2", _address(202)),
    }

    uniswap = pd.DataFrame(
        [
            _flow_row(
                day="2026-01-01",
                pool=_address(101),
                token0=_address(1),
                token1=USDC,
            )
        ]
    )
    sushi = pd.DataFrame(
        [
            _flow_row(
                day="2026-01-02",
                pool=_address(202),
                token0=USDC,
                token1=_address(2),
                venue="sushiswap_v2",
            )
        ]
    )
    uniswap_path = tmp_path / "uniswap.parquet"
    sushi_path = tmp_path / "sushi.parquet"
    uniswap.to_parquet(uniswap_path, index=False)
    sushi.to_parquet(sushi_path, index=False)
    flow = load_relevant_v2_family_flows(pools, uniswap_path, sushi_path)
    assert set(zip(flow["venue"], flow["pool"], strict=True)) == {
        ("uniswap_v2", _address(101)),
        ("sushiswap_v2", _address(202)),
    }


def test_incomplete_event_valuation_is_not_treated_as_zero_dollars() -> None:
    flows = _two_leg_flows()
    target = flows["pool"].eq(_address(101)) & flows["origin_date"].eq(
        pd.Timestamp("2026-01-20")
    )
    flows.loc[target, "v2_add_events_valued"] = 0
    pool_days, _coverage = build_event_pool_days(
        _selected_event(), flows, _support_pools()
    )
    event_days = aggregate_event_days(pool_days)
    row = event_days[event_days["relative_day"].eq(-9)].iloc[0]
    assert row["add_flow_usd"] == pytest.approx(100)
    assert np.isnan(row["strict_add_flow_usd"])
    assert np.isnan(row["strict_net_add_flow_usd"])


def test_pre_use_acceleration_excludes_first_use_day() -> None:
    rows: list[dict[str, object]] = []
    for event_index in range(4):
        first_use = pd.Timestamp("2026-02-01") + pd.Timedelta(days=event_index)
        for relative_day in EVENT_DAYS:
            add = 1_000_000_000.0 if relative_day == 0 else 1.0
            rows.append(
                {
                    "event_id": f"event-{event_index}",
                    "ordered_pair": f"pair-{event_index}",
                    "first_stable_route_date": first_use,
                    "candidate_symbol": "USDC",
                    "candidate_address": USDC,
                    "relative_day": relative_day,
                    "origin_date": first_use + pd.Timedelta(days=relative_day),
                    "both_legs_strictly_before_first_use": True,
                    "strict_add_flow_usd": add,
                    "strict_seed_add_flow_usd": 0.0,
                    "strict_existing_add_flow_usd": add,
                    "strict_remove_flow_usd": 0.0,
                    "strict_net_add_flow_usd": add,
                    "usd_flow_complete": True,
                }
            )
    results, support = estimate_lp_flow_timing(pd.DataFrame(rows))
    acceleration = results[
        results["record_type"].eq("pre_use_acceleration")
        & results["outcome"].eq("add_flow_usd")
        & results["sample"].eq("both_v2_family_legs_by_first_use")
    ].iloc[0]
    assert bool(acceleration["first_use_day_excluded"])
    assert acceleration["estimate"] == pytest.approx(0.0, abs=1e-12)
    use_day = results[
        results["record_type"].eq("event_path_level")
        & results["outcome"].eq("add_flow_usd")
        & results["event_bin"].eq("first_use_day")
        & results["sample"].eq("both_v2_family_legs_by_first_use")
    ].iloc[0]
    assert use_day["estimate"] == pytest.approx(1_000_000_000.0)
    assert support.iloc[0]["events"] == 4
