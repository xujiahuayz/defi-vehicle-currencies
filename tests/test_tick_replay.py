from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from ddvc.source_records import transaction_id
from ddvc.pricing.tick_quote import prepare_tick_quote_index
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    chain_order,
    load_tick_day_events,
    warm_tick_day,
)
from ddvc.state_data import TICK_STREAMS, write_tick_partition


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


def materialize_tick(root: Path, rows: dict[tuple[str, str], list[dict]]) -> Path:
    raw, state = root / "raw", root / "state"
    venues: set[str] = set()
    for (venue, stream), values in rows.items():
        venues.add(venue)
        path = raw / venue / f"{venue}_{stream}_20250101.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as handle:
            for value in values:
                handle.write(json.dumps(value) + "\n")
    for venue in venues:
        for stream, _record_type, _sign in TICK_STREAMS[venue]:
            path = raw / venue / f"{venue}_{stream}_20250101.jsonl.gz"
            if not path.exists():
                with gzip.open(path, "wt"):
                    pass
        write_tick_partition(raw, venue, "20250101", root=state)
    return state


class TickReplayTests(unittest.TestCase):
    def test_common_chain_order_and_transaction_identity(self) -> None:
        row = v4_swap(timestamp=123, log_index=7)
        self.assertEqual(chain_order(row), (10, 7))
        self.assertEqual(transaction_id(row), "0xabc")
        row["transaction"] = {"id": "0xdef", "blockNumber": "99"}
        self.assertEqual(transaction_id(row), "0xdef")
        self.assertEqual(chain_order(row), (99, 7))
        row["transaction"] = "0xlegacy"
        self.assertIsNone(chain_order(row))

    def test_state_applies_liquidity_before_indexing_swap(self) -> None:
        state = TickReplayState(token_decimals={"0xa": 18, "0xb": 18})
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

    def test_quarantined_pool_releases_tick_and_state_indexes(self) -> None:
        state = TickReplayState(token_decimals={"0xa": 0, "0xb": 18})
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
        self.assertEqual([event.order for event in events], [(10, 4), (11, 9)])
        self.assertEqual([event.venue for event in events], ["uniswap_v4", "uniswap_v3"])

    def test_day_loader_deduplicates_source_ids_for_one_chain_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {**v4_swap(), "id": "0xabc#1"},
                {**v4_swap(), "id": "0xabc#2"},
            ]
            state = materialize_tick(root, {("uniswap_v4", "swaps"): rows})
            events = load_tick_day_events(state, "20250101", raw_root=root / "raw")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].row["id"], "0xabc#1")

    def test_day_loader_rejects_conflicting_rows_for_one_chain_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [v4_swap(), {**v4_swap(), "amount0": "2"}]
            state = materialize_tick(root, {("uniswap_v4", "swaps"): rows})
            with self.assertRaisesRegex(ValueError, "identity gate"):
                load_tick_day_events(state, "20250101", raw_root=root / "raw")

    def test_liquidity_change_invalidates_prepared_quote_index(self) -> None:
        state = TickReplayState()
        ticks = {-10: 1000, 10: -1000}
        state.ticks_by_venue = {"uniswap_v4": {"pool": dict(ticks)}}
        state.quote_indexes_by_venue = {
            "uniswap_v4": {"pool": prepare_tick_quote_index(ticks)}
        }
        change = {
            "pool": {"id": "pool"},
            "tickLower": "-20",
            "tickUpper": "20",
            "amount": "500",
        }
        state.apply(TickReplayEvent((101, 1), "uniswap_v4", "liquidity", change, 1))
        self.assertNotIn("pool", state.quote_indexes_by_venue["uniswap_v4"])

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
