from __future__ import annotations

import math

import pytest

from ddvc.analysis.dominance_cost_contract import (
    COMPARATOR_SYMBOLS,
    COMPARATOR_VEHICLES,
    NATIVE_VEHICLE,
    OUTCOME_COLUMNS,
    PAIR_CELL_KEYS,
    SUPPORT_STAGES,
    SUPPORT_STRATA_KEYS,
    comparator_symbol,
    dominance_outcomes,
)
from ddvc.asset_types import VEHICLE_CANDIDATES, WETH


def test_membership_and_keys_have_canonical_owners() -> None:
    assert NATIVE_VEHICLE == WETH
    assert set(COMPARATOR_VEHICLES.values()) == set(COMPARATOR_SYMBOLS)
    assert COMPARATOR_VEHICLES == {
        address: symbol
        for address, symbol in VEHICLE_CANDIDATES.items()
        if symbol in COMPARATOR_SYMBOLS
    }
    assert PAIR_CELL_KEYS == (
        "date",
        "reserve_hour_utc",
        "src",
        "tgt",
        "trade_size_usd",
        "comparator",
    )
    assert "method" not in PAIR_CELL_KEYS
    assert SUPPORT_STRATA_KEYS == ("date", "comparator", "trade_size_usd")
    assert SUPPORT_STAGES[0] == "candidate_pair_attempted"
    assert tuple(OUTCOME_COLUMNS) == (
        "weth_symmetric_output_edge_bps",
        "weth_output_gain_bps_of_notional",
        "weth_log_output_ratio",
        "weth_signed_win",
        "weth_direct_threshold_edge",
    )


def test_comparator_symbol_rejects_native_and_unknown_assets() -> None:
    usdc = next(address for address, symbol in COMPARATOR_VEHICLES.items() if symbol == "USDC")
    assert comparator_symbol(usdc.upper()) == "USDC"
    with pytest.raises(ValueError, match="outside the locked set"):
        comparator_symbol(WETH)
    with pytest.raises(ValueError, match="outside the locked set"):
        comparator_symbol("0xdead")


def test_outcomes_are_bounded_and_keep_magnitude_incidence_and_tail_separate() -> None:
    values = dominance_outcomes(
        weth_output_usd=990.0,
        comparator_output_usd=980.0,
        trade_size_usd=1_000.0,
        direct_output_usd=985.0,
    )
    assert values["weth_symmetric_output_edge_bps"] == pytest.approx(20_000.0 * 10.0 / 1_970.0)
    assert values["weth_output_gain_bps_of_notional"] == pytest.approx(100.0)
    assert values["weth_log_output_ratio"] == pytest.approx(math.log(990.0 / 980.0))
    assert values["weth_signed_win"] == 1
    assert values["weth_direct_threshold_edge"] == 1


def test_equal_outputs_and_missing_direct_output_have_explicit_values() -> None:
    values = dominance_outcomes(
        weth_output_usd=500.0,
        comparator_output_usd=500.0,
        trade_size_usd=1_000.0,
        direct_output_usd=None,
    )
    assert values["weth_symmetric_output_edge_bps"] == 0.0
    assert values["weth_output_gain_bps_of_notional"] == 0.0
    assert values["weth_log_output_ratio"] == 0.0
    assert values["weth_signed_win"] == 0
    assert values["weth_direct_threshold_edge"] is None


def test_symmetric_edge_remains_bounded_when_one_output_is_near_zero() -> None:
    positive = dominance_outcomes(
        weth_output_usd=1_000.0,
        comparator_output_usd=1e-12,
        trade_size_usd=1_000.0,
        direct_output_usd=1.0,
    )
    negative = dominance_outcomes(
        weth_output_usd=1e-12,
        comparator_output_usd=1_000.0,
        trade_size_usd=1_000.0,
        direct_output_usd=1.0,
    )
    assert 0 < positive["weth_symmetric_output_edge_bps"] <= 20_000.0
    assert -20_000.0 <= negative["weth_symmetric_output_edge_bps"] < 0
    assert positive["weth_direct_threshold_edge"] == 1
    assert negative["weth_direct_threshold_edge"] == -1


@pytest.mark.parametrize(
    ("weth", "comparator", "notional"),
    [
        (0.0, 1.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 0.0),
        (float("nan"), 1.0, 1.0),
        (1.0, float("inf"), 1.0),
    ],
)
def test_invalid_primary_inputs_fail_closed(weth: float, comparator: float, notional: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        dominance_outcomes(
            weth_output_usd=weth,
            comparator_output_usd=comparator,
            trade_size_usd=notional,
            direct_output_usd=1.0,
        )
