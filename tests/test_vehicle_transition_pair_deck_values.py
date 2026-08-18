from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from scripts.tabulate.build_vehicle_transition_pair_deck_values import (
    _cohort_endpoint_margins,
    render_pair_decomposition_deck_values,
)


ROOT = Path(__file__).resolve().parents[1]
SIGNED_TEXT_MACRO = re.compile(
    r"\\newcommand\{\\(?P<name>[^}]+)\}\{(?P<value>[+-]\d)"
)


def _macro(rendered: str, name: str) -> str:
    """The rendered body of one macro, so a test can compare two of them."""
    match = re.search(rf"\\newcommand\{{\\{name}\}}\{{(?P<value>[^}}]*)\}}", rendered)
    assert match is not None, f"missing macro {name}"
    return match.group("value")


def _points(rendered_value: str) -> float:
    """Percentage points out of a rendered ``$+1.2$ pp`` cell."""
    return float(rendered_value.replace("$", "").replace(" pp", ""))


def test_audience_facing_deck_macros_use_math_signs() -> None:
    defects: list[str] = []
    for path in sorted((ROOT / "output" / "exhibits").glob("*_deck_values.tex")):
        for match in SIGNED_TEXT_MACRO.finditer(path.read_text(encoding="utf-8")):
            if "Raw" not in match.group("name"):
                defects.append(f"{path.name}:{match.group('name')}")
    assert defects == []


def _row(metric: str, scope: str, scale: float = 1.0) -> dict[str, object]:
    base = 0.20
    terms = {
        "within_common": -0.001,
        "common_pair_reweighting": 0.08 * scale,
        "common_support_mass": -0.005,
        "exclusive_pair_contribution": 0.176,
    }
    total = sum(terms.values())
    comparison = base + total
    # Block weights and block stablecoin shares that satisfy the same three
    # premises the renderer proves: the two blocks partition activity in each
    # year, each year's aggregate share is their activity-weighted mean, and
    # their midpoint gap times the common block's mass shift is exactly
    # ``common_support_mass``. Here the shift is -10 pp and the term is -0.5 pp,
    # so the gap must be 5 pp; the baseline pair (22.4\%, 16.4\%) averages to the
    # 20\% baseline under the 60/40 split, and the comparison pair straddles that
    # year's aggregate by 2 pp so the gap holds at every scale.
    blocks = {
        "W_baseline": 0.60,
        "W_comparison": 0.50,
        "S_C_baseline": 0.224,
        "S_E_baseline": 0.164,
        "S_C_comparison": comparison + 0.02,
        "S_E_comparison": comparison - 0.02,
    }
    blocks["E_baseline"] = 1 - blocks["W_baseline"]
    blocks["E_comparison"] = 1 - blocks["W_comparison"]
    return {
        "metric": metric,
        "reporting_scope": scope,
        "baseline_year": 2024,
        "comparison_year": 2026,
        "common_calendar_end": "06-30",
        "common_month_days": 181,
        "formula_id": "midpoint_common_exclusive_support_v1",
        "mechanism_status": "descriptive_realised_composition_noncausal",
        "baseline_stable_share": base,
        "comparison_stable_share": comparison,
        "total_change": total,
        "support_and_exclusive_joint": (
            terms["common_support_mass"] + terms["exclusive_pair_contribution"]
        ),
        "identity_error": 0.0,
        **terms,
        **blocks,
    }


# Panel A factors the *same* pooled count total a second way, so the fixture has
# to satisfy the two relations the renderer proves across the panels: the two
# totals agree, and the identity's within-pair and reweighting terms equal the
# common block's own stablecoin-share change scaled by that block's midpoint
# weight. Solving Panel A's two free terms out of the identity row keeps the
# fixture honest without hand-retuning it whenever `_row` moves.
_POOLED_IDENTITY = _row("count_share", "pooled")
_AGGREGATE_BASE = float(_POOLED_IDENTITY["baseline_stable_share"])
_ESTABLISHED_BASE = 0.25
_COMMON_WEIGHT_MIDPOINT = (
    float(_POOLED_IDENTITY["W_baseline"]) + float(_POOLED_IDENTITY["W_comparison"])
) / 2.0
_COMMON_ROLE_CHANGE = (
    float(_POOLED_IDENTITY["within_common"])
    + float(_POOLED_IDENTITY["common_pair_reweighting"])
) / _COMMON_WEIGHT_MIDPOINT
_ROLE_SUPPORT_BRIDGE = -0.004
_MARKET_TERMS = {
    "market_pair_support_bridge": (
        float(_POOLED_IDENTITY["total_change"])
        - _COMMON_ROLE_CHANGE
        - _ROLE_SUPPORT_BRIDGE
    ),
    "vehicle_role_support_bridge": _ROLE_SUPPORT_BRIDGE,
    "market_activity_reweighting": 0.08,
    "vehicle_incidence_reweighting": _COMMON_ROLE_CHANGE - 0.094,
    "within_pair_stable_share": 0.014,
}


def _decomposition() -> pd.DataFrame:
    rows = [
            _row(metric, scope, scale=1 + index / 10)
            for metric in ("count_share", "strict_intermediation_value_share")
            for index, scope in enumerate(("pooled", "single_venue", "cross_venue"))
    ]
    market_terms = dict(_MARKET_TERMS)
    common_role = sum(
        market_terms[column]
        for column in (
            "market_activity_reweighting",
            "vehicle_incidence_reweighting",
            "within_pair_stable_share",
        )
    )
    established = market_terms["vehicle_role_support_bridge"] + common_role
    total = sum(market_terms.values())
    rows.append(
        {
            "metric": "count_share",
            "reporting_scope": "pooled",
            "baseline_year": 2024,
            "comparison_year": 2026,
            "formula_id": "shapley_market_incidence_stable_bridge_v1",
            "mechanism_status": (
                "descriptive_observed_activity_and_realised_incidence_noncausal"
            ),
            "baseline_stable_share": _AGGREGATE_BASE,
            "comparison_stable_share": _AGGREGATE_BASE + total,
            "total_change": total,
            "established_market_baseline_stable_share": _ESTABLISHED_BASE,
            "established_market_comparison_stable_share": _ESTABLISHED_BASE + established,
            "established_market_total_change": established,
            "common_role_baseline_stable_share": COMMON_ROLE_BASE,
            "common_role_comparison_stable_share": COMMON_ROLE_BASE + common_role,
            "common_role_total_change": common_role,
            "identity_error": 0.0,
            **market_terms,
        }
    )
    return pd.DataFrame(rows)


# Class weights and stablecoin shares that satisfy every premise the renderer
# proves before publishing a support class. The weights partition each year; the
# common class carries ``common_role_*_stable_share`` by construction; the
# role-turnover share is solved so that the two both-years classes renormalise to
# ``established_market_*_stable_share``, and the market-turnover share so that
# the three-class mean is that year's aggregate. The 2024 side is stated because
# nothing upstream pins it; the 2026 side is solved from the bridge row, which
# now derives its own terms from the identity row, so the two stay consistent.
COMMON_ROLE_BASE = 0.24
_COMMON_2026 = COMMON_ROLE_BASE + _COMMON_ROLE_CHANGE
_ESTABLISHED_2026 = _ESTABLISHED_BASE + _ROLE_SUPPORT_BRIDGE + _COMMON_ROLE_CHANGE
_AGGREGATE_2026 = _AGGREGATE_BASE + sum(_MARKET_TERMS.values())
_WEIGHTS_2026 = {"common": 0.49, "market": 0.50, "role": 0.01}
_ROLE_STABLE_2026 = (
    (_WEIGHTS_2026["common"] + _WEIGHTS_2026["role"]) * _ESTABLISHED_2026
    - _WEIGHTS_2026["common"] * _COMMON_2026
) / _WEIGHTS_2026["role"]
_MARKET_STABLE_2026 = (
    _AGGREGATE_2026
    - _WEIGHTS_2026["common"] * _COMMON_2026
    - _WEIGHTS_2026["role"] * _ROLE_STABLE_2026
) / _WEIGHTS_2026["market"]
INCIDENCE_FIXTURE = {
    ("common_vehicle_role", 2024): (0.55, COMMON_ROLE_BASE),
    ("market_pair_support_turnover", 2024): (0.42, 0.055 / 0.42),
    ("vehicle_role_support_turnover_established_market", 2024): (0.03, 0.013 / 0.03),
    ("common_vehicle_role", 2026): (_WEIGHTS_2026["common"], _COMMON_2026),
    ("market_pair_support_turnover", 2026): (
        _WEIGHTS_2026["market"],
        _MARKET_STABLE_2026,
    ),
    ("vehicle_role_support_turnover_established_market", 2026): (
        _WEIGHTS_2026["role"],
        _ROLE_STABLE_2026,
    ),
}


