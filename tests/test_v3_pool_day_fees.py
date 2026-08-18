from __future__ import annotations

import json

import pandas as pd

from scripts.process.build_v3_pool_day_fees import build_v3_pool_day_fees


def test_build_v3_pool_day_fees_deduplicates_raw_pool_days(tmp_path) -> None:
    raw = tmp_path / "fees.jsonl"
    rows = [
        {
            "date": 1735689600,
            "pool": {
                "id": "0xpool",
                "token0": {"id": "0xusdc", "symbol": "USDC"},
                "token1": {"id": "0xweth", "symbol": "WETH"},
            },
            "feesUSD": "10",
            "volumeUSD": "1000",
            "tvlUSD": "100000",
        },
        {
            "date": 1735689600,
            "pool": {
                "id": "0xpool",
                "token0": {"id": "0xusdc", "symbol": "USDC"},
                "token1": {"id": "0xweth", "symbol": "WETH"},
            },
            "feesUSD": "12",
            "volumeUSD": "1100",
            "tvlUSD": "100500",
        },
    ]
    raw.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    panel = build_v3_pool_day_fees(raw)

    assert len(panel) == 1
    row = panel.iloc[0]
    assert pd.Timestamp(row["origin_date"]).date().isoformat() == "2025-01-01"
    assert row["pool"] == "0xpool"
    assert row["token0_address"] == "0xusdc"
    assert row["token1_address"] == "0xweth"
    assert row["fees_usd"] == 12.0
    assert row["volume_usd"] == 1100.0
