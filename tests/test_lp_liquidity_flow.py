from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.analysis.lp_liquidity_flow import (
    CausalRangeClassifier,
    Q96,
    aggregate_daily_liquidity_flow,
    allocate_candidate_event_values,
)
from scripts import build_lp_liquidity_flow_panel as builder


TOKEN_BY_SYMBOL = {symbol: token for token, symbol in VEHICLE_CANDIDATES.items()}


def row(record_type: str, *, block: int, log_index: int, **updates) -> dict:
    base = {
        "record_type": record_type,
        "event_id": f"{record_type}-{block}-{log_index}",
        "tx_hash": f"tx-{block}",
        "block_number": block,
        "log_index": log_index,
        "timestamp": block * 10,
        "pool": "pool",
        "source_stream": "swaps" if record_type == "swap" else "mints",
        "pool_family": "concentrated_liquidity",
        "invariant_family": "concentrated_liquidity",
        "state_generation": "uniswap_v3_tick_state_v2",
        "token0": TOKEN_BY_SYMBOL["WETH"],
        "token1": TOKEN_BY_SYMBOL["USDC"],
        "symbol0": "WETH",
        "symbol1": "USDC",
        "decimals0": 18,
        "decimals1": 6,
        "fee_pips": 500,
        "tick": 0,
        "sqrt_price_x96": str(Q96),
        "tick_lower": -10,
        "tick_upper": 10,
        "liquidity_delta": 100,
        "amount0": "0",
        "amount1": "1000",
        "value_usd": None,
    }
    base.update(updates)
    return base


def test_range_classification_uses_strict_upper_bound_and_prior_tick() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1, tick=10),
            row("liquidity", block=10, log_index=2, tick_lower=0, tick_upper=10),
            row("swap", block=10, log_index=3, tick=9),
            row("liquidity", block=10, log_index=4, tick_lower=0, tick_upper=10),
        ]
    )
    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )
    assert rejected.empty
    assert events["tick_before"].tolist() == [10, 9]
    assert events["range_active_before"].tolist() == [False, True]


def test_event_before_first_observed_swap_is_rejected_without_lookahead() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("liquidity", block=10, log_index=1),
            row("swap", block=10, log_index=2),
        ]
    )
    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )
    assert events.empty
    assert rejected["failure_reason"].tolist() == ["no_prior_swap_tick"]


def test_zero_liquidity_burn_is_named_as_noncapital_fee_bookkeeping() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1),
            row(
                "liquidity",
                block=10,
                log_index=2,
                source_stream="burns",
                liquidity_delta=0,
                amount0="0",
                amount1="0",
            ),
        ]
    )

    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )

    assert events.empty
    assert rejected["failure_reason"].tolist() == [
        "zero_liquidity_burn_no_capital_flow"
    ]


def test_bad_range_and_missing_delta_remain_hard_failures() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1),
            row("liquidity", block=10, log_index=2, tick_lower=10, tick_upper=10),
            row("liquidity", block=10, log_index=3, liquidity_delta=None),
        ]
    )

    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )

    assert events.empty
    assert rejected["failure_reason"].tolist() == [
        "invalid_tick_range",
        "missing_liquidity_delta",
    ]


def test_classifier_refuses_a_partition_outside_causal_order() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=2),
            row("liquidity", block=10, log_index=1),
        ]
    )
    try:
        classifier.classify_day(
            "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
        )
    except ValueError as exc:
        assert "not in causal order" in str(exc)
    else:
        raise AssertionError("unsorted canonical state was accepted")


def test_candidate_allocation_conserves_event_value_without_a_capital_proxy() -> None:
    events = pd.DataFrame(
        [
            {
                "venue": "uniswap_v3",
                "day": "20250101",
                "pool": "pool",
                "event_id": "event",
                "tx_hash": "tx",
                "block_number": 10,
                "log_index": 2,
                "event_value_usd": 1_000.0,
                "event_sign": -1,
                "token0": TOKEN_BY_SYMBOL["WETH"],
                "token1": TOKEN_BY_SYMBOL["USDC"],
                "pool_family": "concentrated_liquidity",
                "invariant_family": "concentrated_liquidity",
            }
        ]
    )
    allocated, rejected = allocate_candidate_event_values(events)
    assert rejected.empty
    assert allocated["allocated_event_value_usd"].sum() == 1_000.0
    assert allocated["signed_allocated_event_value_usd"].sum() == -1_000.0
    assert set(allocated["flow_normalization_status"]) == {
        "dollar_flow_no_capital_stock_denominator"
    }


