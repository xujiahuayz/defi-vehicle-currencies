from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from ddvc.analysis.fluid_route_label_validation import (
    FLUID_SWAP_TOPIC,
    FLUID_NATIVE_ETH,
    HALF_YEARS,
    TRANSFER_TOPIC,
    decode_fluid_swap_log,
    deterministic_component_sample,
    parse_pool_constants,
    parse_complete_receipt,
    validate_fluid_leg,
    validation_summary,
)
from scripts.process.build_fluid_route_validation_sample import attach_fluid_legs


POOL = "0x" + "1" * 40
TOKEN_IN = "0x" + "2" * 40
TOKEN_OUT = "0x" + "3" * 40
TX = "0x" + "a" * 64
ROOT = Path(__file__).resolve().parents[1]


def _word(value: int) -> str:
    return f"{value:064x}"


def _topic_address(value: str) -> str:
    return "0x" + value[2:].rjust(64, "0")


def _swap_log(amount_in: int = 125_000_000, amount_out: int = 124_900_000) -> dict:
    return {
        "address": POOL,
        "log_index": 17,
        "topics": [FLUID_SWAP_TOPIC],
        "data": "0x" + _word(1) + _word(amount_in) + _word(amount_out) + _word(4),
    }


def _transfer(token: str, amount: int, index: int) -> dict:
    return {
        "address": token,
        "log_index": index,
        "topics": [
            TRANSFER_TOPIC,
            _topic_address("0x" + "5" * 40),
            _topic_address("0x" + "6" * 40),
        ],
        "data": "0x" + _word(amount),
    }


def _leg() -> dict:
    return {
        "half_year": "2025H1",
        "venue_scope": "cross_venue",
        "selection_basis": "high_value",
        "day": "20250115",
        "tx_hash": TX,
        "component_id": 0,
        "log_index": 17,
        "block_number": 22_000_000,
        "pool": POOL,
        "token_in": TOKEN_IN,
        "token_out": TOKEN_OUT,
        "amount_in": 125.0,
        "amount_out": 124.9,
    }


def _receipt(*, exact_amounts: bool = True) -> dict:
    input_amount = 125_000_000 if exact_amounts else 125_000_001
    output_amount = 124_900_000 if exact_amounts else 124_900_001
    return {
        "status": 1,
        "block_number": 22_000_000,
        "logs": [
            _transfer(TOKEN_IN, input_amount, 15),
            _transfer(TOKEN_OUT, output_amount, 16),
            _swap_log(),
        ],
    }


def _constants(*, reversed_tokens: bool = False) -> dict:
    return {
        "pool": POOL,
        "block_number": 22_000_000,
        "token0": TOKEN_OUT if reversed_tokens else TOKEN_IN,
        "token1": TOKEN_IN if reversed_tokens else TOKEN_OUT,
    }


def test_decodes_exact_fluid_swap_event() -> None:
    decoded = decode_fluid_swap_log(_swap_log())
    assert decoded == {
        "swap_zero_to_one": True,
        "amount_in_raw": 125_000_000,
        "amount_out_raw": 124_900_000,
        "recipient": "0x" + "0" * 39 + "4",
    }


def test_complete_receipt_retains_legal_zero_topic_log() -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "transactionHash": TX,
            "blockNumber": hex(22_000_000),
            "blockHash": "0x" + "f" * 64,
            "gasUsed": hex(100_000),
            "status": "0x1",
            "to": POOL,
            "from": "0x" + "5" * 40,
            "logs": [
                {
                    "address": POOL,
                    "logIndex": "0x0",
                    "topics": [],
                    "data": "0x",
                }
            ],
        },
    }
    parsed = parse_complete_receipt(TX, response, expected_block=22_000_000)
    assert parsed is not None
    assert parsed["logs"] == [
        {"address": POOL, "log_index": 0, "topics": [], "data": "0x"}
    ]


def test_pool_constants_decode_token_order() -> None:
    words = [0] * 18
    words[9] = int(TOKEN_IN, 16)
    words[10] = int(TOKEN_OUT, 16)
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": "0x" + "".join(_word(value) for value in words),
    }
    parsed = parse_pool_constants(
        POOL, response, block_number=22_000_000
    )
    assert parsed == {
        "pool": POOL,
        "block_number": 22_000_000,
        "token0": TOKEN_IN,
        "token1": TOKEN_OUT,
    }


def test_receipt_transfers_confirm_label_direction_and_amounts() -> None:
    result = validate_fluid_leg(_leg(), _receipt(), _constants())
    assert result["event_exact"] is True
    assert result["pool_identity_available"] is True
    assert result["pool_direction_exact"] is True
    assert result["transfer_tokens_observed"] is True
    assert result["exact_transfer_support"] is True
    assert result["label_confirmed"] is True
    assert result["reported_amounts_consistent"] is True
    assert result["input_decimals_inferred"] == 6
    assert result["output_decimals_inferred"] == 6
    assert result["result"] == "confirmed"


def test_pool_token_order_contradicts_reversed_route_label() -> None:
    result = validate_fluid_leg(_leg(), _receipt(), _constants(reversed_tokens=True))
    assert result["pool_identity_available"] is True
    assert result["pool_direction_exact"] is False
    assert result["label_confirmed"] is False
    assert result["result"] == "contradicted"


def test_native_eth_pool_side_confirms_the_weth_economic_label() -> None:
    constants = _constants()
    constants["token1"] = FLUID_NATIVE_ETH
    leg = _leg()
    leg["token_out"] = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    result = validate_fluid_leg(leg, _receipt(), constants)
    assert result["pool_direction_literal"] is False
    assert result["pool_direction_exact"] is True
    assert result["wrapped_native_equivalent"] is True
    assert result["label_confirmed"] is True


