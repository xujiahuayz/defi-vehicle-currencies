from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ddvc.variable_registry import OBSERVATIONS_TABLE_COLUMNS, SUMMARY_SPECS, VARIABLE_SPECS


class VariableRegistryTests(unittest.TestCase):
    def test_registered_columns_are_unique(self) -> None:
        columns = [spec.column for spec in VARIABLE_SPECS]
        self.assertEqual(len(columns), len(set(columns)))

    def test_summary_specs_are_observation_columns(self) -> None:
        observation_columns = set(OBSERVATIONS_TABLE_COLUMNS)
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.column, observation_columns)

    def test_core_bridge_and_route_cost_variables_are_registered(self) -> None:
        columns = set(OBSERVATIONS_TABLE_COLUMNS)
        self.assertLessEqual(
            {
                "bridge_share",
                "all_route_bridge_share",
                "lp_concentration",
                "direct_available_share",
                "no_direct_vehicle_available_share",
                "route_cost_advantage_median_bps",
                "settlement_transfer_incidence",
            },
            columns,
        )


if __name__ == "__main__":
    unittest.main()
