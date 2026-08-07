from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from ddvc.fetch.raw import transaction_id
from ddvc.pricing.tick_quote import prepare_tick_quote_index
from ddvc.pricing.tick_replay import (
    TickReplayEvent,
    TickReplayState,
    load_tick_day_events,
    timestamp_order,
    warm_tick_day,
)


def v4_swap(*, timestamp: int = 100, log_index: int = 4) -> dict:
    return {
        "transaction": "0xabc",
        "timestamp": str(timestamp),
        "logIndex": str(log_index),
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


class TickReplayTests(unittest.TestCase):
    def test_common_timestamp_order_and_transaction_identity(self) -> None:
        row = v4_swap(timestamp=123, log_index=7)
        self.assertEqual(timestamp_order(row), (123, 7))
        self.assertEqual(transaction_id(row), "0xabc")
        row["transaction"] = {"id": "0xdef", "blockNumber": "99"}
        self.assertEqual(transaction_id(row), "0xdef")
        self.assertEqual(timestamp_order(row), (123, 7))

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

    def test_day_loader_interleaves_venues_by_timestamp_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = {
                ("uniswap_v3", "swaps"): [
                    {**v4_swap(timestamp=100, log_index=9), "transaction": {"id": "0x1"}}
                ],
                ("uniswap_v4", "swaps"): [v4_swap(timestamp=100, log_index=4)],
            }
            for (venue, stream), values in rows.items():
                path = root / venue / f"{venue}_{stream}_20250101.jsonl.gz"
                path.parent.mkdir(parents=True)
                with gzip.open(path, "wt") as handle:
                    for value in values:
                        handle.write(json.dumps(value) + "\n")
            events = load_tick_day_events(root, "20250101")
        self.assertEqual([event.order for event in events], [(100, 4), (100, 9)])
        self.assertEqual([event.venue for event in events], ["uniswap_v4", "uniswap_v3"])

    def test_day_loader_deduplicates_source_ids_for_one_chain_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "uniswap_v4" / "uniswap_v4_swaps_20250101.jsonl.gz"
            path.parent.mkdir(parents=True)
            rows = [
                {**v4_swap(), "id": "0xabc#1"},
                {**v4_swap(), "id": "0xabc#2"},
            ]
            with gzip.open(path, "wt") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            events = load_tick_day_events(root, "20250101")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].row["id"], "0xabc#1")

    def test_day_loader_rejects_conflicting_rows_for_one_chain_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "uniswap_v4" / "uniswap_v4_swaps_20250101.jsonl.gz"
            path.parent.mkdir(parents=True)
            rows = [v4_swap(), {**v4_swap(), "amount0": "1"}]
            with gzip.open(path, "wt") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "conflicting tick events"):
                load_tick_day_events(root, "20250101")

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
                "pool": {"id": "pool"},
                "tickLower": "-10",
                "tickUpper": "10",
                "amount": "1000",
            }
            rows = {
                ("uniswap_v4", "modify_liquidities"): [change],
                ("uniswap_v4", "swaps"): [v4_swap()],
            }
            for (venue, stream), values in rows.items():
                path = root / venue / f"{venue}_{stream}_20250101.jsonl.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wt") as handle:
                    for value in values:
                        handle.write(json.dumps(value) + "\n")
            ordered = TickReplayState()
            ordered.apply_all(load_tick_day_events(root, "20250101"))
            streamed = TickReplayState()
            warm_tick_day(root, "20250101", streamed)
        self.assertEqual(streamed.ticks_by_venue, ordered.ticks_by_venue)
        self.assertEqual(streamed.states_by_venue, ordered.states_by_venue)
        self.assertEqual(streamed.pool_index, ordered.pool_index)


if __name__ == "__main__":
    unittest.main()
