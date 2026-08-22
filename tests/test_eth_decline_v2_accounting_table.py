from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.render_eth_decline_v2_accounting import (
    render_eth_decline_v2_accounting,
    render_eth_decline_v2_accounting_values,
)


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "output/exhibits/eth_decline_v2_accounting.jsonl"
SUPPORT = ROOT / "output/exhibits/eth_decline_v2_accounting_support.jsonl"
TABLE = ROOT / "output/tables/eth_decline_v2_accounting.tex"
VALUES = ROOT / "output/exhibits/eth_decline_v2_accounting_values.tex"


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_json(RESULTS, lines=True), pd.read_json(SUPPORT, lines=True)


def test_checked_in_accounting_table_and_values_match_renderers() -> None:
    results, support = _inputs()
    assert TABLE.read_text(encoding="utf-8") == render_eth_decline_v2_accounting(
        results, support
    )
    assert VALUES.read_text(
        encoding="utf-8"
    ) == render_eth_decline_v2_accounting_values(results, support)


def test_table_shows_pooled_identity_margins_and_benchmark() -> None:
    results, support = _inputs()
    rendered = render_eth_decline_v2_accounting(results, support)
    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert r"Total capital, $\Delta\ln V$" in rendered
    assert r"Invariant-unit component, $\Delta\ln\sqrt{k}$" in rendered
    assert r"Unit value, $\Delta\ln(V/\sqrt{k})$" in rendered
    assert "$+0.0437^{***}$" in rendered
    assert "$-0.0176$" in rendered
    assert "$+0.0614$" in rendered
    assert "$+0.0614^{" not in rendered
    assert "79,583" in rendered
    assert "Note:" not in rendered
    assert r"\begin{minipage}" not in rendered
    assert "10 pp ETH decline" not in rendered


def test_zero_null_stars_use_holm_p_values_only() -> None:
    results, support = _inputs()
    capital = (
        results["venue"].eq("pooled_v2")
        & results["horizon_days"].eq(1)
        & results["outcome"].eq("stable_minus_weth_log_capital_change")
    )
    results.loc[capital, "p_value"] = 0.001
    results.loc[capital, "holm_p_value"] = 0.20
    quantity = (
        results["venue"].eq("pooled_v2")
        & results["horizon_days"].eq(1)
        & results["outcome"].eq("stable_minus_weth_log_quantity_component")
    )
    results.loc[quantity, "p_value"] = 0.20
    results.loc[quantity, "holm_p_value"] = 0.04
    rendered = render_eth_decline_v2_accounting(results, support)
    assert "$+0.0437^{" not in rendered
    assert "$-0.0176^{**}$" in rendered


def test_value_macros_cover_effects_inference_benchmark_and_support() -> None:
    results, support = _inputs()
    values = render_eth_decline_v2_accounting_values(results, support)
    assert (
        r"\newcommand{\EthVTwoAccountingCapitalOneDayEffectLogPoints}{$+0.0437$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingCapitalOneDayEffectApproxPercent}{$+4.37\%$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingCapitalOneDaySELogPoints}{$0.0091$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingCapitalOneDayHolmP}{$p<0.001$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingUnitValueSevenDayBenchmarkDifferenceLogPoints}{$+0.0026$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingUnitValueSevenDayBenchmarkHolmP}{$p<0.001$}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingUnitValueThreeDayEffectApproxPercent}{$+5.48\%$}"
        in values
    )
    assert r"\newcommand{\EthVTwoAccountingSevenDayIntervals}{78{,}262}" in values
    assert (
        r"\newcommand{\EthVTwoAccountingCapitalApproxPercentRange}{about 4--5\%}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingQuantityApproxPercentRange}{$-1.8\%$ to $-0.8\%$}"
        in values
    )
    assert r"\newcommand{\EthVTwoAccountingMaterialPoolCapital}{\$50{,}000}" in values
    assert (
        r"\newcommand{\EthVTwoAccountingCompleteFollowupCellRange}{90.0--93.5\%}"
        in values
    )
    assert (
        r"\newcommand{\EthVTwoAccountingSinglePricedEndpointShare}{96.7\%}"
        in values
    )
    commands = [line for line in values.splitlines() if line.startswith(r"\newcommand")]
    names = [line.split("{")[1] for line in commands]
    assert len(names) == len(set(names))


def test_renderer_rejects_a_broken_capital_identity() -> None:
    results, support = _inputs()
    selected = (
        results["venue"].eq("pooled_v2")
        & results["horizon_days"].eq(3)
        & results["outcome"].eq("stable_minus_weth_log_capital_change")
    )
    results.loc[selected, "coefficient"] += 0.01
    results.loc[selected, "difference_from_benchmark"] += 0.01
    with pytest.raises(ValueError, match="accounting identity fails"):
        render_eth_decline_v2_accounting(results, support)
