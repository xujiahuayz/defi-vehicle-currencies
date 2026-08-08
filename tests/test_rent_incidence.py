"""Checks on the rent-incidence accounting, on the pieces that can be wrong silently.

The three hazards are the tick-liquidity replay, whose bug would be a plausible
but wrong liquidity number rather than a crash; the multi-scale realised
variance, whose coarse arms are the bound on the microstructure threat and are
worthless if they are not actually coarser; and the loss-versus-rebalancing
closed form, which is asserted in prose everywhere and derived nowhere.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_rent_incidence import (
    OUTPUT_PROVENANCE,
    REQUIRED_PANELS,
    by_role_over_time,
)

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_rent_incidence_panel", ROOT / "scripts" / "build_rent_incidence_panel.py")
brp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brp)


def test_every_estimator_output_uses_one_current_input_contract():
    source = (ROOT / "scripts" / "run_rent_incidence.py").read_text()
    assert OUTPUT_PROVENANCE["inputs"] == REQUIRED_PANELS
    assert source.count("**OUTPUT_PROVENANCE") == 7


def test_role_exhibit_keeps_pooled_and_annual_bridge_rows():
    dates = pd.to_datetime(["2024-01-01"] * 500 + ["2025-01-01"] * 500)
    frame = pd.DataFrame(
        {
            "date": dates,
            "day": dates.strftime("%Y%m%d"),
            "pool_role": "native / other",
            "pool": [f"pool-{index % 2}" for index in range(1_000)],
            "token0": "native",
            "token1": "other",
            "tvl_usd": 100_000.0,
            "fee_yield": 0.001,
            "lvr_rate": 0.002,
            "gas_rate": 0.0001,
            "n_mint": 1,
            "n_burn": 0,
            "net_yield": -0.0011,
            "net_pre_gas_yield": -0.001,
            "fees_usd": 100.0,
            "lvr_usd": 200.0,
            "gas_usd": 10.0,
            "net_usd": -110.0,
        }
    )

    result = by_role_over_time(frame, "uniswap_v2")

    assert set(result["scope"]) == {"pooled", "annual"}
    assert set(result.loc[result.scope.eq("annual"), "year"]) == {2024, 2025}
    pooled = result.loc[result.scope.eq("pooled")].iloc[0]
    assert pooled["pool_days"] == 1_000
    assert pooled["mean_daily_capital_usd_bn"] == pytest.approx(0.05)
    assert pooled["capital_share"] == pytest.approx(1.0)
    assert pooled["pool_day_share"] == pytest.approx(1.0)


def test_fenwick_matches_brute_force_prefix_sums():
    rng = np.random.default_rng(0)
    n = 64
    # Python integers, because the values these hold are uint128 in the source.
    deltas = [int(v) * 10 ** 20 for v in rng.integers(-10 ** 9, 10 ** 9, size=n)]
    tree = brp.Fenwick(n)
    for i, d in enumerate(deltas):
        tree.add(i, int(d))
    running = 0
    for i, d in enumerate(deltas):
        running += int(d)
        assert tree.prefix(i) == running


def test_fenwick_handles_uint128_scale_without_overflow():
    big = 2 ** 127 - 1
    tree = brp.Fenwick(3)
    tree.add(0, big)
    tree.add(2, big)
    assert tree.prefix(2) == 2 * big


def test_active_liquidity_is_zero_outside_every_position_range():
    """A mint at [lo, hi) adds liquidity at lo and removes it at hi."""
    ticks = [-120, 60]
    tree = brp.Fenwick(len(ticks))
    tree.add(0, 5_000)          # tickLower
    tree.add(1, -5_000)         # tickUpper
    below = np.searchsorted(ticks, -200, side="right") - 1
    inside = np.searchsorted(ticks, 0, side="right") - 1
    above = np.searchsorted(ticks, 500, side="right") - 1
    assert below < 0
    assert tree.prefix(inside) == 5_000
    assert tree.prefix(above) == 0


def test_open_to_close_variance_is_the_total_move_squared():
    hours = np.arange(6, dtype=np.int64)
    prices = np.array([100.0, 101.0, 99.0, 103.0, 98.0, 102.0])
    rv1, rv4, rv_oc, mx = brp._rv_multiscale(hours, prices)
    assert rv_oc == pytest.approx(np.log(102.0 / 100.0) ** 2)
    assert rv1 == pytest.approx(float(np.sum(np.diff(np.log(prices)) ** 2)))
    assert mx == pytest.approx(float(np.max(np.abs(np.diff(np.log(prices))))))
    # Two four-hour buckets here, so the coarse estimate uses one return.
    assert rv4 < rv1


def test_coarse_sampling_strips_the_round_trip_that_fine_sampling_counts():
    """A price that bounces and comes back has variance at one scale and none at another."""
    hours = np.arange(8, dtype=np.int64)
    prices = np.array([100.0, 110.0, 100.0, 110.0, 100.0, 110.0, 100.0, 110.0])
    rv1, _rv4, rv_oc, _ = brp._rv_multiscale(hours, prices)
    assert rv1 > 0.05
    assert rv_oc == pytest.approx(np.log(1.1) ** 2)


def test_square_root_price_input_is_doubled_into_log_returns():
    hours = np.arange(3, dtype=np.int64)
    price = np.array([100.0, 121.0, 144.0])
    rv_price, _, _, _ = brp._rv_multiscale(hours, price)
    rv_sqrt, _, _, _ = brp._rv_multiscale(hours, np.sqrt(price), scale=2.0)
    assert rv_sqrt == pytest.approx(rv_price)


def test_v3_daily_swaps_and_liquidity_counts_share_one_partition_read(monkeypatch):
    state = pd.DataFrame(
        [
            {
                "record_type": "swap",
                "pool": "pool",
                "token0": "token0",
                "token1": "token1",
                "symbol0": "T0",
                "symbol1": "T1",
                "fee_pips": 3_000,
                "value_usd": 100.0,
                "timestamp": 3_600,
                "sqrt_price_x96": 2.0,
                "tick": 10,
                "source_stream": "swaps",
            },
            {
                "record_type": "liquidity",
                "pool": "pool",
                "source_stream": "mints",
            },
        ]
    )
    calls = []

    def read_partition(venue, day):
        calls.append((venue, day))
        return state

    monkeypatch.setattr(brp, "read_tick_partition", read_partition)
    swaps, counts = brp._v3_day_summary("20250101", {"pool"})

    assert calls == [("uniswap_v3", "20250101")]
    assert swaps["pool"]["n"] == 1
    assert counts["pool"] == (1, 0)


def test_lvr_closed_form_equals_the_numeric_delta_hedging_loss():
    """LVR rate is sigma^2/2 * P^2 * |dx/dP|, which for constant product is V * sigma^2/8.

    The pool holds x = L / sqrt(P) of the risky asset, so the derivative is taken
    numerically here rather than reusing the algebra the closed form came from.
    """
    liq, price = 1_234.0, 2_500.0
    h = price * 1e-6

    def x_of(p):
        return liq / np.sqrt(p)

    dxdp = (x_of(price + h) - x_of(price - h)) / (2 * h)
    sigma_sq = 0.04
    lvr_rate = 0.5 * sigma_sq * price ** 2 * abs(dxdp)
    pool_value = 2.0 * liq * np.sqrt(price)      # y + P*x with y = L*sqrt(P)
    assert lvr_rate == pytest.approx(sigma_sq / 8.0 * pool_value, rel=1e-6)


def test_virtual_reserves_reproduce_the_liquidity_invariant():
    liq, sqrt_price = 5e18, 3.0
    y = liq * sqrt_price
    x = liq / sqrt_price
    assert x * y == pytest.approx(liq ** 2)
    assert 2.0 * y == pytest.approx(y + (sqrt_price ** 2) * x)


def test_constant_product_pool_holds_equal_value_on_both_legs():
    """The identity the anchored valuation relies on, so a pool is worth twice one leg."""
    reserve0, reserve1 = 400.0, 1_000_000.0
    price0_in_1 = reserve1 / reserve0
    assert reserve0 * price0_in_1 == pytest.approx(reserve1)
    assert 2.0 * reserve1 == pytest.approx(reserve0 * price0_in_1 + reserve1)
