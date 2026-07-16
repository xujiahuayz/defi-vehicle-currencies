from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ddvc.metrics import _routes


class RouteUnitTests(unittest.TestCase):
    def test_multileg_path_is_one_route_unit(self) -> None:
        legs = pd.DataFrame(
            [
                {
                    "tx_hash": "0xtx",
                    "component_id": 0,
                    "route_class": "coherent",
                    "token_in_sym": "A",
                    "token_out_sym": "B",
                    "tin_role": "source",
                    "tout_role": "intermediate",
                    "amount_usd": 100.0,
                },
                {
                    "tx_hash": "0xtx",
                    "component_id": 0,
                    "route_class": "coherent",
                    "token_in_sym": "B",
                    "token_out_sym": "C",
                    "tin_role": "intermediate",
                    "tout_role": "sink",
                    "amount_usd": 100.0,
                },
            ]
        )

        routes = _routes(legs)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["src"], "A")
        self.assertEqual(routes[0]["tgt"], "C")
        self.assertEqual(routes[0]["inter"], frozenset({"B"}))


if __name__ == "__main__":
    unittest.main()
