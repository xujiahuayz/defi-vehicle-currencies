from __future__ import annotations

from pathlib import Path
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts import build_pool_capital_panel as capital_builder
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
    assert rows[0]["reported_capital_source"] == "unavailable_missing_provider_pool_day"
    assert rows[0]["capital_source"] == "reconciled_constant_product_reserves"
    assert rows[0]["capital_validation_status"] == "missing_pool_day_capital"


def test_state_coverage_rejections_append_without_loading_the_existing_ledger(
    tmp_path,
    monkeypatch,
) -> None:
    base = {
        "venue": "uniswap_v2",
        "day": "20250101",
        "pool": "0x" + "01" * 20,
        "token0_address": "0x" + "03" * 20,
        "token0_symbol": "A",
        "token1_address": "0x" + "04" * 20,
        "token1_symbol": "B",
        "reported_capital_usd": None,
        "reported_capital_source": "unavailable_missing_provider_pool_day",
        "reconstructed_capital_usd": None,
        "capital_reconciliation_ratio": None,
        "balance_value_ratio": None,
        "reserve_source": "unavailable_missing_provider_pool_day",
        "reserve_state_timestamp": None,
        "reserve_validation_status": "unavailable_missing_provider_pool_day",
        "capital_source": "reconciled_constant_product_reserves",
        "price_source": "unavailable_missing_provider_pool_day",
        "quantity_kind": "deposited_capital",
        "pool_family": "full_range_constant_product",
        "invariant_family": "full_range_constant_product",
        "state_generation": "reconciled_constant_product_reserves_v2",
        "capital_validation_status": "missing_pool_day_capital",
        "failure_reason": "canonical state pool-day lacks provider capital",
    }
    path = tmp_path / "rejections.parquet"
    pq.write_table(
        pa.Table.from_pylist([base], schema=capital_builder.REJECTION_SCHEMA),
        path,
    )
    added = {**base, "pool": "0x" + "02" * 20}
    monkeypatch.setattr(capital_builder, "REJECTIONS_OUT", path)
    monkeypatch.setattr(
        capital_builder,
        "state_coverage_rejections",
        lambda _venue: [added],
    )
    row_count, counts, _sources = capital_builder.append_state_coverage_rejections(
        ("uniswap_v2",)
    )
    result = pd.read_parquet(path)
    assert row_count == 2
    assert counts == {"uniswap_v2": 1}
    assert set(result["pool"]) == {base["pool"], added["pool"]}
