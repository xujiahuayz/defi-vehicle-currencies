from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ddvc.cpquote import ReserveEvent
from ddvc.pricing.mixed_frontier import MixedFrontierState, mixed_leg_quotes, quote_mixed_path
from ddvc.pricing.tick_state import TickPoolState
from ddvc.pricing.v2_frontier import quote_v2_pool, v2_leg_quotes
from ddvc.pricing.v2_replay import V2PoolMeta, V2ReplayDay, load_v2_replay_day
from ddvc.state_data import CP_STREAMS, write_cp_partition


A = "0x0000000000000000000000000000000000000001"
B = "0x0000000000000000000000000000000000000002"
K = "0x0000000000000000000000000000000000000003"


def write_gzip(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def complete_cp_day(raw: Path, venue: str, day: str) -> None:
    for stream, _record_type, _sign in CP_STREAMS[venue]:
        path = raw / venue / f"{venue}_{stream}_{day}.jsonl.gz"
        if not path.exists():
            write_gzip(path, [])


class V2ReplayFrontierTests(unittest.TestCase):
    def test_loader_owns_clean_pretrade_state_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, state = root / "raw", root / "state"
            venue = "uniswap_v2"
            pair = {
                "id": "pool",
                "token0": {"id": A},
                "token1": {"id": B},
            }
            write_gzip(
                raw / venue / f"{venue}_hourly_reserves_20250614.jsonl.gz",
                [{"hourStartUnix": 0, "reserve0": "1000", "reserve1": "1000", "pair": pair}],
            )
            write_gzip(
                raw / venue / f"{venue}_hourly_reserves_20250615.jsonl.gz",
                [{"hourStartUnix": 3600, "reserve0": "1010", "reserve1": "991", "pair": pair}],
            )
            swap = {
                "id": "swap",
                "timestamp": "3601",
                "logIndex": "5",
                "amount0In": "10",
                "amount0Out": "0",
                "amount1In": "0",
                "amount1Out": "9",
                "pair": pair,
                "transaction": {"id": "tx", "blockNumber": "100"},
            }
            write_gzip(
                raw / venue / f"{venue}_swaps_20250615.jsonl.gz",
                [swap],
            )
            complete_cp_day(raw, venue, "20250614")
            complete_cp_day(raw, venue, "20250615")
            write_cp_partition(raw, venue, "20250614", root=state)
            write_cp_partition(raw, venue, "20250615", root=state)
            replay = load_v2_replay_day(
                state, "20250615", venues=(venue,), raw_root=raw
            )
            self.assertEqual(
                replay.state_before(venue, "pool", 3600, (100, 5)),
                (Decimal("1000"), Decimal("1000")),
            )
            self.assertEqual(
                replay.swaps_by_identity[(venue, "tx", 5)].pool,
                "pool",
            )

    def test_frontier_quotes_identified_and_enumerated_pool(self) -> None:
        venue = "uniswap_v2"
        event = ReserveEvent(
            order=(100, 5),
            before=(Decimal("1000"), Decimal("1000")),
            after=(Decimal("1010"), Decimal("990.128419656")),
        )
        replay = V2ReplayDay(
            meta={(venue, "pool"): V2PoolMeta(venue, "pool", A, B)},
            pool_hour_events={(venue, "pool", 3600): [event]},
            state_support={(venue, "pool", 3600): (1, 0)},
            swaps_by_pool_hour={},
            swaps_by_identity={},
            pair_index={frozenset((A, B)): [(venue, "pool")]},
        )
        identified = quote_v2_pool(
            A,
            B,
            10.0,
            venue=venue,
            pool_id="pool",
            hour=3600,
            order=(100, 5),
            replay=replay,
            max_input_to_reserve=None,
        )
        enumerated = v2_leg_quotes(
            A,
            B,
            10.0,
            replay=replay,
            hour=3600,
            order=(100, 5),
            allowed_venues=None,
            max_input_to_reserve=0.05,
        )
        self.assertIsNotNone(identified)
        self.assertEqual(enumerated, [identified])
        assert identified is not None
        self.assertAlmostEqual(identified.amount_out, 9.87158034397)
        self.assertGreater(identified.price_impact, 0)
        self.assertEqual(
            v2_leg_quotes(
                A,
                B,
                100.0,
                replay=replay,
                hour=3600,
                order=(100, 5),
                allowed_venues=None,
                max_input_to_reserve=0.05,
            ),
            [],
        )

    def test_mixed_path_threads_tick_output_into_v2_pool(self) -> None:
        venue = "uniswap_v2"
        event = ReserveEvent(
            order=(100, 5),
            before=(Decimal("1000"), Decimal("1000")),
            after=(Decimal("1010"), Decimal("990.128419656")),
        )
        v2_replay = V2ReplayDay(
            meta={(venue, "kb"): V2PoolMeta(venue, "kb", K, B)},
            pool_hour_events={(venue, "kb", 3600): [event]},
            state_support={(venue, "kb", 3600): (1, 0)},
            swaps_by_pool_hour={},
            swaps_by_identity={},
            pair_index={frozenset((K, B)): [(venue, "kb")]},
        )
        tick_state = TickPoolState(
            pool="ak",
            token0=A,
            token1=K,
            sym0="A",
            sym1="K",
            dec0=18,
            dec1=18,
            sqrt_price_x96=1 << 96,
            tick=0,
            fee_pips=500,
            tick_spacing=60,
            block=99,
            log_index=1,
        )
        state = MixedFrontierState(
            tick_pool_index={frozenset((A, K)): [("uniswap_v3", "ak")]},
            tick_states_by_venue={"uniswap_v3": {"ak": tick_state}},
            tick_ticks_by_venue={"uniswap_v3": {"ak": {-600: 10**25, 600: -(10**25)}}},
            tick_quote_indexes_by_venue={},
            v2_replay=v2_replay,
            v2_hour=3600,
            v2_order=(100, 5),
        )
        path = quote_mixed_path(
            A,
            B,
            K,
            1.0,
            venues=("uniswap_v3", venue),
            pools=("ak", "kb"),
            state=state,
            max_support=None,
        )
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.venues, ("uniswap_v3", venue))
        self.assertGreater(path.amount_out, 0)
        quotes = mixed_leg_quotes(
            K,
            B,
            path.amount_out,
            state=state,
            allowed_venues=None,
            max_support=0.05,
        )
        self.assertEqual([(quote.venue, quote.pool) for quote in quotes], [(venue, "kb")])


if __name__ == "__main__":
    unittest.main()