def _support() -> pd.DataFrame:
    rows = []
    for (status, year), (weight, stable_share) in INCIDENCE_FIXTURE.items():
        primary = 4_000_000.0 * weight
        rows.append(
            {
                "record_type": "market_incidence_support",
                "metric": "count_share",
                "reporting_scope": "pooled",
                "endpoint_year": float(year),
                "support_status": status,
                "unit": "ordered_endpoint_pair",
                "units": max(1, round(200_000 * weight)),
                "primary_choice_mass": primary,
                "primary_choice_mass_share": weight,
                "stable_choice_mass": primary * stable_share,
                "stable_share": stable_share,
            }
        )
    # Rows the class reader must ignore and the coverage reader must use: the
    # same file carries the block-support ledger of the *other* factorisation.
    # Reading one of these as a Panel A class would break that partition, and
    # reading a Panel A class as a block would misprice the matched estimator's
    # reach. Both metrics' common shares are 0.60 and 0.50, the ``_row`` block
    # weights, because the coverage reader refuses any other partition.
    rows.extend(
        _decomposition_support_rows(
            "count_share", baseline_total=1_000_000.0, comparison_total=800_000.0
        )
    )
    rows.extend(
        _decomposition_support_rows(
            "strict_intermediation_value_share",
            baseline_total=1.0e10,
            comparison_total=4.0e9,
        )
    )
    # The estimator's own unit. These rows must reproduce the fixed-effects
    # exhibit's cells and endpoint masses exactly, so the fixture pins the
    # exhibit's 94,260 and 91,417 cells and its 150,000/200,000 and 3.0e9/1.0e9
    # masses. The one-sided classes then set the year denominators, and they are
    # deliberately asymmetric so a reader that swapped the two years would print
    # a different multiple rather than the same one twice.
    rows.extend(
        _cell_support_rows(
            "count_share",
            cells=94_260,
            baseline_only_cells=282_780,
            comparison_only_cells=94_260,
            baseline=(150_000.0, 150_000.0),
            comparison=(200_000.0, 600_000.0),
            emptied=0.0,
        )
    )
    for metric in ("matched_strict_count_share", "strict_intermediation_value_share"):
        rows.extend(
            _cell_support_rows(
                metric,
                cells=91_417,
                baseline_only_cells=274_251,
                comparison_only_cells=91_417,
                baseline=(3.0e9, 1.0e9),
                comparison=(1.0e9, 3.0e9),
                emptied=142_972.0,
            )
        )
    return pd.DataFrame(rows)


def _cell_support_rows(
    metric: str,
    *,
    cells: int,
    baseline_only_cells: int,
    comparison_only_cells: int,
    baseline: tuple[float, float],
    comparison: tuple[float, float],
    emptied: float,
) -> list[dict[str, object]]:
    """Three pair-day-scope classes: the matched cells and the two one-sided sets."""
    common_baseline, baseline_only_mass = baseline
    common_comparison, comparison_only_mass = comparison
    classes = {
        "baseline_only": (baseline_only_cells, baseline_only_mass, 0.0),
        "common": (cells, common_baseline, common_comparison),
        "comparison_only": (comparison_only_cells, 0.0, comparison_only_mass),
    }
    return [
        {
            "record_type": "pair_month_day_scope_support",
            "metric": metric,
            "reporting_scope": "scope_specific",
            "endpoint_year": None,
            "support_status": status,
            "unit": "ordered_endpoint_pair_month_day_integration_scope",
            "units": units,
            "baseline_denominator": baseline_mass,
            "comparison_denominator": comparison_mass,
            "baseline_denominator_share": None,
            "comparison_denominator_share": None,
            "zero_denominator_cell_years": emptied,
            "primary_choice_mass": None,
            "primary_choice_mass_share": None,
            "stable_choice_mass": None,
            "stable_share": None,
        }
        for status, (units, baseline_mass, comparison_mass) in classes.items()
    ]


# Pair counts and masses for the identity's three blocks. The block weights are
# fixed by ``_row``; only the year totals and the pair counts vary here, so a
# test that moves a share moves it away from the weight the identity published.
DECOMPOSITION_SUPPORT_UNITS = {
    "baseline_exclusive": 143_784,
    "common": 26_547,
    "comparison_exclusive": 69_686,
}


def _decomposition_support_rows(
    metric: str, *, baseline_total: float, comparison_total: float
) -> list[dict[str, object]]:
    masses = {
        "baseline_exclusive": (0.40 * baseline_total, 0.0),
        "common": (0.60 * baseline_total, 0.50 * comparison_total),
        "comparison_exclusive": (0.0, 0.50 * comparison_total),
    }
    return [
        {
            "record_type": "decomposition_pair_support",
            "metric": metric,
            "reporting_scope": "pooled",
            "endpoint_year": None,
            "support_status": status,
            "unit": "ordered_endpoint_pair",
            "units": DECOMPOSITION_SUPPORT_UNITS[status],
            "baseline_denominator": baseline,
            "comparison_denominator": comparison,
            "baseline_denominator_share": baseline / baseline_total,
            "comparison_denominator_share": comparison / comparison_total,
            "zero_denominator_cell_years": 0.0,
            "primary_choice_mass": None,
            "primary_choice_mass_share": None,
            "stable_choice_mass": None,
            "stable_share": None,
        }
        for status, (baseline, comparison) in masses.items()
    ]


def _fixed_effects() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "count_share",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "estimator_id": (
                    "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
                ),
                "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
                "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
                "estimand_scope": "common_pair_month_day_realised_integration_scope",
                "coefficient": 0.00224,
                "standard_error": 0.00764,
                "confidence_interval_lower": -0.01278,
                "confidence_interval_upper": 0.01726,
                "p_value_holm": 1.0,
                "observations": 188_520,
                "fixed_effect_cells": 94_260,
                "ordered_pair_clusters": 5_432,
                "calendar_date_clusters": 362,
                # 15.0% of the fixture's 2024 route mass and 25.0% of the
                # identity's common block; 25.0% and 50.0% in 2026.
                "baseline_denominator_mass": 150_000.0,
                "comparison_denominator_mass": 200_000.0,
            },
            {
                "metric": "strict_intermediation_value_share",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "estimator_id": (
                    "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
                ),
                "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
                "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
                "estimand_scope": "common_pair_month_day_realised_integration_scope",
                "coefficient": -0.01346,
                "standard_error": 0.02188,
                "confidence_interval_lower": -0.05649,
                "confidence_interval_upper": 0.02957,
                "p_value_holm": 1.0,
                "observations": 182_834,
                "fixed_effect_cells": 91_417,
                "ordered_pair_clusters": 5_278,
                "calendar_date_clusters": 362,
                # 30.0% of the fixture's 2024 dollar mass and 50.0% of the
                # block; 25.0% and 50.0% in 2026.
                "baseline_denominator_mass": 3.0e9,
                "comparison_denominator_mass": 1.0e9,
            },
        ]
    )


def _usdt_integration() -> pd.DataFrame:
    rows = []
    for weighting, support, total, within, between in (
        ("episode", "all_routes", 0.095, 0.089, 0.006),
        ("value", "within_20pct", 0.313, 0.268, 0.045),
    ):
        rows.append(
            {
                "record_type": "midpoint_decomposition",
                "focal_symbol": "USDT",
                "comparison_components": "native+USDC+USDT",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "weighting": weighting,
                "value_support": support,
                "total_usdt_share_change": total,
                "within_scope_change": within,
                "between_scope_composition_change": between,
                "within_scope_share_of_change": within / total,
                "between_scope_share_of_change": between / total,
                "identity_residual": 0.0,
            }
        )
    return pd.DataFrame(rows)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
UNLABELLED = "0x" + "ab" * 20
UNLABELLED_TWO = "0x" + "cd" * 20
# Activity weights of the five continuing pairs, keyed by ordered pair. They are
# a distribution over that year's continuing activity and therefore close on one
# in each year, which is what makes an endpoint class's weight readable as a
# share of routed activity. Two pairs have a stablecoin endpoint, one has
# neither a stablecoin nor WETH at an endpoint, and two have a WETH endpoint.
_COMMON_WEIGHTS = {
    (USDC, USDT): (0.30, 0.20),
    (UNLABELLED, USDT): (0.40, 0.30),
    (UNLABELLED_TWO, UNLABELLED): (0.10, 0.05),
    (USDT, WETH): (0.12, 0.25),
    (USDC, WETH): (0.08, 0.20),
}


def _common_weights(src: str, tgt: str) -> dict[str, float]:
    baseline, comparison = _COMMON_WEIGHTS[(src, tgt)]
    return {"weight_baseline": baseline, "weight_comparison": comparison}


def _contribution(
    component: str,
    src: str,
    tgt: str,
    contribution_pp: float,
    *,
    metric: str = "count_share",
    scope: str = "pooled",
    stable_baseline: float = 0.0,
    stable_comparison: float = 1.0,
    weight_baseline: float = 0.004,
    weight_comparison: float = 0.045,
    routes_baseline: float = 7_447.0,
    routes_comparison: float = 54_112.0,
    mass_share: float = 0.5,
) -> dict[str, object]:
    return {
        "metric": metric,
        "reporting_scope": scope,
        "baseline_year": 2024,
        "comparison_year": 2026,
        "src": src,
        "tgt": tgt,
        "stable_share_baseline": stable_baseline,
        "stable_share_comparison": stable_comparison,
        "pair_weight_baseline": weight_baseline,
        "pair_weight_comparison": weight_comparison,
        "denominator_baseline": routes_baseline,
        "denominator_comparison": routes_comparison,
        "contribution_component": component,
        "contribution_pp": contribution_pp,
        "aggregate_mass_share_midpoint": mass_share,
        "aggregate_total_change": 0.25,
        "allocation_scope": "pair_level_excludes_common_support_mass",
        "mechanism_status": "descriptive_pair_contribution_noncausal",
    }


