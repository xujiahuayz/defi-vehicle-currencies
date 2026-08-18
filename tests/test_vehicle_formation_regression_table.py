from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_vehicle_formation_regressions import (
    TABLE_ROWS,
    render_vehicle_formation_regressions,
)


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, table_row in enumerate(TABLE_ROWS):
        row = dict(table_row.selector)
        row.update(
            {
                "coefficient": 0.86 if index == 0 else 0.10 + index * 0.05,
                "standard_error": 0.058 if index == 0 else 0.02 + index * 0.01,
                "p_value": 0.009 if index != 8 else 0.040,
                "observations": 12345 + index,
                "entry_date_clusters": 120 + index,
            }
        )
        rows.append(row)
    return rows


def test_vehicle_formation_regression_table_scales_and_labels_rows() -> None:
    rendered = render_vehicle_formation_regressions(pd.DataFrame(_complete_rows()))

    assert "Entry persistence" in rendered
    assert "Named-stable identity" in rendered
    assert "Stable endpoint $\\times$ 2026" in rendered
    assert "Complex-route share $\\times$ 2026 (+10 pp)" in rendered
    assert "$+8.6^{***}$" in rendered
    assert "$(0.6)$" in rendered
    assert "12,345 / 120" in rendered
    assert "$+5.0^{**}$" in rendered


def test_vehicle_formation_regression_table_rejects_missing_specification() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one row"):
        render_vehicle_formation_regressions(pd.DataFrame(rows))
