from __future__ import annotations

from eth_abi import encode as abi_encode
import gzip
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

from ddvc.v3_inventory import (
    EVENT_TOPICS,
    PoolStatic,
    apply_inventory_event,
    apply_inventory_events,
    audit_inventory_chunks,
    balance_of_calldata,
    block_ranges,
    canonical_inventory_start_block,
    canonical_inventory_event,
    day_for_block,
    decimal_to_raw,
    decode_balance_of_result,
    decode_inventory_log,
    inventory_snapshot_rows,
    inventory_chunk_paths,
    pool_static_from_graph,
)
from ddvc.v3_inventory_calendar import (
    CODE_SOURCES as CALENDAR_CODE_SOURCES,
    _fetch_block_timestamp,
    last_block_before_timestamp,
)
from ddvc.quoter import Throttled
from scripts.build_v3_inventory_panel import CODE_SOURCES as PANEL_CODE_SOURCES
from scripts.audit_v3_inventory_balances import audit_sample_table
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
    assert rows[0]["replay_arithmetic_valid"] is False
    assert rows[0]["quantity_kind"] == "event_replayed_pool_inventory"
    assert rows[0]["custody_validation_status"] == "pending_historical_balance_validation"
    assert rows[0]["ownership_validation_status"] == (
        "pending_protocol_fee_ownership_reconciliation"
    )


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


def test_calendar_provenance_covers_every_semantic_dependency() -> None:
    assert set(CALENDAR_CODE_SOURCES) == {
        "src/ddvc/v3_inventory_calendar.py",
        "src/ddvc/fetch/raw.py",
        "src/ddvc/paths.py",
        "src/ddvc/quoter.py",
        "src/ddvc/runtime.py",
        "src/ddvc/state_data.py",
    }


def test_physical_inventory_cache_covers_every_semantic_dependency() -> None:
    assert set(PANEL_CODE_SOURCES) == {
        "scripts/build_v3_inventory_panel.py",
        "src/ddvc/asset_types.py",
        "src/ddvc/fetch/raw.py",
        "src/ddvc/panel_assembly.py",
        "src/ddvc/paths.py",
        "src/ddvc/runtime.py",
        "src/ddvc/state_data.py",
        "src/ddvc/v3_inventory.py",
        "src/ddvc/v3_inventory_calendar.py",
    }


def test_calendar_rpc_retry_budget_is_not_nested_inside_rpc_post() -> None:
    response = {
        "result": {
            "number": "0x64",
            "hash": "0xhash",
            "parentHash": "0xparent",
            "timestamp": "0x3e8",
        }
    }
    evidence: list[dict[str, object]] = []
    with (
        patch("ddvc.v3_inventory_calendar.rpc_post", side_effect=[Throttled(), response]) as request,
        patch("ddvc.v3_inventory_calendar.time.sleep"),
    ):
        assert _fetch_block_timestamp(100, evidence) == 1_000
    assert request.call_count == 2
    assert all(item.kwargs["retries"] == 1 for item in request.call_args_list)
    assert len(evidence) == 1


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


def test_raw_inventory_chunk_audit_reconciles_content_and_metadata() -> None:
    raw = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    raw["address"] = "0xpool"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        raw_path, meta_path = inventory_chunk_paths(100, 100, root)
        with gzip.open(raw_path, "wt") as handle:
            handle.write(json.dumps(raw) + "\n")
        meta_path.write_text(
            json.dumps(
                {
                    "status": "complete",
                    "from_block": 100,
                    "to_block": 100,
                    "event_topics": sorted(EVENT_TOPICS.values()),
                    "raw_logs": 1,
                    "recognized_v3_logs": 1,
                    "unrecognized_logs": 0,
                    "recognized_by_event": {
                        "collect": 0,
                        "flash": 0,
                        "collect_protocol": 1,
                    },
                }
            )
        )
        totals = audit_inventory_chunks([(100, 100)], root, known_pools={"0xpool"})
    assert totals == {"chunks": 1, "raw_logs": 1, "recognized_v3_logs": 1}


def test_balance_of_call_and_result_are_exact_uint256() -> None:
    calldata = balance_of_calldata("0x" + "12" * 20)
    assert calldata.endswith("12" * 20)
    assert len(calldata) == 74
    assert decode_balance_of_result("0x" + "ff" * 32) == 2**256 - 1


def test_balance_audit_sample_keeps_pool_edges_and_calendar_audit_date_value_mass() -> None:
    token0 = "0x" + "01" * 20
    token1 = "0x" + "02" * 20
    pool = "0x" + "03" * 20
    rows = []
    for day, block in (("20250101", 100), ("20250115", 200), ("20250131", 300)):
        rows.append(
            {
                "venue": "uniswap_v3",
                "day": day,
                "day_end_block": block,
                "pool": pool,
                "token0_address": token0,
                "token0_symbol": "A",
                "token0_decimals": 6,
                "token1_address": token1,
                "token1_symbol": "B",
                "token1_decimals": 18,
                "balance0_raw": "1000000",
                "balance1_raw": "1000000000000000000",
                "balance0_units": 1.0,
                "balance1_units": 1.0,
                "negative_inventory": False,
                "replay_arithmetic_valid": True,
                "quantity_kind": "event_replayed_pool_inventory",
                "custody_validation_status": "pending_historical_balance_validation",
                "ownership_validation_status": "pending_protocol_fee_ownership_reconciliation",
                "state_generation": "test",
            }
        )
    prices = [
        {"day": day, "token": token, "price_usd": price}
        for day in ("20250101", "20250115", "20250131")
        for token, price in ((token0, 1.0), (token1, 2.0))
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory_path = root / "inventory.parquet"
        price_path = root / "prices.parquet"
        pd.DataFrame(rows).to_parquet(inventory_path, index=False)
        pd.DataFrame(prices).to_parquet(price_path, index=False)
        sample = audit_sample_table(inventory_path, price_path).to_pandas()
    assert sample["day"].tolist() == ["20250101", "20250131"]
    final_reason = sample.loc[sample["day"].eq("20250131"), "sample_reason"].iloc[0]
    assert "audit_date_value_mass" in final_reason
    assert "final_observed_pool_cut" in final_reason
    assert bool(sample.loc[sample["day"].eq("20250131"), "full_valuation_support"].iloc[0])


def test_removed_inventory_log_is_rejected() -> None:
    removed = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    removed["removed"] = True
    with pytest.raises(ValueError, match="removed"):
        decode_inventory_log(removed)
