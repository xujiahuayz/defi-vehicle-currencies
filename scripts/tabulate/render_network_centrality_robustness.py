#!/usr/bin/env python3
"""Render network-centrality levels and coverage sensitivity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


RESULTS = OUTPUT_DIR / "exhibits" / "network_centrality_robustness.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "network_centrality_robustness_support.jsonl"
VALUES = OUTPUT_DIR / "exhibits" / "network_centrality_paper_values.tex"
PERIODS = ("2024 H1", "2026 H1")
SYMBOLS = ("WETH", "USDC", "USDT")
MEASURE = "eigenvector_two_sided_share"
RANK = "eigenvector_two_sided_rank"

TABLE_NOTE = (
    "The graph contains unambiguous direct trades and every leg in a coherent "
    "multi-leg route. Count gives each observed leg equal weight; USD value uses "
    "repriced leg value. Two-sided eigenvector centrality is the normalized "
    "geometric mean of incoming and outgoing eigenvector centrality on the "
    "largest strongly connected component. Panel B reports named-currency rank "
    "ranges and the minimum Kendall rank correlation with the full graph when "
    "one sampled date or one venue is omitted. Panel C removes "
    "stablecoin-to-stablecoin legs from the 2026 H1 USD-value graph. Centrality "
    "depends on the edge weight and on whether the stablecoin core is included."
)


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    description: str,
) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{description} lacks columns: {missing}")


def _one(
    frame: pd.DataFrame,
    selectors: dict[str, object],
    *,
    description: str,
) -> pd.Series:
    selected = frame
    for column, expected in selectors.items():
        selected = selected.loc[selected[column].eq(expected)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {description} row for {selectors}; found {len(selected)}"
        )
    return selected.iloc[0]


def _score_and_rank(
    results: pd.DataFrame,
    *,
    period: str,
    scenario: str,
    weight: str,
    symbol: str,
) -> tuple[float, int]:
    row = _one(
        results,
        {
            "period": period,
            "scenario": scenario,
            "weight": weight,
            "symbol": symbol,
        },
        description="centrality",
    )
    score = float(row[MEASURE])
    rank = float(row[RANK])
    if not np.isfinite(score) or score < 0:
        raise ValueError("eigenvector-centrality scores must be finite and nonnegative")
    if not np.isfinite(rank) or rank < 1 or not rank.is_integer():
        raise ValueError("eigenvector-centrality ranks must be positive integers")
    return score, int(rank)


def _rank_range(
    results: pd.DataFrame,
    *,
    period: str,
    scenario_kind: str,
    symbol: str,
) -> tuple[int, int]:
    selected = results.loc[
        results["period"].eq(period)
        & results["scenario_kind"].eq(scenario_kind)
        & results["weight"].eq("leg_value_usd")
        & results["symbol"].eq(symbol)
    ]
    if selected.empty:
        raise ValueError("network-centrality results lack an omission family")
    if selected["omitted"].nunique() != len(selected):
        raise ValueError("network-centrality results repeat an omitted unit")
    ranks = pd.to_numeric(selected[RANK], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(ranks).all() or (ranks < 1).any():
        raise ValueError("omission ranks must be finite and positive")
    return int(ranks.min()), int(ranks.max())


def _minimum_tau(
    support: pd.DataFrame,
    *,
    period: str,
    scenario_kind: str,
) -> float:
    selected = support.loc[
        support["period"].eq(period)
        & support["scenario_kind"].eq(scenario_kind)
        & support["weight"].eq("leg_value_usd")
        & support["measure"].eq(MEASURE)
    ]
    if selected.empty:
        raise ValueError(
            "network-centrality support lacks a requested omission family"
        )
    if selected["omitted"].nunique() != len(selected):
        raise ValueError("network-centrality support repeats an omitted unit")
    values = pd.to_numeric(
        selected["kendall_tau_common_nodes"], errors="coerce"
    ).to_numpy(dtype=float)
    if not np.isfinite(values).all() or ((values < -1) | (values > 1)).any():
        raise ValueError("Kendall correlations must be finite and lie in [-1, 1]")
    return float(values.min())


def _rank_text(bounds: tuple[int, int]) -> str:
    low, high = bounds
    return str(low) if low == high else f"{low}--{high}"


def render_table(results: pd.DataFrame, support: pd.DataFrame) -> str:
    """Return the compact three-panel appendix table."""

    _require_columns(
        results,
        {
            "period",
            "scenario",
            "scenario_kind",
            "omitted",
            "weight",
            "symbol",
            MEASURE,
            RANK,
        },
        description="network-centrality results",
    )
    _require_columns(
        support,
        {
            "period",
            "scenario_kind",
            "omitted",
            "weight",
            "measure",
            "kendall_tau_common_nodes",
        },
        description="network-centrality support",
    )

    lines = [
        r"\textit{Panel A. Two-sided eigenvector centrality in the full graph}",
        r"\par\smallskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xl*{4}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"Edge weight & Currency & \multicolumn{2}{c}{2024 H1} & \multicolumn{2}{c}{2026 H1} \\",
        r"\cmidrule(lr){3-4}\cmidrule(l){5-6}",
        r"& & Score (\%) & Rank & Score (\%) & Rank \\",
        r"\midrule",
    ]
    for weight, label in (("leg_count", "Count"), ("leg_value_usd", "USD value")):
        for symbol in SYMBOLS:
            before = _score_and_rank(
                results,
                period=PERIODS[0],
                scenario="full",
                weight=weight,
                symbol=symbol,
            )
            after = _score_and_rank(
                results,
                period=PERIODS[1],
                scenario="full",
                weight=weight,
                symbol=symbol,
            )
            lines.append(
                f"{label} & {symbol} & {100 * before[0]:.1f} & {before[1]} & "
                f"{100 * after[0]:.1f} & {after[1]} " + r"\\"
            )
        if weight == "leg_count":
            lines.append(r"\addlinespace[0.25em]")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel B. USD-value ranks when one sampled unit is omitted}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xl*{4}{>{\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Omitted unit & Period & WETH & USDC & USDT & Minimum Kendall $\tau$ \\",
            r"\midrule",
        ]
    )
    for scenario_kind, label in (
        ("leave_one_date_out", "Sampled date"),
        ("leave_one_venue_out", "Venue"),
    ):
        for period in PERIODS:
            ranges = [
                _rank_range(
                    results,
                    period=period,
                    scenario_kind=scenario_kind,
                    symbol=symbol,
                )
                for symbol in SYMBOLS
            ]
            tau = _minimum_tau(
                support,
                period=period,
                scenario_kind=scenario_kind,
            )
            lines.append(
                f"{label} & {period} & "
                + " & ".join(_rank_text(bounds) for bounds in ranges)
                + f" & {tau:.3f} "
                + r"\\"
            )
        if scenario_kind == "leave_one_date_out":
            lines.append(r"\addlinespace[0.25em]")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel C. 2026 H1 USD-value graph without stablecoin-to-stablecoin legs}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{2}{>{\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Currency & Score (\%) & Rank \\",
            r"\midrule",
        ]
    )
    for symbol in SYMBOLS:
        score, rank = _score_and_rank(
            results,
            period="2026 H1",
            scenario="exclude_stable_stable",
            weight="leg_value_usd",
            symbol=symbol,
        )
        lines.append(f"{symbol} & {100 * score:.1f} & {rank} " + r"\\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            "% Suggested manuscript note: " + TABLE_NOTE,
            "",
        ]
    )
    return "\n".join(lines)


def render_values(results: pd.DataFrame, support: pd.DataFrame) -> str:
    """Return generated values drawn from the table inputs."""

    lines = [
        "% Generated by scripts/tabulate/render_network_centrality_robustness.py; do not edit."
    ]
    for weight, weight_name in (("leg_count", "Count"), ("leg_value_usd", "Value")):
        for symbol in SYMBOLS:
            for period, period_name in zip(PERIODS, ("Start", "End"), strict=True):
                score, rank = _score_and_rank(
                    results,
                    period=period,
                    scenario="full",
                    weight=weight,
                    symbol=symbol,
                )
                stem = f"NetworkEC{weight_name}{symbol}{period_name}"
                lines.append(
                    f"\\newcommand{{\\{stem}Score}}{{{100 * score:.1f}\\%}}"
                )
                lines.append(f"\\newcommand{{\\{stem}Rank}}{{{rank}}}")
    for scenario_kind, omission_name in (
        ("leave_one_date_out", "LeaveDate"),
        ("leave_one_venue_out", "LeaveVenue"),
    ):
        for period, period_name in zip(PERIODS, ("Start", "End"), strict=True):
            for symbol in SYMBOLS:
                bounds = _rank_range(
                    results,
                    period=period,
                    scenario_kind=scenario_kind,
                    symbol=symbol,
                )
                stem = f"NetworkEC{omission_name}{symbol}{period_name}Rank"
                lines.append(f"\\newcommand{{\\{stem}}}{{{_rank_text(bounds)}}}")
            tau = _minimum_tau(
                support,
                period=period,
                scenario_kind=scenario_kind,
            )
            lines.append(
                f"\\newcommand{{\\NetworkEC{omission_name}{period_name}MinTau}}"
                f"{{{tau:.3f}}}"
            )
    for symbol in SYMBOLS:
        score, rank = _score_and_rank(
            results,
            period="2026 H1",
            scenario="exclude_stable_stable",
            weight="leg_value_usd",
            symbol=symbol,
        )
        lines.append(
            f"\\newcommand{{\\NetworkECNoStableCore{symbol}Score}}"
            f"{{{100 * score:.1f}\\%}}"
        )
        lines.append(f"\\newcommand{{\\NetworkECNoStableCore{symbol}Rank}}{{{rank}}}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "network_centrality_robustness",
        render_table(results, support),
        preview_width="7.5in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(render_values(results, support), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
