from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ddvc.source_records import transaction_id
from ddvc.pricing.tick_frontier import quote_tick_pool
from ddvc.pricing.tick_quote import prepare_tick_quote_index
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    chain_order,
    load_tick_day_events,
    warm_tick_day,
)
from ddvc.state_data import TICK_STREAMS, write_tick_partition
from ddvc.tick_state_events import TickInitialization, certificate_identity_sha256, state_event_generation, write_daily_initializations, write_daily_v4_state_events
from day_cut_fixtures import certified_day_cuts


def initialization_certificate(venue: str) -> dict[str, object]:
    certificate = {"status": "pass", "generation": state_event_generation(venue), "venue": venue, "precedence_status": "pass"}
    certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
    return certificate


def v4_swap(*, block: int = 10, timestamp: int = 100, log_index: int = 4) -> dict:
    return {
        "transaction": {
            "id": "0xabc",
            "blockNumber": str(block),
            "timestamp": str(timestamp),
        },
        "timestamp": str(timestamp),
        "logIndex": str(log_index),
        "amount0": "1",
        "amount1": "-1",
        "sqrtPriceX96": str(1 << 96),
        "tick": "0",
        "pool": {
            "id": "pool",
            "feeTier": 500,
            "tickSpacing": 10,
            "hooks": "0x0000000000000000000000000000000000000000",
            "token0": {"id": "0xa", "symbol": "A", "decimals": 18},
            "token1": {"id": "0xb", "symbol": "B", "decimals": 18},
        },
    }


def initialize_for(row: dict, *, block: int = 8, log_index: int = 1) -> dict:
    return {
        "id": f"0xinit#{log_index}",
        "transaction": {"id": "0xinit", "blockNumber": str(block)},
        "logIndex": str(log_index),
        "sqrtPriceX96": row["sqrtPriceX96"],
        "tick": row["tick"],
        "pool": row["pool"],
    }


