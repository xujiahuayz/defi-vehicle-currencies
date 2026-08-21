from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_v1_architecture_deck_values import (
    WETH,
    render_v1_architecture_deck_values,
    render_v1_architecture_table,
)


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    other = "0x0000000000000000000000000000000000000001"
    v1 = pd.DataFrame({"n_token_to_token": [100, 117_003, 99_900]})
    routing = pd.DataFrame(
        {
            "t0": [WETH, other, other],
            "t1": [other, other, WETH],
            "kind": ["direct", "direct", "eth_routed"],
            "n": [90, 5, 1_000],
        }
    )
    first_trade = pd.DataFrame(
        {"token0": [WETH] * 47 + [other], "token1": [other] * 48}
    )
    return v1, routing, first_trade


def test_renders_values_from_structured_inputs() -> None:
    rendered = render_v1_architecture_deck_values(*_inputs())
    assert r"\newcommand{\VOneForcedRoutes}{217,003}" in rendered
    assert r"\newcommand{\VTwoWethTradeShare}{94.7\%}" in rendered
    assert r"\newcommand{\VTwoWethNewPairShare}{97.9\%}" in rendered


def test_renders_compact_appendix_table_from_same_inputs() -> None:
    rendered = render_v1_architecture_table(*_inputs())
    assert "Reconstructed token-to-token routes [count] & 217,003" in rendered
    assert r"Single-leg trades executed in WETH pools, 2026 [\%] & 94.7" in rendered
    assert r"Token combinations first traded with WETH, 2026 [\%] & 97.9" in rendered
    assert "8.6" not in rendered


def test_refuses_empty_inputs() -> None:
    v1, routing, first_trade = _inputs()
    with pytest.raises(ValueError, match="empty"):
        render_v1_architecture_deck_values(v1.iloc[0:0], routing, first_trade)
