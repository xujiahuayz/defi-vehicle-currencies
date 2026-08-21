from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_network_betweenness import exhibit_rows


def _row(year: int, symbol: str) -> dict[str, object]:
    return {"year": year, "symbol": symbol}


def test_named_currency_may_be_absent_before_its_first_graph_appearance() -> None:
    frame = pd.DataFrame(
        [
            _row(2019, "WETH"),
            _row(2019, "USDC"),
            _row(2020, "WETH"),
            _row(2020, "USDC"),
            _row(2020, "USDT"),
            _row(2021, "WETH"),
            _row(2021, "USDC"),
            _row(2021, "USDT"),
            _row(2019, "OTHER"),
            _row(2020, "OTHER"),
            _row(2021, "OTHER"),
        ]
    )

    selected = exhibit_rows(frame)

    assert set(selected.loc[selected["year"].eq(2019), "symbol"]) == {"WETH", "USDC"}
    assert len(selected) == 8


def test_named_currency_cannot_disappear_after_entering_graph() -> None:
    frame = pd.DataFrame(
        [
            _row(year, symbol)
            for year in (2019, 2020, 2021)
            for symbol in ("WETH", "USDC", "USDT", "OTHER")
            if not (year == 2020 and symbol == "USDT")
        ]
    )

    with pytest.raises(ValueError, match="disappears after entering"):
        exhibit_rows(frame)
