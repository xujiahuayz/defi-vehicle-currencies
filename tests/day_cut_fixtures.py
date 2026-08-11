"""Central exact UTC-day cut fixtures for tick-state release tests."""

from __future__ import annotations

from collections.abc import Mapping

from ddvc.ethereum_day_cuts import utc_day_timestamps


def certified_day_cut(day: str, lower: int, upper: int) -> dict[str, object]:
    start_timestamp, end_timestamp = utc_day_timestamps(day)
    start_block = max(1, int(lower))
    end_block = max(start_block, int(upper))
    end_block_timestamp = (
        start_timestamp if end_block == start_block else end_timestamp - 1
    )
    observations = {
        start_block - 1: start_timestamp - 1,
        start_block: start_timestamp,
        end_block: end_block_timestamp,
        end_block + 1: end_timestamp,
    }
    return {
        "status": "complete",
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "start_block": start_block,
        "start_block_timestamp": start_timestamp,
        "end_block": end_block,
        "end_block_timestamp": end_block_timestamp,
        "before_start_block": start_block - 1,
        "before_start_block_timestamp": start_timestamp - 1,
        "after_end_block": end_block + 1,
        "after_end_block_timestamp": end_timestamp,
        "initial_lower_bracket": 0,
        "initial_upper_bracket": end_block + 1,
        "rpc_evidence": [
            {
                "request": {
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block), False],
                },
                "response": {
                    "number": hex(block),
                    "hash": "0x" + f"{block:064x}",
                    "parentHash": "0x" + f"{max(0, block - 1):064x}",
                    "timestamp": hex(timestamp),
                },
            }
            for block, timestamp in observations.items()
        ],
    }


def certified_day_cuts(
    bounds: Mapping[str, tuple[int, int]],
) -> dict[str, dict[str, object]]:
    return {
        day: certified_day_cut(day, lower, upper)
        for day, (lower, upper) in bounds.items()
    }
