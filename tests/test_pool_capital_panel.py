from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd

from scripts.build_pool_capital_panel import (
    missing_state_pool_keys,
    state_coverage_rejections,
)


def test_missing_provider_state_pool_day_becomes_an_explicit_rejection() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state_root = root / "state"
        venue_root = state_root / "constant_product" / "uniswap_v2"
        venue_root.mkdir(parents=True)
        known_pool = "0x" + "01" * 20
        missing_pool = "0x" + "02" * 20
        token0 = "0x" + "03" * 20
        token1 = "0x" + "04" * 20
        pd.DataFrame(
            [
                {
                    "day": "20250101",
                    "pool": known_pool,
                    "token0": token0,
                    "token1": token1,
                    "symbol0": "A",
                    "symbol1": "B",
                },
                {
                    "day": "20250101",
                    "pool": missing_pool,
                    "token0": token0,
                    "token1": token1,
                    "symbol0": "A",
                    "symbol1": "B",
                },
            ]
        ).to_parquet(venue_root / "20250101.parquet", index=False)
        capital_path = root / "capital.parquet"
        pd.DataFrame(
            [{"venue": "uniswap_v2", "day": "20250101", "pool": known_pool}]
        ).to_parquet(capital_path, index=False)
        keys = missing_state_pool_keys(
            "uniswap_v2",
            capital_path=capital_path,
            state_root=state_root,
        )
        rows = state_coverage_rejections(
            "uniswap_v2",
            capital_path=capital_path,
            state_root=state_root,
        )
    assert keys == [("20250101", missing_pool)]
    assert len(rows) == 1
    assert rows[0]["pool"] == missing_pool
    assert rows[0]["reported_capital_usd"] is None
    assert rows[0]["capital_source"] == "unavailable_missing_provider_pool_day"
    assert rows[0]["capital_validation_status"] == "missing_pool_day_capital"
