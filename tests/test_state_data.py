from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from ddvc.state_data import (
    CODE_SOURCES,
    FAMILY_STREAMS,
    available_state_days,
    balancer_pool_family,
    normalise_cp_partition,
    normalise_multi_asset_partition,
    normalise_tick_partition,
    read_cp_partition,
    read_cp_quality,
    read_multi_asset_partition,
    read_multi_asset_quality,
    read_tick_partition,
    read_tick_quality,
    write_cp_partition,
    write_multi_asset_partition,
    write_tick_partition,
)
from scripts.build_market_state import selected_days


def swap(*, block: int | None = 10, amount0: str = "1", amount1: str = "-2") -> dict:
    transaction: object = "0xtx"
    if block is not None:
        transaction = {"id": "0xtx", "blockNumber": str(block), "timestamp": "100"}
    return {
        "id": "event",
        "transaction": transaction,
        "timestamp": "100",
        "logIndex": "4",
        "amount0": amount0,
        "amount1": amount1,
        "sqrtPriceX96": str(1 << 96),
        "tick": "0",
        "pool": {
            "id": "pool",
            "feeTier": "500",
            "tickSpacing": "10",
            "hooks": "0x0000000000000000000000000000000000000000",
            "token0": {"id": "0xa", "symbol": "A", "decimals": "18"},
            "token1": {"id": "0xb", "symbol": "B", "decimals": "6"},
        },
    }


def write_rows(root: Path, venue: str, stream: str, day: str, rows: list[dict]) -> None:
    required = next(streams[venue] for streams in FAMILY_STREAMS.values() if venue in streams)
    for required_stream, _record_type, _sign in required:
        required_path = root / venue / f"{venue}_{required_stream}_{day}.jsonl.gz"
        required_path.parent.mkdir(parents=True, exist_ok=True)
        if not required_path.exists():
            with gzip.open(required_path, "wt"):
                pass
    path = root / venue / f"{venue}_{stream}_{day}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def cp_pair() -> dict:
    return {
        "id": "pool",
        "token0": {"id": "0xa", "symbol": "A", "decimals": "18"},
        "token1": {"id": "0xb", "symbol": "B", "decimals": "6"},
    }


def cp_swap(*, block: int = 10, log_index: int = 4) -> dict:
    return {
        "id": "swap",
        "transaction": {"id": "0xtx", "blockNumber": str(block), "timestamp": "100"},
        "timestamp": "100",
        "logIndex": str(log_index),
        "amount0In": "1",
        "amount0Out": "0",
        "amount1In": "0",
        "amount1Out": "2",
        "pair": cp_pair(),
    }


def cp_snapshot(*, reserve0: str = "100", reserve1: str = "200") -> dict:
    return {
        "id": "snapshot",
        "hourStartUnix": 0,
        "reserve0": reserve0,
        "reserve1": reserve1,
        "pair": cp_pair(),
    }


