from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v4_lp_origin_timing import (
    OUTCOMES,
    PREDICTORS,
    PRIMARY_SAMPLE,
    render_v4_lp_origin_timing,
)


def _complete_rows() -> list[dict[str, object]]:
    rows = []
    for predictor_index, predictor in enumerate(PREDICTORS):
        for outcome_index, outcome in enumerate(OUTCOMES):
            rows.append(
                {
                    "sample_variant": PRIMARY_SAMPLE,
                    "predictor": predictor,
                    "outcome": outcome,
                    "effect_per_10pp_predictor": 0.01 * (predictor_index + 1),
                    "standard_error_per_10pp_predictor": 0.002 * (outcome_index + 1),
                    "holm_p_value": 0.009 if outcome_index == 0 else 0.2,
                    "n_observations": 1000,
                    "date_clusters": 200,
                    "fixed_effects": "candidate+origin_date",
                    "controls": "activity+capital",
                }
            )
    return rows


def test_origin_timing_table_uses_holm_stars_and_log_point_scaling() -> None:
    rendered = render_v4_lp_origin_timing(pd.DataFrame(_complete_rows()))
    assert "Internal same-asset share" in rendered
    assert "$+0.010^{***}$" in rendered
    assert "1,000 / 200" in rendered


def test_origin_timing_table_rejects_incomplete_grid() -> None:
    rows = _complete_rows()
    rows.pop()
    with pytest.raises(ValueError, match="incomplete"):
        render_v4_lp_origin_timing(pd.DataFrame(rows))
