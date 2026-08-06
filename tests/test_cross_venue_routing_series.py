from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.build_cross_venue_routing_series import bounded_workers, one_day


class CrossVenueRoutingSeriesTests(unittest.TestCase):
    def test_clean_routes_are_ordered_and_ambiguous_components_are_excluded(self) -> None:
        rows = [
            {
                "tx_hash": "cross",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "K",
                "token_out": "B",
                "log_index": 2,
            },
            {
                "tx_hash": "cross",
                "component_id": 0,
                "source": "v3",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "A",
                "token_out": "K",
                "log_index": 1,
            },
            {
                "tx_hash": "ambiguous",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 999.0,
                "route_class": "tricky_bridged",
                "token_in": "X",
                "token_out": "Y",
                "log_index": 0,
            },
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["legs"], 2)
        self.assertEqual(result["routes"], 1)
        self.assertEqual(result["economic_multileg_routes"], 1)
        self.assertEqual(result["economic_multileg_swap_legs"], 2)
        self.assertEqual(result["economic_multileg_venue_count"], 2)
        self.assertEqual(result["economic_multileg_over_two_routes"], 0)
        self.assertEqual(result["economic_multileg_mean_legs"], 2.0)
        self.assertEqual(result["economic_multileg_mean_venues"], 2.0)
        self.assertEqual(result["cross_venue_routes"], 1)
        self.assertEqual(result["round_trip_routes"], 0)

    def test_round_trip_is_excluded_from_headline_but_retained_as_diagnostic(self) -> None:
        rows = [
            {
                "tx_hash": "cycle",
                "component_id": 0,
                "source": "v2",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "A",
                "token_out": "K",
                "log_index": 1,
            },
            {
                "tx_hash": "cycle",
                "component_id": 0,
                "source": "v3",
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": "K",
                "token_out": "A",
                "log_index": 2,
            },
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["round_trip_routes"], 1)
        self.assertEqual(result["economic_multileg_routes"], 0)
        self.assertEqual(result["cross_venue_routes"], 0)

    def test_route_complexity_is_aggregated_over_economic_routes(self) -> None:
        rows = [
            {
                "tx_hash": "complex",
                "component_id": 0,
                "source": source,
                "amount_usd": 100.0,
                "route_class": "coherent",
                "token_in": token_in,
                "token_out": token_out,
                "log_index": log_index,
            }
            for log_index, source, token_in, token_out in [
                (1, "v2", "A", "K1"),
                (2, "v2", "K1", "K2"),
                (3, "v3", "K2", "B"),
            ]
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "20250101.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)
            result = one_day(path)
        assert result is not None
        self.assertEqual(result["economic_multileg_routes"], 1)
        self.assertEqual(result["economic_multileg_swap_legs"], 3)
        self.assertEqual(result["economic_multileg_venue_count"], 2)
        self.assertEqual(result["economic_multileg_over_two_routes"], 1)
        self.assertEqual(result["economic_multileg_over_two_share"], 1.0)

    def test_worker_count_is_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)


if __name__ == "__main__":
    unittest.main()