def test_real_provider_shape_is_valued_without_a_fabricated_amount_usd() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1),
            row("liquidity", block=10, log_index=2, value_usd=None),
        ]
    )

    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )

    assert rejected.empty
    assert events["event_value_usd"].tolist() == [1_000.0]
    assert events["event_value_source"].tolist() == [
        "candidate_day_price_anchor_plus_exact_prior_v3_sqrt_price"
    ]


def test_address_decimal_registry_supports_historical_rows_without_decimals() -> None:
    classifier = CausalRangeClassifier(
        {TOKEN_BY_SYMBOL["WETH"]: 18, TOKEN_BY_SYMBOL["USDC"]: 6}
    )
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1, decimals0=None, decimals1=None),
            row("liquidity", block=10, log_index=2),
        ]
    )

    events, rejected = classifier.classify_day(
        "20250101", state, {TOKEN_BY_SYMBOL["USDC"]: 1.0}
    )

    assert rejected.empty
    assert events[["decimals0", "decimals1"]].iloc[0].tolist() == [18, 6]


def test_missing_canonical_candidate_price_is_explicitly_rejected() -> None:
    classifier = CausalRangeClassifier()
    state = pd.DataFrame(
        [
            row("swap", block=10, log_index=1),
            row("liquidity", block=10, log_index=2),
        ]
    )

    events, rejected = classifier.classify_day("20250101", state, {})

    assert events.empty
    assert rejected["failure_reason"].tolist() == [
        "missing_candidate_day_price_anchor"
    ]


def test_candidate_allocation_rejects_a_pool_without_a_candidate_side() -> None:
    events = pd.DataFrame(
        [{
            "venue": "uniswap_v3",
            "day": "20250101",
            "pool": "pool",
            "event_id": "event",
            "tx_hash": "tx",
            "block_number": 10,
            "log_index": 2,
            "event_value_usd": 1_000.0,
            "event_sign": 1,
            "token0": "0xnotcandidate0",
            "token1": "0xnotcandidate1",
            "pool_family": "concentrated_liquidity",
            "invariant_family": "concentrated_liquidity",
        }]
    )
    allocated, rejected = allocate_candidate_event_values(events)
    assert allocated.empty
    assert rejected["failure_reason"].tolist() == [
        "no_candidate_pool_side"
    ]


def test_daily_flow_perimeter_keeps_zero_event_candidate_days() -> None:
    events = pd.DataFrame(
        [{
            "day": "20250101",
            "candidate": "WETH",
            "event_id": "event",
            "allocated_event_value_usd": 100.0,
            "signed_allocated_event_value_usd": 100.0,
            "range_active_before": True,
            "range_near_active_before": True,
        }]
    )
    candidate_days = pd.DataFrame(
        [
            {
                "day": "20250101",
                "candidate": "WETH",
            },
            {
                "day": "20250102",
                "candidate": "WETH",
            },
        ]
    )
    panel = aggregate_daily_liquidity_flow(events, candidate_days)
    assert panel["net_flow_pressure"].iloc[0] == 1.0
    assert pd.isna(panel["net_flow_pressure"].iloc[1])
    assert panel["event_count"].tolist() == [1.0, 0.0]


def test_assembled_release_provenance_excludes_resumability_cache(
    monkeypatch, tmp_path: Path
) -> None:
    cache = tmp_path / "engine_test" / "events"
    cache.mkdir(parents=True)
    shard = cache / "20250101.parquet"
    shard.touch()
    output = tmp_path / "events.parquet"
    canonical = tmp_path / "canonical-input"
    stamps = []
    monkeypatch.setattr(builder, "INPUTS", [canonical])
    monkeypatch.setattr(
        builder,
        "assemble_parquet_shards",
        lambda *args, **kwargs: SimpleNamespace(rows=1),
    )
    monkeypatch.setattr(
        builder,
        "stamp",
        lambda artefact, **kwargs: stamps.append((artefact, kwargs)),
    )

    assert builder._assemble([shard], output, ("day",), "test") == 1
    assert stamps[0][1]["inputs"] == [canonical]
    assert "resumable cache events" in stamps[0][1]["notes"]
