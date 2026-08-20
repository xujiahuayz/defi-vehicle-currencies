from __future__ import annotations

import gzip
import json

import pytest

from scripts.process.build_v3_internal_routing_candidate_daily import (
    load_raw_v3_internal_routing,
)


A = "0x0000000000000000000000000000000000000001"
B = "0x0000000000000000000000000000000000000002"
C = "0x0000000000000000000000000000000000000003"


def test_v3_internal_routing_matches_transaction_leg_definition(tmp_path) -> None:
    path = tmp_path / "uniswap_v3_swaps_20250101.jsonl.gz"
    rows = [
        {
            "id": "tx1#1",
            "transaction": {"id": "tx1"},
            "pool": {"token0": {"id": A}, "token1": {"id": B}},
        },
        {
            "id": "tx1#2",
            "transaction": {"id": "tx1"},
            "pool": {"token0": {"id": B}, "token1": {"id": C}},
        },
        {
            "id": "tx2#1",
            "transaction": {"id": "tx2"},
            "pool": {"token0": {"id": A}, "token1": {"id": C}},
        },
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    frame, support = load_raw_v3_internal_routing(
        event_dir=tmp_path,
        candidate_map={A: (A, "A"), B: (B, "B")},
    )
    a = frame[frame["candidate_address"].eq(A)].iloc[0]
    b = frame[frame["candidate_address"].eq(B)].iloc[0]
    assert a["candidate_tx_count"] == 2
    assert a["multi_leg_tx_count"] == 1
    assert a["internal_tx_count"] == 0
    assert b["candidate_tx_count"] == 1
    assert b["swap_leg_assignments"] == 2
    assert b["internal_tx_share"] == pytest.approx(1.0)
    assert support["transactions"] == 2
    assert support["matched_candidate_leg_assignments"] == 4
