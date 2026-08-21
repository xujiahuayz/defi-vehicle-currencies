from __future__ import annotations

import math

import pandas as pd
import pytest

from ddvc.pricing.path_frontier import LegQuote
from scripts.analyze.run_fixed_notional_vehicle_reach import (
    NOTIONALS_USD,
    STABLE_VEHICLES,
    VEHICLES,
    snapshot_frontier,
    summarize_reach,
    validate_snapshot_support,
    v2_leg_quotes,
    v2_pool_index,
)


ENDPOINT = "0x1111111111111111111111111111111111111111"
WETH = VEHICLES[0]
USDC = STABLE_VEHICLES[0]


def _capital_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "venue": "uniswap_v2",
                "day": "20260115",
                "pool": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "token0_address": WETH,
                "token1_address": ENDPOINT,
                "reserve0": 1_000_000.0,
                "reserve1": 1_000_000.0,
                "reserve_validation_status": "validated_last_hourly_reserve_snapshot",
                "identity_validation_status": "exact_identity_and_decimals_passed",
                "capital_valid": True,
            },
            {
                "venue": "sushiswap_v2",
                "day": "20260115",
                "pool": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "token0_address": USDC,
                "token1_address": ENDPOINT,
                "reserve0": 3_000_000.0,
                "reserve1": 3_000_000.0,
                "reserve_validation_status": "validated_last_hourly_reserve_snapshot",
                "identity_validation_status": "exact_identity_and_decimals_passed",
                "capital_valid": True,
            },
        ]
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"day": "20260115", "token": token, "price_usd": 1.0}
            for token in (*VEHICLES, ENDPOINT)
        ]
    )


def test_v2_fixed_notional_quote_obeys_the_frontier_support_bound() -> None:
    pools = v2_pool_index(_capital_rows())
    small = v2_leg_quotes(WETH, ENDPOINT, 10_000.0, pools=pools)
    large = v2_leg_quotes(WETH, ENDPOINT, 100_000.0, pools=pools)

    assert len(small) == 1
    assert small[0].amount_out > 0
    assert large == []


def test_v2_reach_accepts_the_released_certified_reserve_status() -> None:
    released = _capital_rows().copy()
    released["reserve_validation_status"] = (
        "certified_last_hourly_reserve_snapshot"
    )

    assert sum(map(len, v2_pool_index(released).values())) == 2


def test_snapshot_keeps_fixed_notional_zeros_and_selects_best_exact_quote() -> None:
    def tick_quotes(token_in: str, token_out: str, amount_in: float):
        if token_in == WETH and token_out == ENDPOINT and amount_in == 10_000.0:
            return [LegQuote(9_990.0, "uniswap_v3", "v3-pool", 0.001)]
        return []

    tick_index = {
        frozenset((WETH, ENDPOINT)): [("uniswap_v3", "v3-pool")],
    }
    panel, support = snapshot_frontier(
        "20260115",
        _capital_rows(),
        _prices(),
        tick_pool_index=tick_index,
        tick_quote_legs=tick_quotes,
        notionals_usd=NOTIONALS_USD,
    )
    indexed = panel.set_index(
        ["candidate_address", "endpoint_address", "notional_usd"]
    )
    small = indexed.loc[(WETH, ENDPOINT, 10_000.0)]
    large = indexed.loc[(WETH, ENDPOINT, 100_000.0)]

    assert bool(small["executable"])
    assert small["best_venue"] == "uniswap_v3"
    assert small["best_output_usd"] == 9_990.0
    assert math.isclose(small["all_in_cost_bps"], 10.0)
    assert not bool(large["executable"])
    assert pd.isna(large["all_in_cost_bps"])
    assert support["priced_candidate_linked_endpoints"] == 3


def test_summary_separates_noncandidate_spokes_from_vehicle_core() -> None:
    panel, _ = snapshot_frontier(
        "20260115",
        _capital_rows(),
        _prices(),
        notionals_usd=(10_000.0,),
    )
    summary = summarize_reach(panel)
    weth_spokes = summary[
        summary["candidate_address"].eq(WETH)
        & summary["scope"].eq("noncandidate_spokes")
    ].iloc[0]
    weth_core = summary[
        summary["candidate_address"].eq(WETH)
        & summary["scope"].eq("candidate_core")
    ].iloc[0]

    assert weth_spokes["priced_endpoints"] == 1
    assert weth_spokes["executable_endpoints"] == 1
    assert weth_core["priced_endpoints"] == 1
    assert weth_core["executable_endpoints"] == 0


def test_unsupported_early_snapshot_is_recorded_then_later_support_is_required() -> None:
    empty, early_support = snapshot_frontier(
        "20200615",
        _capital_rows().iloc[0:0],
        _prices().assign(day="20200615"),
        notionals_usd=(10_000.0,),
    )
    assert empty.empty
    assert early_support["snapshot_status"] == "unsupported"
    assert early_support["unsupported_reason"] == "no_priced_candidate_linked_endpoints"

    support = pd.DataFrame(
        [
            early_support,
            {
                **early_support,
                "day": "20200715",
                "snapshot_status": "supported",
                "unsupported_reason": None,
                "frontier_rows": 4,
            },
        ]
    )
    validate_snapshot_support(["20200615", "20200715"], support)

    broken = pd.concat(
        [
            support,
            pd.DataFrame(
                [
                    {
                        **early_support,
                        "day": "20200815",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="unsupported post-support target"):
        validate_snapshot_support(
            ["20200615", "20200715", "20200815"], broken
        )


def test_snapshot_calendar_fails_when_every_target_is_unsupported() -> None:
    support = pd.DataFrame(
        [
            {
                "day": "20200615",
                "snapshot_status": "unsupported",
            }
        ]
    )
    with pytest.raises(ValueError, match="no supported snapshot"):
        validate_snapshot_support(["20200615"], support)
