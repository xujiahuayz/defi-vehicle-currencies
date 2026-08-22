from __future__ import annotations

from eth_abi import encode as abi_encode
import pandas as pd

from ddvc.analysis.v4_route_label_validation import (
    decimal_to_raw,
    event_validation_counts,
    exact_swap,
    initialize_registry,
    label_frame,
    pooled_metric_rows,
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
from scripts.analyze.run_v4_route_label_validation import (
    _write_jsonl,
    canonical_output_frame,
    merge_shard_outputs,
    observed_v4_only_routes,
)


POOL_A = "0x" + "a" * 64
POOL_B = "0x" + "b" * 64
TOKEN_A = "0x" + "1" * 40
TOKEN_B = "0x" + "2" * 40
TOKEN_C = "0x" + "3" * 40
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
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
            "token_out": USDC,
            "amount0": 1,
            "amount1": -1,
        },
        {
            "transaction_hash": TX,
            "log_index": 4,
            "token_in": USDC,
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
        "exact_two_leg_inclusion",
    }
    assert all(row["precision"] == 1 for row in rows)
    assert all(row["recall"] == 1 for row in rows)
    assert all(row["scope_transactions"] == 1 for row in rows)
    assert all(row["provider_label_transactions"] == 1 for row in rows)
    assert all(row["exact_label_transactions"] == 1 for row in rows)
    assert all(row["union_label_transactions"] == 1 for row in rows)
    assert all(row["exact_match_transactions"] == 1 for row in rows)
    assert all(row["unconditional_exact_match_share"] == 1 for row in rows)
    assert all(row["conditional_exact_match_share"] == 1 for row in rows)


def test_empty_route_labels_do_not_count_as_matched_transactions() -> None:
    empty = label_frame([])
    rows, mismatch = route_validation_counts(
        empty,
        empty,
        day="2026-01-01",
        transactions={TX},
    )
    assert not mismatch
    assert all(row["scope_transactions"] == 1 for row in rows)
    assert all(row["provider_label_transactions"] == 0 for row in rows)
    assert all(row["exact_label_transactions"] == 0 for row in rows)
    assert all(row["union_label_transactions"] == 0 for row in rows)
    assert all(row["exact_match_transactions"] == 0 for row in rows)
    assert all(row["unconditional_exact_match_share"] == 0 for row in rows)
    assert all(row["conditional_exact_match_share"] is None for row in rows)


def test_pooled_route_metrics_preserve_scope_and_both_denominators() -> None:
    daily = [
        {
            "record_type": "route_label",
            "dimension": "endpoint_pair",
            "true_positive": 7,
            "provider_assignments": 8,
            "exact_assignments": 9,
            "scope_transactions": 10,
            "provider_label_transactions": 8,
            "exact_label_transactions": 9,
            "union_label_transactions": 9,
            "exact_match_transactions": 7,
        },
        {
            "record_type": "route_label",
            "dimension": "endpoint_pair",
            "true_positive": 2,
            "provider_assignments": 2,
            "exact_assignments": 2,
            "scope_transactions": 5,
            "provider_label_transactions": 2,
            "exact_label_transactions": 2,
            "union_label_transactions": 2,
            "exact_match_transactions": 2,
        },
    ]
    pooled = pooled_metric_rows(daily)[0]
    assert pooled["scope_transactions"] == 15
    assert pooled["provider_label_transactions"] == 10
    assert pooled["exact_label_transactions"] == 11
    assert pooled["union_label_transactions"] == 11
    assert pooled["exact_match_transactions"] == 9
    assert pooled["unconditional_exact_match_share"] == 9 / 15
    assert pooled["conditional_exact_match_share"] == 9 / 11


def test_canonical_output_is_byte_stable_across_execution_metadata(tmp_path) -> None:
    logical = [
        {
            "record_type": "support",
            "covered_days": 1,
            "runtime_seconds": 9.2,
            "parallel_shard_wall_seconds": 3.4,
            "source_shards": ["shard-b", "shard-a"],
        },
        {
            "record_type": "event_label",
            "day": "2026-01-01",
            "dimension": "event_identity",
            "true_positive": 1,
        },
    ]
    alternate = [
        {**logical[0], "runtime_seconds": 1.1, "source_shards": ["serial"]},
        logical[1],
    ][::-1]
    first = canonical_output_frame(logical)
    second = canonical_output_frame(alternate)
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    _write_jsonl(first, first_path)
    _write_jsonl(second, second_path)
    assert first_path.read_bytes() == second_path.read_bytes()
    assert "runtime_seconds" not in first
    assert "parallel_shard_wall_seconds" not in first
    assert "source_shards" not in first


