from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from scripts.build_v2_token_panel import one_swaps_day, token_decimals


def canonical_state() -> pd.DataFrame:
    common = {
        "token0": "0x0",
        "token1": "0x1",
        "symbol0": "ZERO",
        "symbol1": "ONE",
        "decimals0": 6,
        "decimals1": 18,
    }
    return pd.DataFrame(
        [
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-2",
                "amount1_delta": "1",
                "value_usd": "100",
            },
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-4",
                "amount1_delta": "2",
                "value_usd": "200",
            },
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-1",
                "amount1_delta": "0.5",
                "value_usd": "10",
            },
            {
                **common,
                "record_type": "snapshot",
                "amount0_delta": None,
                "amount1_delta": None,
                "value_usd": "0",
            },
        ]
    )


@patch("scripts.build_v2_token_panel.read_cp_partition")
def test_price_and_pair_panels_consume_canonical_state(read_partition) -> None:
    read_partition.return_value = canonical_state()

    result = one_swaps_day("20250101")

    assert result is not None
    assert read_partition.call_args.args == ("uniswap_v2", "20250101")
    assert result["n_swaps"] == 3
    assert result["price_obs_dropped_small"] == 1
    prices = {row["token"]: row["price_usd"] for row in result["_px"]}
    assert prices == {"0x0": pytest.approx(50.0), "0x1": pytest.approx(100.0)}
    assert result["_pairs"][0]["n_swaps"] == 3


@patch("scripts.build_v2_token_panel.read_cp_partition")
def test_decimals_cover_tokens_in_small_swaps_too(read_partition) -> None:
    read_partition.return_value = canonical_state()
    result = one_swaps_day("20250101")
    assert result is not None
    decimals = token_decimals(pd.DataFrame(result["_px"]))
    assert dict(zip(decimals["token"], decimals["decimals"], strict=True)) == {
        "0x0": 6,
        "0x1": 18,
    }


def test_decimals_conflict_is_a_hard_failure() -> None:
    token_days = pd.DataFrame(
        {
            "token": ["0x0", "0x0"],
            "decimals": [6, 18],
            "symbol": ["ZERO", "ZERO"],
        }
    )
    with pytest.raises(RuntimeError, match="disagrees on decimals"):
        token_decimals(token_days)