class StateDataTests(unittest.TestCase):
    def test_state_engine_depends_on_record_semantics_not_fetch_orchestration(self) -> None:
        self.assertIn("src/ddvc/source_records.py", CODE_SOURCES)
        self.assertIn("src/ddvc/execution_contracts.py", CODE_SOURCES)
        self.assertIn("src/ddvc/ethereum_receipts.py", CODE_SOURCES)
        self.assertNotIn("src/ddvc/liquidity.py", CODE_SOURCES)
        self.assertNotIn("src/ddvc/fetch/raw.py", CODE_SOURCES)

    def test_builder_clamps_to_venue_genesis_and_locked_sample_end(self) -> None:
        days = selected_days("uniswap_v4", None, "20250125")
        self.assertEqual(days, ["20250124", "20250125"])

    def test_builder_calendar_keeps_days_whose_primary_stream_is_missing(self) -> None:
        self.assertEqual(
            selected_days("uniswap_v3", "20250101", "20250103"),
            ["20250101", "20250102", "20250103"],
        )

    def test_missing_required_stream_fails_partition_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "curve", "daily", "20250101", [])
            (raw / "curve" / "curve_swaps_20250101.jsonl.gz").unlink()
            _frame, quality = normalise_multi_asset_partition(raw, "curve", "20250101")
        self.assertFalse(quality.passed)
        self.assertEqual(quality.missing_required_streams, 1)

    def test_curve_partition_harmonises_token_state_and_raw_swap_amounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            pool = {
                "id": "pool",
                "symbol": "stable",
                "inputTokens": [
                    {"id": "0xa", "symbol": "A", "decimals": 18},
                    {"id": "0xb", "symbol": "B", "decimals": 6},
                ],
            }
            write_rows(
                raw,
                "curve",
                "daily",
                "20250101",
                [{"id": "state", "timestamp": "100", "inputTokenBalances": ["1000", "2000"], "pool": pool}],
            )
            write_rows(
                raw,
                "curve",
                "swaps",
                "20250101",
                [{
                    "id": "swap",
                    "hash": "0xtx",
                    "blockNumber": "10",
                    "logIndex": 4,
                    "timestamp": "99",
                    "pool": pool,
                    "tokenIn": {"id": "0xa"},
                    "tokenOut": {"id": "0xb"},
                    "amountIn": "10",
                    "amountOut": "9",
                }],
            )
            frame, quality = normalise_multi_asset_partition(raw, "curve", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(quality.snapshot_rows, 1)
        self.assertEqual(quality.swap_rows, 1)
        self.assertEqual(len(frame[frame["record_type"] == "snapshot_token"]), 2)
        trade = frame[frame["record_type"] == "swap"].iloc[0]
        self.assertEqual(trade["amount_in_raw"], "10")
        self.assertEqual(trade["provider_pool_type"], "stable")
        self.assertEqual(trade["pool_family"], "ng_or_unclassified")
        self.assertEqual(trade["invariant_family"], "ng_or_unclassified")
        self.assertFalse(trade["quote_supported"])
        self.assertEqual(
            trade["quote_unsupported_reason"],
            "pool_family_or_state_generation_not_admitted",
        )

    def test_balancer_partition_converts_human_units_and_liquidity_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            pool = {
                "id": "pool",
                "poolType": "Weighted",
                "swapFee": "0.003",
                "tokensList": ["0xa", "0xb"],
                "tokens": [
                    {"address": "0xa", "symbol": "A", "decimals": 18, "weight": "0.5"},
                    {"address": "0xb", "symbol": "B", "decimals": 6, "weight": "0.5"},
                ],
            }
            write_rows(
                raw,
                "balancer",
                "daily",
                "20250101",
                [{"id": "state", "timestamp": 100, "amounts": ["1", "2"], "pool": pool}],
            )
            write_rows(
                raw,
                "balancer",
                "swaps",
                "20250101",
                [{
                    "id": "0x" + "1" * 64 + "7",
                    "tx": "0xtx",
                    "block": "10",
                    "timestamp": 99,
                    "poolId": {"id": "pool"},
                    "tokenIn": "0xa",
                    "tokenOut": "0xb",
                    "tokenAmountIn": "134659708639.360367020044220053",
                    "tokenAmountOut": "0.2",
                }],
            )
            write_rows(
                raw,
                "balancer",
                "joins_exits",
                "20250101",
                [{
                    "id": "0x" + "2" * 64 + "8",
                    "tx": "0xjoin",
                    "block": "9",
                    "timestamp": 98,
                    "type": "Exit",
                    "amounts": ["0.01", "0.02"],
                    "pool": {"id": "pool", "tokensList": ["0xa", "0xb"]},
                }],
            )
            frame, quality = normalise_multi_asset_partition(raw, "balancer", "20250101")
        self.assertTrue(quality.passed)
        trade = frame[frame["record_type"] == "swap"].iloc[0]
        self.assertEqual(trade["amount_in_raw"], "134659708639360367020044220053")
        self.assertEqual(trade["amount_out_raw"], "200000")
        self.assertEqual(trade["provider_pool_type"], "Weighted")
        self.assertEqual(trade["pool_family"], "weighted")
        self.assertEqual(trade["invariant_family"], "weighted_geometric_mean")
        self.assertFalse(trade["quote_supported"])
        liquidity = frame[frame["record_type"] == "liquidity_token"].set_index("token_raw")
        self.assertEqual(liquidity.loc["0xa", "balance_delta_raw"], "-10000000000000000")
        self.assertEqual(liquidity.loc["0xb", "balance_delta_raw"], "-20000")

    def test_balancer_pool_type_mapping_is_exact_and_unknown_types_fail_closed(self) -> None:
        self.assertEqual(balancer_pool_family("Weighted"), "weighted")
        self.assertEqual(
            balancer_pool_family("ComposableStable"),
            "stable_or_composable_stable",
        )
        self.assertEqual(
            balancer_pool_family("LiquidityBootstrapping"),
            "dynamic_weight_or_managed",
        )
        self.assertEqual(balancer_pool_family("Weighted-ish"), "unclassified")

    def test_multi_asset_cache_invalidates_with_raw_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            pool = {
                "id": "pool",
                "symbol": "stable",
                "inputTokens": [
                    {"id": "0xa", "symbol": "A", "decimals": 18},
                    {"id": "0xb", "symbol": "B", "decimals": 6},
                ],
            }
            state = {"id": "state", "timestamp": "100", "inputTokenBalances": ["1000", "2000"], "pool": pool}
            write_rows(raw, "curve", "daily", "20250101", [state])
            write_multi_asset_partition(raw, "curve", "20250101", root=out)
            self.assertIsNotNone(read_multi_asset_quality(raw, "curve", "20250101", root=out))
            self.assertEqual(
                len(read_multi_asset_partition("curve", "20250101", root=out, raw_root=raw)),
                2,
            )
            write_rows(raw, "curve", "daily", "20250101", [state, {**state, "id": "two", "pool": {**pool, "id": "pool2"}}])
            self.assertIsNone(read_multi_asset_quality(raw, "curve", "20250101", root=out))

    def test_canonical_readers_exclude_quarantined_rows_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            pool = {
                "id": "pool",
                "symbol": "stable",
                "inputTokens": [
                    {"id": "0xa", "symbol": "A", "decimals": 18},
                    {"id": "0xb", "symbol": "B", "decimals": 6},
                ],
            }
            write_rows(
                raw,
                "curve",
                "daily",
                "20250101",
                [{"id": "state", "timestamp": "100", "inputTokenBalances": ["-1", "2"], "pool": pool}],
            )
            quality = write_multi_asset_partition(raw, "curve", "20250101", root=out)
            clean = read_multi_asset_partition("curve", "20250101", root=out, raw_root=raw)
            audited = read_multi_asset_partition(
                "curve",
                "20250101",
                root=out,
                raw_root=raw,
                include_quarantined=True,
            )
        self.assertTrue(quality.passed)
        self.assertEqual(quality.invalid_state, 1)
        self.assertTrue(clean.empty)
        self.assertEqual(len(audited), 2)

    def test_constant_product_partition_harmonises_snapshots_swaps_and_liquidity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            write_rows(raw, "uniswap_v2", "swaps", "20250101", [cp_swap()])
            mint = {
                **cp_swap(block=9, log_index=3),
                "id": "mint",
                "amount0": "3",
                "amount1": "4",
            }
            write_rows(raw, "uniswap_v2", "mints", "20250101", [mint])
            frame, quality = normalise_cp_partition(raw, "uniswap_v2", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(quality.snapshot_rows, 1)
        self.assertEqual(quality.swap_rows, 1)
        self.assertEqual(quality.liquidity_rows, 1)
        self.assertEqual(frame.loc[frame["record_type"] == "swap", "amount0_delta"].iloc[0], "1")
        self.assertEqual(frame.loc[frame["record_type"] == "swap", "amount1_delta"].iloc[0], "-2")
        self.assertEqual(frame.loc[frame["record_type"] == "liquidity", "amount0_delta"].iloc[0], "3")
        self.assertTrue(frame.loc[frame["record_type"] == "swap", "quote_supported"].iloc[0])
        self.assertEqual(set(frame["pool_family"]), {"full_range_constant_product"})
        self.assertEqual(set(frame["state_generation"]), {"constant_product_state_v2"})

    def test_constant_product_partition_rejects_conflicting_chain_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            conflicting = {**cp_swap(), "id": "other", "amount1Out": "3"}
            write_rows(raw, "uniswap_v2", "swaps", "20250101", [cp_swap(), conflicting])
            _frame, quality = normalise_cp_partition(raw, "uniswap_v2", "20250101")
        self.assertFalse(quality.passed)
        self.assertEqual(quality.conflicting_events, 1)

    def test_constant_product_nontrade_delta_updates_state_without_supporting_a_quote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            same_sign = {**cp_swap(), "amount1In": "3", "amount1Out": "0"}
            write_rows(raw, "uniswap_v2", "swaps", "20250101", [same_sign])
            incomplete = {
                **cp_swap(block=11, log_index=5),
                "id": "burn",
                "logIndex": None,
                "amount0": None,
                "amount1": None,
                "needsComplete": True,
            }
            write_rows(raw, "uniswap_v2", "burns", "20250101", [incomplete])
            frame, quality = normalise_cp_partition(raw, "uniswap_v2", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(quality.invalid_swap_sign, 1)
        self.assertEqual(quality.unsupported_state, 2)
        self.assertEqual(quality.missing_order, 0)
        same_sign_row = frame[frame["record_type"].eq("swap")].iloc[0]
        self.assertTrue(same_sign_row["usable"])
        self.assertFalse(same_sign_row["quote_supported"])
        self.assertEqual(frame["usable"].tolist().count(False), 1)

    def test_constant_product_cache_invalidates_with_raw_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            write_rows(raw, "sushiswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            write_rows(raw, "sushiswap_v2", "swaps", "20250101", [cp_swap()])
            write_cp_partition(raw, "sushiswap_v2", "20250101", root=out)
            self.assertIsNotNone(read_cp_quality(raw, "sushiswap_v2", "20250101", root=out))
            self.assertEqual(
                len(read_cp_partition("sushiswap_v2", "20250101", root=out, raw_root=raw)),
                2,
            )
            mint = {
                **cp_swap(block=9, log_index=3),
                "id": "mint",
                "amount0": "3",
                "amount1": "4",
            }
            write_rows(raw, "sushiswap_v2", "mints", "20250101", [mint])
            self.assertIsNone(read_cp_quality(raw, "sushiswap_v2", "20250101", root=out))
            with self.assertRaisesRegex(ValueError, "stale"):
                read_cp_partition(
                    "sushiswap_v2",
                    "20250101",
                    root=out,
                    raw_root=raw,
                )

    def test_sushiswap_constant_product_partition_replays_mints_and_burns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "sushiswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            write_rows(raw, "sushiswap_v2", "swaps", "20250101", [cp_swap()])
            mint = {
                **cp_swap(block=9, log_index=3),
                "id": "mint",
                "amount0": "3",
                "amount1": "4",
            }
            burn = {
                **cp_swap(block=11, log_index=5),
                "id": "burn",
                "amount0": "1",
                "amount1": "2",
                "needsComplete": False,
            }
            write_rows(raw, "sushiswap_v2", "mints", "20250101", [mint])
            write_rows(raw, "sushiswap_v2", "burns", "20250101", [burn])
            frame, quality = normalise_cp_partition(raw, "sushiswap_v2", "20250101")
        liquidity = frame[frame["record_type"].eq("liquidity")]
        self.assertTrue(quality.passed)
        self.assertEqual(quality.liquidity_rows, 2)
        self.assertEqual(liquidity["amount0_delta"].tolist(), ["3", "-1"])
        self.assertEqual(liquidity["amount1_delta"].tolist(), ["4", "-2"])

    def test_available_state_days_requires_panel_and_quality_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tick" / "uniswap_v3" / "20250101.parquet"
            path.parent.mkdir(parents=True)
            path.touch()
            self.assertEqual(available_state_days("tick", "uniswap_v3", root=root), [])
            path.with_suffix(".quality.json").write_text("{}")
            self.assertEqual(
                available_state_days("tick", "uniswap_v3", root=root),
                ["20250101"],
            )

    def test_tick_partition_normalises_exact_order_and_signed_liquidity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v4", "swaps", "20250101", [swap()])
            change = {
                **swap(block=9),
                "id": "change",
                "logIndex": "3",
                "amount": "-7",
                "tickLower": "-10",
                "tickUpper": "10",
                "pool": {"id": "pool"},
            }
            write_rows(raw, "uniswap_v4", "modify_liquidities", "20250101", [change])
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(frame["record_type"].tolist(), ["liquidity", "swap"])
        self.assertEqual(frame.iloc[0]["liquidity_delta"], "-7")
        self.assertEqual(frame.iloc[1]["block_number"], 10)
        self.assertEqual(set(frame["pool_family"]), {"vanilla_concentrated"})
        self.assertEqual(set(frame["state_generation"]), {"uniswap_v4_tick_state_v2"})
        self.assertTrue(frame.iloc[1]["quote_supported"])

    def test_v4_hooked_pool_is_usable_evidence_but_not_quote_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            hooked = swap()
            hooked["pool"]["hooks"] = "0x0000000000000000000000000000000000000001"
            write_rows(raw, "uniswap_v4", "swaps", "20250101", [hooked])
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        self.assertTrue(frame.iloc[0]["usable"])
        self.assertEqual(frame.iloc[0]["pool_family"], "hooked_or_dynamic_fee")
        self.assertFalse(frame.iloc[0]["quote_supported"])

    def test_tick_partition_quarantines_missing_order_and_same_sign_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(
                raw,
                "uniswap_v4",
                "swaps",
                "20250101",
                [swap(block=None, amount0="1", amount1="2")],
            )
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(quality.missing_order, 1)
        self.assertEqual(quality.invalid_swap_sign, 1)
        self.assertEqual(quality.quote_supported_swaps, 0)
        self.assertFalse(frame.iloc[0]["usable"])
        self.assertFalse(frame.iloc[0]["quote_supported"])

    def test_constant_product_quote_support_requires_usable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            unordered = cp_swap()
            unordered["transaction"] = {"id": "0xtx", "timestamp": "100"}
            write_rows(raw, "uniswap_v2", "swaps", "20250101", [unordered])
            frame, quality = normalise_cp_partition(raw, "uniswap_v2", "20250101")
        swap_row = frame[frame["record_type"] == "swap"].iloc[0]
        self.assertTrue(quality.passed)
        self.assertEqual(quality.missing_order, 1)
        self.assertEqual(quality.quote_supported_swaps, 0)
        self.assertFalse(swap_row["usable"])
        self.assertFalse(swap_row["quote_supported"])

    def test_liquidity_identity_needs_pool_and_order_but_not_repeated_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            change = {
                "id": "change",
                "transaction": {"id": "0xtx", "blockNumber": "9", "timestamp": "99"},
                "timestamp": "99",
                "logIndex": "3",
                "pool": {"id": "pool"},
                "amount": "7",
                "tickLower": "-10",
                "tickUpper": "10",
            }
            write_rows(raw, "uniswap_v3", "mints", "20250101", [change])
            frame, quality = normalise_tick_partition(raw, "uniswap_v3", "20250101")
        self.assertTrue(quality.passed)
        self.assertTrue(frame.iloc[0]["usable"])
        self.assertEqual(frame.iloc[0]["liquidity_delta"], "7")

    def test_partition_cache_invalidates_when_raw_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            write_rows(raw, "uniswap_v4", "swaps", "20250101", [swap()])
            write_tick_partition(raw, "uniswap_v4", "20250101", root=out)
            self.assertIsNotNone(read_tick_quality(raw, "uniswap_v4", "20250101", root=out))
            frame = read_tick_partition("uniswap_v4", "20250101", root=out, raw_root=raw)
            self.assertEqual(len(frame), 1)
            write_rows(raw, "uniswap_v4", "swaps", "20250101", [swap(), {**swap(), "id": "two", "logIndex": "5"}])
            self.assertIsNone(read_tick_quality(raw, "uniswap_v4", "20250101", root=out))


if __name__ == "__main__":
    unittest.main()