def test_parallel_shard_merge_matches_canonical_sequential_output(tmp_path) -> None:
    def metric(day: str, matches: int) -> dict[str, object]:
        return {
            "record_type": "route_label",
            "day": day,
            "dimension": "endpoint_pair",
            "true_positive": matches,
            "provider_assignments": 2,
            "exact_assignments": 2,
            "precision": matches / 2,
            "recall": matches / 2,
            "scope_transactions": 3,
            "provider_label_transactions": 2,
            "exact_label_transactions": 2,
            "union_label_transactions": 2,
            "exact_match_transactions": matches,
            "unconditional_exact_match_share": matches / 3,
            "conditional_exact_match_share": matches / 2,
        }

    def support(day: str, exact_initializes: int) -> dict[str, object]:
        return {
            "record_type": "support",
            "requested_start": day,
            "requested_end": day,
            "requested_days": 1,
            "covered_days": 1,
            "skipped_days": 0,
            "first_covered_day": day,
            "last_covered_day": day,
            "first_skipped_day": None,
            "exact_initializes": exact_initializes,
            "provider_swaps": 10,
            "exact_swaps": 10,
            "provider_zero_amount_swaps": 0,
            "exact_zero_amount_swaps": 0,
            "raw_amount_comparable_swaps": 10,
            "v4_touch_observed_transactions": 4,
            "v4_only_observed_transactions": 3,
            "route_scope": "observed_v4_only_transactions",
            "route_provider_source": "data/unified/{YYYYMMDD}.parquet",
            "cross_venue_scope": "v4_leg_only_no_full_route_certification",
            "poolmanager_direction_rule": "negative_delta_is_input_positive_delta_is_output",
            "provider_amount_sign_mapping": "provider_amount_equals_negative_poolmanager_delta",
            "owned_exact_log_chunks": 2,
        }

    first_metric = metric("2026-01-01", 2)
    second_metric = metric("2026-01-02", 1)
    first_support = support("2026-01-01", 10)
    second_support = support("2026-01-02", 11)
    first_path = tmp_path / "shard-1.jsonl"
    second_path = tmp_path / "shard-2.jsonl"
    _write_jsonl(pd.DataFrame([first_metric, first_support]), first_path)
    _write_jsonl(pd.DataFrame([second_metric, second_support]), second_path)

    merged_path = tmp_path / "merged.jsonl"
    merged = merge_shard_outputs(
        [second_path, first_path], output=merged_path, mismatch_limit=50
    )
    pooled = merged[merged["record_type"].eq("pooled_route_label")].iloc[0]
    assert int(pooled["scope_transactions"]) == 6
    assert int(pooled["exact_match_transactions"]) == 3
    assert pooled["unconditional_exact_match_share"] == 0.5
    merged_support = merged[merged["record_type"].eq("support")].iloc[0]
    assert int(merged_support["requested_days"]) == 2
    assert int(merged_support["exact_initializes"]) == 11

    expected_support = {
        **first_support,
        "requested_end": "2026-01-02",
        "requested_days": 2,
        "covered_days": 2,
        "last_covered_day": "2026-01-02",
        "exact_initializes": 11,
        "provider_swaps": 20,
        "exact_swaps": 20,
        "raw_amount_comparable_swaps": 20,
        "v4_touch_observed_transactions": 8,
        "v4_only_observed_transactions": 6,
    }
    expected = canonical_output_frame(
        [
            first_metric,
            second_metric,
            *pooled_metric_rows([first_metric, second_metric]),
            expected_support,
        ]
    )
    expected_path = tmp_path / "expected.jsonl"
    _write_jsonl(expected, expected_path)
    assert merged_path.read_bytes() == expected_path.read_bytes()


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
