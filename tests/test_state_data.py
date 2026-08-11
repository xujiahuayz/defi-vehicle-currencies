from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.graph_event_order import EventOrderCorrections, SCHEMA_VERSION as EVENT_ORDER_SCHEMA
from ddvc.state_data import (
    CODE_SOURCES,
    FAMILY_STREAMS,
    STATE_GENERATIONS,
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
    tick_scientific_support,
    write_cp_partition,
    write_multi_asset_partition,
    write_tick_partition,
)
from ddvc.tick_state_events import TickInitialization, certificate_identity_sha256, state_event_generation, write_daily_initializations, write_daily_v4_state_events
from day_cut_fixtures import certified_day_cuts


def initialization_certificate(venue: str) -> dict[str, object]:
    certificate = {"status": "pass", "generation": state_event_generation(venue), "venue": venue, "precedence_status": "pass"}
    certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
    return certificate
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
    write_daily_initializations(
        venue,
        [],
        day_cuts=certified_day_cuts({day: (0, 1)}),
        token_metadata={},
        raw_root=root,
        generation_certificate=initialization_certificate(venue),
    )
    path = root / venue / f"{venue}_{stream}_{day}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def write_v4_exact_rows(root: Path, day: str, rows: list[dict]) -> None:
    pool_rows = {str(row["pool"]["id"]): row for row in rows if (row.get("pool") or {}).get("token0")}
    initializations = []
    metadata: dict[str, tuple[str, int]] = {}
    for index, (pool_id, row) in enumerate(pool_rows.items(), start=1):
        pool = row["pool"]
        status = "hooks" if pool["hooks"] != "0x" + "0" * 40 else None
        initializations.append(TickInitialization(
            venue="uniswap_v4", pool=pool_id,
            token0=pool["token0"]["id"], token1=pool["token1"]["id"],
            fee_pips=int(pool["feeTier"]), tick_spacing=int(pool["tickSpacing"]), hooks=pool["hooks"],
            sqrt_price_x96=1 << 96, tick=0, block_number=8, block_hash="0x" + "1" * 64,
            transaction_hash="0x" + f"{index:064x}", transaction_index=index, log_index=index,
            quote_supported=status is None, quote_unsupported_reason=status,
        ))
        for token in (pool["token0"], pool["token1"]):
            metadata[token["id"]] = (token["symbol"], int(token["decimals"]))
    exact = []
    for row in rows:
        pool_id = str(row["pool"]["id"])
        transaction = row.get("transaction") or {}
        common = {
            "kind": "modify_liquidity" if row.get("tickLower") is not None else "swap",
            "pool": pool_id,
            "block_number": int(transaction["blockNumber"]),
            "block_hash": "0x" + "2" * 64,
            "transaction_hash": transaction["id"],
            "transaction_index": 0,
            "log_index": int(row["logIndex"]),
        }
        if common["kind"] == "swap":
            common.update(amount0=int(row["amount0"]), amount1=int(row["amount1"]), sqrt_price_x96=int(row["sqrtPriceX96"]), liquidity=1, tick=int(row["tick"]), fee=int(pool_rows[pool_id]["pool"]["feeTier"]))
        else:
            common.update(tick_lower=int(row["tickLower"]), tick_upper=int(row["tickUpper"]), liquidity_delta=int(row["amount"]), salt="0x" + "0" * 64)
        exact.append(common)
    certificate = initialization_certificate("uniswap_v4")
    certificate.update(exact_modify_liquidity_events=sum(row["kind"] == "modify_liquidity" for row in exact), exact_swap_events=sum(row["kind"] == "swap" for row in exact))
    certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
    cuts = certified_day_cuts({day: (0, 20)})
    write_daily_initializations("uniswap_v4", initializations, day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=certificate)
    write_daily_v4_state_events(exact, initializations, day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=certificate)


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
    def test_v4_scientific_support_is_explicit_and_never_inferred_from_empty_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            marker = root.parent / "ethereum" / "tick_state_events" / "daily" / "uniswap_v4" / "20250101.jsonl.meta.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({"status": "complete", "venue": "uniswap_v4", "day": "20250101", "scientific_support": False}))
            self.assertFalse(tick_scientific_support(root, "uniswap_v4", "20250101"))
            self.assertTrue(tick_scientific_support(root, "uniswap_v3", "20250101"))

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

    def test_cp_and_tick_normalizers_share_the_corrected_provider_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_rows(raw, "uniswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            write_rows(raw, "uniswap_v2", "swaps", "20250101", [cp_swap()])
            cp_action = {
                "action": "correction",
                "schema_version": EVENT_ORDER_SCHEMA,
                "venue": "uniswap_v2",
                "stream": "swaps",
                "event_id": "swap",
                "tx_hash": "0xtx",
                "pool": "pool",
                "block_number": 10,
                "provider_log_index": 4,
                "provider_occurrence": 0,
                "chain_log_index": 14,
                "amount0_in_override": "3",
                "amount1_in_override": "0",
                "amount0_out_override": "0",
                "amount1_out_override": "4",
            }
            with patch(
                "ddvc.state_data.load_event_order_corrections",
                return_value=(EventOrderCorrections([cp_action]), []),
            ):
                cp_frame, cp_quality = normalise_cp_partition(
                    raw,
                    "uniswap_v2",
                    "20250101",
                )

            write_rows(raw, "uniswap_v3", "swaps", "20250101", [swap()])
            tick_action = {
                "action": "correction",
                "schema_version": EVENT_ORDER_SCHEMA,
                "venue": "uniswap_v3",
                "stream": "swaps",
                "event_id": "event",
                "tx_hash": "0xtx",
                "pool": "pool",
                "block_number": 10,
                "provider_log_index": 4,
                "provider_occurrence": 0,
                "chain_log_index": 14,
                "amount0_override": "3",
                "amount1_override": "-4",
                "sqrt_price_x96_override": 1 << 96,
                "tick_override": 0,
            }
            with patch(
                "ddvc.state_data.load_event_order_corrections",
                return_value=(EventOrderCorrections([tick_action]), []),
            ):
                tick_frame, tick_quality = normalise_tick_partition(
                    raw,
                    "uniswap_v3",
                    "20250101",
                )

        cp_trade = cp_frame.loc[cp_frame["record_type"] == "swap"].iloc[0]
        tick_trade = tick_frame.loc[tick_frame["record_type"] == "swap"].iloc[0]
        self.assertTrue(cp_quality.passed)
        self.assertTrue(tick_quality.passed)
        self.assertEqual(int(cp_trade["log_index"]), 14)
        self.assertEqual(int(tick_trade["log_index"]), 14)
        self.assertEqual((cp_trade["amount0_delta"], cp_trade["amount1_delta"]), ("3", "-4"))
        self.assertEqual((tick_trade["amount0"], tick_trade["amount1"]), ("3", "-4"))

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

    def test_state_quality_rejects_same_size_output_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            write_rows(raw, "sushiswap_v2", "hourly_reserves", "20250101", [cp_snapshot()])
            write_rows(raw, "sushiswap_v2", "swaps", "20250101", [cp_swap()])
            write_cp_partition(raw, "sushiswap_v2", "20250101", root=out)
            path = out / "constant_product" / "sushiswap_v2" / "20250101.parquet"
            original = path.stat()
            payload = bytearray(path.read_bytes())
            payload[-1] ^= 1
            path.write_bytes(payload)
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
            self.assertIsNone(
                read_cp_quality(raw, "sushiswap_v2", "20250101", root=out)
            )
            with self.assertRaisesRegex(ValueError, "content disagrees"):
                read_cp_partition(
                    "sushiswap_v2", "20250101", root=out, raw_root=raw
                )

    def test_tick_partition_normalises_exact_order_and_signed_liquidity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            change = {
                **swap(block=9),
                "id": "change",
                "logIndex": "3",
                "amount": "-7",
                "tickLower": "-10",
                "tickUpper": "10",
                "pool": swap()["pool"],
            }
            write_v4_exact_rows(raw, "20250101", [change, swap()])
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        self.assertEqual(frame["record_type"].tolist(), ["initialize", "liquidity", "swap"])
        self.assertEqual(frame.iloc[1]["liquidity_delta"], "-7")
        self.assertEqual(frame.iloc[2]["block_number"], 10)
        self.assertEqual(set(frame["pool_family"]), {"vanilla_concentrated"})
        self.assertEqual(set(frame["state_generation"]), {STATE_GENERATIONS["uniswap_v4"]})
        self.assertTrue(frame.iloc[2]["quote_supported"])

    def test_v4_hooked_pool_is_usable_evidence_but_not_quote_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            hooked = swap()
            hooked["pool"]["hooks"] = "0x0000000000000000000000000000000000000001"
            write_v4_exact_rows(raw, "20250101", [hooked])
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        swap_row = frame[frame["record_type"].eq("swap")].iloc[0]
        self.assertTrue(swap_row["usable"])
        self.assertEqual(swap_row["pool_family"], "hooked_or_dynamic_fee")
        self.assertFalse(swap_row["quote_supported"])

    def test_tick_partition_ignores_conflicting_graph_v4_state_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            write_v4_exact_rows(raw, "20250101", [swap()])
            provider_path = raw / "uniswap_v4" / "uniswap_v4_swaps_20250101.jsonl.gz"
            provider_path.parent.mkdir(parents=True)
            with gzip.open(provider_path, "wt") as handle:
                handle.write(json.dumps({**swap(amount0="999", amount1="-1"), "sqrtPriceX96": "1"}) + "\n")
            frame, quality = normalise_tick_partition(raw, "uniswap_v4", "20250101")
        self.assertTrue(quality.passed)
        swap_row = frame[frame["record_type"].eq("swap")].iloc[0]
        self.assertEqual((swap_row["amount0"], swap_row["amount0_raw"]), ("0.000000000000000001", "1"))
        self.assertEqual(swap_row["sqrt_price_x96"], str(1 << 96))
        self.assertNotIn("uniswap_v4_swaps_20250101.jsonl.gz", [path.name for path in __import__("ddvc.state_data", fromlist=["_state_partition_inputs"])._state_partition_inputs(raw, "tick", "uniswap_v4", "20250101")])

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
            write_v4_exact_rows(raw, "20250101", [swap()])
            write_tick_partition(raw, "uniswap_v4", "20250101", root=out)
            self.assertIsNotNone(read_tick_quality(raw, "uniswap_v4", "20250101", root=out))
            frame = read_tick_partition("uniswap_v4", "20250101", root=out, raw_root=raw)
            self.assertEqual(len(frame), 2)
            write_v4_exact_rows(raw, "20250101", [swap(), {**swap(), "id": "two", "logIndex": "5"}])
            self.assertIsNone(read_tick_quality(raw, "uniswap_v4", "20250101", root=out))


if __name__ == "__main__":
    unittest.main()
