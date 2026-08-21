from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_result_resolution_checks import (
    render_adjacent_year_rotation,
    render_entry_price_alignment,
    render_nonvehicle_endpoint_rotation,
    render_values,
)


def _decomposition(
    baseline: int,
    comparison: int,
    *,
    metric: str = "count_share",
    start: float = 0.2,
    change: float = 0.1,
) -> dict[str, object]:
    return {
        "metric": metric,
        "reporting_scope": "pooled",
        "baseline_year": baseline,
        "comparison_year": comparison,
        "baseline_stable_share": start,
        "comparison_stable_share": start + change,
        "total_change": change,
        "within_common": 0.01,
        "common_pair_reweighting": 0.02,
        "common_support_mass": 0.01,
        "exclusive_pair_contribution": change - 0.04,
        "identity_error": 0.0,
    }


def _price_results() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for entry_type in ("pooled", "native", "stable"):
        for weighting in ("route", "pair_day"):
            for relation, share in (("incumbent", 0.9), ("challenger", 0.4)):
                rows.append(
                    {
                        "record_type": "entry_price_leader_alignment",
                        "horizon_days": 120,
                        "weighting": weighting,
                        "entry_vehicle_type": entry_type,
                        "price_leader_relation": relation,
                        "observations": 1_234,
                        "pairs": 321,
                        "incumbent_vehicle_share": share,
                    }
                )
    return pd.DataFrame(rows)


def test_result_resolution_tables_render_direct_checks() -> None:
    adjacent = pd.DataFrame(
        [
            _decomposition(2019, 2020, change=-0.1),
            _decomposition(2020, 2021, change=0.2),
        ]
    )
    endpoint = pd.DataFrame(
        [
            _decomposition(2024, 2026, start=0.1, change=0.3),
            _decomposition(
                2024,
                2026,
                metric="strict_intermediation_value_share",
                start=0.2,
                change=0.4,
            ),
        ]
    )
    price = _price_results()
    adjacent_tex = render_adjacent_year_rotation(adjacent)
    endpoint_tex = render_nonvehicle_endpoint_rotation(endpoint)
    price_tex = render_entry_price_alignment(price)
    values = render_values(adjacent, endpoint, price)
    assert "2019--2020 & $-10.0$" in adjacent_tex
    assert "Supported value & 20.0 & 60.0 & $+40.0$" in endpoint_tex
    assert (
        "All pairs & 90.0 [1{,}234] & 40.0 [1{,}234] & "
        "90.0 [1{,}234] & 40.0 [1{,}234]" in price_tex
    )
    assert r"\newcommand{\AdjacentLargestDeclineYears}{2019--2020}" in values
    assert r"\newcommand{\PriceChallengerIncumbentRetention}{40.0\%}" in values
