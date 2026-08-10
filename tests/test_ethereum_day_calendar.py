from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import scripts.build_ethereum_day_calendar as calendar_builder


def _evidence(block: int, timestamp: int) -> dict[str, object]:
    return {
        "request": {
            "jsonrpc": "2.0",
            "id": 1,
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


def _v3_cut(day: str, end_block: int, end_timestamp: int) -> dict[str, object]:
    target = int(
        (
            datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        ).timestamp()
    )
    return {
        "status": "complete",
        "day": day,
        "target_timestamp": target,
        "day_end_block": end_block,
        "day_end_block_timestamp": end_timestamp,
        "next_block": end_block + 1,
        "next_block_timestamp": target,
        "initial_lower_bracket": end_block - 10,
        "resolved_upper_bracket": end_block + 1,
        "rpc_evidence": [
            _evidence(end_block, end_timestamp),
            _evidence(end_block + 1, target),
        ],
    }


def test_adjacent_v3_cuts_promote_to_a_chain_wide_utc_day(tmp_path, monkeypatch) -> None:
    cut_root = tmp_path / "v3-cuts"
    bound_root = tmp_path / "bounds"
    cut_root.mkdir()
    day = "20250115"
    previous_day = "20250114"
    start = int(datetime(2025, 1, 15, tzinfo=timezone.utc).timestamp())
    end = start + 86_400
    (cut_root / f"{previous_day}.json").write_text(
        json.dumps(_v3_cut(previous_day, 99, start - 1))
    )
    (cut_root / f"{day}.json").write_text(
        json.dumps(_v3_cut(day, 199, end - 1))
    )
    monkeypatch.setattr(calendar_builder, "RAW_DAY_CUT_ROOT", cut_root)
    monkeypatch.setattr(calendar_builder, "RAW_DAY_BOUND_ROOT", bound_root)

    record = calendar_builder.promote_adjacent_v3_cuts(day)

    assert record is not None
    assert record["start_block"] == 100
    assert record["end_block"] == 199
    assert record["promoted_from"] == "uniswap_v3_inventory_day_cuts"
    assert (bound_root / f"{day}.json").is_file()


def test_graph_metadata_is_only_an_upper_search_bracket(tmp_path, monkeypatch) -> None:
    graph_root = tmp_path / "thegraph"
    for venue, upper in (("uniswap_v1", 100), ("uniswap_v2", 120)):
        venue_root = graph_root / venue
        venue_root.mkdir(parents=True)
        (venue_root / f"{venue}_meta_20200101.json").write_text(
            json.dumps({"head_block_at_fetch": upper})
        )
    monkeypatch.setattr(calendar_builder, "GRAPH_ROOT", graph_root)

    assert calendar_builder.graph_head_upper("20200101") == 120
