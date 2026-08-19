from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_vehicle_mechanism_regressions import (
    TABLE_ROWS,
    render_vehicle_mechanism_regressions,
)


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, table_row in enumerate(TABLE_ROWS):
        row = dict(table_row.selector)
        row.update(
            {
                "coefficient_pp": -2.5 if index == 0 else 3.0 + index,
                "standard_error_pp": 0.5 + index / 10,
                "p_value": 0.009 if index != 4 else 0.04,
                "observations": 1000 + index,
                "date_clusters": 100 + index,
                "month_day_clusters": 50 + index,
                "fixed_effects": "fe",
            }
        )
        rows.append(row)
    return rows


def test_vehicle_mechanism_regression_table_renders_driver_rows() -> None:
    rendered = render_vehicle_mechanism_regressions(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert r"p{" not in rendered
    assert "Turn-on" in rendered
    assert "Rolling hazard" in rendered
    assert "Issuer split" in rendered
    assert "USDT $\\times$ 2026" in rendered
    assert "$-2.5^{***}$" in rendered
    assert "$+7.0^{**}$" in rendered
    assert "1,000 / 100" in rendered


def test_vehicle_mechanism_regression_table_rejects_missing_row() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one vehicle-mechanism row"):
        render_vehicle_mechanism_regressions(pd.DataFrame(rows))
