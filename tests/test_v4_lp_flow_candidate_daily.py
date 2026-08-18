from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.process.build_v4_lp_action_candidate_daily import (
    NATIVE_ETH_ADDRESS,
    USDC_ADDRESS,
    WETH_ADDRESS,
)
from scripts.process.build_v4_lp_flow_candidate_daily import (
    load_raw_uniswap_v4_lp_flows,
    run,
)


def _timestamp(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp()))


def _write_price_panel(path: Path) -> None:
    rows = []
    for day in pd.date_range("2025-01-01", "2025-01-05", freq="D"):
        day_text = day.strftime("%Y%m%d")
        rows.extend(
            [
                {
                    "day": day_text,
                    "token": WETH_ADDRESS,
                    "symbol": "WETH",
                    "price_usd": 2_000.0,
                    "n_observations": 5,
                    "n_consensus": 5,
                    "consensus_share": 1.0,
                    "gross_weight_usd": 1_000.0,
                    "consensus_weight_usd": 1_000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                },
                {
                    "day": day_text,
                    "token": USDC_ADDRESS,
                    "symbol": "USDC",
                    "price_usd": 1.0,
                    "n_observations": 5,
                    "n_consensus": 5,
                    "consensus_share": 1.0,
                    "gross_weight_usd": 1_000.0,
                    "consensus_weight_usd": 1_000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _event(
    *,
    amount: str,
    amount0: str,
    amount1: str,
    token0: str,
    token1: str,
    tick_lower: str,
    tick_upper: str,
    tx: str,
) -> dict[str, object]:
    return {
        "amount": amount,
        "amount0": amount0,
        "amount1": amount1,
        "id": f"{tx}-1",
        "origin": f"0xorigin{tx[-1]}",
        "sender": "0xsender",
        "pool": {
            "id": f"0xpool{tx[-1]}",
            "token0": {"id": token0, "symbol": "ETH" if token0 == NATIVE_ETH_ADDRESS else "USDC"},
            "token1": {"id": token1, "symbol": "USDC" if token1 == USDC_ADDRESS else "OTHER"},
        },
        "tickLower": tick_lower,
        "tickUpper": tick_upper,
        "timestamp": _timestamp("2025-01-05"),
        "transaction": {"id": tx, "timestamp": _timestamp("2025-01-05")},
    }


def test_v4_lp_flow_loader_prices_native_eth_and_screens_outliers(tmp_path: Path) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    _write_price_panel(price_path)
    with gzip.open(event_dir / "uniswap_v4_modify_liquidities_20250105.jsonl.gz", "wt") as handle:
        for row in [
            _event(
                amount="1",
                amount0="2",
                amount1="1000",
                token0=NATIVE_ETH_ADDRESS,
                token1=USDC_ADDRESS,
                tick_lower="0",
                tick_upper="500",
                tx="0xaaa",
            ),
            _event(
                amount="-1",
                amount0="-0.5",
                amount1="0",
                token0=WETH_ADDRESS,
                token1="0x0000000000000000000000000000000000000001",
                tick_lower="0",
                tick_upper="20000",
                tx="0xbbb",
            ),
            _event(
                amount="-1",
                amount0="-200000000",
                amount1="0",
                token0=USDC_ADDRESS,
                token1="0x0000000000000000000000000000000000000002",
                tick_lower="0",
                tick_upper="500",
                tx="0xccc",
            ),
        ]:
            handle.write(json.dumps(row) + "\n")

    candidate_map = {
        WETH_ADDRESS: (WETH_ADDRESS, "WETH"),
        NATIVE_ETH_ADDRESS: (WETH_ADDRESS, "WETH"),
        USDC_ADDRESS: (USDC_ADDRESS, "USDC"),
    }
    flows, support = load_raw_uniswap_v4_lp_flows(
        event_dir=event_dir,
        candidate_map=candidate_map,
        price_path=price_path,
        max_candidate_side_event_usd=100_000_000.0,
    )

    weth = flows[flows["candidate_symbol"].eq("WETH")].iloc[0]
    usdc = flows[flows["candidate_symbol"].eq("USDC")].iloc[0]
    assert weth["v4_gross_lp_flow_usd_screened"] == pytest.approx(5_000.0)
    assert weth["v4_add_lp_flow_usd_screened"] == pytest.approx(4_000.0)
    assert weth["v4_remove_lp_flow_usd_screened"] == pytest.approx(1_000.0)
    assert weth["v4_narrow_flow_usd_screened"] == pytest.approx(4_000.0)
    assert weth["v4_wide_flow_usd_screened"] == pytest.approx(1_000.0)
    assert usdc["v4_gross_lp_flow_usd_screened"] == pytest.approx(1_000.0)
    assert usdc["v4_lp_flow_above_screen_assignments"] == 1
    assert support["native_eth_to_weth_assignments"] == 1
    assert support["above_screen_assignments"] == 1


def test_v4_lp_flow_run_writes_panel_and_support(tmp_path: Path) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    candidate_day = tmp_path / "candidate_day.parquet"
    output = tmp_path / "flows.parquet"
    support = tmp_path / "support.jsonl"
    _write_price_panel(price_path)
    pd.DataFrame(
        [
            {"candidate_address": WETH_ADDRESS, "candidate_symbol": "WETH"},
            {"candidate_address": USDC_ADDRESS, "candidate_symbol": "USDC"},
        ]
    ).to_parquet(candidate_day, index=False)
    with gzip.open(event_dir / "uniswap_v4_modify_liquidities_20250105.jsonl.gz", "wt") as handle:
        handle.write(
            json.dumps(
                _event(
                    amount="1",
                    amount0="1",
                    amount1="2",
                    token0=NATIVE_ETH_ADDRESS,
                    token1=USDC_ADDRESS,
                    tick_lower="0",
                    tick_upper="500",
                    tx="0xaaa",
                )
            )
            + "\n"
        )

    assert (
        run(
            output_path=output,
            support_path=support,
            event_dir=event_dir,
            candidate_day_path=candidate_day,
            price_path=price_path,
        )
        == 0
    )
    assert pd.read_parquet(output)["v4_gross_lp_flow_usd_screened"].sum() == pytest.approx(
        2_002.0
    )
    assert "v4_lp_flow_support" in support.read_text()
