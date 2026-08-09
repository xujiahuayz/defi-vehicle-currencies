from __future__ import annotations

from eth_abi import encode as abi_encode

from ddvc.v3_inventory import EVENT_TOPICS, decode_inventory_log
from scripts.fetch_v3_inventory_events import block_ranges


def log(event: str, values: list[int], types: list[str]) -> dict:
    return {
        "address": "0xpool",
        "blockNumber": "0x64",
        "logIndex": "0x7",
        "transactionHash": "0xtx",
        "topics": [EVENT_TOPICS[event]],
        "data": "0x" + abi_encode(types, values).hex(),
    }


def test_collect_and_protocol_collection_reduce_physical_inventory() -> None:
    collect = log(
        "collect",
        ["0x" + "00" * 20, 11, 13],
        ["address", "uint128", "uint128"],
    )
    protocol = log("collect_protocol", [17, 19], ["uint128", "uint128"])
    assert decode_inventory_log(collect)["amount0_delta_raw"] == -11
    assert decode_inventory_log(collect)["amount1_delta_raw"] == -13
    assert decode_inventory_log(protocol)["amount0_delta_raw"] == -17
    assert decode_inventory_log(protocol)["amount1_delta_raw"] == -19


def test_flash_inventory_delta_is_paid_less_borrowed() -> None:
    flash = log(
        "flash",
        [100, 200, 103, 207],
        ["uint256", "uint256", "uint256", "uint256"],
    )
    decoded = decode_inventory_log(flash)
    assert decoded["amount0_delta_raw"] == 3
    assert decoded["amount1_delta_raw"] == 7


def test_block_chunks_cover_the_perimeter_once() -> None:
    assert block_ranges(10, 25, 6) == [(10, 11), (12, 17), (18, 23), (24, 25)]
