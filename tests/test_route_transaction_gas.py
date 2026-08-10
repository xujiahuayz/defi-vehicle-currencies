from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.ethereum_receipts import parse_receipt
from ddvc.gas import load_route_transaction_gas
from scripts.process import build_route_gas_units, build_route_transaction_gas
from scripts.process.build_route_transaction_gas import receipt_panel, route_receipt_requests


def receipt(tx_hash: str, block_number: int, gas_price: int) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
        "gas_used": 120_000,
        "status": 1,
        "tx_to": "0xrouter",
        "tx_from": "0xsender",
        "effective_gas_price_wei": gas_price,
    }


def test_route_requests_deduplicate_exact_transaction_identity(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame(
        {"tx": ["0xABC", "0xabc", "0xdef"], "block": [10, 10, 11]}
    ).to_parquet(source, index=False)
    requests = route_receipt_requests(source)
    assert requests.to_dict("records") == [
        {"tx_hash": "0xabc", "block_number": 10},
        {"tx_hash": "0xdef", "block_number": 11},
    ]


def test_receipt_builders_share_one_canonical_cache() -> None:
    assert build_route_gas_units.CACHE == build_route_transaction_gas.CACHE


def test_route_requests_reject_conflicting_transaction_blocks(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame({"tx": ["0xabc", "0xabc"], "block": [10, 11]}).to_parquet(
        source, index=False
    )
    with pytest.raises(ValueError, match="multiple Ethereum blocks"):
        route_receipt_requests(source)


def test_receipt_panel_marks_zero_effective_price_unsupported(tmp_path: Path) -> None:
    requests = pd.DataFrame(
        {"tx_hash": ["0xabc", "0xdef"], "block_number": [10, 11]}
    )
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000), receipt("0xdef", 11, 0)],
        requests,
    )
    assert panel["gas_price_supported"].tolist() == [True, False]
    assert panel["gas_gwei"].iloc[0] == 10.0
    assert pd.isna(panel["gas_gwei"].iloc[1])
    assert panel["gas_price_support_reason"].iloc[1] == "zero_effective_price_private_payment_possible"

    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(
        path,
        required_routes=pd.DataFrame(
            {"tx": ["0xabc", "0xdef"], "block": [10, 11]}
        ),
    )
    assert len(loaded) == 2


def test_receipt_parser_enforces_requested_block() -> None:
    response = {
        "result": {
            "transactionHash": "0xabc",
            "blockNumber": "0xa",
            "gasUsed": "0x1d4c0",
            "status": "0x1",
            "effectiveGasPrice": "0x2540be400",
        }
    }
    assert parse_receipt("0xabc", response, expected_block=10)["block_number"] == 10
    with pytest.raises(ValueError, match="block differs"):
        parse_receipt("0xabc", response, expected_block=11)