# Per scope and metric: the open (choosable) share of the reweighting margin,
# the two WETH-endpoint contributions, and the two new-pair contributions. The
# reweighting entries sum to that scope's `_row` term (+8.0, +8.8, +9.6 pp under
# the 1.0/1.1/1.2 scaling), and the eligible share differs by scope in opposite
# directions across the two metrics, so a renderer that reported the pooled
# split under a scope macro would fail every scope assertion below.
#
# Each cohort of corridors traded in only one year is built from the same
# identity the renderer proves: a margin is that cohort's exclusive activity mass
# times its weighted stablecoin routing rate, with the WETH-endpoint corridors
# carrying a rate of exactly one. The mass differs by scope so a renderer that
# read the pooled cohort under a scope macro would fail, and the retiring cohort
# keeps its `$-3.4$ pp` total in every cell, split -1.0 locked and -2.4 open.
_COHORT_MASS = {"pooled": 0.5, "single_venue": 0.4, "cross_venue": 0.6}
_EXIT_LOCKED_PP = -1.0
_EXIT_OPEN_PP = -2.4
_SCOPE_CONTRIBUTIONS = {
    ("pooled", "count_share"): (4.5, 2.0, 1.5, 0.13, 20.87),
    ("pooled", "strict_intermediation_value_share"): (-1.0, 6.0, 3.0, 1.0, 20.0),
    ("single_venue", "count_share"): (6.8, 1.2, 0.8, 5.0, 16.0),
    ("single_venue", "strict_intermediation_value_share"): (0.8, 5.0, 3.0, 5.0, 16.0),
    ("cross_venue", "count_share"): (1.6, 5.0, 3.0, 15.0, 6.0),
    ("cross_venue", "strict_intermediation_value_share"): (3.6, 4.0, 2.0, 15.0, 6.0),
}


def _contributions() -> pd.DataFrame:
    """Reproduce the aggregate terms of `_row` from named and unlabelled pairs.

    `_row` sets within_common to -0.1 pp, exclusive_pair_contribution to
    +17.6 pp, and common_pair_reweighting to +8.0 pp pooled, rising with the
    per-scope scaling. The unlabelled rows carry the bulk of each margin so the
    renderer must report the margin total separately from the named example it
    prints.

    Five ordered pairs trade in both years. Three have no WETH endpoint and can
    move their own stablecoin share; two have a WETH endpoint, so native WETH is
    ineligible as their intermediary, their stablecoin share is one in both
    years, and their within-pair contribution is exactly zero. The fixture
    respects that identity because the data do, in every scope.

    The dollar-weighted allocation reaches each margin total from a different
    spread of pairs, so breadth and eligibility are never read off the count.
    """
    value = "strict_intermediation_value_share"
    within = {
        "count_share": (0.05, 0.40, -0.55),
        value: (0.30, 0.10, -0.50),
    }

    def locked(component: str, src: str, tgt: str, pp: float, **kwargs) -> dict:
        return _contribution(
            component,
            src,
            tgt,
            pp,
            stable_baseline=1.0,
            stable_comparison=1.0,
            **kwargs,
        )

    rows: list[dict[str, object]] = []
    for (scope, metric), split in _SCOPE_CONTRIBUTIONS.items():
        open_reweight, locked_usdt, locked_usdc, new_named, new_unlabelled = split
        first, second, third = within[metric]
        rows.extend(
            [
                _contribution(
                    "within_pair_choice",
                    USDC,
                    USDT,
                    first,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDC, USDT),
                ),
                _contribution(
                    "within_pair_choice",
                    UNLABELLED,
                    USDT,
                    second,
                    metric=metric,
                    scope=scope,
                    **_common_weights(UNLABELLED, USDT),
                ),
                _contribution(
                    "within_pair_choice",
                    UNLABELLED_TWO,
                    UNLABELLED,
                    third,
                    metric=metric,
                    scope=scope,
                    **_common_weights(UNLABELLED_TWO, UNLABELLED),
                ),
                locked(
                    "within_pair_choice",
                    USDT,
                    WETH,
                    0.0,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDT, WETH),
                ),
                locked(
                    "within_pair_choice",
                    USDC,
                    WETH,
                    0.0,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDC, WETH),
                ),
                _contribution(
                    "pair_composition_reweighting",
                    USDC,
                    USDT,
                    0.0,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDC, USDT),
                ),
                _contribution(
                    "pair_composition_reweighting",
                    UNLABELLED,
                    USDT,
                    open_reweight,
                    metric=metric,
                    scope=scope,
                    **_common_weights(UNLABELLED, USDT),
                ),
                _contribution(
                    "pair_composition_reweighting",
                    UNLABELLED_TWO,
                    UNLABELLED,
                    0.0,
                    metric=metric,
                    scope=scope,
                    **_common_weights(UNLABELLED_TWO, UNLABELLED),
                ),
                locked(
                    "pair_composition_reweighting",
                    USDT,
                    WETH,
                    locked_usdt,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDT, WETH),
                ),
                locked(
                    "pair_composition_reweighting",
                    USDC,
                    WETH,
                    locked_usdc,
                    metric=metric,
                    scope=scope,
                    **_common_weights(USDC, WETH),
                ),
                *_cohort(
                    "comparison_exclusive_composition",
                    metric=metric,
                    scope=scope,
                    named=(USDT, USDC, new_named),
                    locked_pp=new_unlabelled,
                ),
                *_cohort(
                    "baseline_exclusive_composition",
                    metric=metric,
                    scope=scope,
                    named=(UNLABELLED, USDC, _EXIT_OPEN_PP),
                    locked_pp=_EXIT_LOCKED_PP,
                ),
            ]
        )
    return pd.DataFrame(rows)


def _cohort(
    component: str,
    *,
    metric: str,
    scope: str,
    named: tuple[str, str, float],
    locked_pp: float,
) -> list[dict[str, object]]:
    """One exclusive-support cohort that satisfies the cohort identity.

    The cohort's weights close on one and each corridor's contribution is its
    weight times its stablecoin routing rate times the cohort's exclusive
    activity mass, exactly as the ledger builds them. The WETH-endpoint corridor
    routes at one by construction; the open corridors' rate is whatever the
    remaining contribution implies.

    The open side is carried by two corridors at the same routing rate, one with
    a stablecoin endpoint and one with neither a stablecoin nor WETH at an
    endpoint, so the entry margin exercises both endpoint classes. Splitting a
    single corridor's weight and contribution in the same proportion leaves the
    cohort's weighted rate, and therefore every cohort identity, untouched.
    """
    entering = component == "comparison_exclusive_composition"
    mass = _COHORT_MASS[scope]
    source, target, open_pp = named
    locked_weight = abs(locked_pp) / (100 * mass)
    open_weight = 1.0 - locked_weight
    open_share = abs(open_pp) / (100 * mass * open_weight)
    stable_fraction = 0.6
    weights = (
        {"weight_comparison": locked_weight, "weight_baseline": 0.0}
        if entering
        else {"weight_baseline": locked_weight, "weight_comparison": 0.0}
    )
    shares = (
        {"stable_comparison": 1.0, "stable_baseline": 0.0}
        if entering
        else {"stable_baseline": 1.0, "stable_comparison": 0.0}
    )
    def open_corridor(
        src: str, tgt: str, fraction: float
    ) -> dict[str, object]:
        return _contribution(
            component,
            src,
            tgt,
            fraction * open_pp,
            metric=metric,
            scope=scope,
            mass_share=mass,
            **(
                {
                    "weight_comparison": fraction * open_weight,
                    "weight_baseline": 0.0,
                    "stable_comparison": open_share,
                    "stable_baseline": 0.0,
                }
                if entering
                else {
                    "weight_baseline": fraction * open_weight,
                    "weight_comparison": 0.0,
                    "stable_baseline": open_share,
                    "stable_comparison": 0.0,
                }
            ),
        )

    return [
        open_corridor(source, target, stable_fraction),
        open_corridor(UNLABELLED_TWO, UNLABELLED, 1.0 - stable_fraction),
        _contribution(
            component,
            UNLABELLED,
            WETH,
            locked_pp,
            metric=metric,
            scope=scope,
            mass_share=mass,
            **weights,
            **shares,
        ),
    ]