def materialize_tick(root: Path, rows_by_stream: dict[tuple[str, str], list[dict]]) -> Path:
    raw, state = root / "raw", root / "state"
    venues: set[str] = set()
    for (venue, stream), values in rows_by_stream.items():
        venues.add(venue)
        path = raw / venue / f"{venue}_{stream}_20250101.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as handle:
            for value in values:
                handle.write(json.dumps(value) + "\n")
    for venue in venues:
        candidate_rows = [
            row
            for (candidate_venue, _stream), values in rows_by_stream.items()
            if candidate_venue == venue
            for row in values
            if (row.get("pool") or {}).get("token0")
        ]
        unique_pools: dict[str, dict] = {}
        for row in candidate_rows:
            unique_pools.setdefault(str(row["pool"]["id"]), row)
        venue_offset = 0 if venue == "uniswap_v3" else 100
        initializations = [
            TickInitialization(
                venue=venue,
                pool=str(row["pool"]["id"]),
                token0=str(row["pool"]["token0"]["id"]),
                token1=str(row["pool"]["token1"]["id"]),
                fee_pips=int(row["pool"]["feeTier"]),
                tick_spacing=int(row["pool"]["tickSpacing"]),
                hooks=str(row["pool"]["hooks"]),
                sqrt_price_x96=int(row["sqrtPriceX96"]),
                tick=int(row["tick"]),
                block_number=8,
                block_hash="0x" + "11" * 32,
                transaction_hash="0x" + f"{index:064x}",
                transaction_index=index,
                log_index=venue_offset + index,
                quote_supported=True,
                quote_unsupported_reason=None,
            )
            for index, row in enumerate(unique_pools.values(), start=1)
        ]
        metadata = {
            str(token["id"]): (str(token.get("symbol") or ""), int(token["decimals"]))
            for row in unique_pools.values()
            for token in (row["pool"]["token0"], row["pool"]["token1"])
        }
        certificate = initialization_certificate(venue)
        if venue == "uniswap_v4":
            exact_state_events = []
            for (row_venue, stream), stream_rows in rows_by_stream.items():
                if row_venue != venue:
                    continue
                for event_row in stream_rows:
                    transaction = event_row["transaction"]
                    common = {
                        "kind": "modify_liquidity" if stream == "modify_liquidities" else "swap",
                        "pool": event_row["pool"]["id"], "block_number": int(transaction["blockNumber"]),
                        "block_hash": "0x" + "2" * 64, "transaction_hash": transaction["id"],
                        "transaction_index": 0, "log_index": int(row["logIndex"]),
                    }
                    if common["kind"] == "swap":
                        common.update(amount0=int(event_row["amount0"]), amount1=int(event_row["amount1"]), sqrt_price_x96=int(event_row["sqrtPriceX96"]), liquidity=1, tick=int(event_row["tick"]), fee=int(event_row["pool"]["feeTier"]))
                    else:
                        common.update(tick_lower=int(event_row["tickLower"]), tick_upper=int(event_row["tickUpper"]), liquidity_delta=int(event_row["amount"]), salt="0x" + "0" * 64)
                    exact_state_events.append(common)
            certificate.update(exact_modify_liquidity_events=sum(row["kind"] == "modify_liquidity" for row in exact_state_events), exact_swap_events=sum(row["kind"] == "swap" for row in exact_state_events))
            certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
        write_daily_initializations(
            venue,
            initializations,
            day_cuts=certified_day_cuts({"20250101": (0, 20)}),
            token_metadata=metadata,
            raw_root=raw,
            generation_certificate=certificate,
        )
        if venue == "uniswap_v4":
            write_daily_v4_state_events(exact_state_events, initializations, day_cuts=certified_day_cuts({"20250101": (0, 20)}), token_metadata=metadata, raw_root=raw, generation_certificate=certificate)
        for stream, _record_type, _sign in TICK_STREAMS[venue]:
            path = raw / venue / f"{venue}_{stream}_20250101.jsonl.gz"
            if not path.exists():
                with gzip.open(path, "wt"):
                    pass
        write_tick_partition(raw, venue, "20250101", root=state)
    return state


