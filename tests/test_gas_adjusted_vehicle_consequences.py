from __future__ import annotations

import pandas as pd

from scripts.analyze.run_gas_adjusted_vehicle_consequences import (
    consequence_panel,
    consequence_rows,
)
from scripts.tabulate.render_gas_adjusted_vehicle_consequences import render


def _panel() -> pd.DataFrame:
    rows = []
    for index, input_usd in enumerate((500.0, 5_000.0, 50_000.0, 500_000.0)):
        rows.append(
            {
                "route_id": f"route-{index}",
                "day": "20240115",
                "ordered_pair": f"pair-{index}",
                "input_usd": input_usd,
                "chosen_stable": index % 2 == 0,
                "stable_public_out": 101.0 if index % 2 == 0 else 100.0,
                "native_public_out": 100.0 if index % 2 == 0 else 101.0,
                "output_token_price_usd": input_usd / 100.0,
                "effective_gas_price_wei": 20_000_000_000,
                "weth_price_usd": 2_000.0,
                "stable_gas_median": 600_000.0,
                "stable_gas_p25": 500_000.0,
                "stable_gas_p75": 700_000.0,
                "native_gas_median": 100_000.0,
                "native_gas_p25": 80_000.0,
                "native_gas_p75": 120_000.0,
            }
        )
    return pd.DataFrame(rows)


def test_gas_cost_can_change_the_output_ranking_for_small_routes() -> None:
    gross = consequence_panel(_panel(), "gross")
    central = consequence_panel(_panel(), "central")
    assert not gross["net_lower_output"].any()
    assert central["ranking_changes_after_gas"].any()
    assert central["chosen_path_gas_usd"].gt(0).all()


def test_consequence_rows_cover_sizes_and_bounds() -> None:
    rows = consequence_rows(_panel())
    assert set(rows["gas_scenario"]) == {
        "gross",
        "central",
        "chosen_favorable_bound",
        "chosen_unfavorable_bound",
    }
    assert set(rows["size_group"]) == {
        "all",
        "usd_100_to_999",
        "usd_1k_to_9_999",
        "usd_10k_to_99_999",
        "usd_100k_plus",
    }
    rendered = render(rows)
    assert "Panel A. Share using the lower-output vehicle path" in rendered
    assert "Panel B. Input-value-weighted output shortfall" in rendered
