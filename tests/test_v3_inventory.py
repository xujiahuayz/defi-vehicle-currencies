from __future__ import annotations

from eth_abi import encode as abi_encode
import pytest

from ddvc.v3_inventory import (
    EVENT_TOPICS,
    PoolStatic,
    apply_inventory_event,
    apply_inventory_events,
    balance_of_calldata,
    block_ranges,
    canonical_inventory_start_block,
    canonical_inventory_event,
    day_for_block,
    decimal_to_raw,
    decode_balance_of_result,
    decode_inventory_log,
    inventory_snapshot_rows,
    pool_static_from_graph,
)
from ddvc.v3_inventory_calendar import last_block_before_timestamp
from ddvc.quoter import Throttled
from scripts.fetch_v3_inventory_events import run_fetch_jobs


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


def test_inventory_perimeter_starts_at_first_mint_or_swap_not_first_swap() -> None:
    records = [
        {"record_type": "liquidity", "source_stream": "burns", "block_number": 8},
        {"record_type": "swap", "source_stream": "swaps", "block_number": 12},
        {"record_type": "liquidity", "source_stream": "mints", "block_number": 10},
    ]
    assert canonical_inventory_start_block(records) == 10


def static() -> PoolStatic:
    return PoolStatic(
        pool="0xpool",
        token0="0xtoken0",
        token1="0xtoken1",
        symbol0="USDC",
        symbol1="WETH",
        decimals0=6,
        decimals1=18,
    )


def test_graph_static_requires_exact_pool_and_token_identities() -> None:
    parsed = pool_static_from_graph(
        {
            "id": "0x" + "01" * 20,
            "token0": {"id": "0x" + "02" * 20, "symbol": "A", "decimals": "6"},
            "token1": {"id": "0x" + "03" * 20, "symbol": "B", "decimals": "18"},
        }
    )
    assert parsed.decimals0 == 6
    with pytest.raises(ValueError, match="exact contract identities"):
        pool_static_from_graph(
            {
                "id": "0xpool",
                "token0": {"id": "0xtoken0", "decimals": "6"},
                "token1": {"id": "0xtoken1", "decimals": "18"},
            }
        )


def test_decimal_amounts_convert_to_raw_units_without_rounding() -> None:
    assert decimal_to_raw("1.234567", 6) == 1_234_567
    assert decimal_to_raw("-0.000000000000000001", 18) == -1
    with pytest.raises(ValueError, match="not exact"):
        decimal_to_raw("0.0000001", 6)


def test_mint_and_swap_change_inventory_but_burn_does_not_transfer() -> None:
    base = {
        "pool": "0xpool",
        "block_number": 100,
        "log_index": 7,
        "tx_hash": "0xtx",
        "amount0": "1.5",
        "amount1": "2",
    }
    mint = canonical_inventory_event(
        {**base, "record_type": "liquidity", "source_stream": "mints"}, static()
    )
    swap = canonical_inventory_event(
        {
            **base,
            "log_index": 8,
            "record_type": "swap",
            "source_stream": "swaps",
            "amount0": "-0.5",
            "amount1": "0.25",
        },
        static(),
    )
    burn = canonical_inventory_event(
        {**base, "record_type": "liquidity", "source_stream": "burns"}, static()
    )
    balances: dict[str, tuple[int, int]] = {}
    assert apply_inventory_event(balances, mint) == (1_500_000, 2 * 10**18)
    assert apply_inventory_event(balances, swap) == (1_000_000, 2_250_000_000_000_000_000)
    assert burn is None


def test_inventory_checkpoint_preserves_negative_raw_balances_without_flooring() -> None:
    item = static()
    events = [
        {
            "pool": item.pool,
            "block_number": 10,
            "log_index": 1,
            "tx_hash": "0xa",
            "amount0_delta_raw": 2,
            "amount1_delta_raw": -3,
        }
    ]
    balances: dict[str, tuple[int, int]] = {}
    last: dict[str, tuple[int, int]] = {}
    counts: dict[str, int] = {}
    apply_inventory_events(balances, events, last_events=last, event_counts=counts)
    rows = inventory_snapshot_rows(
        day="20250101",
        end_block=20,
        statics={item.pool: item},
        balances=balances,
        last_events=last,
        event_counts=counts,
    )
    assert rows[0]["balance1_raw"] == "-3"
    assert rows[0]["negative_inventory"] is True
    assert rows[0]["inventory_valid"] is False


def test_day_calendar_uses_inclusive_strictly_increasing_block_cuts() -> None:
    days = ["20250101", "20250102", "20250103"]
    ends = [100, 200, 300]
    assert day_for_block(100, days, ends) == "20250101"
    assert day_for_block(101, days, ends) == "20250102"
    with pytest.raises(ValueError, match="strictly increasing"):
        day_for_block(1, days, [100, 100, 300])


def test_exact_day_cut_is_last_block_strictly_before_midnight() -> None:
    timestamps = {block: 1_000 + 12 * block for block in range(10, 31)}
    block, block_timestamp, next_timestamp = last_block_before_timestamp(
        1_241, 10, 30, timestamps.__getitem__
    )
    assert block == 20
    assert block_timestamp == 1_240
    assert next_timestamp == 1_252


def test_fetch_queue_retries_throttled_chunk_without_abandoning_other_work() -> None:
    calls: dict[tuple[int, int], int] = {}

    def fetch(lower: int, upper: int, _pools: set[str]) -> dict[str, int]:
        key = (lower, upper)
        calls[key] = calls.get(key, 0) + 1
        if key == (1, 1) and calls[key] == 1:
            raise Throttled("temporary")
        return {"raw_logs": 1, "recognized_v3_logs": 1}

    totals, failures = run_fetch_jobs(
        [(1, 1), (2, 2)],
        set(),
        workers=1,
        max_attempts=2,
        fetch=fetch,
    )
    assert totals == {"raw": 2, "recognized": 2}
    assert failures == []
    assert calls == {(1, 1): 2, (2, 2): 1}


def test_balance_of_call_and_result_are_exact_uint256() -> None:
    calldata = balance_of_calldata("0x" + "12" * 20)
    assert calldata.endswith("12" * 20)
    assert len(calldata) == 74
    assert decode_balance_of_result("0x" + "ff" * 32) == 2**256 - 1


def test_removed_inventory_log_is_rejected() -> None:
    removed = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    removed["removed"] = True
    with pytest.raises(ValueError, match="removed"):
        decode_inventory_log(removed)
