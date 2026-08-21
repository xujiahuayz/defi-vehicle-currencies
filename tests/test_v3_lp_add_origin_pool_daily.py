from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.process.build_v3_lp_add_origin_pool_daily import (
    attach_pool_identity,
    four_vehicle_candidate_map,
    load_v3_lp_add_origins,
    validate_panel,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
ENDPOINT = "0x0000000000000000000000000000000000000001"


def _timestamp(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp()))


def _price_panel(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "day": day.strftime("%Y%m%d"),
                "token": USDC,
                "symbol": "USDC",
                "price_usd": 1.0,
                "n_observations": 5,
                "n_consensus": 5,
                "consensus_share": 1.0,
                "gross_weight_usd": 1_000.0,
                "consensus_weight_usd": 1_000.0,
                "price_source": "canonical_repriced_route_legs",
                "validation_status": "minimum_observations_and_price_consensus_passed",
            }
            for day in pd.date_range("2025-01-01", "2025-01-05", freq="D")
        ]
    ).to_parquet(path, index=False)


def _mint(*, event_id: str, origin: str, liquidity: str, amount0: str) -> dict:
    return {
        "id": event_id,
        "amount": liquidity,
        "amount0": amount0,
        "amount1": "1",
        "origin": origin,
        "owner": "0xposition-manager",
        "sender": "0xposition-manager",
        "pool": {
            "id": "0xpool",
            "token0": {"id": USDC, "symbol": "USDC"},
            "token1": {"id": ENDPOINT, "symbol": "TOKEN"},
        },
        "timestamp": _timestamp("2025-01-05"),
        "transaction": {
            "id": f"0xtx-{event_id}",
            "timestamp": _timestamp("2025-01-05"),
        },
    }


def test_v3_origin_panel_keeps_transaction_origin_and_positive_mints(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    prices = tmp_path / "prices.parquet"
    _price_panel(prices)
    rows = [
        _mint(event_id="one", origin="0xorigin", liquidity="1", amount0="100"),
        _mint(event_id="two", origin="0xorigin", liquidity="2", amount0="50"),
        _mint(event_id="blank", origin="", liquidity="1", amount0="20"),
        _mint(event_id="zero", origin="0xother", liquidity="0", amount0="20"),
    ]
    with gzip.open(event_dir / "uniswap_v3_mints_20250105.jsonl.gz", "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    pool_sides = pd.DataFrame(
        [
            {
                "pool": "0xpool",
                "side_index": 0,
                "candidate_address": USDC,
                "candidate_symbol": "USDC",
            }
        ]
    )
    frame, support = load_v3_lp_add_origins(
        event_dir=event_dir,
        candidate_map={USDC: (USDC, "USDC")},
        pool_candidate_sides=pool_sides,
        price_path=prices,
    )

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["origin"] == "0xorigin"
    assert row["v3_add_action_events"] == 2
    assert row["v3_add_action_transactions"] == 2
    assert row["v3_add_flow_usd_screened"] == pytest.approx(150.0)
    assert support["positive_mints_missing_origin"] == 1
    assert support["nonpositive_liquidity_candidate_events"] == 1

    registry = pd.DataFrame(
        [
            {
                "pool": "0xpool",
                "token0_address": USDC,
                "token0_symbol": "USDC",
                "token1_address": ENDPOINT,
                "token1_symbol": "TOKEN",
                "fee_tier": 3000,
            }
        ]
    )
    attached, registry_support = attach_pool_identity(frame, registry)
    validate_panel(attached)
    assert attached.iloc[0]["paired_token_address"] == ENDPOINT
    assert registry_support["missing_registry_rows"] == 0


def test_v3_origin_registry_gap_is_bounded() -> None:
    frame = pd.DataFrame(
        [
            {
                "pool": "0xmissing",
                "candidate_address": USDC,
                "v3_add_flow_usd_screened": 101.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="registry gap"):
        attach_pool_identity(frame, pd.DataFrame(columns=["pool"]))


def test_four_vehicle_scope_excludes_wbtc(tmp_path: Path) -> None:
    path = tmp_path / "candidate_day.parquet"
    pd.DataFrame(
        [
            {"candidate_address": address, "candidate_symbol": symbol}
            for address, symbol in (
                (WETH, "WETH"),
                (DAI, "DAI"),
                (USDC, "USDC"),
                (USDT, "USDT"),
                (WBTC, "WBTC"),
            )
        ]
    ).to_parquet(path, index=False)
    mapping = four_vehicle_candidate_map(path)
    assert {symbol for _address, symbol in mapping.values()} == {
        "WETH",
        "DAI",
        "USDC",
        "USDT",
    }
    assert WBTC not in mapping
