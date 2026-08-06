from __future__ import annotations

import unittest

import pandas as pd

from scripts.test_venue_technology_rival import bounded_workers, support_status


class VenueTechnologyRivalTests(unittest.TestCase):
    def test_scope_with_no_intermediation_is_explicitly_unsupported(self) -> None:
        daily = pd.DataFrame(
            {
                "year": [2025, 2025, 2025, 2025],
                "scope": [
                    "curve_only",
                    "curve_only",
                    "constant_product_only",
                    "no_demand_scope",
                ],
                "intermediate_usd": [0.0, 0.0, 10.0, 0.0],
                "intermediate_routes": [0, 0, 1, 0],
                "endpoint_usd": [100.0, 200.0, 100.0, 0.0],
                "endpoint_routes": [1, 2, 1, 0],
            }
        )
        status = support_status(daily).set_index("scope")
        self.assertEqual(status.loc["curve_only", "support_status"], "no_intermediation")
        self.assertEqual(status.loc["constant_product_only", "support_status"], "identified")
        self.assertEqual(status.loc["no_demand_scope", "support_status"], "no_endpoint_demand")

    def test_workers_are_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)


if __name__ == "__main__":
    unittest.main()
