from __future__ import annotations

import pandas as pd
import pytest

from ddvc.analysis.lp_concentration import candidate_capital_changes, compute_lp_capital_day
from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.liquidity import equal_candidate_capital_weights, liquidity_contract


def address(symbol: str) -> str:
    return next(item for item, candidate in VEHICLE_CANDIDATES.items() if candidate == symbol)


def candidate_row(
    *,
    pool: str,
    candidate: str,
    capital: float,
    venue: str = "uniswap_v2",
) -> dict[str, object]:
    contract = liquidity_contract(venue)
    return {
        "day": "20250101",
        "venue": venue,
        "pool": pool,
        "candidate": candidate,
        "candidate_address": address(candidate),
        "candidate_capital_usd": capital,
        "quantity_kind": "deposited_capital",
        "pool_family": contract.pool_family,
        "state_generation": contract.capability("deposited_capital").state_generation,
        "capital_validation_status": "exact_state_current",
    }


def test_candidate_universe_matches_the_locked_five_tokens() -> None:
    assert set(VEHICLE_CANDIDATES.values()) == {"WETH", "USDC", "USDT", "DAI", "WBTC"}


def test_shared_allocator_counts_one_pool_once() -> None:
    weth = address("WETH")
    usdc = address("USDC")
    assert equal_candidate_capital_weights(
        (weth, usdc),
        frozenset(VEHICLE_CANDIDATES),
    ) == {weth: 0.5, usdc: 0.5}


def test_cross_venue_capital_share_preserves_allocated_pool_total() -> None:
    frame = pd.DataFrame(
        [
            candidate_row(pool="shared", candidate="WETH", capital=500.0),
            candidate_row(pool="shared", candidate="USDC", capital=500.0),
            candidate_row(
                pool="weth-only",
                candidate="WETH",
                capital=800.0,
                venue="sushiswap_v2",
            ),
        ]
    )

    result = compute_lp_capital_day(frame).set_index("token_symbol")

    assert result["total_lp_capital_usd"].sum() == 1_800.0
    assert result.loc["WETH", "total_lp_capital_usd"] == 1_300.0
    assert result.loc["USDC", "total_lp_capital_usd"] == 500.0
    assert result["lp_capital_share"].sum() == pytest.approx(1.0)
    assert result.loc["WETH", "venue_count"] == 2
    assert result.loc["WETH", "pool_family_count"] == 1
    assert result.loc["WETH", "state_generation_count"] == 1
    assert set(result["quantity_kind"]) == {"deposited_capital"}


def test_duplicate_pool_candidate_rows_fail_closed() -> None:
    row = candidate_row(pool="duplicate", candidate="WETH", capital=100.0)
    with pytest.raises(ValueError, match="double count"):
        compute_lp_capital_day(pd.DataFrame([row, row]))


def test_noncapital_or_quarantined_rows_cannot_enter_share() -> None:
    admitted = candidate_row(pool="admitted", candidate="WETH", capital=100.0)
    depth = {
        **candidate_row(pool="depth", candidate="USDC", capital=1_000.0),
        "quantity_kind": "local_depth",
    }
    quarantined = {
        **candidate_row(pool="quarantined", candidate="USDT", capital=1_000.0),
        "capital_validation_status": "quarantined",
    }

    result = compute_lp_capital_day(pd.DataFrame([admitted, depth, quarantined]))

    assert result["token_symbol"].tolist() == ["WETH"]
    assert result["total_lp_capital_usd"].tolist() == [100.0]


def test_capital_change_uses_persisted_exact_calendar_lag_only() -> None:
    frame = pd.DataFrame(
        {
            "candidate_capital_usd": [100.0, 150.0, 180.0],
            "candidate_capital_usd_lagged": [float("nan"), float("nan"), 150.0],
            "exact_lag_valid": [False, False, True],
        }
    )

    result = candidate_capital_changes(frame)

    assert result["dlog_capital"].isna().tolist() == [True, True, False]
    assert result.loc[2, "dlog_capital"] == pytest.approx(0.1823215567939546)