def test_renderer_emits_complete_display_and_coordinate_macros() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro in (
        "PairPooledBase",
        "PairPooledEnd",
        "PairPooledTotal",
        "PairPooledReweight",
        "PairPooledSupportMass",
        "PairPooledExclusive",
        "PairPooledWithin",
        "PairPooledBaseRawPct",
        "PairPooledEndRawPct",
        "PairPooledReweightRawPP",
        "PairPooledSupportMassRawPP",
        "PairPooledExclusiveRawPP",
        "PairPooledWithinRawPP",
        "PairSingleTotal",
        "PairSingleWithin",
        "PairCrossTotal",
        "PairCrossWithin",
        "PairValueTotal",
        "PairValueWithin",
        "PairValueReweight",
        "PairValueSupportMass",
        "PairValueExclusive",
        "MarketBridgeBase",
        "MarketBridgeEnd",
        "MarketBridgeTotal",
        "MarketSupportBridge",
        "VehicleRoleSupportBridge",
        "MarketActivityReweight",
        "VehicleIncidenceReweight",
        "WithinPairStableShare",
        "ObservedBothYearsBase",
        "ObservedBothYearsEnd",
        "ObservedBothYearsTotal",
        "CommonRoleTotal",
        "PairActivityTotal",
        "VehicleUseNet",
        "PairAndVehicleTotal",
        "PairAndVehicleShare",
        "MarketBridgeBaseRawPct",
        "MarketSupportBridgeRawPP",
        "VehicleRoleSupportBridgeRawPP",
        "MarketActivityReweightRawPP",
        "VehicleIncidenceReweightRawPP",
        "WithinPairStableShareRawPP",
        "PairActivityTotalRawPP",
        "VehicleUseNetRawPP",
        "PairAndVehicleTotalRawPP",
        "MatchedMarketCountChange",
        "MatchedMarketCountSE",
        "MatchedMarketCountCILower",
        "MatchedMarketCountCIUpper",
        "MatchedMarketCountChangeRawPP",
        "MatchedMarketCountCILowerRawPP",
        "MatchedMarketCountCIUpperRawPP",
        "MatchedMarketValueChange",
        "MatchedMarketValueSE",
        "MatchedMarketValueCILower",
        "MatchedMarketValueCIUpper",
        "USDTVenueMixCountShare",
        "USDTVenueWithinCountShare",
        "USDTVenueMixValueShare",
        "USDTVenueWithinValueShare",
    ):
        assert f"\\newcommand{{\\{macro}}}" in rendered
    assert "\\newcommand{\\PairPooledWithin}{$-0.1$ pp}" in rendered
    assert "\\newcommand{\\PairPooledExclusive}{$+17.6$ pp}" in rendered
    assert "\\newcommand{\\PairActivityTotal}{$+19.0$ pp}" in rendered
    assert "\\newcommand{\\VehicleUseNet}{$+4.6$ pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleTotal}{$+23.6$ pp}" in rendered
    assert "\\newcommand{\\PairAndVehicleShare}{94.4\\%}" in rendered
    assert "\\newcommand{\\MatchedMarketCountChange}{$+0.2$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountSE}{$0.8$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountCILower}{$-1.3$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketCountCIUpper}{$+1.7$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueChange}{$-1.3$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueSE}{$2.2$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueCILower}{$-5.6$ pp}" in rendered
    assert "\\newcommand{\\MatchedMarketValueCIUpper}{$+3.0$ pp}" in rendered
    assert "\\newcommand{\\USDTVenueMixCountShare}{6.3\\%}" in rendered
    assert "\\newcommand{\\USDTVenueWithinCountShare}{93.7\\%}" in rendered
    assert "\\newcommand{\\USDTVenueMixValueShare}{14.4\\%}" in rendered
    assert "\\newcommand{\\USDTVenueWithinValueShare}{85.6\\%}" in rendered
    assert "generation" not in rendered.lower()


