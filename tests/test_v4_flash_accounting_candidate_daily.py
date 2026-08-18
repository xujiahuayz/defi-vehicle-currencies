from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
import pandas as pd

from scripts.process.build_v4_flash_accounting_candidate_daily import (
    load_raw_uniswap_v4_flash_accounting,
)
from scripts.process.build_v4_lp_action_candidate_daily import (
    DAI_ADDRESS,
    NATIVE_ETH_ADDRESS,
    USDC_ADDRESS,
    WETH_ADDRESS,
    vehicle_candidate_map,
)


def _write_swap(path: Path, event: dict[str, object]) -> None:
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_v4_flash_accounting_builder_maps_native_eth_and_nets_transactions(
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
    path = event_dir / "uniswap_v4_swaps_20250101.jsonl.gz"
    _write_swap(
        path,
        {
            "id": "0xaaa-0",
            "transaction": {"id": "0xaaa"},
            "amount0": "100",
            "amount1": "-1",
            "pool": {
                "token0": {"id": USDC_ADDRESS},
                "token1": {"id": WETH_ADDRESS},
            },
        },
    )
    _write_swap(
        path,
        {
            "id": "0xaaa-1",
            "transaction": {"id": "0xaaa"},
            "amount0": "-40",
            "amount1": "40",
            "pool": {
                "token0": {"id": USDC_ADDRESS},
                "token1": {"id": DAI_ADDRESS},
            },
        },
    )
    _write_swap(
        path,
        {
            "id": "0xbbb-0",
            "transaction": {"id": "0xbbb"},
            "amount0": "2",
            "amount1": "-200",
            "pool": {
                "token0": {"id": NATIVE_ETH_ADDRESS},
                "token1": {"id": USDC_ADDRESS},
            },
        },
    )

    mapping = vehicle_candidate_map(candidate_day)
    frame, support = load_raw_uniswap_v4_flash_accounting(
        event_dir=event_dir,
        candidate_map=mapping,
    )

    assert mapping[NATIVE_ETH_ADDRESS] == mapping[WETH_ADDRESS]
    assert support["raw_swap_rows"] == 3
    assert support["transactions"] == 2
    assert support["matched_candidate_leg_assignments"] == 6
    assert support["native_eth_to_weth_assignments"] == 1
    usdc = frame[frame["candidate_symbol"].eq("USDC")].iloc[0]
    assert usdc["candidate_tx_count"] == 2
    assert usdc["swap_leg_assignments"] == 3
    assert usdc["internal_tx_count"] == 1
    assert usdc["multi_leg_tx_count"] == 1
    assert usdc["gross_abs_amount"] == 340
    assert usdc["net_abs_amount"] == 260
    assert usdc["netting_reduction_amount"] == 80
    assert usdc["netting_reduction_share"] == pytest.approx(80 / 340)