class TickReplayTests(unittest.TestCase):
    @staticmethod
    def initialize(state: TickReplayState, row: dict, *, venue: str = "uniswap_v4") -> None:
        initialization = initialize_for(row)
        state.apply(TickReplayEvent((8, 1), venue, "initialize", initialization))

    def test_common_chain_order_and_transaction_identity(self) -> None:
        row = v4_swap(timestamp=123, log_index=7)
        self.assertEqual(chain_order(row), (10, 7))
        self.assertEqual(transaction_id(row), "0xabc")
        row["transaction"] = {"id": "0xdef", "blockNumber": "99"}
        self.assertEqual(transaction_id(row), "0xdef")
        self.assertEqual(chain_order(row), (99, 7))
        row.pop("logIndex")
        self.assertIsNone(chain_order(row))
        row["logIndex"] = 0
        self.assertEqual(chain_order(row), (99, 0))
        row["transaction"] = "0xlegacy"
        self.assertIsNone(chain_order(row))

    def test_state_applies_liquidity_before_indexing_swap(self) -> None:
        state = TickReplayState(token_decimals={"0xa": 18, "0xb": 18})
        self.initialize(state, v4_swap())
        change = {
            "pool": {"id": "pool"},
            "tickLower": "-10",
            "tickUpper": "10",
            "amount": "1000",
        }
        state.apply(TickReplayEvent((100, 3), "uniswap_v4", "liquidity", change, 1))
        state.apply(TickReplayEvent((100, 4), "uniswap_v4", "swap", v4_swap()))
        self.assertEqual(state.ticks_by_venue["uniswap_v4"]["pool"], {-10: 1000, 10: -1000})
        self.assertEqual(state.pool_index[frozenset(("0xa", "0xb"))], [("uniswap_v4", "pool")])

    def test_state_rejects_swap_without_exact_chain_order(self) -> None:
        state = TickReplayState(token_decimals={"0xa": 18, "0xb": 18})
        row = v4_swap()
        row["transaction"] = "0xlegacy"
        state.apply_swap("uniswap_v4", row)
        self.assertEqual(state.states_by_venue, {})
        self.assertEqual(state.pool_index, {})

    def test_unknown_token_metadata_is_explicitly_unsupported_for_both_tick_venues(self) -> None:
        for venue in ("uniswap_v3", "uniswap_v4"):
            state = TickReplayState()
            row = initialize_for(v4_swap())
            row["pool"]["token1"]["decimals"] = None
            row["quoteUnsupportedReason"] = "unknown_token_metadata"
            state.apply(TickReplayEvent((8, 1), venue, "initialize", row))
            self.assertEqual(state.initialization_status_by_venue[venue]["pool"], "unsupported:unknown_token_metadata")
            self.assertNotIn("pool", state.states_by_venue.get(venue, {}))

    def test_quarantined_pool_releases_tick_and_state_indexes(self) -> None:
        state = TickReplayState(token_decimals={"0xa": 0, "0xb": 18})
        initialized = v4_swap()
        initialized["pool"]["token0"]["decimals"] = 0
        self.initialize(state, initialized)
        change = {
            "pool": {"id": "pool"},
            "tickLower": "-10",
            "tickUpper": "10",
            "amount": "1000",
        }
        state.apply(TickReplayEvent((100, 3), "uniswap_v4", "liquidity", change, 1))
        state.apply(TickReplayEvent((100, 4), "uniswap_v4", "swap", v4_swap()))
        self.assertEqual(state.quarantined_pools, {"uniswap_v4": {"pool"}})
        self.assertEqual(state.ticks_by_venue["uniswap_v4"], {})
        self.assertEqual(state.states_by_venue["uniswap_v4"], {})
        self.assertEqual(state.pool_index, {})

    def test_day_loader_interleaves_venues_by_block_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = {
                ("uniswap_v3", "swaps"): [
                    v4_swap(block=11, timestamp=99, log_index=9)
                ],
                ("uniswap_v4", "swaps"): [v4_swap(block=10, timestamp=100, log_index=4)],
            }
            state = materialize_tick(root, rows)
            events = load_tick_day_events(state, "20250101", raw_root=root / "raw")
        swaps = [event for event in events if event.kind == "swap"]
        self.assertEqual([event.order for event in swaps], [(10, 4), (11, 9)])
        self.assertEqual([event.venue for event in swaps], ["uniswap_v4", "uniswap_v3"])

    def test_unknown_v4_metadata_initialize_and_exact_state_events_remain_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, state_root = root / "raw", root / "state"
            initialization = TickInitialization(
                venue="uniswap_v4", pool="pool", token0="0xa", token1="0xb", fee_pips=500,
                tick_spacing=10, hooks="0x" + "0" * 40, sqrt_price_x96=1 << 96, tick=0,
                block_number=8, block_hash="0x" + "1" * 64, transaction_hash="0x" + "1" * 64,
                transaction_index=0, log_index=1, quote_supported=True, quote_unsupported_reason=None,
            )
            exact = [
                {"kind": "modify_liquidity", "pool": "pool", "block_number": 9, "block_hash": "0x" + "2" * 64, "transaction_hash": "0x" + "2" * 64, "transaction_index": 0, "log_index": 2, "tick_lower": -10, "tick_upper": 10, "liquidity_delta": 7, "salt": "0x" + "0" * 64},
                {"kind": "swap", "pool": "pool", "block_number": 10, "block_hash": "0x" + "3" * 64, "transaction_hash": "0x" + "3" * 64, "transaction_index": 0, "log_index": 3, "amount0": 5, "amount1": -4, "sqrt_price_x96": 1 << 96, "liquidity": 7, "tick": 0, "fee": 500},
            ]
            certificate = initialization_certificate("uniswap_v4")
            certificate.update(exact_modify_liquidity_events=1, exact_swap_events=1)
            certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
            cuts = certified_day_cuts({"20250101": (0, 20)})
            write_daily_initializations("uniswap_v4", [initialization], day_cuts=cuts, token_metadata={}, raw_root=raw, generation_certificate=certificate)
            write_daily_v4_state_events(exact, [initialization], day_cuts=cuts, token_metadata={}, raw_root=raw, generation_certificate=certificate)
            provider_path = raw / "uniswap_v4" / "uniswap_v4_swaps_20250101.jsonl.gz"
            provider_path.parent.mkdir(parents=True)
            with gzip.open(provider_path, "wt") as handle:
                handle.write(json.dumps(v4_swap()) + "\n")
            write_tick_partition(raw, "uniswap_v4", "20250101", root=state_root)
            events = load_tick_day_events(state_root, "20250101", raw_root=raw)
            replay = TickReplayState()
            replay.apply_all(events)
        self.assertEqual(replay.initialization_status_by_venue["uniswap_v4"]["pool"], "unsupported:unknown_token_metadata")
        self.assertNotIn("pool", replay.states_by_venue.get("uniswap_v4", {}))
        self.assertEqual([event.order for event in events], [(8, 1), (9, 2), (10, 3)])
        self.assertTrue(all(event.row.get("timestamp") is None for event in events))

    def test_v3_provider_decimals_cannot_override_exact_anchor_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, state_root = root / "raw", root / "state"
            initialization = TickInitialization(
                venue="uniswap_v3", pool="pool", token0="0xa", token1="0xb", fee_pips=500,
                tick_spacing=10, hooks="0x" + "0" * 40, sqrt_price_x96=1 << 96, tick=0,
                block_number=8, block_hash="0x" + "1" * 64, transaction_hash="0x" + "1" * 64,
                transaction_index=0, log_index=1, quote_supported=True, quote_unsupported_reason=None,
            )
            write_daily_initializations("uniswap_v3", [initialization], day_cuts=certified_day_cuts({"20250101": (0, 20)}), token_metadata={"0xa": ("A", 18), "0xb": ("B", 6)}, raw_root=raw, generation_certificate=initialization_certificate("uniswap_v3"))
            wrong = v4_swap()
            wrong["pool"]["token0"]["decimals"] = 8
            wrong["pool"]["token1"]["decimals"] = 8
            for stream, rows in (("swaps", [wrong]), ("mints", []), ("burns", [])):
                path = raw / "uniswap_v3" / f"uniswap_v3_{stream}_20250101.jsonl.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wt") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            write_tick_partition(raw, "uniswap_v3", "20250101", root=state_root)
            replay = TickReplayState()
            replay.apply_all(load_tick_day_events(state_root, "20250101", raw_root=raw))
        state = replay.states_by_venue["uniswap_v3"]["pool"]
        self.assertEqual((state.dec0, state.dec1), (18, 6))

    def test_exact_v4_materialization_rejects_duplicate_chain_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {**v4_swap(), "id": "0xabc#1"},
                {**v4_swap(), "id": "0xabc#2"},
            ]
            with self.assertRaisesRegex(ValueError, "strictly ordered"):
                materialize_tick(root, {("uniswap_v4", "swaps"): rows})

    def test_exact_v4_materialization_rejects_conflicting_chain_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [v4_swap(), {**v4_swap(), "amount0": "2"}]
            with self.assertRaisesRegex(ValueError, "strictly ordered"):
                materialize_tick(root, {("uniswap_v4", "swaps"): rows})

    def test_liquidity_change_invalidates_prepared_quote_index(self) -> None:
        state = TickReplayState()
        ticks = {-10: 1000, 10: -1000}
        state.ticks_by_venue = {"uniswap_v4": {"pool": dict(ticks)}}
        state.quote_indexes_by_venue = {
            "uniswap_v4": {"pool": prepare_tick_quote_index(ticks)}
        }
        state.initialization_status_by_venue = {"uniswap_v4": {"pool": "quote_supported"}}
        change = {
            "pool": {"id": "pool"},
            "tickLower": "-20",
            "tickUpper": "20",
            "amount": "500",
        }
        state.apply(TickReplayEvent((101, 1), "uniswap_v4", "liquidity", change, 1))
        self.assertNotIn("pool", state.quote_indexes_by_venue["uniswap_v4"])

    def test_unsupported_v4_day_purges_replay_state_and_cannot_quote_or_reopen(self) -> None:
        replay = TickReplayState(token_decimals={"0xa": 18, "0xb": 18})
        row = v4_swap()
        self.initialize(replay, row)
        replay.ticks_by_venue["uniswap_v4"]["pool"] = {-10: 1000, 10: -1000}
        replay.quote_indexes_by_venue = {"uniswap_v4": {"pool": prepare_tick_quote_index(replay.ticks_by_venue["uniswap_v4"]["pool"])}}
        replay.swap_samples["pool"] = [row]
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            with patch("ddvc.pricing.tick_replay.tick_scientific_support", return_value=False), patch("ddvc.pricing.tick_replay.tick_partition_path", return_value=state_root / "absent.parquet"):
                events = load_tick_day_events(state_root, "20250102", raw_root=state_root / "raw")
        self.assertEqual([(event.kind, event.order) for event in events], [("scientific_support_end", (0, 0))])
        replay.apply_all(events)
        self.assertNotIn("uniswap_v4", replay.states_by_venue)
        self.assertNotIn("uniswap_v4", replay.ticks_by_venue)
        self.assertNotIn("uniswap_v4", replay.quote_indexes_by_venue)
        self.assertNotIn("pool", replay.swap_samples)
        self.assertEqual(replay.pool_index, {})
        self.assertIsNone(quote_tick_pool("0xa", "0xb", 1.0, venue="uniswap_v4", pool_id="pool", states_by_venue=replay.states_by_venue, ticks_by_venue=replay.ticks_by_venue, max_price_impact=None, quote_indexes_by_venue=replay.quote_indexes_by_venue))
        with self.assertRaisesRegex(ValueError, "reopen closed scientific support"):
            replay.apply(TickReplayEvent((20, 1), "uniswap_v4", "initialize", initialize_for(row, block=20)))

    def test_unsupported_v4_day_rejects_nonempty_canonical_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            partition = state_root / "present.parquet"
            partition.touch()
            with patch("ddvc.pricing.tick_replay.tick_scientific_support", return_value=False), patch("ddvc.pricing.tick_replay.tick_partition_path", return_value=partition), patch("ddvc.pricing.tick_replay.read_tick_partition", return_value=pd.DataFrame([{"record_type": "swap"}])):
                with self.assertRaisesRegex(ValueError, "unsupported V4 day carries canonical tick state"):
                    load_tick_day_events(state_root, "20250102", venues=("uniswap_v4",), raw_root=state_root / "raw")

    def test_streaming_warm_matches_ordered_end_of_day_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            change = {
                "timestamp": "99",
                "logIndex": "3",
                "transaction": {"id": "0xchange", "blockNumber": "9"},
                "pool": {"id": "pool"},
                "tickLower": "-10",
                "tickUpper": "10",
                "amount": "1000",
            }
            rows = {
                ("uniswap_v4", "modify_liquidities"): [change],
                ("uniswap_v4", "swaps"): [v4_swap()],
            }
            state_root = materialize_tick(root, rows)
            ordered = TickReplayState()
            ordered.apply_all(
                load_tick_day_events(state_root, "20250101", raw_root=root / "raw")
            )
            streamed = TickReplayState()
            warm_tick_day(state_root, "20250101", streamed, raw_root=root / "raw")
        self.assertEqual(streamed.ticks_by_venue, ordered.ticks_by_venue)
        self.assertEqual(streamed.states_by_venue, ordered.states_by_venue)
        self.assertEqual(streamed.pool_index, ordered.pool_index)


if __name__ == "__main__":
    unittest.main()
