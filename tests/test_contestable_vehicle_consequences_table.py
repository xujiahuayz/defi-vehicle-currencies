from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_contestable_vehicle_consequences import (
    AGE_SAMPLES,
    POOLED_SAMPLE,
    RETAINED_SAMPLE,
    render_contestable_vehicle_consequences,
)


def _row(
    *,
    record_type: str,
    sample: str,
    split_dimension: str,
    split_category: str,
    routes: int,
    lower_routes: int,
    lower_share: float,
    median_bps: float,
    p90_bps: float,
    weighted_bps: float,
) -> dict[str, object]:
    return {
        "record_type": record_type,
        "sample": sample,
        "split_dimension": split_dimension,
        "split_category": split_category,
        "comparison": (
            "best exact public route in the observed vehicle family versus the "
            "best exact public route in the rival vehicle family"
        ),
        "exact_venue_scope": "uniswap_v2+sushiswap_v2+uniswap_v3",
        "quoted_vehicle_universe": "WETH+DAI+USDC+USDT",
        "loss_bps_denominator": "exact output from observed vehicle family",
        "weighting": "observed_route_input_value_usd",
        "output_difference_rule": "strictly_greater_than_threshold",
        "minimum_output_difference_bps": 1.0,
        "quoted_alternative_max_leg_price_impact": 0.05,
        "weighted_loss_below_threshold_bps": 0.0,
        "cell_meets_minimum_support": True,
        "conditional_loss_meets_minimum_support": True,
        "gas_consequence_reported": False,
        "causal_interpretation": False,
        "routes": routes,
        "lower_output_family_routes": lower_routes,
        "lower_output_family_share": lower_share,
        "median_foregone_output_bps_if_over_1bp": median_bps,
        "p90_foregone_output_bps_if_over_1bp": p90_bps,
        "input_value_weighted_foregone_bps": weighted_bps,
        "split_categories_exhaustive_within_parent_sample": True,
        "split_categories_mutually_exclusive": True,
    }


def _rows() -> list[dict[str, object]]:
    rows = [
        _row(
            record_type="family_output_consequence",
            sample=POOLED_SAMPLE,
            split_dimension="all",
            split_category="all",
            routes=52_477,
            lower_routes=6_786,
            lower_share=0.1293138,
            median_bps=27.2358,
            p90_bps=171.4820,
            weighted_bps=7.4360,
        ),
        _row(
            record_type="family_output_consequence_split",
            sample=RETAINED_SAMPLE,
            split_dimension="mature_exclusive_route_choice",
            split_category="incumbent_retained",
            routes=27_215,
            lower_routes=2_901,
            lower_share=0.1065956,
            median_bps=17.1133,
            p90_bps=126.5254,
            weighted_bps=3.3143,
        ),
    ]
    age_values = (
        (13_159, 2_000, 0.1519872, 40.6648, 232.1973, 16.8206),
        (13_166, 1_699, 0.1290445, 52.1678, 217.6697, 19.0334),
        (26_152, 3_087, 0.1180407, 13.5226, 89.2889, 2.1310),
    )
    for (category, sample, _), values in zip(AGE_SAMPLES, age_values, strict=True):
        routes, lower_routes, share, median, p90, weighted = values
        rows.append(
            _row(
                record_type="family_output_consequence_split",
                sample=sample,
                split_dimension="pair_age",
                split_category=category,
                routes=routes,
                lower_routes=lower_routes,
                lower_share=share,
                median_bps=median,
                p90_bps=p90,
                weighted_bps=weighted,
            )
        )
    return rows


def test_vehicle_consequence_table_renders_requested_metrics() -> None:
    rendered = render_contestable_vehicle_consequences(pd.DataFrame(_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert r"@{\hspace{1.6em}}" in rendered
    assert "Panel A. All contestable routes" in rendered
    assert "Panel B. Routes retaining a mature exclusive incumbent" in rendered
    assert "Panel C. Input-value-weighted mean shortfall by pair age" in rendered
    assert r"12.9\%" in rendered
    assert "27.2" in rendered
    assert "171.5" in rendered
    assert "7.4" in rendered
    assert r"10.7\%" in rendered
    assert "17.1" in rendered
    assert "3.3" in rendered
    assert "Pairs aged 0--89 days [bp] & 16.8 & 13,159" in rendered
    assert "Pairs aged 90--364 days [bp] & 19.0 & 13,166" in rendered
    assert "Pairs aged at least 365 days [bp] & 2.1 & 26,152" in rendered


def test_vehicle_consequence_table_rejects_missing_age_cell() -> None:
    rows = [row for row in _rows() if row["split_category"] != "365_plus_days"]
    with pytest.raises(ValueError, match="expected one vehicle-consequence row"):
        render_contestable_vehicle_consequences(pd.DataFrame(rows))


def test_vehicle_consequence_table_rejects_nonexhaustive_age_cells() -> None:
    rows = _rows()
    for row in rows:
        if row["split_dimension"] == "pair_age":
            row["split_categories_exhaustive_within_parent_sample"] = False
            break
    with pytest.raises(ValueError, match="must be exhaustive"):
        render_contestable_vehicle_consequences(pd.DataFrame(rows))


def test_vehicle_consequence_table_rejects_gas_inclusive_interpretation() -> None:
    rows = _rows()
    rows[0]["gas_consequence_reported"] = True
    with pytest.raises(ValueError, match="unexpectedly includes gas"):
        render_contestable_vehicle_consequences(pd.DataFrame(rows))
