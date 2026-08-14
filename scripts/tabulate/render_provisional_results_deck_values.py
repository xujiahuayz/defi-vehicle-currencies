#!/usr/bin/env python3
"""Render the shared paper/deck macros from current certified route exhibits."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_certified_presentation_source
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output


EXHIBITS = OUTPUT_DIR / "exhibits"
ROTATION = EXHIBITS / "intermediation_complexity_rival.jsonl"
INTEGRATION = EXHIBITS / "intermediation_integration_interaction.jsonl"
TOKEN_INTEGRATION = EXHIBITS / "intermediation_token_integration_interaction.jsonl"
EXCESS_USE = EXHIBITS / "vehicle_excess_use.jsonl"
EXCESS_USE_TRANSITION = EXHIBITS / "vehicle_excess_use_transition.jsonl"
ROUTING_SERIES = EXHIBITS / "cross_venue_routing_series.jsonl"
ROUTING_INFERENCE = EXHIBITS / "cross_venue_routing_inference.jsonl"
OUTPUT = EXHIBITS / "provisional_results_deck_values.tex"
INPUTS = (
    ROTATION,
    INTEGRATION,
    TOKEN_INTEGRATION,
    EXCESS_USE,
    EXCESS_USE_TRANSITION,
    ROUTING_SERIES,
    ROUTING_INFERENCE,
)
CODE_SOURCES = ["scripts/tabulate/render_provisional_results_deck_values.py"]


def _one(frame: pd.DataFrame, **identity: object) -> pd.Series:
    selected = frame
    for column, value in identity.items():
        if column not in selected:
            raise ValueError(f"presentation source lacks identity column {column}")
        selected = selected.loc[selected[column].eq(value)]
    if len(selected) != 1:
        terms = ", ".join(f"{key}={value}" for key, value in identity.items())
        raise ValueError(f"presentation source requires one {terms} row; found {len(selected)}")
    return selected.iloc[0]


def _finite(row: pd.Series, *columns: str) -> None:
    missing = [column for column in columns if column not in row.index]
    if missing:
        raise ValueError(f"presentation source lacks {', '.join(missing)}")
    if not all(math.isfinite(float(row[column])) for column in columns):
        raise ValueError("presentation source contains a non-finite displayed value")


def _share(value: float, decimals: int = 1) -> str:
    return f"{100 * value:.{decimals}f}\\%"


def _pp(value: float, decimals: int = 2) -> str:
    return f"${100 * value:+.{decimals}f}$ pp"


def _se_pp(value: float, decimals: int = 2) -> str:
    return f"{100 * value:.{decimals}f} pp"


def _pvalue(value: float) -> str:
    coefficient, exponent = f"{value:.2e}".split("e")
    return f"${coefficient}\\times10^{{{int(exponent)}}}$"


def render_provisional_results_deck_values(
    rotation: pd.DataFrame,
    integration: pd.DataFrame,
    token_integration: pd.DataFrame,
    excess_use: pd.DataFrame,
    excess_use_transition: pd.DataFrame,
    routing_series: pd.DataFrame,
    routing_inference: pd.DataFrame,
) -> str:
    """Bind display macros to unique scientific identities in certified exhibits."""

    count = _one(
        rotation,
        baseline_year=2024,
        comparison_year=2026,
        routing_scope="two_leg",
        weighting="episode",
        value_support="all_routes",
        transformation="share_level",
    )
    value = _one(
        rotation,
        baseline_year=2024,
        comparison_year=2026,
        routing_scope="two_leg",
        weighting="value",
        value_support="within_20pct",
        transformation="share_level",
    )
    for row in (count, value):
        _finite(
            row,
            "baseline_daily_mean",
            "comparison_daily_mean",
            "change",
            "hac_standard_error",
            "p_value_holm",
        )

    candidate = excess_use.loc[
        excess_use["scope"].eq("candidate_currencies")
        & excess_use["year"].isin([2024, 2026])
    ]
    stable = candidate.loc[
        candidate["level"].eq("asset_type") & candidate["asset_type"].eq("stable")
    ].set_index("year")
    focal = candidate.loc[
        candidate["level"].eq("token") & candidate["symbol"].isin(["USDC", "USDT"])
    ]
    if set(stable.index) != {2024, 2026} or len(focal) != 4:
        raise ValueError("vehicle-excess-use exhibit lacks the locked stable token decomposition")
    stable_change = float(stable.loc[2026, "intermediate_count_share"]) - float(
        stable.loc[2024, "intermediate_count_share"]
    )
    focal_totals = focal.groupby("year", observed=True)["intermediate_count_share"].sum()
    joint_contribution = float(focal_totals.loc[2026] - focal_totals.loc[2024]) / stable_change
    usdt_2024 = _one(candidate, level="token", symbol="USDT", year=2024)
    usdt_2026 = _one(candidate, level="token", symbol="USDT", year=2026)
    _finite(
        usdt_2024,
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    )
    _finite(
        usdt_2026,
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    )

    count_interaction = _one(
        token_integration,
        baseline_year=2024,
        comparison_year=2026,
        focal_symbol="USDT",
        comparison_components="native+USDC+USDT",
        weighting="episode",
        value_support="all_routes",
        transformation="share_level",
    )
    value_interaction = _one(
        token_integration,
        baseline_year=2024,
        comparison_year=2026,
        focal_symbol="USDT",
        comparison_components="native+USDC+USDT",
        weighting="value",
        value_support="within_20pct",
        transformation="share_level",
    )
    broad_interaction = _one(
        integration,
        baseline_year=2024,
        comparison_year=2026,
        weighting="episode",
        value_support="all_routes",
        transformation="share_level",
    )
    for row in (count_interaction, value_interaction, broad_interaction):
        _finite(row, "differential_change", "hac_standard_error")

    gap = _one(
        excess_use_transition,
        baseline_year=2024,
        comparison_year=2026,
        focal_symbol="USDT",
        observation_clock="daily",
        period_days=1,
        anchor_offset_days=-1,
        weighting="value",
        value_support="within_20pct",
        transformation="share_gap",
    )
    _finite(
        gap,
        "baseline_period_mean",
        "comparison_period_mean",
        "change",
        "hac_standard_error",
    )

    full = _one(
        routing_inference,
        baseline_year=2022,
        comparison_year=2026,
        scope="full",
    )
    balanced = _one(
        routing_inference,
        baseline_year=2022,
        comparison_year=2026,
        scope="balanced",
    )
    for row in (full, balanced):
        _finite(
            row,
            "baseline_daily_mean",
            "comparison_daily_mean",
            "change",
            "hac_standard_error",
        )

    routes = routing_series.copy()
    routes["year"] = pd.to_datetime(routes["date"], errors="raise").dt.year
    annual: dict[int, tuple[float, float]] = {}
    for year in (2020, 2026):
        sample = routes.loc[routes["year"].eq(year)]
        if sample.empty:
            raise ValueError(f"cross-venue routing series lacks {year}")
        count_denominator = float(sample["intermediated_routes"].sum())
        value_denominator = float(sample["intermediated_usd_within_20pct"].sum())
        if count_denominator <= 0 or value_denominator <= 0:
            raise ValueError(f"cross-venue routing series lacks positive {year} support")
        annual[year] = (
            float(sample["cross_venue_routes"].sum()) / count_denominator,
            float(sample["cross_venue_usd_within_20pct"].sum()) / value_denominator,
        )

    lines = [
        "% Generated by scripts/tabulate/render_provisional_results_deck_values.py.",
        "% PROVISIONAL working-paper values; scientific identity is recorded in the provenance sidecar.",
        f"\\newcommand{{\\StableCountBase}}{{{_share(float(count['baseline_daily_mean']))}}}",
        f"\\newcommand{{\\StableCountEnd}}{{{_share(float(count['comparison_daily_mean']))}}}",
        f"\\newcommand{{\\StableCountChange}}{{{_pp(float(count['change']), 1)}}}",
        f"\\newcommand{{\\StableCountSE}}{{{_se_pp(float(count['hac_standard_error']))}}}",
        f"\\newcommand{{\\StableCountP}}{{{_pvalue(float(count['p_value_holm']))}}}",
        f"\\newcommand{{\\StableValueBase}}{{{_share(float(value['baseline_daily_mean']))}}}",
        f"\\newcommand{{\\StableValueEnd}}{{{_share(float(value['comparison_daily_mean']))}}}",
        f"\\newcommand{{\\StableValueChange}}{{{_pp(float(value['change']), 1)}}}",
        f"\\newcommand{{\\StableValueSE}}{{{_se_pp(float(value['hac_standard_error']))}}}",
        f"\\newcommand{{\\StableValueP}}{{{_pvalue(float(value['p_value_holm']))}}}",
        f"\\newcommand{{\\JointStableContribution}}{{{_share(joint_contribution)}}}",
        f"\\newcommand{{\\USDTCountExcessBase}}{{{float(usdt_2024['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\USDTCountExcessEnd}}{{{float(usdt_2026['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\USDTValueExcessBase}}{{{float(usdt_2024['vehicle_excess_use_ratio_within_20pct']):.2f}}}",
        f"\\newcommand{{\\USDTValueExcessEnd}}{{{float(usdt_2026['vehicle_excess_use_ratio_within_20pct']):.2f}}}",
        f"\\newcommand{{\\USDTCrossCountChange}}{{{_pp(float(count_interaction['differential_change']))}}}",
        f"\\newcommand{{\\USDTCrossCountSE}}{{{_se_pp(float(count_interaction['hac_standard_error']))}}}",
        f"\\newcommand{{\\USDTCrossValueChange}}{{{_pp(float(value_interaction['differential_change']))}}}",
        f"\\newcommand{{\\USDTCrossValueSE}}{{{_se_pp(float(value_interaction['hac_standard_error']))}}}",
        f"\\newcommand{{\\USDTEndpointGapBase}}{{{_pp(float(gap['baseline_period_mean']))}}}",
        f"\\newcommand{{\\USDTEndpointGapEnd}}{{{_pp(float(gap['comparison_period_mean']))}}}",
        f"\\newcommand{{\\USDTEndpointGapChange}}{{{_pp(float(gap['change']))}}}",
        f"\\newcommand{{\\USDTEndpointGapSE}}{{{_se_pp(float(gap['hac_standard_error']))}}}",
        f"\\newcommand{{\\FullIntermediationBase}}{{{_share(float(full['baseline_daily_mean']), 2)}}}",
        f"\\newcommand{{\\FullIntermediationEnd}}{{{_share(float(full['comparison_daily_mean']), 2)}}}",
        f"\\newcommand{{\\FullIntermediationChange}}{{{_pp(float(full['change']))}}}",
        f"\\newcommand{{\\FullIntermediationSE}}{{{_se_pp(float(full['hac_standard_error']))}}}",
        f"\\newcommand{{\\BalancedIntermediationEnd}}{{{_share(float(balanced['comparison_daily_mean']), 2)}}}",
        f"\\newcommand{{\\BalancedIntermediationChange}}{{{_pp(float(balanced['change']))}}}",
        f"\\newcommand{{\\BalancedIntermediationSE}}{{{_se_pp(float(balanced['hac_standard_error']))}}}",
        f"\\newcommand{{\\CrossVenueCountStart}}{{{_share(annual[2020][0])}}}",
        f"\\newcommand{{\\CrossVenueCountEnd}}{{{_share(annual[2026][0])}}}",
        f"\\newcommand{{\\CrossVenueValueEnd}}{{{_share(annual[2026][1])}}}",
        f"\\newcommand{{\\CrossVenueRotationPremium}}{{{_pp(float(broad_interaction['differential_change']))}}}",
        f"\\newcommand{{\\CrossVenueRotationSE}}{{{_se_pp(float(broad_interaction['hac_standard_error']))}}}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    provenance_inputs: list[Path] = []
    frames: list[pd.DataFrame] = []
    for path in INPUTS:
        provenance_inputs.extend((path, require_certified_presentation_source(path)))
        frames.append(pd.read_json(path, lines=True))
    rendered = render_provisional_results_deck_values(*frames)
    with atomic_output(OUTPUT) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    stamp(
        OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=provenance_inputs,
        rows=sum(len(frame) for frame in frames),
        notes=(
            "Generated working-paper and deck display macros bound to current certified "
            "route-composition, excess-use, integration, and routing exhibits."
        ),
    )


main()
