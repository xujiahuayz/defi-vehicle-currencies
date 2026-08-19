from __future__ import annotations

import unittest

import pandas as pd

from scripts.tabulate.render_vehicle_dominance_determinants import (
    PANELS,
    REGRESSORS,
    SPECIFICATIONS,
    render_vehicle_dominance_determinants,
)


class VehicleDominanceDeterminantsTableTests(unittest.TestCase):
    def test_renderer_places_models_in_columns_and_regressors_in_rows(self) -> None:
        rows = []
        for metric, _heading in PANELS:
            for specification in SPECIFICATIONS:
                for index, (regressor, _label) in enumerate(REGRESSORS[:2]):
                    rows.append(
                        {
                            "metric": metric,
                            "model_id": specification.model_id,
                            "outcome": "stable_share_change",
                            "regressor": regressor,
                            "coefficient_pp": 0.1 + index,
                            "standard_error_pp": 0.01,
                            "p_value": 0.001,
                            "observations": 1000,
                            "ordered_pair_clusters": 100,
                            "month_day_clusters": 181,
                            "r_squared_within": 0.25,
                        }
                    )
        rendered = render_vehicle_dominance_determinants(pd.DataFrame(rows))
        self.assertIn(
            r"Panel A: $\Delta S^{(N)}_{pds}$, route-count stable share [pp]",
            rendered,
        )
        self.assertIn(
            r"Panel B: $\Delta S^{(V)}_{pds}$, routed-value stable share [pp]",
            rendered,
        )
        self.assertIn("Within $R^2$", rendered)
        self.assertIn("Month-day fixed effects & Yes & Yes & Yes & Yes", rendered)
        self.assertIn("$+0.100^{***}$", rendered)


if __name__ == "__main__":
    unittest.main()
