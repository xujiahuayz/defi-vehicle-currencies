from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from scripts.process.build_v4_lp_action_candidate_daily import (
    DAI_ADDRESS,
    NATIVE_ETH_ADDRESS,
    USDC_ADDRESS,
    WETH_ADDRESS,
    load_raw_uniswap_v4_lp_actions,
    vehicle_candidate_map,
)


def _write_event(path: Path, event: dict[str, object]) -> None:
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_v4_lp_action_builder_maps_native_eth_and_counts_ranges(
    tmp_path: Path,
) -> None:
    candidate_day = tmp_path / "candidate_day.parquet"
    pd.DataFrame(
        [
            {"candidate_address": WETH_ADDRESS, "candidate_symbol": "WETH"},
            {"candidate_address": USDC_ADDRESS, "candidate_symbol": "USDC"},
            {"candidate_address": DAI_ADDRESS, "candidate_symbol": "DAI"},
        ]
    ).to_parquet(candidate_day, index=False)
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    path = event_dir / "uniswap_v4_modify_liquidities_20250101.jsonl.gz"
    _write_event(
        path,
        {
            "timestamp": 1_735_689_600,
            "amount": "10",
            "origin": "0xorigin1",
            "sender": "0xsender1",
            "tickLower": "-100",
            "tickUpper": "100",
            "pool": {
                "token0": {"id": NATIVE_ETH_ADDRESS},
                "token1": {"id": USDC_ADDRESS},
            },
        },
    )
    _write_event(
        path,
        {
            "transaction": {"timestamp": 1_735_689_600},
            "amount": "-4",
            "origin": "0xorigin2",
            "sender": "0xsender2",
            "tickLower": "-100000",
            "tickUpper": "100000",
            "pool": {
                "token0": {"id": WETH_ADDRESS},
                "token1": {"id": DAI_ADDRESS},
            },
        },
    )

    mapping = vehicle_candidate_map(candidate_day)
    actions, support = load_raw_uniswap_v4_lp_actions(
        event_dir=event_dir,
        candidate_map=mapping,
    )

    assert mapping[NATIVE_ETH_ADDRESS] == mapping[WETH_ADDRESS]
    assert support["raw_modify_liquidity_events"] == 2
    assert support["matched_candidate_event_assignments"] == 4
    assert support["native_eth_to_weth_assignments"] == 1
    weth = actions[actions["candidate_symbol"].eq("WETH")].iloc[0]
    usdc = actions[actions["candidate_symbol"].eq("USDC")].iloc[0]
    dai = actions[actions["candidate_symbol"].eq("DAI")].iloc[0]
    assert weth["v4_add_events"] == 1
    assert weth["v4_remove_events"] == 1
    assert weth["v4_narrow_range_events"] == 1
    assert weth["v4_very_wide_range_events"] == 1
    assert usdc["v4_add_events"] == 1
    assert dai["v4_remove_events"] == 1
