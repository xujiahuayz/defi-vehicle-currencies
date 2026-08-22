from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_stablecoin_supply_lp import render_stablecoin_supply_lp


def test_table_renders_only_the_four_primary_holm_models() -> None:
    rows = []
    for model_family, scope, coefficient, standard_error, n in (
        ("capital_growth", "stable_core", 0.0083, 0.0069, 2_274),
        ("capital_growth", "stable_spoke", 0.0041, 0.0049, 5_182),
        ("formation", "stable_core", -0.000019, 0.000447, 9_726),
        ("formation", "stable_spoke", -0.0000016, 0.0000028, 9_097_834),
    ):
        row = {
            "record_type": "stablecoin_supply_lp_coefficient",
            "model_id": f"{model_family}_{scope}_asset_wide_supply",
            "predictor": "supply_growth_per_10pct",
            "supply_measure": "asset_wide",
            "coefficient": coefficient,
            "standard_error": standard_error,
            "coefficient_pp": 100 * coefficient,
            "standard_error_pp": 100 * standard_error,
            "p_value_holm": 1.0,
            "family_hypotheses": 4,
            "observations": n,
        }
        rows.append(row)

    rendered = render_stablecoin_supply_lp(pd.DataFrame(rows))
    assert "Panel A. Next-month log capital growth" in rendered
    assert "Panel B. First material link in the next month" in rendered
    assert "$+0.0083$" in rendered
    assert "$-0.0019$" in rendered
    assert "9,097,834" in rendered
    assert "Holm-adjusted" in rendered