def test_component_sample_is_fixed_within_each_half_year_and_scope() -> None:
    rows = []
    period_day = {
        "2024H2": "20241101",
        "2025H1": "20250201",
        "2025H2": "20250801",
        "2026H1": "20260201",
    }
    sequence = 0
    for period in HALF_YEARS:
        for venue_count, venues in ((2, "fluid|uniswap_v4"), (1, "fluid")):
            for value in (10.0, 20.0, 30.0, 40.0):
                sequence += 1
                rows.append(
                    {
                        "day": period_day[period],
                        "tx_hash": f"0x{sequence:064x}",
                        "component_id": 0,
                        "component_value_usd": value,
                        "component_leg_count": 2,
                        "fluid_leg_count": 1,
                        "venue_count": venue_count,
                        "venues": venues,
                    }
                )
    sample = deterministic_component_sample(
        pd.DataFrame(rows),
        sample_counts={
            "cross_venue": {"high_value": 1, "rank_spread": 1},
            "fluid_only": {"high_value": 1, "rank_spread": 1},
        },
    )
    assert len(sample) == 16
    assert not sample["tx_hash"].duplicated().any()
    high = sample[sample["selection_basis"].eq("high_value")]
    assert set(high["component_value_usd"]) == {40.0}


def test_summary_reports_coverage_and_precision_separately() -> None:
    confirmed = validate_fluid_leg(_leg(), _receipt(), _constants())
    contradicted = validate_fluid_leg(
        _leg(), _receipt(), _constants(reversed_tokens=True)
    )
    contradicted["tx_hash"] = "0x" + "b" * 64
    missing = validate_fluid_leg(_leg(), None)
    missing["tx_hash"] = "0x" + "c" * 64
    summary = validation_summary(pd.DataFrame([confirmed, contradicted, missing]))
    overall = summary.loc[summary["scope"].eq("overall")].iloc[0]
    assert overall["sampled_fluid_legs"] == 3
    assert overall["pool_identity_testable_legs"] == 2
    assert overall["confirmed_labels"] == 1
    assert overall["pool_identity_coverage"] == 2 / 3
    assert overall["testable_label_precision"] == 0.5


def test_sample_attachment_joins_raw_pool_and_token_identity(tmp_path) -> None:
    unified = tmp_path / "unified"
    raw = tmp_path / "fluid"
    unified.mkdir()
    raw.mkdir()
    pd.DataFrame(
        [
            {
                "tx_hash": TX,
                "component_id": 0,
                "source": "fluid",
                "log_index": 17,
                "token_in": TOKEN_IN,
                "token_out": TOKEN_OUT,
            }
        ]
    ).to_parquet(unified / "20250115.parquet", index=False)
    raw_row = {
        "tx_hash": TX,
        "evt_index": 17,
        "block_number": 22_000_000,
        "pool": POOL,
        "token_sold_address": TOKEN_IN,
        "token_bought_address": TOKEN_OUT,
        "token_sold_symbol": "IN",
        "token_bought_symbol": "OUT",
        "token_sold_amount": 125.0,
        "token_bought_amount": 124.9,
        "amount_usd": 125.0,
    }
    with gzip.open(raw / "fluid_swaps_20250115.jsonl.gz", "wt") as handle:
        handle.write(json.dumps(raw_row) + "\n")
    selected = pd.DataFrame(
        [
            {
                "day": "20250115",
                "tx_hash": TX,
                "component_id": 0,
                "component_value_usd": 125.0,
                "component_leg_count": 2,
                "fluid_leg_count": 1,
                "venue_count": 2,
                "venues": "fluid|uniswap_v3",
                "half_year": "2025H1",
                "venue_scope": "cross_venue",
                "population_components_in_stratum": 10,
                "population_value_usd_in_stratum": 1_000.0,
                "selection_basis": "high_value",
                "selection_rank": 1,
            }
        ]
    )
    attached = attach_fluid_legs(selected, unified=unified, fluid_raw=raw)
    assert len(attached) == 1
    assert attached.iloc[0]["pool"] == POOL
    assert attached.iloc[0]["amount_in"] == 125.0


def test_installed_fluid_validation_result_is_exact_and_auditable() -> None:
    path = ROOT / "output" / "exhibits" / "fluid_route_label_validation.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line]
    support = next(row for row in records if row["record_type"] == "support")
    overall = next(
        row
        for row in records
        if row["record_type"] == "estimate" and row["scope"] == "overall"
    )
    cross_venue = next(
        row
        for row in records
        if row["record_type"] == "estimate"
        and row["scope"] == "venue_scope:cross_venue"
    )
    assert support["calldata_used"] is False
    assert overall["sampled_components"] == 180
    assert overall["sampled_fluid_legs"] == 245
    assert overall["confirmed_labels"] == 245
    assert overall["literal_contract_token_matches"] == 171
    assert overall["wrapped_native_equivalents"] == 74
    assert overall["testable_label_precision"] == 1.0
    assert overall["precision_wilson_95_lower"] > 0.98
    assert cross_venue["sampled_fluid_legs"] == 123
    assert cross_venue["confirmed_labels"] == 123


def test_fluid_validation_is_consumed_by_route_validation_table() -> None:
    table = (
        ROOT
        / "output"
        / "tables"
        / "route_reconstruction_exact_chain_validation.tex"
    ).read_text(encoding="utf-8")
    assert "Panel E. Fluid route labels against receipts and pool constants" in table
    assert "Overall & 180 & 245 & 100.0 & 100.0 & 100.0 & 98.5" in table