def test_margin_examples_name_labelled_pairs_and_report_the_margin_total() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        ("MarginWithinPair", "USDC\\,$\\to$\\,USDT"),
        ("MarginWithinContribution", "$+0.05$ pp"),
        ("MarginWithinTotal", "$-0.1$ pp"),
        ("MarginReweightPair", "USDT\\,$\\to$\\,WETH"),
        ("MarginReweightContribution", "$+2.00$ pp"),
        ("MarginReweightTotal", "$+8.0$ pp"),
        ("MarginNewPairPair", "USDT\\,$\\to$\\,USDC"),
        ("MarginNewPairContribution", "$+0.08$ pp"),
        ("MarginNewPairTotal", "$+21.0$ pp"),
        ("MarginRetiredPairTotal", "$-3.4$ pp"),
        ("MarginReweightRoutesBase", "7,447"),
        ("MarginReweightRoutesEnd", "54,112"),
        ("MarginReweightWeightBase", "12.00\\%"),
        ("MarginReweightWeightEnd", "25.00\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered
    # An unlabelled endpoint is never printed, even when it dominates its margin.
    assert "0xab" not in rendered


def test_margin_examples_reject_contributions_that_miss_the_aggregate_term() -> None:
    contributions = _contributions()
    reweighting = contributions["contribution_component"].eq(
        "pair_composition_reweighting"
    )
    contributions.loc[reweighting, "contribution_pp"] *= 2
    with pytest.raises(ValueError, match="do not reconcile common_pair_reweighting"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_margin_examples_reject_a_causal_mechanism_label() -> None:
    contributions = _contributions()
    contributions["mechanism_status"] = "causal_pair_contribution"
    with pytest.raises(ValueError, match="causal mechanism label"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_margin_examples_require_a_labelled_positive_contributor() -> None:
    contributions = _contributions()
    within = contributions["contribution_component"].eq("within_pair_choice")
    contributions.loc[within, "src"] = UNLABELLED
    with pytest.raises(
        ValueError, match="within_pair_choice has no labelled positive contributor"
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(frame.index[-1]), "exactly one"),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "exactly one",
        ),
        (
            lambda frame: frame.assign(
                identity_error=frame["identity_error"].where(frame.index != 0, 1e-6)
            ),
            "identity error",
        ),
        (
            lambda frame: frame.assign(
                support_and_exclusive_joint=frame["support_and_exclusive_joint"].where(
                    frame.index != 0, 0.0
                )
            ),
            "joint support term",
        ),
    ],
)
def test_renderer_fails_closed_on_incomplete_or_inconsistent_accounting(
    mutation, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        render_pair_decomposition_deck_values(
            mutation(_decomposition()), _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_renderer_fails_closed_when_market_incidence_bridge_is_inconsistent() -> None:
    frame = _decomposition()
    market = frame["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
    frame.loc[market, "market_activity_reweighting"] += 0.01
    with pytest.raises(ValueError, match="total change"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_margin_breadth_counts_pairs_and_splits_gains_from_losses() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        # Two pairs gain and one loses within continuing pairs, so the -0.1 pp
        # margin total is an offset rather than an absence of movement.
        ("MarginWithinGainPairs", "2"),
        ("MarginWithinLossPairs", "1"),
        ("MarginWithinGrossUp", "$+0.5$ pp"),
        ("MarginWithinGrossDown", "$-0.6$ pp"),
        ("MarginReweightGainPairs", "3"),
        ("MarginReweightLossPairs", "0"),
        ("MarginReweightGrossUp", "$+8.0$ pp"),
        ("MarginReweightHalfPairs", "1"),
        ("MarginReweightNinetyPairs", "3"),
        ("MarginNewPairGainPairs", "3"),
        ("MarginNewPairTopShare", "99.4\\%"),
        ("MarginNewPairHalfPairs", "1"),
        # Dollar weighting reaches the same totals from a different spread.
        ("MarginWithinValueGainPairs", "2"),
        ("MarginWithinValueGrossUp", "$+0.4$ pp"),
        ("MarginWithinValueGrossDown", "$-0.5$ pp"),
        ("MarginReweightValueLossPairs", "1"),
        ("MarginReweightValueGrossUp", "$+9.0$ pp"),
        ("MarginReweightValueGrossDown", "$-1.0$ pp"),
        ("MarginNewPairValueTopShare", "95.2\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_margin_breadth_reconciles_the_value_margins_it_reports() -> None:
    contributions = _contributions()
    value_reweighting = contributions["metric"].eq(
        "strict_intermediation_value_share"
    ) & contributions["contribution_component"].eq("pair_composition_reweighting")
    contributions.loc[value_reweighting, "contribution_pp"] += 1.0
    with pytest.raises(
        ValueError,
        match="strict_intermediation_value_share pair_composition_reweighting",
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_margin_breadth_requires_the_dollar_weighted_allocation() -> None:
    contributions = _contributions()
    contributions = contributions[
        contributions["metric"].ne("strict_intermediation_value_share")
    ]
    with pytest.raises(ValueError, match="no pooled 2024--2026"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_endpoint_eligibility_splits_the_two_composition_margins() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        # Two of five continuing pairs have a WETH endpoint, and their weight in
        # routed activity rises, so they move the aggregate through composition
        # alone: +3.5 pp of the +8.0 pp reweighting margin. The five continuing
        # pairs' weights are a distribution over each year's activity, so these
        # two shares are readable as shares of routed activity.
        ("LockedPairs", "2"),
        ("LockedCommonPairs", "5"),
        ("LockedPairShare", "40.0\\%"),
        ("LockedWeightBase", "20.0\\%"),
        ("LockedWeightEnd", "45.0\\%"),
        ("LockedReweight", "$+3.5$ pp"),
        ("OpenReweight", "$+4.5$ pp"),
        ("LockedReweightShare", "43.8\\%"),
        ("LockedNewPair", "$+20.9$ pp"),
        ("OpenNewPair", "$+0.1$ pp"),
        # Dollar weighting sends the split the other way: the eligible corridors
        # supply more than the whole margin because the rest of it is negative.
        ("LockedValueReweight", "$+9.0$ pp"),
        ("OpenValueReweight", "$-1.0$ pp"),
        ("LockedValueReweightShare", "112.5\\%"),
        ("LockedValueNewPairShare", "95.2\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_endpoint_eligibility_is_taken_inside_each_integration_scope() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        # Each scope carries its own reweighting total and its own eligible
        # share of it. By count the eligible corridors dominate across venues
        # and not within one; by value the ordering reverses. Neither number is
        # the pooled 43.8% / 112.5% split, so a scope macro cannot be silently
        # fed the pooled allocation.
        ("PairSingleReweight", "$+8.8$ pp"),
        ("LockedSingleReweight", "$+2.0$ pp"),
        ("LockedSingleReweightShare", "22.7\\%"),
        ("PairCrossReweight", "$+9.6$ pp"),
        ("LockedCrossReweight", "$+8.0$ pp"),
        ("LockedCrossReweightShare", "83.3\\%"),
        ("PairValueSingleReweight", "$+8.8$ pp"),
        ("LockedValueSingleReweightShare", "90.9\\%"),
        ("PairValueCrossReweight", "$+9.6$ pp"),
        ("LockedValueCrossReweightShare", "62.5\\%"),
        # The new-pair margin splits by scope too.
        ("LockedSingleNewPairShare", "76.2\\%"),
        ("LockedCrossNewPairShare", "28.6\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_scope_new_pair_total_is_the_gross_entry_margin() -> None:
    """The entry margin has no decomposition term of its own.

    ``exclusive_pair_contribution`` nets the pairs that stopped trading against
    the ones that started, while the eligibility split is taken of the gross
    entry margin alone. A scope total read from that term would understate the
    margin its own eligible share is a share of, so the renderer takes the total
    from the split's own components and only the reweighting total from the row.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for suffix in ("Single", "Cross"):
        for infix in ("", "Value"):
            locked = _macro(rendered, f"Locked{infix}{suffix}NewPair")
            opened = _macro(rendered, f"Open{infix}{suffix}NewPair")
            total = _macro(rendered, f"Pair{infix}{suffix}NewPair")
            assert _points(locked) + _points(opened) == pytest.approx(_points(total))
            # The fixture's netted exclusive term is +17.6 pp against a gross
            # entry margin of +21.0 pp, so the two cannot be confused silently.
            assert total != "$+17.6$ pp"
    # The reweighting total still comes from the scope's own decomposition row,
    # against which the producer reconciles the split.
    assert _macro(rendered, "PairSingleReweight") == "$+8.8$ pp"


def test_support_cohorts_reads_the_netted_term_as_corridor_replacement() -> None:
    """One exclusive activity mass, two cohorts, and the routing rate of each.

    The netted exclusive-pair term is the mass times the gap between the two
    cohorts' rates, so the renderer must publish all three and they must close.
    The exiting cohort's margin is negative, which is exactly the case the
    positive-margin eligibility guard refuses to interpret.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for infix in ("", "Value"):
        for suffix, scope in (("", "pooled"), ("Single", "single_venue"), ("Cross", "cross_venue")):
            mass = _COHORT_MASS[scope]
            exit_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Exit"))
            enter_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Enter"))
            net_pp = _points(_macro(rendered, f"Cohort{infix}{suffix}Net"))
            assert exit_pp == pytest.approx(-3.4)
            assert enter_pp == pytest.approx(21.0)
            assert exit_pp + enter_pp == pytest.approx(net_pp)
            # The netted term, never the gross entry margin.
            assert net_pp == pytest.approx(17.6)
            assert _macro(rendered, f"Cohort{infix}{suffix}Mass") == f"{100 * mass:.1f}\\%"
            # Each cohort's margin is its own mass times its own routing rate.
            for prefix, pp in (("Exit", exit_pp), ("Enter", enter_pp)):
                rate = _macro(rendered, f"Cohort{infix}{suffix}{prefix}Share")
                assert abs(pp) == pytest.approx(
                    mass * float(rate.replace("\\%", "")), abs=0.05
                )
    # The retiring cohort routes at 6.8% pooled against the arriving cohort's
    # 42.0%; strip the WETH-endpoint corridors and both rates fall, which is the
    # whole point of publishing the open rate beside the cohort rate.
    assert _macro(rendered, "CohortExitShare") == "6.8\\%"
    assert _macro(rendered, "CohortEnterShare") == "42.0\\%"
    assert _macro(rendered, "CohortExitOpenShare") == "4.9\\%"
    assert _macro(rendered, "CohortEnterOpenShare") == "0.4\\%"
    assert _macro(rendered, "CohortEnterOpenWeight") == "58.3\\%"
    # A scope's cohorts are read inside that scope, never off the pooled rows.
    assert _macro(rendered, "CohortCrossEnterOpenShare") == "27.8\\%"


def test_support_cohorts_rejects_a_margin_that_is_not_mass_times_routing() -> None:
    contributions = _contributions()
    # Only the open corridor moves, so the WETH-endpoint identity still holds and
    # the failure is the cohort arithmetic rather than its structure.
    entering = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    ) & contributions["tgt"].eq(USDC)
    contributions.loc[entering, "stable_share_comparison"] *= 0.5
    with pytest.raises(ValueError, match="activity mass times its routing rate"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_support_cohorts_rejects_cohorts_that_carry_different_activity_mass() -> None:
    """Without a common mass the two rates are not comparable, only their sum is."""
    contributions = _contributions()
    entering = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    )
    contributions.loc[entering, "aggregate_mass_share_midpoint"] = 0.25
    with pytest.raises(ValueError, match="different activity mass"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_support_cohorts_rejects_an_eligibility_split_that_straddles_zero() -> None:
    """A share of a margin whose parts disagree in sign is not a share of it."""
    contributions = _contributions()
    retiring = contributions["contribution_component"].eq(
        "baseline_exclusive_composition"
    )
    locked = retiring & contributions["tgt"].eq(WETH)
    contributions.loc[locked, "contribution_pp"] = 2.0
    contributions.loc[retiring & ~locked, "contribution_pp"] = -2.7
    with pytest.raises(ValueError, match="straddles zero"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_support_cohorts_rejects_a_switching_weth_endpoint_cohort_corridor() -> None:
    contributions = _contributions()
    locked = contributions["contribution_component"].eq(
        "baseline_exclusive_composition"
    ) & contributions["tgt"].eq(WETH)
    contributions.loc[locked, "stable_share_baseline"] = 0.5
    with pytest.raises(ValueError, match="eligibility identity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_support_mass_term_is_published_as_a_shift_times_a_block_gap() -> None:
    """The fourth term's two factors, and the blocks they are formed from."""
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        # A 10 pp migration of activity out of the common block, priced at the
        # 5 pp midpoint gap between the two blocks' routing rates.
        ("BlockTerm", "$-0.5$ pp"),
        ("BlockShift", "$-10.0$ pp"),
        ("BlockGap", "$+5.0$ pp"),
        ("BlockWeightBase", "60.0\\%"),
        ("BlockWeightEnd", "50.0\\%"),
        ("BlockCommonBase", "22.4\\%"),
        ("BlockCommonEnd", "47.0\\%"),
        ("BlockCommonMid", "34.7\\%"),
        ("BlockExclusiveMid", "29.7\\%"),
        # Every scope and both weightings carry the same factorisation.
        ("BlockSingleGap", "$+5.0$ pp"),
        ("BlockCrossGap", "$+5.0$ pp"),
        ("BlockValueTerm", "$-0.5$ pp"),
        ("BlockValueShift", "$-10.0$ pp"),
        ("BlockValueCrossShift", "$-10.0$ pp"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered
    # The published factors multiply back to the published term.
    assert (
        pytest.approx(
            _points(_macro(rendered, "BlockShift"))
            * _points(_macro(rendered, "BlockGap"))
            / 100,
            abs=1e-9,
        )
        == _points(_macro(rendered, "BlockTerm"))
    )


def test_support_mass_requires_blocks_that_partition_the_year() -> None:
    """A gap between blocks prices a mass shift only if the blocks exhaust it."""
    frame = _decomposition()
    scoped = frame["formula_id"].eq("midpoint_common_exclusive_support_v1")
    frame.loc[scoped, "E_baseline"] += 0.05
    with pytest.raises(ValueError, match="do not partition activity"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_support_mass_requires_blocks_that_reconcile_their_own_year() -> None:
    frame = _decomposition()
    scoped = frame["formula_id"].eq("midpoint_common_exclusive_support_v1")
    frame.loc[scoped, "S_C_comparison"] += 0.05
    with pytest.raises(ValueError, match="do not reconcile that"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_support_mass_rejects_factors_that_miss_their_own_term() -> None:
    """Compensating block shares keep both years' means and move only the gap."""
    frame = _decomposition()
    scoped = frame["formula_id"].eq("midpoint_common_exclusive_support_v1")
    frame.loc[scoped, "S_C_baseline"] += 0.02
    frame.loc[scoped, "S_E_baseline"] -= 0.03
    with pytest.raises(ValueError, match="do not multiply to the term"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_support_mass_requires_the_block_columns() -> None:
    frame = _decomposition().drop(columns=["S_E_comparison"])
    with pytest.raises(ValueError, match="missing columns: S_E_comparison"):
        render_pair_decomposition_deck_values(
            frame, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_endpoint_eligibility_rejects_a_scope_split_against_another_scope() -> None:
    """A scope's allocation must reconcile that scope's own aggregate term."""
    contributions = _contributions()
    cross_reweighting = (
        contributions["reporting_scope"].eq("cross_venue")
        & contributions["metric"].eq("count_share")
        & contributions["contribution_component"].eq("pair_composition_reweighting")
        & contributions["src"].eq(UNLABELLED)
    )
    contributions.loc[cross_reweighting, "contribution_pp"] -= 1.6
    with pytest.raises(
        ValueError, match="cross_venue eligibility split does not reconcile"
    ):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_endpoint_eligibility_requires_the_scope_specific_allocation() -> None:
    contributions = _contributions()
    contributions = contributions[contributions["reporting_scope"].ne("cross_venue")]
    with pytest.raises(ValueError, match="no cross_venue 2024--2026"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_endpoint_eligibility_rejects_a_switching_weth_endpoint_pair() -> None:
    contributions = _contributions()
    locked = contributions["contribution_component"].eq("within_pair_choice") & (
        contributions["tgt"].eq(WETH)
    )
    contributions.loc[locked, "stable_share_baseline"] = 0.5
    with pytest.raises(ValueError, match="eligibility identity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_endpoint_eligibility_rejects_within_pair_movement_on_an_eligible_pair() -> None:
    contributions = _contributions()
    within = contributions["contribution_component"].eq("within_pair_choice")
    # Move the movement onto an eligible pair rather than inventing it, so the
    # margin still reconciles and only the eligibility guard can reject it.
    contributions.loc[within & contributions["tgt"].eq(WETH), "contribution_pp"] = 0.01
    contributions.loc[within & contributions["src"].eq(USDC) & contributions["tgt"].eq(
        USDT
    ), "contribution_pp"] -= 0.02
    with pytest.raises(ValueError, match="eligibility identity forbids"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def _stable_endpoint_common(contributions: pd.DataFrame) -> pd.Series:
    """The continuing pairs with a stablecoin, and no WETH, at an endpoint."""
    within = contributions["contribution_component"].eq("within_pair_choice")
    weth = contributions["src"].eq(WETH) | contributions["tgt"].eq(WETH)
    stable = contributions["src"].isin((USDC, USDT)) | contributions["tgt"].isin(
        (USDC, USDT)
    )
    return within & ~weth & stable


def test_open_corridor_endpoints_split_the_choice_live_remainder() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        # Three continuing pairs have no WETH endpoint. Two hold a stablecoin at
        # an endpoint and carry seven-tenths of 2024 activity; one holds neither
        # candidate and carries a tenth. Their contributions are shares of the
        # whole margin, so each class sits beside the eligible share of the same
        # margin: 56.2 + 0.0 + 43.8 closes on the reweighting margin.
        ("StableEndPairs", "2"),
        ("OtherEndPairs", "1"),
        ("StableEndWeightBase", "70.0\\%"),
        ("StableEndWeightEnd", "50.0\\%"),
        ("OtherEndWeightBase", "10.0\\%"),
        ("StableEndReweight", "$+4.5$ pp"),
        ("StableEndReweightShare", "56.2\\%"),
        ("OtherEndReweightShare", "0.0\\%"),
        ("StableEndWithin", "$+0.5$ pp"),
        ("OtherEndWithin", "$-0.6$ pp"),
        # Both endpoint classes carry part of the entry margin, so a renderer
        # that dropped either class's rows would miss one of these.
        ("StableEndNewPairPairs", "1"),
        ("OtherEndNewPairPairs", "1"),
        ("StableEndNewPairShare", "0.4\\%"),
        ("OtherEndNewPairShare", "0.2\\%"),
        # A margin whose choice-live remainder is negative still reports each
        # class as a signed share of the positive margin rather than of the
        # remainder, which would not be a readable base.
        ("StableEndValueReweight", "$-1.0$ pp"),
        ("StableEndValueReweightShare", "-12.5\\%"),
    ):
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered


def test_open_corridor_endpoints_require_classes_that_exhaust_the_year() -> None:
    """A class weight is only a share of routed activity if the classes close."""
    contributions = _contributions()
    within = contributions["contribution_component"].eq("within_pair_choice")
    contributions.loc[
        within & contributions["src"].eq(USDC) & contributions["tgt"].eq(USDT),
        "pair_weight_baseline",
    ] = 0.20
    with pytest.raises(ValueError, match="do not exhaust that year's activity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_open_corridor_endpoints_reject_a_stablecoin_eligibility_class() -> None:
    """A stablecoin endpoint must leave the intermediary a live choice.

    The whole point of the split is that these corridors could have been routed
    either way. If every one of them routed through a stablecoin in both years,
    the endpoint would be forcing the intermediary exactly as a WETH endpoint
    does, and the class share would be an accounting rule rather than a fact
    about how traders routed.
    """
    contributions = _contributions()
    live = _stable_endpoint_common(contributions)
    contributions.loc[live, "stable_share_baseline"] = 1.0
    contributions.loc[live, "stable_share_comparison"] = 1.0
    with pytest.raises(ValueError, match="forcing the intermediary"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_open_corridor_endpoints_reject_a_pinned_stablecoin_majority() -> None:
    """Most of the class pinned at one is close enough to the identity to refuse."""
    contributions = _contributions()
    live = _stable_endpoint_common(contributions)
    pinned = live & contributions["src"].eq(USDC) & contributions["tgt"].eq(USDT)
    contributions.loc[pinned, "stable_share_baseline"] = 1.0
    contributions.loc[pinned, "stable_share_comparison"] = 1.0
    with pytest.raises(ValueError, match="pinned at a stablecoin share of one"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_open_corridor_endpoints_reject_a_frozen_within_pair_term() -> None:
    """A class with no within-pair movement at all behaves like the locked one."""
    contributions = _contributions()
    live = _stable_endpoint_common(contributions)
    other = (
        contributions["contribution_component"].eq("within_pair_choice")
        & contributions["src"].eq(UNLABELLED_TWO)
    )
    gain = live & contributions["src"].eq(USDC) & contributions["tgt"].eq(USDT)
    loss = live & contributions["src"].eq(UNLABELLED) & contributions["tgt"].eq(USDT)
    # Offset the class to exactly zero and move what it carried onto the other
    # open class. Its two pairs still move in opposite directions, so a labelled
    # positive contributor survives and the within-pair total still reconciles:
    # only the non-degeneracy guard can reject the result.
    for scope in ("pooled", "single_venue", "cross_venue"):
        for metric in ("count_share", "strict_intermediation_value_share"):
            cell = contributions["reporting_scope"].eq(scope) & contributions[
                "metric"
            ].eq(metric)
            moved = float(contributions.loc[live & cell, "contribution_pp"].sum())
            contributions.loc[gain & cell, "contribution_pp"] = 0.5
            contributions.loc[loss & cell, "contribution_pp"] = -0.5
            contributions.loc[other & cell, "contribution_pp"] += moved
    with pytest.raises(ValueError, match="within-pair term is exactly zero"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_cohort_endpoint_margins_split_replacement_into_composition_and_rate() -> None:
    """Why the two cohorts route differently: different markets, or different routing.

    The corridor-replacement gap is decomposed exactly on the three endpoint
    classes, so the two published terms must sum to the netted exclusive term
    and their shares of it to one. The wrapped-ether class is the premise that
    gives the split its economics: its routing rate is one in *both* cohorts, so
    it can move the margin only through weight and its rate term must be zero.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for infix in ("", "Value"):
        net_pp = _points(_macro(rendered, f"Cohort{infix}Net"))
        composition = _points(_macro(rendered, f"Replace{infix}Composition"))
        rate = _points(_macro(rendered, f"Replace{infix}Rate"))
        assert composition + rate == pytest.approx(net_pp, abs=0.05)
        shares = [
            float(_macro(rendered, f"Replace{infix}{stem}Share").replace("\\%", ""))
            for stem in ("Composition", "Rate")
        ]
        assert sum(shares) == pytest.approx(100.0, abs=0.1)
        # Each class's two terms, and the class totals that must rebuild them.
        class_composition = 0.0
        class_rate = 0.0
        for name in ("Locked", "StableEnd", "OtherEnd"):
            class_composition += _points(_macro(rendered, f"Replace{infix}{name}Composition"))
            class_rate += _points(_macro(rendered, f"Replace{infix}{name}Rate"))
            for suffix in ("Exit", "Enter"):
                weight = _macro(rendered, f"Replace{infix}{name}{suffix}Weight")
                assert 0 < float(weight.replace("\\%", "")) < 100
        # Three rounded cells rebuild one rounded total, so the tolerance is the
        # rounding and nothing looser.
        assert class_composition == pytest.approx(composition, abs=0.2)
        assert class_rate == pytest.approx(rate, abs=0.2)
        # The eligibility identity, and therefore a class that is pure composition.
        for suffix in ("Exit", "Enter"):
            assert _macro(rendered, f"Replace{infix}Locked{suffix}Rate") == "100.0\\%"
        assert _points(_macro(rendered, f"Replace{infix}LockedRate")) == pytest.approx(0.0)
    # The arriving cohort is 41.7% wrapped-ether-paired against 2.0% for the one
    # it replaced, which alone carries $+19.9$ pp of the $+17.6$ pp netted term.
    assert _macro(rendered, "ReplaceLockedExitWeight") == "2.0\\%"
    assert _macro(rendered, "ReplaceLockedEnterWeight") == "41.7\\%"
    assert _macro(rendered, "ReplaceLockedComposition") == "$+19.9$ pp"
    assert _macro(rendered, "ReplaceStableEndEnterRate") == "0.4\\%"
    assert _macro(rendered, "ReplaceStableEndExitRate") == "4.9\\%"


def test_cohort_endpoint_margins_require_every_class_in_both_cohorts() -> None:
    """A class absent from one cohort has no rate there, so no gap to attribute."""
    contributions = _contributions()
    arriving = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    ) & contributions["src"].eq(UNLABELLED_TWO)
    # Move the arriving cohort's other-endpoint corridor onto its stablecoin-
    # endpoint pair. The cohort's own weights, rate and margin are untouched, so
    # only the class partition can reject the result.
    contributions.loc[arriving, "src"] = USDT
    contributions.loc[arriving, "tgt"] = USDC
    with pytest.raises(ValueError, match="carries no OtherEnd activity"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), contributions, _support()
        )


def test_cohort_endpoint_margins_reject_a_stablecoin_eligibility_class() -> None:
    """If a stablecoin endpoint forced the vehicle, the rate term would be a rule.

    The fixture's two open corridors share one routing rate, so moving the
    stablecoin-endpoint one also moves the cohort mean and ``_support_cohorts``
    would reject the frame before this guard could speak. In the ledger the two
    classes route independently, so the guard is exercised on its own function.
    """
    contributions = _contributions()
    arriving = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    ) & contributions["src"].eq(USDT)
    contributions.loc[arriving, "stable_share_comparison"] = 1.0
    with pytest.raises(ValueError, match="identity rather than a choice"):
        _cohort_endpoint_margins(
            contributions,
            "count_share",
            {"mass_share": _COHORT_MASS["pooled"], "net_pp": 17.6},
        )


def test_cohort_endpoint_margins_reject_a_class_that_never_uses_the_vehicle() -> None:
    """A class routing at zero cannot carry the margin the split gives it."""
    contributions = _contributions()
    retiring = (
        contributions["contribution_component"].eq("baseline_exclusive_composition")
        & contributions["src"].eq(UNLABELLED)
        & contributions["tgt"].eq(USDC)
    )
    contributions.loc[retiring, "stable_share_baseline"] = 0.0
    with pytest.raises(ValueError, match="never route through a stablecoin"):
        _cohort_endpoint_margins(
            contributions,
            "count_share",
            {"mass_share": _COHORT_MASS["pooled"], "net_pp": 17.6},
        )


def test_cohort_endpoint_margins_reprove_the_eligibility_identity_per_cohort() -> None:
    """The split's own contract, not one inherited from the cohort reading.

    ``_support_cohorts`` runs first in the renderer and would catch a switching
    wrapped-ether corridor before this function ever saw it. The premise still
    has to hold here, because the zero rate term is what licenses reading the
    wrapped-ether class as pure composition, so the guard is exercised directly.
    """
    contributions = _contributions()
    locked = contributions["contribution_component"].eq(
        "comparison_exclusive_composition"
    ) & contributions["tgt"].eq(WETH)
    contributions.loc[locked, "stable_share_comparison"] = 0.5
    with pytest.raises(ValueError, match="eligibility identity forbids"):
        _cohort_endpoint_margins(
            contributions,
            "count_share",
            {"mass_share": _COHORT_MASS["pooled"], "net_pp": 17.6},
        )


def test_renderer_fails_closed_on_wrong_matched_market_scope() -> None:
    fixed_effects = _fixed_effects()
    fixed_effects.loc[0, "estimand_scope"] = "wrong_scope"
    with pytest.raises(ValueError, match="comparison set"):
        render_pair_decomposition_deck_values(
            _decomposition(), fixed_effects, _usdt_integration(), _contributions(), _support()
        )


def test_market_incidence_classes_publish_the_bridge_partition() -> None:
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        ("IncidenceCommonWeightBase", "55.0\\%"),
        ("IncidenceCommonStableBase", "24.0\\%"),
        ("IncidenceCommonPairsBase", "110,000"),
        ("IncidenceCommonWeightEnd", "49.0\\%"),
        ("IncidenceCommonStableEnd", "38.4\\%"),
        ("IncidenceMarketTurnoverWeightBase", "42.0\\%"),
        ("IncidenceMarketTurnoverStableBase", "13.1\\%"),
        ("IncidenceMarketTurnoverStableEnd", "51.0\\%"),
        ("IncidenceRoleTurnoverWeightBase", "3.0\\%"),
        ("IncidenceRoleTurnoverStableBase", "43.3\\%"),
        ("IncidenceRoleTurnoverPairsBase", "6,000"),
        ("IncidenceRoleTurnoverWeightEnd", "1.0\\%"),
        ("IncidenceRoleTurnoverStableEnd", "68.4\\%"),
        ("IncidenceRoleTurnoverPairsEnd", "2,000"),
    ):
        assert _macro(rendered, macro) == value


def test_market_incidence_classes_require_one_row_per_class_and_year() -> None:
    support = pd.concat([_support(), _support().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="exactly 6 pooled count rows"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_market_incidence_classes_require_a_partition_of_the_year() -> None:
    support = _support()
    incidence = support["record_type"].eq("market_incidence_support")
    baseline = incidence & support["endpoint_year"].eq(2024.0)
    support.loc[baseline, "primary_choice_mass_share"] *= 0.9
    with pytest.raises(ValueError, match="do not partition 2024 choice mass"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_market_incidence_classes_must_reproduce_the_bridge_aggregate_share() -> None:
    # Weights still close on one, so only the aggregate reconciliation can catch
    # a partition that belongs to some other year's activity.
    support = _support()
    incidence = support["record_type"].eq("market_incidence_support")
    baseline = incidence & support["endpoint_year"].eq(2024.0)
    market = baseline & support["support_status"].eq("market_pair_support_turnover")
    common = baseline & support["support_status"].eq("common_vehicle_role")
    support.loc[market, "primary_choice_mass_share"] += 0.05
    support.loc[common, "primary_choice_mass_share"] -= 0.05
    with pytest.raises(ValueError, match="do not reproduce the 2024 aggregate"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_market_incidence_classes_require_their_own_stable_choice_mass() -> None:
    support = _support()
    role = support["support_status"].eq(
        "vehicle_role_support_turnover_established_market"
    ) & support["endpoint_year"].eq(2026.0)
    support.loc[role, "stable_choice_mass"] *= 0.5
    with pytest.raises(ValueError, match="stablecoin share is not"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_market_incidence_common_class_must_carry_the_common_role_share() -> None:
    # Compensate inside the same year so the three-class mean still reproduces
    # the aggregate; only the common-role pin can then reject the swap.
    support = _support()
    baseline = support["endpoint_year"].eq(2024.0)
    common = baseline & support["support_status"].eq("common_vehicle_role")
    market = baseline & support["support_status"].eq("market_pair_support_turnover")
    for mask, delta in ((common, 0.01), (market, -0.55 * 0.01 / 0.42)):
        share = float(support.loc[mask, "stable_share"].iloc[0]) + delta
        support.loc[mask, "stable_share"] = share
        support.loc[mask, "stable_choice_mass"] = (
            float(support.loc[mask, "primary_choice_mass"].iloc[0]) * share
        )
    with pytest.raises(ValueError, match="common class does not reproduce"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_market_incidence_established_classes_must_carry_their_own_aggregate() -> None:
    # Shift both established-market endpoints by the same amount: the bridge row
    # still reconciles its own change, so only the renormalised class comparison
    # can reject a class set pinned to a different established-market population.
    decomposition = _decomposition()
    bridge = decomposition["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
    for column in (
        "established_market_baseline_stable_share",
        "established_market_comparison_stable_share",
    ):
        decomposition.loc[bridge, column] += 0.02
    with pytest.raises(ValueError, match="established-market classes do not reproduce"):
        render_pair_decomposition_deck_values(
            decomposition, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_two_factorisations_must_bridge_on_the_common_block() -> None:
    # Section 3.1 states as an exact relation that the identity's within-pair and
    # reweighting terms equal the common block's own stablecoin-share change
    # scaled by that block's midpoint weight. Move choice mass between the
    # identity's within-pair and year-specific terms: the identity still sums to
    # its own total and the bridge row is untouched, so nothing but the
    # cross-panel check can catch that the relation has stopped holding.
    decomposition = _decomposition()
    identity = decomposition["formula_id"].eq("midpoint_common_exclusive_support_v1")
    pooled_count = (
        identity
        & decomposition["metric"].eq("count_share")
        & decomposition["reporting_scope"].eq("pooled")
    )
    decomposition.loc[pooled_count, "within_common"] += 0.01
    decomposition.loc[pooled_count, "exclusive_pair_contribution"] -= 0.01
    decomposition.loc[pooled_count, "support_and_exclusive_joint"] -= 0.01
    with pytest.raises(ValueError, match="do not bridge on the common block"):
        render_pair_decomposition_deck_values(
            decomposition, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_two_factorisations_must_share_a_pooled_count_total() -> None:
    # Both panels factor the same raw pooled count-share change. Grow the
    # identity's year-specific term and its endpoints together: the identity is
    # still self-consistent and the common block still bridges, so only the
    # cross-panel total can reject two panels of different aggregate objects.
    decomposition = _decomposition()
    identity = decomposition["formula_id"].eq("midpoint_common_exclusive_support_v1")
    pooled_count = (
        identity
        & decomposition["metric"].eq("count_share")
        & decomposition["reporting_scope"].eq("pooled")
    )
    for column in (
        "exclusive_pair_contribution",
        "support_and_exclusive_joint",
        "total_change",
        "comparison_stable_share",
    ):
        decomposition.loc[pooled_count, column] += 0.01
    with pytest.raises(ValueError, match="do not share a pooled count total"):
        render_pair_decomposition_deck_values(
            decomposition, _fixed_effects(), _usdt_integration(), _contributions(), _support()
        )


def test_matched_coverage_prices_the_estimator_against_the_identity_block() -> None:
    """How much of the market the matched null actually speaks for.

    The estimator conditions on pair, calendar day and route scope jointly, so
    its sample is far narrower than the identity's continuing block. The two
    coverage families answer different questions: share of the year's whole
    activity, and share of the block whose within-pair term the estimate is
    compared against.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        ("SamplePairs", "240,017"),
        ("BlockPairs", "26,547"),
        ("MatchedPairs", "5,432"),
        ("MatchedValuePairs", "5,278"),
        ("MatchedCoverageBase", "15.0\\%"),
        ("MatchedCoverageEnd", "25.0\\%"),
        ("MatchedBlockCoverageBase", "25.0\\%"),
        ("MatchedBlockCoverageEnd", "50.0\\%"),
        ("MatchedValueCoverageBase", "30.0\\%"),
        ("MatchedValueCoverageEnd", "25.0\\%"),
        ("MatchedValueBlockCoverageBase", "50.0\\%"),
        ("MatchedValueBlockCoverageEnd", "50.0\\%"),
    ):
        assert _macro(rendered, macro) == value


def test_matched_coverage_requires_the_identity_own_block_weight() -> None:
    """A partition that is not the identity's prices a different block."""
    # Move mass and share together so the block still partitions its own year
    # and still reports its own mass over that year. Only the identity's
    # published weight can reject a self-consistent partition of 55/45.
    support = _support()
    blocks = support["record_type"].eq("decomposition_pair_support")
    for status, weight in (("baseline_exclusive", 0.55), ("common", 0.45)):
        rows = blocks & support["support_status"].eq(status)
        support.loc[rows, "baseline_denominator"] = (
            support.loc[rows, "baseline_denominator"]
            / support.loc[rows, "baseline_denominator_share"]
            * weight
        )
        support.loc[rows, "baseline_denominator_share"] = weight
    with pytest.raises(ValueError, match="is not the identity's block weight"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_matched_coverage_rejects_a_sample_wider_than_the_block() -> None:
    """The matched cells sit inside the block by construction, or not at all."""
    fixed_effects = _fixed_effects()
    count = fixed_effects["metric"].eq("count_share")
    fixed_effects.loc[count, "baseline_denominator_mass"] = 700_000.0
    with pytest.raises(ValueError, match="exceeds the identity's block mass"):
        render_pair_decomposition_deck_values(
            _decomposition(), fixed_effects, _usdt_integration(), _contributions(), _support()
        )


def test_matched_coverage_rejects_a_degenerate_block_cell_year() -> None:
    """A vanished denominator makes the class's own share a ratio over nothing."""
    support = _support()
    common = support["record_type"].eq("decomposition_pair_support") & support[
        "support_status"
    ].eq("common")
    support.loc[common, "zero_denominator_cell_years"] = 1.0
    with pytest.raises(ValueError, match="carries a zero-denominator cell-year"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_matched_coverage_rejects_a_block_that_is_not_exclusive() -> None:
    """A year-specific class carrying both years puts the boundary elsewhere."""
    support = _support()
    exclusive = support["record_type"].eq("decomposition_pair_support") & support[
        "support_status"
    ].eq("baseline_exclusive")
    support.loc[exclusive, "comparison_denominator"] = 1.0
    with pytest.raises(ValueError, match="is not exclusive"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def _cell_rows(support: pd.DataFrame, metric: str, status: str) -> pd.Series:
    return (
        support["record_type"].eq("pair_month_day_scope_support")
        & support["metric"].eq(metric)
        & support["support_status"].eq(status)
    )


def test_matched_cell_support_measures_what_the_matching_selects_on() -> None:
    """What conditioning on pair, day and scope jointly selects on.

    The pair census answers how many markets the estimate reaches; the cell
    census answers which of their trading days it keeps. The distance between a
    class's share of a year's cells and its share of that year's mass is the
    thickness of a matched cell, and it is the only measurement in the released
    ledger of the recurrence the joint condition demands.
    """
    rendered = render_pair_decomposition_deck_values(
        _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), _support()
    )
    for macro, value in (
        ("MatchedCells", "94,260"),
        ("SampleCellsBase", "377,040"),
        ("SampleCellsEnd", "188,520"),
        ("MatchedCellShareBase", "25.0\\%"),
        ("MatchedCellShareEnd", "50.0\\%"),
        ("MatchedCellThicknessBase", "$2.0$"),
        ("MatchedCellThicknessEnd", "$0.5$"),
        ("MatchedValueCellShareBase", "25.0\\%"),
        ("MatchedValueCellShareEnd", "50.0\\%"),
        ("MatchedValueCellThicknessBase", "$3.0$"),
        ("MatchedValueCellThicknessEnd", "$0.5$"),
        ("StrictFilteredCellYears", "142,972"),
    ):
        assert _macro(rendered, macro) == value


def test_matched_cell_support_requires_the_estimator_own_cells() -> None:
    """A support ledger counting other cells partitions another estimator."""
    support = _support()
    support.loc[_cell_rows(support, "count_share", "common"), "units"] = 94_000
    with pytest.raises(ValueError, match="common cells but the estimator reports"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_matched_cell_support_requires_one_cell_year_per_endpoint() -> None:
    """Two endpoints and one cell each, or the census is not the regression's."""
    # Leave the cell count alone so the ledger and the exhibit still agree on
    # which cells were estimated; only the cell-year count moves.
    fixed_effects = _fixed_effects()
    fixed_effects.loc[fixed_effects["metric"].eq("count_share"), "observations"] = 282_780
    with pytest.raises(ValueError, match="one cell-year per endpoint"):
        render_pair_decomposition_deck_values(
            _decomposition(), fixed_effects, _usdt_integration(), _contributions(), support=_support()
        )


def test_matched_cell_support_requires_the_estimator_own_endpoint_mass() -> None:
    """Same cells and different mass means one artifact reweighted them."""
    support = _support()
    support.loc[
        _cell_rows(support, "count_share", "common"), "baseline_denominator"
    ] = 149_000.0
    with pytest.raises(ValueError, match="baseline mass .* where the estimator reports"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_matched_cell_support_rejects_a_class_that_is_not_one_sided() -> None:
    """A one-sided class carrying both years is a mislabelled common class."""
    support = _support()
    support.loc[
        _cell_rows(support, "count_share", "baseline_only"), "comparison_denominator"
    ] = 1.0
    with pytest.raises(ValueError, match="is not one-sided"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_matched_cell_support_rejects_class_specific_eligibility() -> None:
    """The eligibility filter belongs to the measure, not to one class of it."""
    support = _support()
    support.loc[
        _cell_rows(support, "strict_intermediation_value_share", "comparison_only"),
        "zero_denominator_cell_years",
    ] = 0.0
    with pytest.raises(ValueError, match="disagree on emptied cell-years"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )


def test_strict_metrics_must_weight_one_cell_perimeter() -> None:
    """Both strict measures weight the same value-eligible cells or neither does."""
    # The value metric alone still reconciles with its own exhibit row, so only a
    # cross-metric check can reject a perimeter applied once per measure.
    support = _support()
    support.loc[
        _cell_rows(support, "matched_strict_count_share", "baseline_only"), "units"
    ] = 274_000
    with pytest.raises(ValueError, match="do not match strict value cells"):
        render_pair_decomposition_deck_values(
            _decomposition(), _fixed_effects(), _usdt_integration(), _contributions(), support
        )
