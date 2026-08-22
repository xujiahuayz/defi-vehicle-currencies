from __future__ import annotations

from eth_abi import encode as abi_encode
import pandas as pd

from ddvc.analysis.v4_route_label_validation import (
    decimal_to_raw,
    event_validation_counts,
    exact_swap,
    initialize_registry,
    label_frame,
    provider_swap,
    provider_swap_is_directional,
    route_validation_counts,
)
from ddvc.v4_contract import (
    UNISWAP_V4_INITIALIZE_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_SWAP_TOPIC,
    decode_v4_state_event_identity,
    validate_v4_provider_event_identity,
)
from scripts.analyze.run_v4_route_label_validation import observed_v4_only_routes


POOL_A = "0x" + "a" * 64
POOL_B = "0x" + "b" * 64
TOKEN_A = "0x" + "1" * 40
TOKEN_B = "0x" + "2" * 40
TOKEN_C = "0x" + "3" * 40
SENDER = "0x" + "4" * 40
TX = "0x" + "5" * 64


def topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address[2:]


def chain_record(*, topics: list[str], data: bytes, log: int, block: int = 10) -> dict:
    return {
        "address": UNISWAP_V4_POOL_MANAGER_ADDRESS,
        "block_number": block,
        "block_hash": "0x" + "6" * 64,
        "transaction_hash": TX,
        "transaction_index": 2,
        "log_index": log,
        "topics": topics,
        "data": "0x" + data.hex(),
        "removed": False,
    }


def initialize(pool: str, token0: str, token1: str, *, log: int) -> dict:
    return chain_record(
        topics=[
            UNISWAP_V4_INITIALIZE_TOPIC,
            pool,
            topic_address(token0),
            topic_address(token1),
        ],
        data=abi_encode(
            ["uint24", "int24", "address", "uint160", "int24"],
            [3000, 60, "0x" + "0" * 40, 2**96, 0],
        ),
        log=log,
        block=1,
    )


def swap(pool: str, amount0: int, amount1: int, *, log: int) -> dict:
    return chain_record(
        topics=[UNISWAP_V4_SWAP_TOPIC, pool, topic_address(SENDER)],
        data=abi_encode(
            ["int128", "int128", "uint160", "uint128", "int24", "uint24"],
            [amount0, amount1, 2**96, 10**12, 0, 3000],
        ),
        log=log,
    )


def provider(pool: str, token0: str, token1: str, amount0: str, amount1: str, *, log: int) -> dict:
    return {
        "id": f"{TX}-{log}",
        "transaction": {"id": TX, "blockNumber": "10", "timestamp": "2"},
        "timestamp": "2",
        "logIndex": str(log),
        "amount0": amount0,
        "amount1": amount1,
        "amountUSD": "100",
        "pool": {
            "id": pool,
            "token0": {"id": token0, "symbol": "A", "decimals": "6"},
            "token1": {"id": token1, "symbol": "B", "decimals": "6"},
        },
    }


def test_decimal_to_raw_is_exact() -> None:
    assert decimal_to_raw("1.234567", 6) == 1_234_567
    assert decimal_to_raw("-5e-6", 6) == -5
    try:
        decimal_to_raw("0.0000001", 6)
    except ValueError as error:
        assert "exact raw-token integer" in str(error)
    else:
        raise AssertionError("non-integral raw amount passed")


def test_zero_amount_swap_has_no_route_direction() -> None:
    row = provider(POOL_A, TOKEN_A, TOKEN_B, "0", "0", log=3)
    assert not provider_swap_is_directional(row)


def test_initialize_and_provider_amounts_define_independent_direction() -> None:
    pools = initialize_registry([initialize(POOL_A, TOKEN_A, TOKEN_B, log=1)])
    exact = exact_swap(swap(POOL_A, 1_000_000, -2_000_000, log=3), pools)
    observed = provider_swap(provider(POOL_A, TOKEN_A, TOKEN_B, "-1", "2", log=3))
    assert exact["token_in"] == observed["token_in"] == TOKEN_B
    assert exact["token_out"] == observed["token_out"] == TOKEN_A
    rows, mismatch = event_validation_counts([observed], [exact])
    assert not mismatch
    assert all(row["precision"] == 1 for row in rows)
    assert all(row["recall"] == 1 for row in rows)


def test_provider_payload_validator_rejects_initialize_explicitly() -> None:
    exact = decode_v4_state_event_identity(
        initialize(POOL_A, TOKEN_A, TOKEN_B, log=1), "initialize"
    )
    row = {
        "transaction": {"id": TX, "blockNumber": "1"},
        "logIndex": "1",
        "pool": {"id": POOL_A},
    }
    try:
        validate_v4_provider_event_identity(row, exact)
    except ValueError as error:
        assert "does not accept Initialize" in str(error)
    else:
        raise AssertionError("provider payload validator accepted Initialize")


