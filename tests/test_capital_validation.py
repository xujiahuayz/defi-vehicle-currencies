from __future__ import annotations

import pandas as pd
import pytest

from ddvc.capital_validation import (
    CAPITAL_PRICE_SOURCE,
    CapitalPrice,
    ConstantProductReserveState,
    canonical_constant_product_closing_reserves,
    capital_price_lookup,
    pool_day_reserve_state,
    validate_constant_product_capital,
    validated_capital_prices,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
OTHER = "0x" + "1" * 40


def price(value: float) -> CapitalPrice:
    return CapitalPrice(value, CAPITAL_PRICE_SOURCE, "consensus_and_address_time_sanity_passed")


def row(**overrides: object) -> dict[str, object]:
    base = {
        "token0_address": WETH,
        "token1_address": OTHER,
        "reserve0": 10.0,
        "reserve1": 20_000.0,
        "reported_capital_usd": 40_000.0,
    }
    return {**base, **overrides}


def test_one_anchored_leg_values_both_constant_product_sides() -> None:
    result = validate_constant_product_capital(row(), {WETH: price(2_000.0)})
    assert result.valid
    assert result.capital_usd == 40_000.0
    assert result.reconciliation_ratio == 1.0
    assert result.balance_value_ratio is None


def test_two_anchored_legs_must_agree_before_their_values_are_added() -> None:
    accepted = validate_constant_product_capital(
        row(token1_address=USDC),
        {WETH: price(2_000.0), USDC: price(1.0)},
    )
    rejected = validate_constant_product_capital(
        row(token1_address=USDC, reserve1=5_000.0),
        {WETH: price(2_000.0), USDC: price(1.0)},
    )
    assert accepted.valid and accepted.balance_value_ratio == 1.0
    assert not rejected.valid
    assert rejected.failure_reason == "anchored_leg_value_disagreement"


def test_provider_capital_is_only_a_cross_check_not_the_admitted_quantity() -> None:
    accepted = validate_constant_product_capital(
        row(reported_capital_usd=20_000.0),
        {WETH: price(2_000.0)},
    )
    rejected_between_supported_scales = validate_constant_product_capital(
        row(reported_capital_usd=30_000.0),
        {WETH: price(2_000.0)},
    )
    rejected_far_from_supported_scales = validate_constant_product_capital(
        row(reported_capital_usd=10_000.0),
        {WETH: price(2_000.0)},
    )
    assert accepted.valid
    assert accepted.capital_usd == 40_000.0
    assert accepted.reconciliation_ratio == 2.0
    assert not rejected_between_supported_scales.valid
    assert rejected_between_supported_scales.failure_reason == "reported_capital_disagreement"
    assert not rejected_far_from_supported_scales.valid
    assert rejected_far_from_supported_scales.failure_reason == "reported_capital_disagreement"


@pytest.mark.parametrize(
    ("overrides", "prices", "reason"),
    [
        ({"token0_address": None}, {}, "missing_exact_token_identity"),
        ({"reserve0": 0.0}, {WETH: price(2_000.0)}, "nonpositive_or_missing_reserves"),
        ({"reported_capital_usd": 0.0}, {WETH: price(2_000.0)}, "nonpositive_or_missing_reported_capital"),
        ({"token0_address": OTHER}, {}, "no_valid_anchored_leg_price"),
    ],
)
def test_invalid_capital_states_are_typed(overrides, prices, reason) -> None:
    result = validate_constant_product_capital(row(**overrides), prices)
    assert not result.valid
    assert result.failure_reason == reason
    assert result.validation_status == f"quarantined_{reason}"


def test_capital_price_lookup_rejects_duplicate_address_days() -> None:
    prices = pd.DataFrame(
        [
            {
                "day": "20250101",
                "token": WETH,
                "price_usd": 2_000.0,
                "price_source": CAPITAL_PRICE_SOURCE,
                "validation_status": "consensus_and_address_time_sanity_passed",
            },
            {
                "day": "20250101",
                "token": WETH,
                "price_usd": 2_001.0,
                "price_source": CAPITAL_PRICE_SOURCE,
                "validation_status": "consensus_and_address_time_sanity_passed",
            },
        ]
    )
    with pytest.raises(ValueError, match="duplicate"):
        capital_price_lookup(prices)


def test_capital_price_sanity_filter_never_uses_future_prices(tmp_path) -> None:
    days = pd.date_range("2025-01-01", periods=60, freq="D")
    panel = pd.DataFrame(
        {
            "day": days.strftime("%Y%m%d"),
            "token": WETH,
            "price_usd": [100.0] * 5 + [10_000.0] * 55,
            "price_source": "canonical_repriced_route_legs",
            "validation_status": "minimum_observations_and_price_consensus_passed",
        }
    )
    path = tmp_path / "prices.parquet"
    panel.to_parquet(path, index=False)
    validated = validated_capital_prices(path)
    assert "20250105" in set(validated["day"])


def test_closing_reserve_replay_applies_only_liquidity_after_latest_snapshot() -> None:
    state = pd.DataFrame(
        [
            {
                "record_type": "snapshot",
                "pool": "pool",
                "period_end": 200,
                "timestamp": None,
                "block_number": None,
                "log_index": None,
                "reserve0": "10",
                "reserve1": "20",
                "amount0_delta": None,
                "amount1_delta": None,
                "usable": True,
            },
            {
                "record_type": "liquidity",
                "pool": "pool",
                "period_end": None,
                "timestamp": 150,
                "block_number": 1,
                "log_index": 1,
                "reserve0": None,
                "reserve1": None,
                "amount0_delta": "100",
                "amount1_delta": "100",
                "usable": True,
            },
            {
                "record_type": "liquidity",
                "pool": "pool",
                "period_end": None,
                "timestamp": 250,
                "block_number": 2,
                "log_index": 1,
                "reserve0": None,
                "reserve1": None,
                "amount0_delta": "2",
                "amount1_delta": "3",
                "usable": True,
            },
        ]
    )
    closing = canonical_constant_product_closing_reserves(state)["pool"]
    assert closing.reserve0 == 12.0
    assert closing.reserve1 == 23.0
    assert closing.state_timestamp == 250
    assert closing.validation_status == "latest_snapshot_plus_subsequent_liquidity_events"


def test_pool_day_reserves_use_replay_only_when_provider_fields_are_absent() -> None:
    replay = ConstantProductReserveState(10.0, 20.0, "replay", 100, "valid")
    observed = pool_day_reserve_state(
        {"reserve0": 30.0, "reserve1": 40.0}, replay, day_end_timestamp=200
    )
    fallback = pool_day_reserve_state(
        {"reserve0": float("nan"), "reserve1": float("nan")},
        replay,
        day_end_timestamp=200,
    )
    assert (observed.reserve0, observed.reserve1, observed.state_timestamp) == (30.0, 40.0, 200)
    assert fallback == replay
