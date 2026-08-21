from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.process.build_v3_lp_flow_pool_daily import (
    attach_v3_pool_registry,
    run,
)
from scripts.process.build_v3_lp_flow_candidate_daily import (
    load_raw_uniswap_v3_lp_flows,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
ENDPOINT = "0x0000000000000000000000000000000000000001"


def _timestamp(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp()))


def _price_panel(path: Path) -> None:
    rows = []
    for day in pd.date_range("2025-01-01", "2025-01-05", freq="D"):
        for token, symbol, price in (
            (WETH, "WETH", 2_000.0),
            (USDC, "USDC", 1.0),
        ):
            rows.append(
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": token,
                    "symbol": symbol,
                    "price_usd": price,
                    "n_observations": 5,
                    "n_consensus": 5,
                    "consensus_share": 1.0,
                    "gross_weight_usd": 1_000.0,
                    "consensus_weight_usd": 1_000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _event(
    *,
    event_id: str,
    amount0: str,
    liquidity: str = "1",
    transaction_id: str = "0xtx",
) -> dict[str, object]:
    return {
        "id": event_id,
        "amount": liquidity,
        "amount0": amount0,
        "amount1": "10",
        "origin": "0xorigin",
        "owner": "0xowner",
        "sender": "0xsender",
        "pool": {
            "id": "0xpool",
            "token0": {"id": WETH, "symbol": "WETH"},
            "token1": {"id": ENDPOINT, "symbol": "TOKEN"},
        },
        "tickLower": "-100",
        "tickUpper": "100",
        "timestamp": _timestamp("2025-01-05"),
        "transaction": {
            "id": transaction_id,
            "timestamp": _timestamp("2025-01-05"),
        },
    }


def test_pool_daily_output_retains_pool_and_unpriced_action_counts(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    candidate_day = tmp_path / "candidate_day.parquet"
    fees = tmp_path / "fees.parquet"
    prices = tmp_path / "prices.parquet"
    output = tmp_path / "pool_flow.parquet"
    support = tmp_path / "support.jsonl"
    pd.DataFrame(
        [
            {"candidate_address": WETH, "candidate_symbol": "WETH"},
            {"candidate_address": USDC, "candidate_symbol": "USDC"},
        ]
    ).to_parquet(candidate_day, index=False)
    pd.DataFrame(
        [
            {
                "pool": "0xpool",
                "token0_address": WETH,
                "token0_symbol": "WETH",
                "token1_address": ENDPOINT,
                "token1_symbol": "TOKEN",
                "fee_tier": 3000,
            }
        ]
    ).to_parquet(fees, index=False)
    _price_panel(prices)
    with gzip.open(event_dir / "uniswap_v3_mints_20250105.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(_event(event_id="mint", amount0="1")) + "\n")
        handle.write(
            json.dumps(
                _event(
                    event_id="add-only",
                    amount0="0.5",
                    transaction_id="0xadd",
                )
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                _event(
                    event_id="missing-transaction",
                    amount0="0.1",
                    transaction_id="",
                )
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                _event(
                    event_id="negative",
                    amount0="10",
                    liquidity="-1",
                    transaction_id="0xnegative",
                )
            )
            + "\n"
        )
    with gzip.open(event_dir / "uniswap_v3_burns_20250105.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(_event(event_id="burn", amount0="0")) + "\n")
        handle.write(
            json.dumps(
                _event(
                    event_id="remove-only",
                    amount0="0.25",
                    transaction_id="0xremove",
                )
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                _event(event_id="zero-burn", amount0="0", liquidity="0")
            )
            + "\n"
        )

    assert (
        run(
            output_path=output,
            support_path=support,
            event_dir=event_dir,
            candidate_day_path=candidate_day,
            fee_panel_path=fees,
            price_path=prices,
        )
        == 0
    )
    row = pd.read_parquet(output).iloc[0]
    assert row["pool"] == "0xpool"
    assert row["candidate_symbol"] == "WETH"
    assert row["candidate_side_index"] == 0
    assert row["paired_token_address"] == ENDPOINT
    assert row["fee_tier"] == 3000
    assert row["v3_add_lp_flow_usd_screened"] == pytest.approx(3_200.0)
    assert row["v3_remove_lp_flow_usd_screened"] == pytest.approx(500.0)
    assert row["v3_add_only_lp_flow_usd_screened"] == pytest.approx(1_000.0)
    assert row["v3_remove_only_lp_flow_usd_screened"] == pytest.approx(500.0)
    assert row["v3_reposition_add_lp_flow_usd_screened"] == pytest.approx(
        2_000.0
    )
    assert row["v3_add_action_events"] == 3
    assert row["v3_remove_action_events"] == 2
    assert row["v3_zero_liquidity_remove_events"] == 1
    assert row["v3_reposition_action_transactions"] == 1
    assert row["v3_add_only_action_transactions"] == 1
    assert row["v3_remove_only_action_transactions"] == 1
    assert row["v3_negative_liquidity_add_events"] == 1
    support_text = support.read_text()
    assert "pool_candidate_day" in support_text
    assert json.loads(support_text)[
        "positive_liquidity_missing_transaction_assignments"
    ] == 1


def test_pool_mode_preserves_both_candidate_sides_of_core_pool(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    prices = tmp_path / "prices.parquet"
    _price_panel(prices)
    event = _event(event_id="core-mint", amount0="1")
    event["amount1"] = "1000"
    event["pool"]["token1"] = {"id": USDC, "symbol": "USDC"}
    with gzip.open(event_dir / "uniswap_v3_mints_20250105.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(event) + "\n")
    with gzip.open(event_dir / "uniswap_v3_burns_20250105.jsonl.gz", "wt") as handle:
        handle.write("")

    flows, _support = load_raw_uniswap_v3_lp_flows(
        event_dir=event_dir,
        candidate_map={
            WETH: (WETH, "WETH"),
            USDC: (USDC, "USDC"),
        },
        price_path=prices,
        retain_pool=True,
    )

    assert len(flows) == 2
    assert set(flows["candidate_symbol"]) == {"WETH", "USDC"}
    assert set(flows["pool"]) == {"0xpool"}


def test_registry_gap_is_reported_and_bounded() -> None:
    flows = pd.DataFrame(
        [
            {
                "pool": "0xknown",
                "v3_add_lp_flow_usd_screened": 10.0,
                "v3_remove_lp_flow_usd_screened": 0.0,
            },
            {
                "pool": "0xlate",
                "v3_add_lp_flow_usd_screened": 0.5,
                "v3_remove_lp_flow_usd_screened": 0.25,
            },
        ]
    )
    registry = pd.DataFrame(
        [
            {
                "pool": "0xknown",
                "token0_address": WETH,
                "token0_symbol": "WETH",
                "token1_address": ENDPOINT,
                "token1_symbol": "TOKEN",
                "fee_tier": 3000,
            }
        ]
    )

    kept, support = attach_v3_pool_registry(flows, registry)

    assert kept["pool"].tolist() == ["0xknown"]
    assert support["missing_registry_rows"] == 1
    assert support["missing_registry_pools"] == 1
    assert support["missing_registry_gross_flow_usd"] == pytest.approx(0.75)
    with pytest.raises(ValueError, match="registry gap exceeds"):
        attach_v3_pool_registry(
            flows,
            registry,
            max_missing_rows=0,
        )
