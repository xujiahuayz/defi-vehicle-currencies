from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_liquidity_provision_regressions import (
    TABLE_ROWS,
    render_liquidity_provision_regressions,
)


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, table_row in enumerate(TABLE_ROWS):
        row = dict(table_row.selector)
        row.update(
            {
                "coefficient": 1.0 + index,
                "standard_error": 0.1 + index / 100,
                "coefficient_per_10pp_gap": 0.054 if table_row.unit == "pp" else 0.123,
                "standard_error_per_10pp_gap": 0.006 if table_row.unit == "pp" else 0.012,
                "p_value": 0.009 if index != 5 else 0.200,
                "n_observations": 1000 + index,
                "date_clusters": 100 + index,
            }
        )
        rows.append(row)
    return rows


def test_liquidity_provision_regression_table_scales_units() -> None:
    rendered = render_liquidity_provision_regressions(pd.DataFrame(_complete_rows()))

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert r"p{" not in rendered
    assert "V2 stock" in rendered
    assert "V4 LP flow" in rendered
    assert "Effect" in rendered
    assert "Sender-days" in rendered
    assert "$+5.4^{***}$" in rendered
    assert "$(0.6)$" in rendered
    assert "$+0.123^{***}$" in rendered
    assert "1,000" in rendered


def test_liquidity_provision_regression_table_rejects_missing_row() -> None:
    rows = _complete_rows()[:-1]
    with pytest.raises(ValueError, match="expected one row"):
        render_liquidity_provision_regressions(pd.DataFrame(rows))
