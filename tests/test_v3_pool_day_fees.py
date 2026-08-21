from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.process.build_v3_pool_day_fees import build_v3_pool_day_fees


def _static(path) -> None:
    path.write_text(
        json.dumps(
            {
                "id": "0xpool",
                "feeTier": "3000",
                "token0": {"id": "0xusdc", "symbol": "USDC"},
                "token1": {"id": "0xweth", "symbol": "WETH"},
            }
        ),
        encoding="utf-8",
    )


def test_build_v3_pool_day_fees_uses_static_identity_and_fee_tier(tmp_path) -> None:
    raw = tmp_path / "fees.jsonl"
    static = tmp_path / "statics.jsonl"
    _static(static)
    row = {
        "date": 1735689600,
        "pool": {"id": "0xpool"},
        "feesUSD": "3.3",
        "volumeUSD": "1100",
        "tvlUSD": "100500",
    }
    raw.write_text(json.dumps(row), encoding="utf-8")

    panel = build_v3_pool_day_fees(raw, static)

    assert len(panel) == 1
    result = panel.iloc[0]
    assert pd.Timestamp(result["origin_date"]).date().isoformat() == "2025-01-01"
    assert result["pool"] == "0xpool"
    assert result["token0_address"] == "0xusdc"
    assert result["token1_address"] == "0xweth"
    assert result["fee_tier"] == 3000
    assert result["gross_fees_usd"] == pytest.approx(3.3)
    assert result["fees_usd"] == pytest.approx(3.3)
    assert result["volume_usd"] == 1100.0
    assert result["tvl_usd"] == 100500.0


def test_build_v3_pool_day_fees_rejects_duplicate_pool_days(tmp_path) -> None:
    raw = tmp_path / "fees.jsonl"
    static = tmp_path / "statics.jsonl"
    _static(static)
    rows = [
        {
            "date": 1735689600,
            "pool": {"id": "0xpool"},
            "feesUSD": "3",
            "volumeUSD": "1000",
            "tvlUSD": "100000",
        },
        {
            "date": 1735689600,
            "pool": {"id": "0xpool"},
            "feesUSD": "3.3",
            "volumeUSD": "1100",
            "tvlUSD": "100500",
        },
    ]
    raw.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate pool-days"):
        build_v3_pool_day_fees(raw, static)
