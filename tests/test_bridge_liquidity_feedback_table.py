from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_bridge_liquidity_feedback import (
    HORIZONS,
    PANELS,
    TABLE_ROWS,
    render_bridge_liquidity_feedback,
)


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    pooled_n = {30: 50_000, 60: 39_000, 120: 18_000}
    stable_n = {30: 30_000, 60: 23_000, 120: 10_000}
    pooled_pairs = {30: 500, 60: 430, 120: 340}
    stable_pairs = {30: 480, 60: 410, 120: 320}
    dates = {30: 303, 60: 243, 120: 123}
    for horizon in HORIZONS:
        rows.append(
            {
                "claim_status": "provisional_exploratory",
                "record_type": "bridge_liquidity_feedback_support",
                "model_id": None,
                "timing": "forward",
                "weight_scheme": None,
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
                "initial_level_controls": None,
                "covariance": None,
            }
        )
    for panel_index, (_label, timing, weight_scheme) in enumerate(PANELS):
        for horizon in HORIZONS:
            for row_index, table_row in enumerate(TABLE_ROWS):
                row = dict(table_row.selector)
                stable_sample = "stable_candidate" in str(row["model_id"])
                row.update(
                    {
                        "claim_status": "provisional_exploratory",
                        "timing": timing,
                        "weight_scheme": weight_scheme,
                        "horizon_days": horizon,
                        "coefficient": 0.12 + row_index / 100 + panel_index / 1000,
                        "standard_error": 0.01 + row_index / 1000,
                        "p_value": 0.004 if row_index != 3 else 0.03,
                        "n_observations": (
                            stable_n[horizon] if stable_sample else pooled_n[horizon]
                        ),
                        "ordered_pair_clusters": (
                            stable_pairs[horizon]
                            if stable_sample
                            else pooled_pairs[horizon]
                        ),
                        "date_clusters": dates[horizon],
                        "fixed_effects": "local_bridge+analysis_date",
                        "initial_level_controls": "cubic_standardized_initial_depth",
                        "covariance": "two_way_ordered_pair_date_cr1",
                    }
                )
                rows.append(row)
    return rows


def test_bridge_liquidity_feedback_table_renders_symmetric_benchmarks_and_counts() -> None:
    rendered = render_bridge_liquidity_feedback(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert "$R_{b,t}\\rightarrow B_{b,t+h}$, pooled [log points]" in rendered
    assert "$B_{b,t+h}\\rightarrow R_{b,t}$, stablecoin [pp]" in rendered
    assert "30 days" in rendered
    assert "60 days" in rendered
    assert "120 days" in rendered
    assert "equal pair-date-scope weights" in rendered
    assert rendered.count("Time-reversed benchmark") == 2
    assert "$+0.012^{***}$" in rendered
    assert "$+14.000^{***}$" in rendered
    assert "Pooled rows / pair clusters / dates" in rendered
    assert "50,000 / 500 / 303" in rendered
    assert "Stablecoin rows / pair clusters / dates" in rendered
    assert "30,000 / 480 / 303" in rendered
    assert "Initial outcome level" in rendered


def test_bridge_liquidity_feedback_table_rejects_missing_row() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one bridge-depth row"):
        render_bridge_liquidity_feedback(pd.DataFrame(rows))