def test_route_metrics_separate_endpoint_intermediary_and_leg_order() -> None:
    provider_swaps = [
        {
            "transaction_hash": TX,
            "log_index": 3,
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount0": 1,
            "amount1": -1,
        },
        {
            "transaction_hash": TX,
            "log_index": 4,
            "token_in": TOKEN_B,
            "token_out": TOKEN_C,
            "amount0": 1,
            "amount1": -1,
        },
    ]
    exact_swaps = [dict(row) for row in provider_swaps]
    provider_frame = label_frame(provider_swaps)
    exact_frame = label_frame(exact_swaps)
    rows, mismatch = route_validation_counts(
        provider_frame,
        exact_frame,
        day="2026-01-01",
        transactions={TX},
    )
    assert not mismatch
    assert {row["dimension"] for row in rows} == {
        "endpoint_pair",
        "intermediary_identity",
        "leg_order",
    }
    assert all(row["precision"] == 1 for row in rows)
    assert all(row["recall"] == 1 for row in rows)


def test_empty_route_labels_do_not_count_as_matched_transactions() -> None:
    empty = label_frame([])
    rows, mismatch = route_validation_counts(
        empty,
        empty,
        day="2026-01-01",
        transactions={TX},
    )
    assert not mismatch
    assert all(row["transactions"] == 0 for row in rows)
    assert all(row["exact_match_transactions"] == 0 for row in rows)
    assert all(row["exact_match_share"] is None for row in rows)


def test_route_provider_side_comes_from_published_unified_rows(tmp_path) -> None:
    second_tx = "0x" + "7" * 64
    rows = [
        {
            "transaction_hash": TX,
            "log_index": 3,
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount0": 1,
            "amount1": -1,
        },
        {
            "transaction_hash": second_tx,
            "log_index": 4,
            "token_in": TOKEN_A,
            "token_out": TOKEN_B,
            "amount0": 1,
            "amount1": -1,
        },
    ]
    frame = label_frame(rows)
    other = frame[frame["tx_hash"].eq(second_tx)].copy()
    other["source"] = "uniswap_v3"
    frame = pd.concat([frame, other], ignore_index=True)
    root = tmp_path / "data"
    (root / "unified").mkdir(parents=True)
    frame.to_parquet(root / "unified" / "20260101.parquet", index=False)
    published, only, touched = observed_v4_only_routes(root, "2026-01-01")
    assert touched == 2
    assert only == {TX}
    assert set(published["tx_hash"]) == {TX}


def test_chain_only_swap_lowers_event_recall() -> None:
    pools = initialize_registry([initialize(POOL_A, TOKEN_A, TOKEN_B, log=1)])
    observed = provider_swap(provider(POOL_A, TOKEN_A, TOKEN_B, "-1", "2", log=3))
    exact = [
        exact_swap(swap(POOL_A, 1_000_000, -2_000_000, log=3), pools),
        exact_swap(swap(POOL_A, 2_000_000, -3_000_000, log=4), pools),
    ]
    rows, mismatch = event_validation_counts([observed], exact)
    identity = next(row for row in rows if row["dimension"] == "event_identity")
    assert identity["precision"] == 1
    assert identity["recall"] == 0.5
    example = next(row for row in mismatch if row["reason"] == "chain_only")
    assert example["exact_pool"] == POOL_A
    assert example["exact_direction"] == f"{TOKEN_B}->{TOKEN_A}"
    assert example["exact_block"] == 10
    assert example["exact_provider_sign_amount0_raw"] == "-2000000"
    assert example["exact_provider_sign_amount1_raw"] == "3000000"


def test_raw_amount_recall_includes_decimal_coverage() -> None:
    pools = initialize_registry([initialize(POOL_A, TOKEN_A, TOKEN_B, log=1)])
    exact = exact_swap(swap(POOL_A, 1_000_000, -2_000_000, log=3), pools)
    observed = provider_swap(provider(POOL_A, TOKEN_A, TOKEN_B, "-1", "2", log=3))
    observed["raw_amount_comparable"] = False
    observed["amount0"] = None
    observed["amount1"] = None
    rows, mismatch = event_validation_counts([observed], [exact])
    amounts = next(row for row in rows if row["dimension"] == "raw_amount_identity")
    assert amounts["provider_assignments"] == 0
    assert amounts["exact_assignments"] == 1
    assert amounts["precision"] is None
    assert amounts["recall"] == 0
    assert mismatch[0]["reason"] == "raw_amount_unavailable"
