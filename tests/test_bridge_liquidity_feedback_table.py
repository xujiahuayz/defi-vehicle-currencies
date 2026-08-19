from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_bridge_liquidity_feedback import (
    TABLE_ROWS,
    render_bridge_liquidity_feedback,
)


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon in (30, 120):
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "model_id": None,
                "horizon_days": horizon,
                "outcome": None,
                "regressor": None,
                "candidate_rows": 50_000 if horizon == 30 else 18_000,
                "ordered_pairs": 500 if horizon == 30 else 340,
                "days": 303 if horizon == 30 else 123,
                "coefficient": None,
                "standard_error": None,
                "p_value": None,
                "n_observations": None,
                "ordered_pair_clusters": None,
                "date_clusters": None,
                "fixed_effects": None,
                "covariance": None,
            }
        )
        for index, table_row in enumerate(TABLE_ROWS):
            row = dict(table_row.selector)
            row.update(
                {
                    "claim_status": "provisional_exploratory",
                    "horizon_days": horizon,
                    "coefficient": 0.12 + index / 100,
                    "standard_error": 0.01 + index / 1000,
                    "p_value": 0.004 if index != 3 else 0.03,
                    "n_observations": 50_000 if horizon == 30 else 18_000,
                    "ordered_pair_clusters": 500 if horizon == 30 else 340,
                    "date_clusters": 303 if horizon == 30 else 123,
                    "fixed_effects": "candidate+origin_date",
                    "covariance": "two_way_ordered_pair_date_cr1",
                }
            )
            rows.append(row)
    return rows


def test_bridge_liquidity_feedback_table_renders_two_direction_feedback() -> None:
    rendered = render_bridge_liquidity_feedback(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "$R_{b,t}\\rightarrow\\Delta B_{b,t+h}$, pooled [log points]" in rendered
    assert "$B_{b,t}\\rightarrow\\Delta R_{b,t+h}$, stable [pp]" in rendered
    assert "30 days" in rendered
    assert "120 days" in rendered
    assert "$+0.012^{***}$" in rendered
    assert "$+14.000^{***}$" in rendered
    assert "50,000 / 500 / 303" in rendered


def test_bridge_liquidity_feedback_table_rejects_missing_row() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one bridge-feedback row"):
        render_bridge_liquidity_feedback(pd.DataFrame(rows))
