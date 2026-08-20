from __future__ import annotations

import gzip
import json

import pandas as pd

from scripts.process.build_v3_v4_lp_origin_candidate_daily import (
    build_origin_action_panel,
)


ADDRESS = "0x0000000000000000000000000000000000000001"


def _write(path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_origin_action_builder_keeps_nonzero_named_origins(tmp_path) -> None:
    v3 = tmp_path / "v3"
    v4 = tmp_path / "v4"
    v3.mkdir()
    v4.mkdir()
    _write(
        v3 / "uniswap_v3_mints_20250101.jsonl.gz",
        [
            {
                "timestamp": 1_735_689_600,
                "origin": "0xaaa",
                "amount": "10",
                "pool": {"id": "0xpool"},
            },
            {
                "timestamp": 1_735_689_601,
                "origin": "0xbbb",
                "amount": "0",
                "pool": {"id": "0xpool"},
            },
        ],
    )
    _write(
        v4 / "uniswap_v4_modify_liquidities_20250101.jsonl.gz",
        [
            {
                "timestamp": 1_735_689_600,
                "origin": "0xccc",
                "amount": "12",
                "pool": {"token0": {"id": ADDRESS}, "token1": {"id": "0x2"}},
            },
            {
                "timestamp": 1_735_689_601,
                "origin": "",
                "amount": "12",
                "pool": {"token0": {"id": ADDRESS}, "token1": {"id": "0x2"}},
            },
        ],
    )
    panel, support = build_origin_action_panel(
        v3_event_dir=v3,
        v4_event_dir=v4,
        candidate_map={ADDRESS: (ADDRESS, "AAA")},
        pool_candidates=pd.DataFrame(
            [{"pool": "0xpool", "candidate_address": ADDRESS, "candidate_symbol": "AAA"}]
        ),
    )
    assert set(panel["protocol"]) == {"v3", "v4"}
    assert panel.set_index("protocol")["origin"].to_dict() == {
        "v3": "0xaaa",
        "v4": "0xccc",
    }
    assert support["protocols"]["v3"]["candidate_event_assignments"] == 2
    assert support["protocols"]["v3"]["nonzero_candidate_event_assignments"] == 1
    assert support["protocols"]["v4"]["blank_origin_assignments"] == 1
