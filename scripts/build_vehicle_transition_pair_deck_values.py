#!/usr/bin/env python3
"""Build presentation macros from the current vehicle-pair evidence."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from ddvc.asset_types import WETH, asset_type, classify
from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_certified_presentation_source
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output


DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
FIXED_EFFECTS = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
USDT_INTEGRATION = OUTPUT_DIR / "exhibits" / "e0_usdt_integration_decomposition.jsonl"
CONTRIBUTIONS = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_contributions.parquet"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_support.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition_deck_values.tex"
CODE_SOURCES = ["scripts/build_vehicle_transition_pair_deck_values.py"]
SCOPES = ("pooled", "single_venue", "cross_venue")
TERMS = (
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
)
MARKET_INCIDENCE_TERMS = (
    "market_pair_support_bridge",
    "vehicle_role_support_bridge",
    "market_activity_reweighting",
    "vehicle_incidence_reweighting",
    "within_pair_stable_share",
)
# The three support classes Panel A's bridge is built on, in the order the paper
# reads them. The bridge publishes five signed terms and three aggregate
# stablecoin shares; it never publishes the population behind them. Two of its
# terms -- `market_pair_support_bridge` and `vehicle_role_support_bridge` -- are
# each a class's mass against that class's routing rate, so a term near zero can
# mean either an inert class or a shrinking one that routes very differently
# from the average. Only the classes separate those. `common_vehicle_role` holds
# ordered pairs carrying a native or stablecoin intermediary in both years;
# `market_pair_support_turnover` holds pairs whose market is observed in only one
# year; `vehicle_role_support_turnover_established_market` holds pairs traded in
# both years whose vehicle role is present in only one, which is the extensive
# margin of intermediation inside an established market. The class weights are
# choice-mass weights of the bridge's own partition, never a re-estimation, and
# never the continuing/year-specific blocks of Equation (6): the identity splits
# the same mass in two, the bridge in three.
INCIDENCE_CLASSES = (
    ("Common", "common_vehicle_role"),
    ("MarketTurnover", "market_pair_support_turnover"),
    ("RoleTurnover", "vehicle_role_support_turnover_established_market"),
)
INCIDENCE_YEARS = (("Base", 2024), ("End", 2026))
# One named source--destination pair per aggregate margin, used only to make the
# accounting concrete on a slide. The macro prefix names the margin as the
# conclusion states it; the aggregate term each example belongs to follows.
MARGIN_EXAMPLES = (
    ("MarginWithin", "within_pair_choice", "within_common"),
    ("MarginReweight", "pair_composition_reweighting", "common_pair_reweighting"),
    ("MarginNewPair", "comparison_exclusive_composition", "exclusive_pair_contribution"),
)
# How many ordered pairs carry each margin. A named example says which pair is
# largest; these say whether the margin is one corridor or a whole network, and
# whether a near-zero net term is inert or two offsetting flows.
BREADTH_METRICS = (
    ("", "count_share"),
    ("Value", "strict_intermediation_value_share"),
)
# Ordered pairs with WETH at an endpoint cannot use native WETH as an
# intermediary, so within the native-versus-stablecoin comparison their
# stablecoin share is one in both years by construction. Those corridors can
# therefore move the aggregate only through the two composition margins, never
# through the within-pair margin. Splitting each margin on that endpoint asks how
# much of the rotation is carried by corridors whose vehicle was never in
# question -- a different object from the exclusion sensitivity in
# scripts/run_route_methodology_robustness.py, which drops these corridors and
# re-estimates the matched within-pair change.
ELIGIBILITY_MARGINS = (
    ("Reweight", "pair_composition_reweighting"),
    ("NewPair", "comparison_exclusive_composition"),
)
# The same eligibility split taken inside each integration scope. A route that
# stays on one exchange and a route that crosses exchanges are different
# economic objects, and the pooled split cannot say whether the corridors with
# no intermediary choice sit in one of them. This asks that question and nothing
# else: the terms, calendar, and allocation formula are the scope-specific rows
# of the same certified ledger, never a re-estimation.
ELIGIBILITY_SCOPES = (("Single", "single_venue"), ("Cross", "cross_venue"))
# The eligibility split leaves a remainder -- the corridors whose intermediary
# was a live choice -- and says nothing about what those corridors are. This
# partitions that remainder on whether a stablecoin stands at an endpoint of the
# pair. The class is emphatically NOT a second eligibility class: a route into
# USDC may still be carried by WETH or by a different stablecoin, so its
# stablecoin share is free to take any value and its within-pair term is free to
# move. `_open_corridor_endpoints` proves that non-degeneracy on the data before
# reporting anything, which is what separates this split from the WETH one.
OPEN_ENDPOINT_CLASSES = (("StableEnd", "stable"), ("OtherEnd", "other"))
# Membership is decided by the endpoint asset type rather than by one address,
# so unlike the eligibility split it does depend on the taxonomy. The long
# unlabelled tail resolves to `other` and lands in the second class, which is
# the conservative direction: an unrecognised stablecoin would understate the
# first class, never inflate it.
# Which decomposition term is the scope's own total for each split margin. The
# reweighting margin is a term of the decomposition, so its total is read from
# that scope's row and the split is reconciled against it. The new-pair margin
# has no such term: `exclusive_pair_contribution` is net of the pairs that
# stopped trading, while the split is taken of the gross entry margin, so its
# total is the split's own components.
SCOPE_MARGIN_TERMS = {"Reweight": "common_pair_reweighting"}
# Corridors traded in only one of the two years reach the decomposition through a
# single netted term, `exclusive_pair_contribution`, and that netting hides what
# the term measures. The two cohorts -- corridors that stopped trading and
# corridors that began -- are weighted by the *same* midpoint mass share of
# exclusive-support activity, so the term is exactly that mass times the gap
# between how the two cohorts route:
#     exclusive_pair_contribution = E * (s_enter - s_exit).
# Publishing E, s_exit, and s_enter turns a residual into a statement about
# corridor replacement, which is a different object from the gross entry margin
# the eligibility split is taken of. The WETH-endpoint split of each cohort then
# asks how much of a cohort's routing rate is definitional: those corridors carry
# stablecoin share one by construction, so only the open rate can be read
# economically. Unlike the two composition margins, the exiting cohort's margin is
# negative, so `_support_cohorts` proves the split does not straddle zero rather
# than requiring a positive total as `_endpoint_eligibility` does.
SUPPORT_COHORTS = (
    (
        "Exit",
        "baseline_exclusive_composition",
        "pair_weight_baseline",
        "stable_share_baseline",
        -1.0,
    ),
    (
        "Enter",
        "comparison_exclusive_composition",
        "pair_weight_comparison",
        "stable_share_comparison",
        1.0,
    ),
)
COHORT_SCOPES = (("", "pooled"), *ELIGIBILITY_SCOPES)
# The cohort reading above compares two routing rates and stops there. It cannot
# say whether the corridors that arrived route differently because they are
# different *markets* or because markets of the same kind now route differently,
# and those are separate economic statements. The three endpoint classes already
# used elsewhere in this module partition each cohort, so the gap between the two
# cohort rates admits the same composition/rate reading the paper applies to the
# aggregate,
#     s_enter - s_exit = sum_c (w_enter,c - w_exit,c) sbar_c
#                      + sum_c wbar_c (s_enter,c - s_exit,c),
# with sbar_c and wbar_c the two cohorts' midpoints. The identity is exact, not
# an approximation, and `_cohort_endpoint_margins` proves it closes on the gap
# before publishing either side. Two cautions govern the language it supports.
# The wrapped-ether class carries a routing rate of one in *both* cohorts by the
# same eligibility identity used above, so it can only ever enter the first sum:
# a WETH-paired corridor that arrives raises the margin because of what it is,
# not because of anything it chose. And the second sum is a comparison between
# two disjoint populations of corridors holding endpoint type fixed, never a
# switch inside a corridor; no sentence may read it as pair-level substitution.
COHORT_ENDPOINT_CLASSES = ("Locked", "StableEnd", "OtherEnd")
# The fourth and last term of the identity, and the only one no sentence reads.
# `common_support_mass` prices the migration of activity between the two blocks
# of corridors the decomposition already separates: corridors observed in both
# years and corridors observed in only one. It is a product of two factors the
# exhibit publishes but the deck values never expose,
#     common_support_mass = (S_C_bar - S_E_bar) (W_2026 - W_2024),
# a mass shift times the routing gap between the blocks at their two-year
# midpoint. Publishing the factors separates *where* activity went from *how the
# receiving block routes*, which the netted product conflates: the shift is
# large and the price of it is small, so the term is second order while the
# exclusive-pair term next to it is not. The midpoint gap is the price this
# symmetric decomposition puts on a unit of migrated mass; it is not a
# statement that the two blocks route alike in either year, and the cohort
# reading above gives the year-by-year levels. Both blocks' year shares are
# read off the same row and reconciled against that row's own endpoints, so a
# factor can never be printed against a total it does not belong to.
# Panel D's estimand is `common_pair_month_day_realised_integration_scope`: a
# cell enters the matched regression only when the same ordered pair traded on
# the same day of the calendar year under the same realised route scope in both
# comparison years. The identity of the pair decomposition asks far less of a
# pair -- positive native-plus-stable mass somewhere in each year -- so the
# matched sample is a strict subset of the identity's continuing block and does
# not carry the block's own weight. The two populations live in different frozen
# artifacts, and `_matched_coverage` is the join: the block's three classes come
# from the `decomposition_pair_support` rows of the support ledger, the matched
# denominators from the fixed-effects exhibit's own reported totals. The ratios
# it returns are arithmetic on those cells, not a new estimate, and they are the
# only honest answer to how much of the market the matched null speaks for.
# `_matched_coverage` prices the matched sample in *pairs*, the identity's unit.
# `_matched_cell_support` prices it in the estimator's own unit, the pair-day-
# scope cell, and the two answer different questions. A pair is matched when at
# least one of its cells is; a cell is matched only when that exact calendar day
# and route scope carried native-plus-stable mass in both years. The cell census
# therefore says what the joint condition selects on, and the distance between a
# class's share of cells and its share of mass is the only measurement of that
# selection the released ledger can support. It is arithmetic on frozen cells,
# not a second estimate, and the `pair_month_day_scope_support` rows it reads are
# the same rows the fixed-effects exhibit counted, which is why the reader
# refuses to render unless the two artifacts agree cell for cell.
COVERAGE_CLASSES = ("baseline_exclusive", "common", "comparison_exclusive")
COVERAGE_ABSENT_ENDPOINT = {
    "baseline_exclusive": "comparison",
    "comparison_exclusive": "baseline",
}
CELL_SUPPORT_CLASSES = ("baseline_only", "common", "comparison_only")
CELL_ABSENT_ENDPOINT = {
    "baseline_only": "comparison",
    "comparison_only": "baseline",
}
# Both strict metrics are formed on one value-eligible perimeter and differ only
# in the weight carried by a surviving cell, so their cell populations must be
# the same object.
STRICT_CELL_METRICS = ("matched_strict_count_share", "strict_intermediation_value_share")
SUPPORT_BLOCKS = (
    ("Common", "W", "S_C"),
    ("Exclusive", "E", "S_E"),
)
BLOCK_SCOPES = COHORT_SCOPES
BLOCK_COLUMNS = tuple(
    f"{stem}_{endpoint}"
    for _prefix, weight, share in SUPPORT_BLOCKS
    for stem in (weight, share)
    for endpoint in ("baseline", "comparison")
)


def _signed_pp(value: float) -> str:
    points = 100 * value
    if abs(points) < 0.05:
        return "$0.0$ pp"
    return f"${points:+.1f}$ pp"


def _share(value: float) -> str:
    return f"{100 * value:.1f}\\%"


def _unsigned_pp(value: float) -> str:
    return f"${100 * value:.1f}$ pp"


def _activity_share(value: float) -> str:
    """Pair weights are small; two decimals keep a 0.36\\% weight readable."""
    return f"{100 * value:.2f}\\%"


def _routes(value: float) -> str:
    if not float(value).is_integer():
        raise ValueError("route counts must be whole numbers")
    return f"{int(value):,}"


def _units(value: int) -> str:
    """A census of discrete units, whether ordered pairs or estimation cells."""
    return f"{int(value):,}"


def _multiple(value: float) -> str:
    """A thickness ratio is a pure number and carries no unit of its own."""
    return f"${value:.1f}$"


def _contribution_pp(value: float) -> str:
    """Contribution columns already carry percentage points, unlike the terms."""
    return f"${value:+.1f}$ pp"


def _raw_pp(value: float) -> str:
    return f"{100 * value:.9f}"


def _raw_pct(value: float) -> str:
    return f"{100 * value:.9f}"


def _scope_rows(decomposition: pd.DataFrame, metric: str) -> dict[str, pd.Series]:
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "common_calendar_end",
        "common_month_days",
        "formula_id",
        "mechanism_status",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "support_and_exclusive_joint",
        "identity_error",
        *TERMS,
        *BLOCK_COLUMNS,
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(f"pair decomposition missing columns: {', '.join(missing)}")
    rows: dict[str, pd.Series] = {}
    for scope in SCOPES:
        selected = decomposition[
            decomposition["metric"].eq(metric)
            & decomposition["reporting_scope"].eq(scope)
            & decomposition["formula_id"].eq(
                "midpoint_common_exclusive_support_v1"
            )
        ]
        if len(selected) != 1:
            raise ValueError(
                f"pair decomposition requires exactly one {metric}/{scope} row; "
                f"found {len(selected)}"
            )
        row = selected.iloc[0]
        if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
            raise ValueError("pair decomposition must compare 2024 with 2026")
        if row["common_calendar_end"] != "06-30" or int(row["common_month_days"]) != 181:
            raise ValueError("pair decomposition does not use the locked common calendar")
        if row["formula_id"] != "midpoint_common_exclusive_support_v1":
            raise ValueError("pair decomposition formula differs from the locked identity")
        if row["mechanism_status"] != "descriptive_realised_composition_noncausal":
            raise ValueError("pair decomposition is not labelled as descriptive composition")
        numeric = [
            "baseline_stable_share",
            "comparison_stable_share",
            "total_change",
            "support_and_exclusive_joint",
            "identity_error",
            *TERMS,
            *BLOCK_COLUMNS,
        ]
        if not all(math.isfinite(float(row[column])) for column in numeric):
            raise ValueError("pair decomposition contains a non-finite accounting cell")
        if abs(float(row["identity_error"])) > 1e-12:
            raise ValueError("pair decomposition identity error exceeds tolerance")
        joint = float(row["common_support_mass"]) + float(
            row["exclusive_pair_contribution"]
        )
        if not math.isclose(
            float(row["support_and_exclusive_joint"]), joint, abs_tol=1e-12
        ):
            raise ValueError("pair decomposition joint support term does not reconcile")
        total = sum(float(row[column]) for column in TERMS)
        if not math.isclose(float(row["total_change"]), total, abs_tol=1e-12):
            raise ValueError("pair decomposition terms do not sum to the total change")
        if not math.isclose(
            float(row["baseline_stable_share"]) + total,
            float(row["comparison_stable_share"]),
            abs_tol=1e-12,
        ):
            raise ValueError("pair decomposition endpoints do not reconcile")
        rows[scope] = row
    return rows


def _market_incidence_row(decomposition: pd.DataFrame) -> pd.Series:
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "formula_id",
        "mechanism_status",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "established_market_baseline_stable_share",
        "established_market_comparison_stable_share",
        "established_market_total_change",
        "common_role_baseline_stable_share",
        "common_role_comparison_stable_share",
        "common_role_total_change",
        "identity_error",
        *MARKET_INCIDENCE_TERMS,
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(
            f"market-incidence decomposition missing columns: {', '.join(missing)}"
        )
    selected = decomposition[
        decomposition["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
        & decomposition["metric"].eq("count_share")
        & decomposition["reporting_scope"].eq("pooled")
    ]
    if len(selected) != 1:
        raise ValueError(
            "market-incidence decomposition requires exactly one pooled count row; "
            f"found {len(selected)}"
        )
    row = selected.iloc[0]
    if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
        raise ValueError("market-incidence decomposition must compare 2024 with 2026")
    if (
        row["mechanism_status"]
        != "descriptive_observed_activity_and_realised_incidence_noncausal"
    ):
        raise ValueError("market-incidence decomposition has a causal mechanism label")
    numeric = [
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "established_market_baseline_stable_share",
        "established_market_comparison_stable_share",
        "established_market_total_change",
        "common_role_baseline_stable_share",
        "common_role_comparison_stable_share",
        "common_role_total_change",
        "identity_error",
        *MARKET_INCIDENCE_TERMS,
    ]
    if not all(math.isfinite(float(row[column])) for column in numeric):
        raise ValueError("market-incidence decomposition contains a non-finite cell")
    if abs(float(row["identity_error"])) > 1e-12:
        raise ValueError("market-incidence decomposition identity error exceeds tolerance")
    total = sum(float(row[column]) for column in MARKET_INCIDENCE_TERMS)
    common_role = sum(
        float(row[column])
        for column in (
            "market_activity_reweighting",
            "vehicle_incidence_reweighting",
            "within_pair_stable_share",
        )
    )
    established = float(row["vehicle_role_support_bridge"]) + common_role
    checks = (
        (float(row["total_change"]), total, "total change"),
        (float(row["common_role_total_change"]), common_role, "common-role change"),
        (
            float(row["established_market_total_change"]),
            established,
            "established-market change",
        ),
        (
            float(row["baseline_stable_share"]) + total,
            float(row["comparison_stable_share"]),
            "aggregate endpoints",
        ),
        (
            float(row["established_market_baseline_stable_share"]) + established,
            float(row["established_market_comparison_stable_share"]),
            "established-market endpoints",
        ),
        (
            float(row["common_role_baseline_stable_share"]) + common_role,
            float(row["common_role_comparison_stable_share"]),
            "common-role endpoints",
        ),
    )
    for left, right, label in checks:
        if not math.isclose(left, right, abs_tol=1e-12):
            raise ValueError(f"market-incidence decomposition does not reconcile {label}")
    return row


def _cross_panel_common_bridge(pooled_count: pd.Series, market: pd.Series) -> None:
    """Prove the exact relation Section 3.1 states between the two panels.

    Both factorisations partition the same pooled count-share choice mass and
    agree on which pairs continue, but they price that common block at different
    scales. Panel A's three allocated terms sum to the block's *own* stablecoin-
    share change, while the identity's within-pair and reweighting terms sum to
    the same change multiplied by the block's midpoint weight in aggregate choice
    mass. The paper asserts that this holds exactly; nothing else in the pipeline
    would notice if it stopped, and a reader who found the two within-pair terms
    unrelated would have no way to tell a scale difference from a disagreement.
    So the subsection's macros are withheld unless the relation still closes.

    The relation covers the common block only. The identity charges the
    year-specific remainder at ``1 - W_bar`` while Panel A carries it in two
    support bridges, so the panels never nest term by term and their components
    must not be netted or added -- which is why only the totals are cross-checked
    below.
    """

    common_weight = (
        float(pooled_count["W_baseline"]) + float(pooled_count["W_comparison"])
    ) / 2.0
    identity_common = float(pooled_count["within_common"]) + float(
        pooled_count["common_pair_reweighting"]
    )
    scaled_common_role = common_weight * float(market["common_role_total_change"])
    if not math.isclose(identity_common, scaled_common_role, abs_tol=1e-12):
        raise ValueError(
            "the two factorisations do not bridge on the common block: "
            f"{identity_common} against {scaled_common_role}"
        )
    if not math.isclose(
        float(pooled_count["total_change"]),
        float(market["total_change"]),
        abs_tol=1e-12,
    ):
        raise ValueError("the two factorisations do not share a pooled count total")


def _market_incidence_classes(
    support: pd.DataFrame, market: pd.Series
) -> dict[str, dict[str, float]]:
    """Open the support ledger Panel A's bridge is formed from.

    See ``INCIDENCE_CLASSES`` for what the three classes are. Nothing here is
    estimated: every quantity is a cell of the certified support ledger, and the
    function's work is to prove that these cells are the published bridge's own
    partition before a single class weight reaches a macro. Five premises, in
    order of what they license. Each class's stablecoin share must be its own
    stable-over-primary choice mass, or the share is not the class's. The three
    class weights must close on one in each year, or they are not a partition.
    Their mass-weighted mean must reproduce that year's aggregate stablecoin
    share on the bridge row itself, or they are a partition of something else.
    The common class must reproduce the bridge's common-role share, and the two
    classes observed in both years must reproduce its established-market share
    once renormalised -- the two aggregates the bridge already publishes, which
    is what pins each class to the term that prices it. A class failing any of
    these is withheld rather than printed beside a term it does not belong to.
    """
    required = {
        "record_type",
        "metric",
        "reporting_scope",
        "endpoint_year",
        "support_status",
        "units",
        "primary_choice_mass",
        "primary_choice_mass_share",
        "stable_choice_mass",
        "stable_share",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        raise ValueError(f"pair support ledger missing columns: {', '.join(missing)}")
    selected = support[
        support["record_type"].eq("market_incidence_support")
        & support["metric"].eq("count_share")
        & support["reporting_scope"].eq("pooled")
    ]
    expected = len(INCIDENCE_CLASSES) * len(INCIDENCE_YEARS)
    if len(selected) != expected:
        raise ValueError(
            "market-incidence support requires exactly "
            f"{expected} pooled count rows; found {len(selected)}"
        )
    cells: dict[tuple[str, int], pd.Series] = {}
    for _infix, status in INCIDENCE_CLASSES:
        for _suffix, year in INCIDENCE_YEARS:
            rows = selected[
                selected["support_status"].eq(status)
                & selected["endpoint_year"].eq(float(year))
            ]
            if len(rows) != 1:
                raise ValueError(
                    f"market-incidence support has {len(rows)} rows for "
                    f"{status} in {year}; exactly one is required"
                )
            row = rows.iloc[0]
            numeric = (
                "units",
                "primary_choice_mass",
                "primary_choice_mass_share",
                "stable_choice_mass",
                "stable_share",
            )
            if not all(math.isfinite(float(row[column])) for column in numeric):
                raise ValueError(f"market-incidence support {status} {year} is non-finite")
            primary = float(row["primary_choice_mass"])
            stable = float(row["stable_choice_mass"])
            if int(row["units"]) <= 0 or primary <= 0:
                raise ValueError(f"market-incidence support {status} {year} is empty")
            if not 0 <= stable <= primary:
                raise ValueError(
                    f"market-incidence support {status} {year} routes more stablecoin "
                    "mass than it carries"
                )
            if not math.isclose(float(row["stable_share"]), stable / primary, abs_tol=1e-12):
                raise ValueError(
                    f"market-incidence support {status} {year} stablecoin share is not "
                    "its own stable-over-primary choice mass"
                )
            if not 0 < float(row["primary_choice_mass_share"]) < 1:
                raise ValueError(
                    f"market-incidence support {status} {year} weight leaves the unit range"
                )
            cells[(status, year)] = row
    aggregate = {
        2024: "baseline_stable_share",
        2026: "comparison_stable_share",
    }
    common_role = {
        2024: "common_role_baseline_stable_share",
        2026: "common_role_comparison_stable_share",
    }
    established = {
        2024: "established_market_baseline_stable_share",
        2026: "established_market_comparison_stable_share",
    }
    for _suffix, year in INCIDENCE_YEARS:
        year_rows = [cells[(status, year)] for _infix, status in INCIDENCE_CLASSES]
        weights = [float(row["primary_choice_mass_share"]) for row in year_rows]
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError(
                f"market-incidence support classes do not partition {year} choice mass"
            )
        mean = sum(
            weight * float(row["stable_share"])
            for weight, row in zip(weights, year_rows, strict=True)
        )
        if not math.isclose(mean, float(market[aggregate[year]]), abs_tol=1e-12):
            raise ValueError(
                f"market-incidence support classes do not reproduce the {year} "
                "aggregate stablecoin share of the bridge they are read against"
            )
        common = cells[("common_vehicle_role", year)]
        if not math.isclose(
            float(common["stable_share"]), float(market[common_role[year]]), abs_tol=1e-12
        ):
            raise ValueError(
                f"market-incidence common class does not reproduce the {year} "
                "common-role stablecoin share"
            )
        both_years = [
            cells[("common_vehicle_role", year)],
            cells[("vehicle_role_support_turnover_established_market", year)],
        ]
        both_weight = sum(float(row["primary_choice_mass_share"]) for row in both_years)
        if not 0 < both_weight < 1:
            raise ValueError(
                f"market-incidence established-market classes carry no {year} mass"
            )
        both_mean = (
            sum(
                float(row["primary_choice_mass_share"]) * float(row["stable_share"])
                for row in both_years
            )
            / both_weight
        )
        if not math.isclose(both_mean, float(market[established[year]]), abs_tol=1e-12):
            raise ValueError(
                f"market-incidence established-market classes do not reproduce the "
                f"{year} established-market stablecoin share"
            )
    return {
        infix: {
            suffix: {
                "weight": float(cells[(status, year)]["primary_choice_mass_share"]),
                "stable_share": float(cells[(status, year)]["stable_share"]),
                "pairs": int(cells[(status, year)]["units"]),
            }
            for suffix, year in INCIDENCE_YEARS
        }
        for infix, status in INCIDENCE_CLASSES
    }


def _scoped_contributions(
    contributions: pd.DataFrame, metric: str, scope: str
) -> pd.DataFrame:
    """2024--2026 pair contributions under one measure of activity and one scope."""
    if scope not in SCOPES:
        raise ValueError(f"unknown reporting scope {scope!r}")
    return contributions[
        contributions["metric"].eq(metric)
        & contributions["reporting_scope"].eq(scope)
        & contributions["baseline_year"].eq(2024)
        & contributions["comparison_year"].eq(2026)
    ]


def _pooled_contributions(contributions: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Pooled 2024--2026 pair contributions under one measure of activity."""
    return _scoped_contributions(contributions, metric, "pooled")


def _pooled_count_contributions(contributions: pd.DataFrame) -> pd.DataFrame:
    """The one metric, scope, and comparison whose pairs may be named on a slide."""
    return _pooled_contributions(contributions, "count_share")


def _baseline_exclusive_pp(contributions: pd.DataFrame) -> float:
    """Pooled count contribution of pairs observed only in the baseline year."""
    scoped = _pooled_count_contributions(contributions)
    selected = scoped[
        scoped["contribution_component"].eq("baseline_exclusive_composition")
    ]
    if selected.empty:
        raise ValueError("pair contributions carry no baseline-exclusive rows")
    return float(selected["contribution_pp"].sum())


def _margin_example_rows(
    contributions: pd.DataFrame, pooled: pd.Series
) -> dict[str, dict[str, object]]:
    """Name the largest labelled pair behind each aggregate margin.

    The selection is illustrative and deliberately conservative. Only pairs whose
    two endpoints both resolve in the canonical token taxonomy are eligible, so a
    slide never prints a bare contract address or a guessed ticker. Because the
    long tail of newly traded assets is mostly unlabelled, the named example is
    the largest *named* contributor to its margin, not the largest contributor;
    the caller also reports the margin's own total so the two are never confused.
    """
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "src",
        "tgt",
        "stable_share_baseline",
        "stable_share_comparison",
        "pair_weight_baseline",
        "pair_weight_comparison",
        "denominator_baseline",
        "denominator_comparison",
        "contribution_component",
        "contribution_pp",
        "aggregate_total_change",
        "allocation_scope",
        "mechanism_status",
    }
    missing = sorted(required - set(contributions.columns))
    if missing:
        raise ValueError(f"pair contributions missing columns: {', '.join(missing)}")
    scoped = _pooled_count_contributions(contributions)
    if scoped.empty:
        raise ValueError("pair contributions carry no pooled 2024--2026 count rows")
    if set(scoped["mechanism_status"].unique()) != {
        "descriptive_pair_contribution_noncausal"
    }:
        raise ValueError("pair contributions carry a causal mechanism label")
    if set(scoped["allocation_scope"].unique()) != {
        "pair_level_excludes_common_support_mass"
    }:
        raise ValueError("pair contributions use an unexpected allocation scope")
    if not math.isclose(
        float(scoped["aggregate_total_change"].iloc[0]),
        float(pooled["total_change"]),
        abs_tol=1e-12,
    ):
        raise ValueError("pair contributions disagree with the aggregate total change")
    exclusive_total = float(
        scoped.loc[
            scoped["contribution_component"].isin(
                ("baseline_exclusive_composition", "comparison_exclusive_composition")
            ),
            "contribution_pp",
        ].sum()
    )
    if not math.isclose(
        exclusive_total, 100 * float(pooled["exclusive_pair_contribution"]), abs_tol=1e-6
    ):
        raise ValueError("pair contributions do not reconcile the exclusive-pair term")
    examples: dict[str, dict[str, object]] = {}
    for prefix, component, aggregate_term in MARGIN_EXAMPLES:
        rows = scoped[scoped["contribution_component"].eq(component)]
        if rows.empty:
            raise ValueError(f"pair contributions carry no {component} rows")
        component_pp = float(rows["contribution_pp"].sum())
        if aggregate_term != "exclusive_pair_contribution" and not math.isclose(
            component_pp, 100 * float(pooled[aggregate_term]), abs_tol=1e-6
        ):
            raise ValueError(
                f"{component} contributions do not reconcile {aggregate_term}"
            )
        symbols = [
            (classify(source)[0], classify(target)[0])
            for source, target in zip(rows["src"], rows["tgt"], strict=True)
        ]
        labelled = rows.assign(
            source_symbol=[pair[0] for pair in symbols],
            target_symbol=[pair[1] for pair in symbols],
        )
        labelled = labelled[
            labelled["source_symbol"].notna() & labelled["target_symbol"].notna()
        ]
        labelled = labelled[labelled["contribution_pp"] > 0]
        if labelled.empty:
            raise ValueError(f"{component} has no labelled positive contributor")
        row = labelled.sort_values(
            ["contribution_pp", "source_symbol", "target_symbol"],
            ascending=[False, True, True],
        ).iloc[0]
        numeric = (
            "stable_share_baseline",
            "stable_share_comparison",
            "pair_weight_baseline",
            "pair_weight_comparison",
            "denominator_baseline",
            "denominator_comparison",
            "contribution_pp",
        )
        if not all(math.isfinite(float(row[column])) for column in numeric):
            raise ValueError(f"{component} example contains a non-finite cell")
        examples[prefix] = {
            "source_symbol": str(row["source_symbol"]),
            "target_symbol": str(row["target_symbol"]),
            "stable_share_baseline": float(row["stable_share_baseline"]),
            "stable_share_comparison": float(row["stable_share_comparison"]),
            "pair_weight_baseline": float(row["pair_weight_baseline"]),
            "pair_weight_comparison": float(row["pair_weight_comparison"]),
            "routes_baseline": float(row["denominator_baseline"]),
            "routes_comparison": float(row["denominator_comparison"]),
            "contribution_pp": float(row["contribution_pp"]),
            "component_pp": component_pp,
        }
    return examples


def _rank_for_fraction(sorted_gains: list[float], fraction: float) -> int:
    """Smallest number of pairs whose gains reach a fraction of the gross gain."""
    target = fraction * sum(sorted_gains)
    running = 0.0
    for rank, gain in enumerate(sorted_gains, start=1):
        running += gain
        if running >= target:
            return rank
    return len(sorted_gains)


def _margin_breadth(
    contributions: pd.DataFrame, aggregate: pd.Series, metric: str
) -> dict[str, dict[str, object]]:
    """Count the pairs behind each margin and split it into gains and losses.

    Two facts about a margin cannot be read off its total. A margin of a given
    size can come from one corridor or from tens of thousands of small markets,
    and a total near zero can mean either that no pair moved or that gains and
    losses of similar size cancelled. Both are computed from the same certified
    allocation the margin totals come from, so they reconcile to those totals by
    construction and the renderer refuses to print them if they do not.
    """
    scoped = _pooled_contributions(contributions, metric)
    if scoped.empty:
        raise ValueError(f"pair contributions carry no pooled 2024--2026 {metric} rows")
    exclusive_total = float(
        scoped.loc[
            scoped["contribution_component"].isin(
                ("baseline_exclusive_composition", "comparison_exclusive_composition")
            ),
            "contribution_pp",
        ].sum()
    )
    if not math.isclose(
        exclusive_total,
        100 * float(aggregate["exclusive_pair_contribution"]),
        abs_tol=1e-6,
    ):
        raise ValueError(f"{metric} contributions do not reconcile the exclusive term")
    breadth: dict[str, dict[str, object]] = {}
    for prefix, component, aggregate_term in MARGIN_EXAMPLES:
        rows = scoped[scoped["contribution_component"].eq(component)]
        if rows.empty:
            raise ValueError(f"pair contributions carry no {metric} {component} rows")
        values = [float(value) for value in rows["contribution_pp"]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{metric} {component} contains a non-finite contribution")
        gains = sorted((value for value in values if value > 0), reverse=True)
        losses = [value for value in values if value < 0]
        gross_up = sum(gains)
        gross_down = sum(losses)
        component_pp = sum(values)
        if aggregate_term != "exclusive_pair_contribution" and not math.isclose(
            component_pp, 100 * float(aggregate[aggregate_term]), abs_tol=1e-6
        ):
            raise ValueError(
                f"{metric} {component} contributions do not reconcile {aggregate_term}"
            )
        if not math.isclose(gross_up + gross_down, component_pp, abs_tol=1e-6):
            raise ValueError(f"{metric} {component} gains and losses miss its total")
        if not gains:
            raise ValueError(f"{metric} {component} has no gaining pair")
        half_pairs = _rank_for_fraction(gains, 0.5)
        ninety_pairs = _rank_for_fraction(gains, 0.9)
        if not 1 <= half_pairs <= ninety_pairs <= len(gains):
            raise ValueError(f"{metric} {component} concentration ranks are disordered")
        breadth[prefix] = {
            "gain_pairs": len(gains),
            "loss_pairs": len(losses),
            "gross_up": gross_up,
            "gross_down": gross_down,
            "top_share": gains[0] / gross_up,
            "half_pairs": half_pairs,
            "ninety_pairs": ninety_pairs,
        }
    return breadth


def _endpoint_eligibility(
    contributions: pd.DataFrame,
    metric: str,
    aggregate: pd.Series,
    scope: str = "pooled",
) -> dict[str, object]:
    """Split each composition margin on whether WETH is an endpoint of the pair.

    The split is an identity, not an estimate, and it needs no token taxonomy:
    membership is decided by one canonical address, so the long unlabelled tail
    is classified as reliably as the majors. The function first proves the
    eligibility identity on the data rather than assuming it -- every
    WETH-endpoint route must carry stablecoin share one in both years, and its
    within-pair contribution must be exactly zero -- and then reports what the
    remaining two margins owe to those corridors.

    ``scope`` selects the integration scope the split is taken within, and
    ``aggregate`` is that scope's own decomposition row. The reweighting margin
    is reconciled against it before anything is reported, so a scope-specific
    split can never be printed against another scope's aggregate.
    """
    scoped = _scoped_contributions(contributions, metric, scope)
    if scoped.empty:
        raise ValueError(
            f"pair contributions carry no {scope} 2024--2026 {metric} rows"
        )
    endpoint = scoped["src"].eq(WETH) | scoped["tgt"].eq(WETH)
    common = scoped[scoped["contribution_component"].eq("within_pair_choice")]
    locked = common[endpoint.loc[common.index]]
    if locked.empty:
        raise ValueError(f"{metric} has no WETH-endpoint common pair")
    if not (
        locked["stable_share_baseline"].eq(1.0).all()
        and locked["stable_share_comparison"].eq(1.0).all()
    ):
        raise ValueError(
            f"{metric} breaks the WETH-endpoint eligibility identity: a "
            "WETH-endpoint pair reports a stablecoin share other than one"
        )
    if not locked["contribution_pp"].eq(0.0).all():
        raise ValueError(
            f"{metric} reports a non-zero within-pair contribution on a "
            "WETH-endpoint pair, which the eligibility identity forbids"
        )
    weight_baseline = float(locked["pair_weight_baseline"].sum())
    weight_comparison = float(locked["pair_weight_comparison"].sum())
    if not 0 < weight_baseline < 1 or not 0 < weight_comparison < 1:
        raise ValueError(f"{metric} WETH-endpoint activity weights leave the unit range")
    eligibility: dict[str, object] = {
        "locked_pairs": int(len(locked)),
        "common_pairs": int(len(common)),
        "pair_share": len(locked) / len(common),
        "weight_baseline": weight_baseline,
        "weight_comparison": weight_comparison,
    }
    for prefix, component in ELIGIBILITY_MARGINS:
        rows = scoped[scoped["contribution_component"].eq(component)]
        if rows.empty:
            raise ValueError(f"pair contributions carry no {metric} {component} rows")
        selector = endpoint.loc[rows.index]
        component_pp = float(rows["contribution_pp"].sum())
        locked_pp = float(rows.loc[selector, "contribution_pp"].sum())
        open_pp = float(rows.loc[~selector, "contribution_pp"].sum())
        if not all(math.isfinite(value) for value in (component_pp, locked_pp, open_pp)):
            raise ValueError(f"{metric} {component} eligibility split is not finite")
        if not math.isclose(locked_pp + open_pp, component_pp, abs_tol=1e-6):
            raise ValueError(f"{metric} {component} eligibility split misses its total")
        if component_pp <= 0:
            raise ValueError(
                f"{metric} {component} is not a positive margin, so an "
                "eligibility share of it would not be interpretable"
            )
        if prefix == "Reweight" and not math.isclose(
            component_pp, 100 * float(aggregate["common_pair_reweighting"]), abs_tol=1e-6
        ):
            raise ValueError(
                f"{metric} {scope} eligibility split does not reconcile that "
                "scope's common-pair reweighting term"
            )
        eligibility[prefix] = {
            "component_pp": component_pp,
            "locked_pp": locked_pp,
            "open_pp": open_pp,
            "locked_share": locked_pp / component_pp,
        }
    return eligibility


def _open_corridor_endpoints(
    contributions: pd.DataFrame,
    metric: str,
    eligibility: dict[str, object],
    scope: str = "pooled",
) -> dict[str, object]:
    """Partition the choice-live remainder of each margin on its endpoints.

    ``_endpoint_eligibility`` removes the corridors whose vehicle is fixed by
    the WETH-endpoint identity and reports what is left as one number per
    margin. That remainder is the economically interesting part -- every unit of
    it comes from a corridor that could have been routed either way -- and this
    says what those corridors are, by splitting them on whether a stablecoin
    stands at an endpoint of the ordered pair.

    The split would be worthless if it were a second eligibility class in
    disguise, so the function refuses to report it until it has proved on the
    data that it is not one: the stablecoin-endpoint class must hold pairs whose
    stablecoin share is strictly interior, must not be dominated by pairs pinned
    at one in both years, and must carry a within-pair term that is free to
    move. The two classes are then checked to partition the remainder exactly,
    and the remainder itself against ``eligibility``'s own open total, so no
    class share can be printed against a margin it is not a share of.
    """
    scoped = _scoped_contributions(contributions, metric, scope)
    if scoped.empty:
        raise ValueError(
            f"pair contributions carry no {scope} 2024--2026 {metric} rows"
        )
    endpoint = scoped["src"].eq(WETH) | scoped["tgt"].eq(WETH)
    stable_endpoint = ~endpoint & (
        scoped["src"].map(asset_type).eq("stable")
        | scoped["tgt"].map(asset_type).eq("stable")
    )
    other_endpoint = ~endpoint & ~stable_endpoint
    common = scoped["contribution_component"].eq("within_pair_choice")
    classes: dict[str, object] = {}
    for prefix, selector in (
        ("StableEnd", stable_endpoint),
        ("OtherEnd", other_endpoint),
    ):
        pairs = scoped[common & selector]
        if pairs.empty:
            raise ValueError(f"{metric} {scope} has no {prefix} common pair")
        weight_baseline = float(pairs["pair_weight_baseline"].sum())
        weight_comparison = float(pairs["pair_weight_comparison"].sum())
        if not 0 < weight_baseline < 1 or not 0 < weight_comparison < 1:
            raise ValueError(
                f"{metric} {scope} {prefix} activity weights leave the unit range"
            )
        shares = {}
        for suffix, weight_column, share_column in (
            ("baseline", "pair_weight_baseline", "stable_share_baseline"),
            ("comparison", "pair_weight_comparison", "stable_share_comparison"),
        ):
            mass = float(pairs[weight_column].sum())
            weighted = float((pairs[share_column] * pairs[weight_column]).sum()) / mass
            if not 0 <= weighted <= 1:
                raise ValueError(
                    f"{metric} {scope} {prefix} {suffix} stablecoin share leaves "
                    "the unit interval"
                )
            shares[suffix] = weighted
        within_pp = float(pairs["contribution_pp"].sum())
        if not math.isfinite(within_pp):
            raise ValueError(f"{metric} {scope} {prefix} within-pair term is not finite")
        classes[prefix] = {
            "pairs": int(len(pairs)),
            "weight_baseline": weight_baseline,
            "weight_comparison": weight_comparison,
            "share_baseline": shares["baseline"],
            "share_comparison": shares["comparison"],
            "within_pp": within_pp,
        }
    # The stablecoin-endpoint class must be a choice, not an identity. A route
    # into a stablecoin can still be carried by the native asset or by a
    # different stablecoin, so if this class ever behaved like the WETH one the
    # split would be reporting an accounting rule as an economic fact.
    live = scoped[common & stable_endpoint]
    below = live["stable_share_baseline"].lt(1.0) | live["stable_share_comparison"].lt(1.0)
    above = live["stable_share_baseline"].gt(0.0) | live["stable_share_comparison"].gt(0.0)
    if not below.any():
        raise ValueError(
            f"{metric} {scope} stablecoin-endpoint corridors always route at a "
            "stablecoin share of one, so a stablecoin at an endpoint is forcing "
            "the intermediary and the split is an identity rather than a choice"
        )
    if not above.any():
        raise ValueError(
            f"{metric} {scope} stablecoin-endpoint corridors never route through a "
            "stablecoin at all, so the class cannot carry the margin attributed to it"
        )
    pinned = float(
        (live["stable_share_baseline"].eq(1.0) & live["stable_share_comparison"].eq(1.0))
        .mean()
    )
    if pinned >= 0.25:
        raise ValueError(
            f"{metric} {scope} stablecoin-endpoint corridors are {pinned:.1%} pinned "
            "at a stablecoin share of one in both years, which is too close to the "
            "WETH-endpoint identity for the split to be read as a choice"
        )
    if classes["StableEnd"]["within_pp"] == 0.0:
        raise ValueError(
            f"{metric} {scope} stablecoin-endpoint within-pair term is exactly zero, "
            "which the eligibility identity forbids for a choice-live class"
        )
    classes["pinned_share"] = pinned
    locked_pairs = int(eligibility["locked_pairs"])
    common_pairs = int(eligibility["common_pairs"])
    class_pairs = int(classes["StableEnd"]["pairs"]) + int(classes["OtherEnd"]["pairs"])
    if class_pairs + locked_pairs != common_pairs:
        raise ValueError(
            f"{metric} {scope} endpoint classes do not partition the common pairs"
        )
    weights = {
        suffix: float(eligibility[f"weight_{suffix}"])
        + float(classes["StableEnd"][f"weight_{suffix}"])
        + float(classes["OtherEnd"][f"weight_{suffix}"])
        for suffix in ("baseline", "comparison")
    }
    for suffix, total in weights.items():
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(
                f"{metric} {scope} endpoint-class {suffix} weights sum to {total}, "
                "so the three classes do not exhaust that year's activity"
            )
    # Each class is reported as a share of the whole margin, not of the
    # choice-live remainder. The remainder is a difference of two terms and can
    # come out negative -- the dollar-weighted reweighting margin does exactly
    # that inside one integration scope -- and a share of a negative base is not
    # a quantity anyone can read. The margin itself is positive by the guard in
    # `_endpoint_eligibility`, and the three classes' shares of it sum to one,
    # so a reader can set them beside the published eligible share directly.
    for prefix, component in ELIGIBILITY_MARGINS:
        rows = scoped["contribution_component"].eq(component)
        component_pp = float(eligibility[prefix]["component_pp"])
        locked_pp = float(eligibility[prefix]["locked_pp"])
        split = {
            "StableEnd": float(scoped.loc[rows & stable_endpoint, "contribution_pp"].sum()),
            "OtherEnd": float(scoped.loc[rows & other_endpoint, "contribution_pp"].sum()),
        }
        if not all(math.isfinite(value) for value in split.values()):
            raise ValueError(f"{metric} {scope} {component} endpoint split is not finite")
        if not math.isclose(
            sum(split.values()) + locked_pp, component_pp, abs_tol=1e-6
        ):
            raise ValueError(
                f"{metric} {scope} {component} endpoint classes and the eligible "
                "corridors miss that margin's total"
            )
        for class_prefix, _ in OPEN_ENDPOINT_CLASSES:
            entry = dict(classes[class_prefix])
            entry[prefix] = split[class_prefix]
            entry[f"{prefix}Share"] = split[class_prefix] / component_pp
            classes[class_prefix] = entry
        classes[f"{prefix}OtherPairs"] = int((rows & other_endpoint).sum())
        classes[f"{prefix}StablePairs"] = int((rows & stable_endpoint).sum())
    return classes


def _support_cohorts(
    contributions: pd.DataFrame,
    metric: str,
    aggregate: pd.Series,
    scope: str = "pooled",
) -> dict[str, object]:
    """Read the netted exclusive-pair term as a corridor-replacement comparison.

    See ``SUPPORT_COHORTS`` for the identity. Everything reported here is proved
    on the ledger rather than assumed: each cohort's weights close on one, each
    cohort's margin equals its own mass times its own routing rate, the two
    cohorts carry the same mass (without which their difference is not a routing
    comparison), and the two margins sum to that scope's ``aggregate`` netted
    term. The eligibility split of each cohort is checked for a sign straddle
    before any share of it is formed, because the exiting margin is negative.
    """
    scoped = _scoped_contributions(contributions, metric, scope)
    if scoped.empty:
        raise ValueError(f"pair contributions carry no {scope} 2024--2026 {metric} rows")
    endpoint = scoped["src"].eq(WETH) | scoped["tgt"].eq(WETH)
    cohorts: dict[str, pd.DataFrame] = {}
    mass_shares: list[float] = []
    for prefix, component, _weight, _share, _sign in SUPPORT_COHORTS:
        rows = scoped[scoped["contribution_component"].eq(component)]
        if rows.empty:
            raise ValueError(f"pair contributions carry no {metric} {component} rows")
        mass_share = float(rows["aggregate_mass_share_midpoint"].iloc[0])
        if not rows["aggregate_mass_share_midpoint"].eq(mass_share).all():
            raise ValueError(f"{metric} {scope} {component} carries several mass shares")
        if not 0 < mass_share < 1:
            raise ValueError(f"{metric} {scope} exclusive mass share leaves the unit range")
        cohorts[prefix] = rows
        mass_shares.append(mass_share)
    # The shared premise before any per-cohort arithmetic: the two cohorts are
    # weighted by one activity mass, without which the gap between their routing
    # rates is not what the netted term measures.
    if not math.isclose(mass_shares[0], mass_shares[1], abs_tol=1e-12):
        raise ValueError(
            f"{metric} {scope} exclusive cohorts carry different activity mass, so "
            "their difference is not a routing comparison"
        )
    mass_share = mass_shares[0]
    cohorts_out: dict[str, object] = {}
    margins: list[float] = []
    for prefix, component, weight_column, share_column, sign in SUPPORT_COHORTS:
        rows = cohorts[prefix]
        locked = rows[endpoint.loc[rows.index]]
        if locked.empty:
            raise ValueError(f"{metric} {scope} {component} has no WETH-endpoint corridor")
        if not locked[share_column].eq(1.0).all():
            raise ValueError(
                f"{metric} {scope} breaks the WETH-endpoint eligibility identity on "
                f"the {component} cohort"
            )
        weight = float(rows[weight_column].sum())
        if not math.isclose(weight, 1.0, abs_tol=1e-9):
            raise ValueError(
                f"{metric} {scope} {component} weights do not close on their cohort, "
                "so a cohort routing rate would not be a weighted mean"
            )
        stable_share = float((rows[weight_column] * rows[share_column]).sum())
        margin_pp = float(rows["contribution_pp"].sum())
        if not math.isclose(
            margin_pp, sign * 100 * mass_share * stable_share, abs_tol=1e-6
        ):
            raise ValueError(
                f"{metric} {scope} {component} is not its cohort's activity mass "
                "times its routing rate"
            )
        opened = rows[~endpoint.loc[rows.index]]
        open_weight = float(opened[weight_column].sum())
        if not 0 < open_weight < 1:
            raise ValueError(
                f"{metric} {scope} {component} has no corridor with an open vehicle "
                "choice, so an open routing rate would not be defined"
            )
        open_share = float((opened[weight_column] * opened[share_column]).sum())
        locked_pp = float(locked["contribution_pp"].sum())
        open_pp = float(opened["contribution_pp"].sum())
        if not math.isclose(locked_pp + open_pp, margin_pp, abs_tol=1e-6):
            raise ValueError(f"{metric} {scope} {component} eligibility split misses its total")
        if locked_pp * margin_pp < 0 or open_pp * margin_pp < 0:
            raise ValueError(
                f"{metric} {scope} {component} eligibility split straddles zero, so a "
                "share of that margin would not be interpretable"
            )
        if not math.isclose(
            open_pp, sign * 100 * mass_share * open_share, abs_tol=1e-6
        ):
            raise ValueError(
                f"{metric} {scope} {component} open contribution is not its open mass "
                "times its open routing rate"
            )
        margins.append(margin_pp)
        cohorts_out[prefix] = {
            "margin_pp": margin_pp,
            "stable_share": stable_share,
            "open_weight": open_weight,
            "open_stable_share": open_share / open_weight,
            "locked_pp": locked_pp,
            "open_pp": open_pp,
        }
    net_pp = margins[0] + margins[1]
    if not math.isclose(
        net_pp, 100 * float(aggregate["exclusive_pair_contribution"]), abs_tol=1e-6
    ):
        raise ValueError(
            f"{metric} {scope} exclusive-support cohorts do not reconcile the exclusive-pair term"
        )
    cohorts_out["mass_share"] = mass_share
    cohorts_out["net_pp"] = net_pp
    return cohorts_out


def _cohort_endpoint_margins(
    contributions: pd.DataFrame,
    metric: str,
    cohorts: dict[str, object],
    scope: str = "pooled",
) -> dict[str, object]:
    """Split the corridor-replacement gap into composition and routing rate.

    See ``COHORT_ENDPOINT_CLASSES`` for the identity. ``_support_cohorts``
    establishes that the netted exclusive term is one activity mass times the
    gap between the routing rates of the departing and arriving corridors. That
    gap is still two numbers, and the economics behind it are two different
    claims: the arriving corridors may be a different mix of markets, or markets
    of the same kind may route differently. This separates them exactly.

    Nothing here re-estimates. Each class weight and rate is a weighted sum of
    the same certified rows the cohort reading already used, and the function
    refuses to publish until the two sums close on that cohort's own gap and the
    gap closes on the term the caller validated. The stablecoin-endpoint class
    is held to the same non-degeneracy standard as in
    ``_open_corridor_endpoints``: if a stablecoin at an endpoint forced the
    intermediary, its rate term would be an accounting rule rather than a
    routing choice.
    """
    scoped = _scoped_contributions(contributions, metric, scope)
    if scoped.empty:
        raise ValueError(f"pair contributions carry no {scope} 2024--2026 {metric} rows")
    endpoint = scoped["src"].eq(WETH) | scoped["tgt"].eq(WETH)
    stable_endpoint = ~endpoint & (
        scoped["src"].map(asset_type).eq("stable")
        | scoped["tgt"].map(asset_type).eq("stable")
    )
    selectors = {
        "Locked": endpoint,
        "StableEnd": stable_endpoint,
        "OtherEnd": ~endpoint & ~stable_endpoint,
    }
    cells: dict[tuple[str, str], dict[str, float]] = {}
    for prefix, component, weight_column, share_column, _sign in SUPPORT_COHORTS:
        rows = scoped[scoped["contribution_component"].eq(component)]
        if rows.empty:
            raise ValueError(f"pair contributions carry no {metric} {component} rows")
        covered = 0.0
        for name in COHORT_ENDPOINT_CLASSES:
            block = rows[selectors[name].loc[rows.index]]
            weight = float(block[weight_column].sum())
            if not 0 < weight < 1:
                raise ValueError(
                    f"{metric} {scope} {prefix} cohort carries no {name} activity, so "
                    "that class has no routing rate to compare"
                )
            rate = float((block[weight_column] * block[share_column]).sum()) / weight
            if not 0 <= rate <= 1:
                raise ValueError(
                    f"{metric} {scope} {prefix} {name} routing rate leaves the unit "
                    "interval"
                )
            covered += weight
            cells[(prefix, name)] = {
                "weight": weight,
                "rate": rate,
                "pairs": float(len(block)),
            }
        if not math.isclose(covered, 1.0, abs_tol=1e-9):
            raise ValueError(
                f"{metric} {scope} {prefix} endpoint classes cover {covered} of that "
                "cohort, so they do not partition it"
            )
        # The eligibility identity, re-proved on this cohort rather than
        # inherited: a wrapped-ether-paired corridor cannot use the native asset
        # as its intermediary, so its rate is one and its class can move the gap
        # only through weight.
        if not math.isclose(cells[(prefix, "Locked")]["rate"], 1.0, abs_tol=1e-12):
            raise ValueError(
                f"{metric} {scope} {prefix} wrapped-ether-endpoint corridors do not "
                "route at a stablecoin share of one, which the eligibility identity "
                "forbids"
            )
        live = rows[stable_endpoint.loc[rows.index]]
        if not live[share_column].lt(1.0).any():
            raise ValueError(
                f"{metric} {scope} {prefix} stablecoin-endpoint corridors always route "
                "at a stablecoin share of one, so the class is an identity rather than "
                "a choice"
            )
        if not live[share_column].gt(0.0).any():
            raise ValueError(
                f"{metric} {scope} {prefix} stablecoin-endpoint corridors never route "
                "through a stablecoin, so the class cannot carry the margin attributed "
                "to it"
            )
        pinned = float(live[share_column].eq(1.0).mean())
        if pinned >= 0.25:
            raise ValueError(
                f"{metric} {scope} {prefix} stablecoin-endpoint corridors are "
                f"{pinned:.1%} pinned at a stablecoin share of one, which is too close "
                "to the wrapped-ether identity for the split to be read as a choice"
            )
        cells[(prefix, "pinned")] = {"weight": pinned, "rate": pinned, "pairs": pinned}
    mass_share = float(cohorts["mass_share"])
    net_pp = float(cohorts["net_pp"])
    classes: dict[str, object] = {}
    composition = 0.0
    rate_term = 0.0
    for name in COHORT_ENDPOINT_CLASSES:
        exit_cell = cells[("Exit", name)]
        enter_cell = cells[("Enter", name)]
        composition_c = (enter_cell["weight"] - exit_cell["weight"]) * (
            enter_cell["rate"] + exit_cell["rate"]
        ) / 2
        rate_c = (enter_cell["weight"] + exit_cell["weight"]) / 2 * (
            enter_cell["rate"] - exit_cell["rate"]
        )
        composition += composition_c
        rate_term += rate_c
        classes[name] = {
            "exit_pairs": int(exit_cell["pairs"]),
            "enter_pairs": int(enter_cell["pairs"]),
            "exit_weight": exit_cell["weight"],
            "enter_weight": enter_cell["weight"],
            "exit_rate": exit_cell["rate"],
            "enter_rate": enter_cell["rate"],
            "composition_pp": 100 * mass_share * composition_c,
            "rate_pp": 100 * mass_share * rate_c,
        }
    gap = sum(
        cells[("Enter", name)]["weight"] * cells[("Enter", name)]["rate"]
        - cells[("Exit", name)]["weight"] * cells[("Exit", name)]["rate"]
        for name in COHORT_ENDPOINT_CLASSES
    )
    if not math.isclose(composition + rate_term, gap, abs_tol=1e-12):
        raise ValueError(
            f"{metric} {scope} composition and rate terms miss the cohort routing gap"
        )
    if not math.isclose(100 * mass_share * gap, net_pp, abs_tol=1e-6):
        raise ValueError(
            f"{metric} {scope} cohort endpoint classes do not reconcile the "
            "exclusive-pair term"
        )
    # A share is formed only against a base proved positive. The netted term is
    # positive in every scope this is called for, but the two sides of the split
    # are individually free to take either sign -- the other-endpoint class
    # contributes negative composition in both metrics -- so the guard is on the
    # base and never on the parts.
    if net_pp <= 0:
        raise ValueError(
            f"{metric} {scope} exclusive-pair term is not positive, so a share of it "
            "is not a quantity"
        )
    return {
        **classes,
        "composition_pp": 100 * mass_share * composition,
        "rate_pp": 100 * mass_share * rate_term,
        "composition_share": 100 * mass_share * composition / net_pp,
        "rate_share": 100 * mass_share * rate_term / net_pp,
        "net_pp": net_pp,
    }


def _support_mass_factors(row: pd.Series, metric: str, scope: str) -> dict[str, float]:
    """Split the support-mass term into the mass that moved and the price of it.

    See ``SUPPORT_BLOCKS`` for the identity. Nothing here is a re-estimation:
    every quantity is a cell of the row the caller already validated, and the
    function's work is to prove that the two published factors are the factors
    of that row's own term. Three premises come first -- the two block weights
    partition activity in each year, and each year's aggregate stablecoin share
    is the activity-weighted mean of the two block shares -- because a mass
    shift and a block gap are only the factors of this term if the blocks
    exhaust the year they are read from. The midpoint gap is then formed and
    multiplied out against ``common_support_mass`` itself.
    """
    weights: dict[str, dict[str, float]] = {}
    shares: dict[str, dict[str, float]] = {}
    for prefix, weight_stem, share_stem in SUPPORT_BLOCKS:
        weights[prefix] = {
            endpoint: float(row[f"{weight_stem}_{endpoint}"])
            for endpoint in ("baseline", "comparison")
        }
        shares[prefix] = {
            endpoint: float(row[f"{share_stem}_{endpoint}"])
            for endpoint in ("baseline", "comparison")
        }
        if not all(0 <= value <= 1 for value in weights[prefix].values()):
            raise ValueError(f"{metric} {scope} {prefix} block weight leaves the unit range")
        if not all(0 <= value <= 1 for value in shares[prefix].values()):
            raise ValueError(f"{metric} {scope} {prefix} block share leaves the unit range")
    for endpoint, aggregate in (
        ("baseline", "baseline_stable_share"),
        ("comparison", "comparison_stable_share"),
    ):
        partition = sum(weights[prefix][endpoint] for prefix, _w, _s in SUPPORT_BLOCKS)
        if not math.isclose(partition, 1.0, abs_tol=1e-12):
            raise ValueError(
                f"{metric} {scope} {endpoint} block weights do not partition activity, "
                "so a mass shift between them is not a shift of the whole"
            )
        mean = sum(
            weights[prefix][endpoint] * shares[prefix][endpoint]
            for prefix, _w, _s in SUPPORT_BLOCKS
        )
        if not math.isclose(mean, float(row[aggregate]), abs_tol=1e-12):
            raise ValueError(
                f"{metric} {scope} {endpoint} block shares do not reconcile that "
                "year's aggregate stablecoin share"
            )
    common_mid = (shares["Common"]["baseline"] + shares["Common"]["comparison"]) / 2
    exclusive_mid = (
        shares["Exclusive"]["baseline"] + shares["Exclusive"]["comparison"]
    ) / 2
    gap = common_mid - exclusive_mid
    shift = weights["Common"]["comparison"] - weights["Common"]["baseline"]
    term = float(row["common_support_mass"])
    if not math.isclose(gap * shift, term, abs_tol=1e-12):
        raise ValueError(
            f"{metric} {scope} support-mass factors do not multiply to the term"
        )
    return {
        "common_baseline": shares["Common"]["baseline"],
        "common_comparison": shares["Common"]["comparison"],
        "common_mid": common_mid,
        "exclusive_mid": exclusive_mid,
        "weight_baseline": weights["Common"]["baseline"],
        "weight_comparison": weights["Common"]["comparison"],
        "gap": gap,
        "shift": shift,
        "term": term,
    }


def _scope_margin_total(
    row: pd.Series, prefix: str, statistics: dict[str, float]
) -> str:
    """That scope's own total for the margin the eligibility split is taken of.

    Every scope share must be printable beside the total it is a share of, and
    for one of the two margins that total is not a decomposition term. See
    ``SCOPE_MARGIN_TERMS`` for which is which.
    """
    term = SCOPE_MARGIN_TERMS.get(prefix)
    if term is not None:
        return _signed_pp(float(row[term]))
    return _contribution_pp(float(statistics["component_pp"]))


def _matched_market_row(fixed_effects: pd.DataFrame, metric: str) -> pd.Series:
    required = {
        "metric",
        "baseline_year",
        "comparison_year",
        "estimator_id",
        "covariance_id",
        "mechanism_status",
        "estimand_scope",
        "coefficient",
        "standard_error",
        "confidence_interval_lower",
        "confidence_interval_upper",
        "p_value_holm",
        "observations",
        "fixed_effect_cells",
        "ordered_pair_clusters",
        "calendar_date_clusters",
        "baseline_denominator_mass",
        "comparison_denominator_mass",
    }
    missing = sorted(required - set(fixed_effects.columns))
    if missing:
        raise ValueError(f"pair fixed effects missing columns: {', '.join(missing)}")
    selected = fixed_effects[fixed_effects["metric"].eq(metric)]
    if len(selected) != 1:
        raise ValueError(
            f"pair fixed effects require exactly one {metric} row; "
            f"found {len(selected)}"
        )
    row = selected.iloc[0]
    if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
        raise ValueError("pair fixed effects must compare 2024 with 2026")
    if (
        row["estimator_id"]
        != "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
    ):
        raise ValueError("pair fixed effects use an unexpected estimator")
    if row["covariance_id"] != "two_way_ordered_pair_calendar_date_cr1":
        raise ValueError("pair fixed effects use unexpected inference")
    if row["mechanism_status"] != "descriptive_fixed_realised_scope_noncausal":
        raise ValueError("pair fixed effects carry a causal mechanism label")
    if row["estimand_scope"] != "common_pair_month_day_realised_integration_scope":
        raise ValueError("pair fixed effects use an unexpected comparison set")
    numeric = (
        "coefficient",
        "standard_error",
        "confidence_interval_lower",
        "confidence_interval_upper",
        "p_value_holm",
        "observations",
        "fixed_effect_cells",
        "ordered_pair_clusters",
        "calendar_date_clusters",
    )
    if not all(math.isfinite(float(row[column])) for column in numeric):
        raise ValueError("pair fixed effects contain a non-finite result")
    if float(row["standard_error"]) <= 0:
        raise ValueError("pair fixed effects require a positive standard error")
    if not (
        float(row["confidence_interval_lower"])
        <= float(row["coefficient"])
        <= float(row["confidence_interval_upper"])
    ):
        raise ValueError("pair fixed-effects interval excludes its estimate")
    if not 0 <= float(row["p_value_holm"]) <= 1:
        raise ValueError("pair fixed effects contain an invalid adjusted p-value")
    return row


def _matched_coverage(
    support: pd.DataFrame,
    matched: pd.Series,
    identity: pd.Series,
    metric: str,
) -> dict[str, float]:
    """Price the matched estimator's reach against the identity's own blocks.

    See ``COVERAGE_CLASSES`` for why the two populations differ. Six premises,
    in order of what they license. Every class must report a finite,
    non-negative denominator on both endpoints, or a coverage ratio is a ratio
    over nothing. No class may hold a cell-year whose denominator vanished, or
    the class's own share is a ratio over a degenerate cell. Each exclusive
    class must be empty on the endpoint it is absent from, or it is not
    exclusive and the block boundary is elsewhere. The three classes' shares
    must close on one in each year, or they are not a partition of that year.
    The common class's two shares must reproduce the identity row's own
    ``W_baseline`` and ``W_comparison``, or the support ledger is partitioning
    something other than the block the identity prices. Finally the matched
    denominator must be positive and no larger than the common class's, because
    the matched sample is a subset of the block by construction and a coverage
    ratio above one would mean it is not.
    """

    required = {
        "record_type",
        "metric",
        "reporting_scope",
        "support_status",
        "units",
        "baseline_denominator",
        "comparison_denominator",
        "baseline_denominator_share",
        "comparison_denominator_share",
        "zero_denominator_cell_years",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        raise ValueError(f"pair support ledger missing columns: {', '.join(missing)}")
    selected = support[
        support["record_type"].eq("decomposition_pair_support")
        & support["metric"].eq(metric)
        & support["reporting_scope"].eq("pooled")
    ]
    if len(selected) != len(COVERAGE_CLASSES):
        raise ValueError(
            f"decomposition support requires exactly {len(COVERAGE_CLASSES)} pooled "
            f"{metric} rows; found {len(selected)}"
        )
    classes: dict[str, pd.Series] = {}
    for status in COVERAGE_CLASSES:
        rows = selected[selected["support_status"].eq(status)]
        if len(rows) != 1:
            raise ValueError(
                f"decomposition support has {len(rows)} {metric} rows for {status}"
            )
        classes[status] = rows.iloc[0]
    endpoints = ("baseline", "comparison")
    for status, row in classes.items():
        if float(row["zero_denominator_cell_years"]) != 0:
            raise ValueError(
                f"decomposition support {metric} {status} carries a zero-denominator "
                "cell-year"
            )
        if int(row["units"]) <= 0:
            raise ValueError(f"decomposition support {metric} {status} holds no pairs")
        for endpoint in endpoints:
            mass = float(row[f"{endpoint}_denominator"])
            share = float(row[f"{endpoint}_denominator_share"])
            if not math.isfinite(mass) or mass < 0:
                raise ValueError(
                    f"decomposition support {metric} {status} {endpoint} mass is invalid"
                )
            if not math.isfinite(share) or share < 0:
                raise ValueError(
                    f"decomposition support {metric} {status} {endpoint} share is invalid"
                )
        absent = COVERAGE_ABSENT_ENDPOINT.get(status)
        if absent is not None and float(row[f"{absent}_denominator"]) != 0:
            raise ValueError(
                f"decomposition support {metric} {status} is not exclusive: it carries "
                f"{absent} mass"
            )
    totals: dict[str, float] = {}
    for endpoint in endpoints:
        total = sum(
            float(row[f"{endpoint}_denominator"]) for row in classes.values()
        )
        if total <= 0:
            raise ValueError(f"decomposition support {metric} {endpoint} year is empty")
        totals[endpoint] = total
        shares = sum(
            float(row[f"{endpoint}_denominator_share"]) for row in classes.values()
        )
        if not math.isclose(shares, 1.0, abs_tol=1e-12):
            raise ValueError(
                f"decomposition support {metric} {endpoint} shares do not partition "
                f"the year: {shares}"
            )
        common_share = float(classes["common"][f"{endpoint}_denominator_share"])
        if not math.isclose(
            common_share,
            float(classes["common"][f"{endpoint}_denominator"]) / total,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"decomposition support {metric} common {endpoint} share is not its "
                "own mass over the year"
            )
        identity_weight = float(identity[f"W_{endpoint}"])
        if not math.isclose(common_share, identity_weight, abs_tol=1e-12):
            raise ValueError(
                f"decomposition support {metric} common {endpoint} share "
                f"{common_share} is not the identity's block weight {identity_weight}"
            )
    coverage: dict[str, float] = {
        "pairs": float(sum(int(row["units"]) for row in classes.values())),
        "block_pairs": float(int(classes["common"]["units"])),
        "matched_pairs": float(matched["ordered_pair_clusters"]),
    }
    if not 0 < coverage["matched_pairs"] <= coverage["block_pairs"]:
        raise ValueError(
            f"{metric} matched pairs {coverage['matched_pairs']} do not sit inside the "
            f"identity's block of {coverage['block_pairs']}"
        )
    for endpoint in endpoints:
        block = float(classes["common"][f"{endpoint}_denominator"])
        reached = float(matched[f"{endpoint}_denominator_mass"])
        if not math.isfinite(reached) or reached <= 0:
            raise ValueError(f"{metric} matched {endpoint} denominator is empty")
        if reached > block:
            raise ValueError(
                f"{metric} matched {endpoint} mass {reached} exceeds the identity's "
                f"block mass {block}"
            )
        coverage[f"{endpoint}_of_sample"] = reached / totals[endpoint]
        coverage[f"{endpoint}_of_block"] = reached / block
    return coverage


def _cell_support_classes(support: pd.DataFrame, metric: str) -> dict[str, pd.Series]:
    """Read one metric's three cell classes and reject anything but a partition.

    A class must hold cells, report finite non-negative mass on both endpoints,
    and be empty on the year it is absent from, or the label is wrong and the
    boundary between the classes is somewhere else. The count of cell-years the
    measure's own eligibility filter emptied is a property of the metric rather
    than of a class, so the three rows must agree on it; disagreement means the
    filter was applied class by class and the classes are no longer comparable.
    """

    selected = support[
        support["record_type"].eq("pair_month_day_scope_support")
        & support["metric"].eq(metric)
        & support["reporting_scope"].eq("scope_specific")
    ]
    if len(selected) != len(CELL_SUPPORT_CLASSES):
        raise ValueError(
            f"cell support requires exactly {len(CELL_SUPPORT_CLASSES)} scope-specific "
            f"{metric} rows; found {len(selected)}"
        )
    classes: dict[str, pd.Series] = {}
    for status in CELL_SUPPORT_CLASSES:
        rows = selected[selected["support_status"].eq(status)]
        if len(rows) != 1:
            raise ValueError(f"cell support has {len(rows)} {metric} rows for {status}")
        classes[status] = rows.iloc[0]
    for status, row in classes.items():
        if int(row["units"]) <= 0:
            raise ValueError(f"cell support {metric} {status} holds no cells")
        for endpoint in ("baseline", "comparison"):
            mass = float(row[f"{endpoint}_denominator"])
            if not math.isfinite(mass) or mass < 0:
                raise ValueError(
                    f"cell support {metric} {status} {endpoint} mass is invalid"
                )
        absent = CELL_ABSENT_ENDPOINT.get(status)
        if absent is not None and float(row[f"{absent}_denominator"]) != 0:
            raise ValueError(
                f"cell support {metric} {status} is not one-sided: it carries "
                f"{absent} mass"
            )
    filtered = {float(row["zero_denominator_cell_years"]) for row in classes.values()}
    if len(filtered) != 1 or min(filtered) < 0:
        raise ValueError(
            f"cell support {metric} classes disagree on emptied cell-years: "
            f"{sorted(filtered)}"
        )
    return classes


def _matched_cell_support(
    support: pd.DataFrame,
    matched: pd.Series,
    metric: str,
) -> dict[str, float]:
    """Measure what conditioning on pair, day and scope jointly selects on.

    The matched regression runs on the common class of this partition, so the
    ledger and the estimator must agree cell for cell: the common class must
    hold exactly the exhibit's own fixed-effect cells, contribute one cell-year
    per endpoint and no more, and carry exactly the endpoint masses the exhibit
    reported. Once that holds, the two ratios this returns are comparable. A
    class's share of the year's cells says how much of the market's calendar the
    matching keeps; its share of the year's mass says how much of the market. The
    ratio between them is the thickness of a matched cell relative to the average
    active cell, which is the sense in which the joint condition selects markets
    that trade routinely rather than markets that trade at all.
    """

    classes = _cell_support_classes(support, metric)
    common = classes["common"]
    cells = int(common["units"])
    exhibit_cells = int(matched["fixed_effect_cells"])
    if cells != exhibit_cells:
        raise ValueError(
            f"{metric} cell support holds {cells:,} common cells but the estimator "
            f"reports {exhibit_cells:,}"
        )
    observations = int(matched["observations"])
    if observations != 2 * cells:
        raise ValueError(
            f"{metric} matched sample reports {observations:,} observations on "
            f"{cells:,} cells; a matched cell contributes one cell-year per endpoint"
        )
    reach: dict[str, float] = {
        "matched_cells": float(cells),
        "filtered_cell_years": float(common["zero_denominator_cell_years"]),
    }
    for endpoint in ("baseline", "comparison"):
        one_sided = classes[f"{endpoint}_only"]
        year_cells = cells + int(one_sided["units"])
        block = float(common[f"{endpoint}_denominator"])
        reported = float(matched[f"{endpoint}_denominator_mass"])
        if not math.isclose(block, reported, rel_tol=1e-12, abs_tol=1e-6):
            raise ValueError(
                f"{metric} cell support carries {endpoint} mass {block} where the "
                f"estimator reports {reported}"
            )
        year_mass = block + float(one_sided[f"{endpoint}_denominator"])
        if year_mass <= 0:
            raise ValueError(f"cell support {metric} {endpoint} year is empty")
        cell_share = cells / year_cells
        mass_share = block / year_mass
        if not 0 < cell_share <= 1:
            raise ValueError(
                f"{metric} matched cells are not a share of the {endpoint} year: "
                f"{cell_share}"
            )
        reach[f"{endpoint}_cells"] = float(year_cells)
        reach[f"{endpoint}_cell_share"] = cell_share
        reach[f"{endpoint}_mass_share"] = mass_share
        reach[f"{endpoint}_thickness"] = mass_share / cell_share
    return reach


def _strict_cell_populations_agree(support: pd.DataFrame) -> None:
    """The two strict metrics weight one perimeter; a divergence is a filter bug."""

    populations = {
        metric: {
            status: int(row["units"])
            for status, row in _cell_support_classes(support, metric).items()
        }
        for metric in STRICT_CELL_METRICS
    }
    counted, valued = (populations[metric] for metric in STRICT_CELL_METRICS)
    if counted != valued:
        raise ValueError(
            f"strict count cells {counted} do not match strict value cells {valued}"
        )


def _usdt_integration_rows(decomposition: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "record_type",
        "focal_symbol",
        "comparison_components",
        "baseline_year",
        "comparison_year",
        "weighting",
        "value_support",
        "total_usdt_share_change",
        "within_scope_change",
        "between_scope_composition_change",
        "within_scope_share_of_change",
        "between_scope_share_of_change",
        "identity_residual",
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(f"USDT integration decomposition missing columns: {', '.join(missing)}")
    selected = decomposition[decomposition["record_type"].eq("midpoint_decomposition")]
    rows: dict[str, pd.Series] = {}
    specifications = {
        "count": ("episode", "all_routes"),
        "value": ("value", "within_20pct"),
    }
    for label, (weighting, support) in specifications.items():
        match = selected[
            selected["weighting"].eq(weighting)
            & selected["value_support"].eq(support)
        ]
        if len(match) != 1:
            raise ValueError(
                f"USDT integration decomposition requires exactly one {label} row; "
                f"found {len(match)}"
            )
        row = match.iloc[0]
        if (
            row["focal_symbol"] != "USDT"
            or row["comparison_components"] != "native+USDC+USDT"
            or int(row["baseline_year"]) != 2024
            or int(row["comparison_year"]) != 2026
        ):
            raise ValueError("USDT integration decomposition uses an unexpected scope")
        numeric = (
            "total_usdt_share_change",
            "within_scope_change",
            "between_scope_composition_change",
            "within_scope_share_of_change",
            "between_scope_share_of_change",
            "identity_residual",
        )
        if not all(math.isfinite(float(row[column])) for column in numeric):
            raise ValueError("USDT integration decomposition contains a non-finite value")
        if not math.isclose(
            float(row["within_scope_change"])
            + float(row["between_scope_composition_change"]),
            float(row["total_usdt_share_change"]),
            abs_tol=1e-12,
        ) or not math.isclose(
            float(row["within_scope_share_of_change"])
            + float(row["between_scope_share_of_change"]),
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("USDT integration decomposition does not reconcile")
        if abs(float(row["identity_residual"])) > 1e-12:
            raise ValueError("USDT integration decomposition has an identity residual")
        rows[label] = row
    return rows


def render_pair_decomposition_deck_values(
    decomposition: pd.DataFrame,
    fixed_effects: pd.DataFrame,
    usdt_integration: pd.DataFrame,
    contributions: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Render empirical cells while keeping evidence identity out of the PDF."""
    count = _scope_rows(decomposition, "count_share")
    value = _scope_rows(decomposition, "strict_intermediation_value_share")
    market = _market_incidence_row(decomposition)
    _cross_panel_common_bridge(count["pooled"], market)
    incidence = _market_incidence_classes(support, market)
    matched_count = _matched_market_row(fixed_effects, "count_share")
    matched_value = _matched_market_row(
        fixed_effects, "strict_intermediation_value_share"
    )
    count_coverage = _matched_coverage(
        support, matched_count, count["pooled"], "count_share"
    )
    value_coverage = _matched_coverage(
        support, matched_value, value["pooled"], "strict_intermediation_value_share"
    )
    _strict_cell_populations_agree(support)
    count_cells = _matched_cell_support(support, matched_count, "count_share")
    value_cells = _matched_cell_support(
        support, matched_value, "strict_intermediation_value_share"
    )
    usdt = _usdt_integration_rows(usdt_integration)
    pair_activity_total = float(market["market_pair_support_bridge"]) + float(
        market["market_activity_reweighting"]
    )
    vehicle_use_net = float(market["vehicle_incidence_reweighting"]) + float(
        market["vehicle_role_support_bridge"]
    )
    pair_and_vehicle_total = pair_activity_total + vehicle_use_net
    pair_and_vehicle_share = pair_and_vehicle_total / float(market["total_change"])
    if not math.isclose(
        pair_and_vehicle_total + float(market["within_pair_stable_share"]),
        float(market["total_change"]),
        abs_tol=1e-12,
    ):
        raise ValueError("market-incidence display groups do not reconcile")
    pooled = count["pooled"]
    lines = [
        "% Generated by scripts/build_vehicle_transition_pair_deck_values.py; do not edit.",
        f"\\newcommand{{\\PairPooledBase}}{{{_share(float(pooled['baseline_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledEnd}}{{{_share(float(pooled['comparison_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledTotal}}{{{_signed_pp(float(pooled['total_change']))}}}",
        f"\\newcommand{{\\PairPooledReweight}}{{{_signed_pp(float(pooled['common_pair_reweighting']))}}}",
        f"\\newcommand{{\\PairPooledSupportMass}}{{{_signed_pp(float(pooled['common_support_mass']))}}}",
        f"\\newcommand{{\\PairPooledExclusive}}{{{_signed_pp(float(pooled['exclusive_pair_contribution']))}}}",
        f"\\newcommand{{\\PairPooledWithin}}{{{_signed_pp(float(pooled['within_common']))}}}",
        f"\\newcommand{{\\PairPooledBaseRawPct}}{{{_raw_pct(float(pooled['baseline_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledEndRawPct}}{{{_raw_pct(float(pooled['comparison_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledReweightRawPP}}{{{_raw_pp(float(pooled['common_pair_reweighting']))}}}",
        f"\\newcommand{{\\PairPooledSupportMassRawPP}}{{{_raw_pp(float(pooled['common_support_mass']))}}}",
        f"\\newcommand{{\\PairPooledExclusiveRawPP}}{{{_raw_pp(float(pooled['exclusive_pair_contribution']))}}}",
        f"\\newcommand{{\\PairPooledWithinRawPP}}{{{_raw_pp(float(pooled['within_common']))}}}",
    ]
    for scope, suffix in (("single_venue", "Single"), ("cross_venue", "Cross")):
        row = count[scope]
        lines.extend(
            [
                f"\\newcommand{{\\Pair{suffix}Total}}{{{_signed_pp(float(row['total_change']))}}}",
                f"\\newcommand{{\\Pair{suffix}Within}}{{{_signed_pp(float(row['within_common']))}}}",
            ]
        )
    value_pooled = value["pooled"]
    lines.extend(
        [
            f"\\newcommand{{\\PairValueTotal}}{{{_signed_pp(float(value_pooled['total_change']))}}}",
            f"\\newcommand{{\\PairValueWithin}}{{{_signed_pp(float(value_pooled['within_common']))}}}",
            f"\\newcommand{{\\PairValueReweight}}{{{_signed_pp(float(value_pooled['common_pair_reweighting']))}}}",
            f"\\newcommand{{\\PairValueSupportMass}}{{{_signed_pp(float(value_pooled['common_support_mass']))}}}",
            f"\\newcommand{{\\PairValueExclusive}}{{{_signed_pp(float(value_pooled['exclusive_pair_contribution']))}}}",
        ]
    )
    lines.extend(
        [
            f"\\newcommand{{\\MarketBridgeBase}}{{{_share(float(market['baseline_stable_share']))}}}",
            f"\\newcommand{{\\MarketBridgeEnd}}{{{_share(float(market['comparison_stable_share']))}}}",
            f"\\newcommand{{\\MarketBridgeTotal}}{{{_signed_pp(float(market['total_change']))}}}",
            f"\\newcommand{{\\MarketSupportBridge}}{{{_signed_pp(float(market['market_pair_support_bridge']))}}}",
            f"\\newcommand{{\\VehicleRoleSupportBridge}}{{{_signed_pp(float(market['vehicle_role_support_bridge']))}}}",
            f"\\newcommand{{\\MarketActivityReweight}}{{{_signed_pp(float(market['market_activity_reweighting']))}}}",
            f"\\newcommand{{\\VehicleIncidenceReweight}}{{{_signed_pp(float(market['vehicle_incidence_reweighting']))}}}",
            f"\\newcommand{{\\WithinPairStableShare}}{{{_signed_pp(float(market['within_pair_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsBase}}{{{_share(float(market['established_market_baseline_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsEnd}}{{{_share(float(market['established_market_comparison_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsTotal}}{{{_signed_pp(float(market['established_market_total_change']))}}}",
            f"\\newcommand{{\\CommonRoleTotal}}{{{_signed_pp(float(market['common_role_total_change']))}}}",
            *(
                line
                for infix, _status in INCIDENCE_CLASSES
                for suffix, _year in INCIDENCE_YEARS
                for line in (
                    f"\\newcommand{{\\Incidence{infix}Weight{suffix}}}"
                    f"{{{_share(incidence[infix][suffix]['weight'])}}}",
                    f"\\newcommand{{\\Incidence{infix}Stable{suffix}}}"
                    f"{{{_share(incidence[infix][suffix]['stable_share'])}}}",
                    f"\\newcommand{{\\Incidence{infix}Pairs{suffix}}}"
                    f"{{{_units(incidence[infix][suffix]['pairs'])}}}",
                )
            ),
            f"\\newcommand{{\\PairActivityTotal}}{{{_signed_pp(pair_activity_total)}}}",
            f"\\newcommand{{\\VehicleUseNet}}{{{_signed_pp(vehicle_use_net)}}}",
            f"\\newcommand{{\\PairAndVehicleTotal}}{{{_signed_pp(pair_and_vehicle_total)}}}",
            f"\\newcommand{{\\PairAndVehicleShare}}{{{_share(pair_and_vehicle_share)}}}",
            f"\\newcommand{{\\MarketBridgeBaseRawPct}}{{{_raw_pct(float(market['baseline_stable_share']))}}}",
            f"\\newcommand{{\\MarketSupportBridgeRawPP}}{{{_raw_pp(float(market['market_pair_support_bridge']))}}}",
            f"\\newcommand{{\\VehicleRoleSupportBridgeRawPP}}{{{_raw_pp(float(market['vehicle_role_support_bridge']))}}}",
            f"\\newcommand{{\\MarketActivityReweightRawPP}}{{{_raw_pp(float(market['market_activity_reweighting']))}}}",
            f"\\newcommand{{\\VehicleIncidenceReweightRawPP}}{{{_raw_pp(float(market['vehicle_incidence_reweighting']))}}}",
            f"\\newcommand{{\\WithinPairStableShareRawPP}}{{{_raw_pp(float(market['within_pair_stable_share']))}}}",
            f"\\newcommand{{\\PairActivityTotalRawPP}}{{{_raw_pp(pair_activity_total)}}}",
            f"\\newcommand{{\\VehicleUseNetRawPP}}{{{_raw_pp(vehicle_use_net)}}}",
            f"\\newcommand{{\\PairAndVehicleTotalRawPP}}{{{_raw_pp(pair_and_vehicle_total)}}}",
            f"\\newcommand{{\\MatchedMarketCountChange}}{{{_signed_pp(float(matched_count['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketCountSE}}{{{_unsigned_pp(float(matched_count['standard_error']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCILower}}{{{_signed_pp(float(matched_count['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCIUpper}}{{{_signed_pp(float(matched_count['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\MatchedMarketCountChangeRawPP}}{{{_raw_pp(float(matched_count['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCILowerRawPP}}{{{_raw_pp(float(matched_count['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCIUpperRawPP}}{{{_raw_pp(float(matched_count['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\MatchedMarketValueChange}}{{{_signed_pp(float(matched_value['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketValueSE}}{{{_unsigned_pp(float(matched_value['standard_error']))}}}",
            f"\\newcommand{{\\MatchedMarketValueCILower}}{{{_signed_pp(float(matched_value['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketValueCIUpper}}{{{_signed_pp(float(matched_value['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\SamplePairs}}{{{_units(count_coverage['pairs'])}}}",
            f"\\newcommand{{\\BlockPairs}}{{{_units(count_coverage['block_pairs'])}}}",
            f"\\newcommand{{\\MatchedPairs}}{{{_units(count_coverage['matched_pairs'])}}}",
            f"\\newcommand{{\\MatchedValuePairs}}{{{_units(value_coverage['matched_pairs'])}}}",
            f"\\newcommand{{\\MatchedCoverageBase}}{{{_share(count_coverage['baseline_of_sample'])}}}",
            f"\\newcommand{{\\MatchedCoverageEnd}}{{{_share(count_coverage['comparison_of_sample'])}}}",
            f"\\newcommand{{\\MatchedBlockCoverageBase}}{{{_share(count_coverage['baseline_of_block'])}}}",
            f"\\newcommand{{\\MatchedBlockCoverageEnd}}{{{_share(count_coverage['comparison_of_block'])}}}",
            f"\\newcommand{{\\MatchedValueCoverageBase}}{{{_share(value_coverage['baseline_of_sample'])}}}",
            f"\\newcommand{{\\MatchedValueCoverageEnd}}{{{_share(value_coverage['comparison_of_sample'])}}}",
            f"\\newcommand{{\\MatchedValueBlockCoverageBase}}{{{_share(value_coverage['baseline_of_block'])}}}",
            f"\\newcommand{{\\MatchedValueBlockCoverageEnd}}{{{_share(value_coverage['comparison_of_block'])}}}",
            f"\\newcommand{{\\MatchedCells}}{{{_units(count_cells['matched_cells'])}}}",
            f"\\newcommand{{\\SampleCellsBase}}{{{_units(count_cells['baseline_cells'])}}}",
            f"\\newcommand{{\\SampleCellsEnd}}{{{_units(count_cells['comparison_cells'])}}}",
            f"\\newcommand{{\\MatchedCellShareBase}}{{{_share(count_cells['baseline_cell_share'])}}}",
            f"\\newcommand{{\\MatchedCellShareEnd}}{{{_share(count_cells['comparison_cell_share'])}}}",
            f"\\newcommand{{\\MatchedCellThicknessBase}}{{{_multiple(count_cells['baseline_thickness'])}}}",
            f"\\newcommand{{\\MatchedCellThicknessEnd}}{{{_multiple(count_cells['comparison_thickness'])}}}",
            f"\\newcommand{{\\MatchedValueCellShareBase}}{{{_share(value_cells['baseline_cell_share'])}}}",
            f"\\newcommand{{\\MatchedValueCellShareEnd}}{{{_share(value_cells['comparison_cell_share'])}}}",
            f"\\newcommand{{\\MatchedValueCellThicknessBase}}{{{_multiple(value_cells['baseline_thickness'])}}}",
            f"\\newcommand{{\\MatchedValueCellThicknessEnd}}{{{_multiple(value_cells['comparison_thickness'])}}}",
            f"\\newcommand{{\\StrictFilteredCellYears}}{{{_units(value_cells['filtered_cell_years'])}}}",
            f"\\newcommand{{\\USDTVenueMixCountShare}}{{{_share(float(usdt['count']['between_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueWithinCountShare}}{{{_share(float(usdt['count']['within_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueMixValueShare}}{{{_share(float(usdt['value']['between_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueWithinValueShare}}{{{_share(float(usdt['value']['within_scope_share_of_change']))}}}",
        ]
    )
    examples = _margin_example_rows(contributions, pooled)
    for prefix, _component, _term in MARGIN_EXAMPLES:
        example = examples[prefix]
        lines.extend(
            [
                f"\\newcommand{{\\{prefix}Pair}}{{{example['source_symbol']}\\,$\\to$\\,{example['target_symbol']}}}",
                f"\\newcommand{{\\{prefix}StableBase}}{{{_share(float(example['stable_share_baseline']))}}}",
                f"\\newcommand{{\\{prefix}StableEnd}}{{{_share(float(example['stable_share_comparison']))}}}",
                f"\\newcommand{{\\{prefix}WeightBase}}{{{_activity_share(float(example['pair_weight_baseline']))}}}",
                f"\\newcommand{{\\{prefix}WeightEnd}}{{{_activity_share(float(example['pair_weight_comparison']))}}}",
                f"\\newcommand{{\\{prefix}RoutesBase}}{{{_routes(float(example['routes_baseline']))}}}",
                f"\\newcommand{{\\{prefix}RoutesEnd}}{{{_routes(float(example['routes_comparison']))}}}",
                f"\\newcommand{{\\{prefix}Contribution}}{{${float(example['contribution_pp']):+.2f}$ pp}}",
                f"\\newcommand{{\\{prefix}Total}}{{${float(example['component_pp']):+.1f}$ pp}}",
            ]
        )
    # The new-pair margin is gross; pairs that trade only in the baseline year
    # offset part of it. Publish the offset so a slide can close the arithmetic
    # against the net exclusive-pair term rather than implying +21 pp stands alone.
    lines.append(
        f"\\newcommand{{\\MarginRetiredPairTotal}}{{${_baseline_exclusive_pp(contributions):+.1f}$ pp}}"
    )
    for infix, metric in BREADTH_METRICS:
        aggregate = count["pooled"] if metric == "count_share" else value["pooled"]
        breadth = _margin_breadth(contributions, aggregate, metric)
        for prefix, _component, _term in MARGIN_EXAMPLES:
            statistics = breadth[prefix]
            lines.extend(
                [
                    f"\\newcommand{{\\{prefix}{infix}GainPairs}}"
                    f"{{{_units(int(statistics['gain_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}LossPairs}}"
                    f"{{{_units(int(statistics['loss_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}GrossUp}}"
                    f"{{{_contribution_pp(float(statistics['gross_up']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}GrossDown}}"
                    f"{{{_contribution_pp(float(statistics['gross_down']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}TopShare}}"
                    f"{{{_share(float(statistics['top_share']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}HalfPairs}}"
                    f"{{{_units(int(statistics['half_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}NinetyPairs}}"
                    f"{{{_units(int(statistics['ninety_pairs']))}}}",
                ]
            )
    # How much of each composition margin runs through corridors whose vehicle
    # was never in question. The count and value answers differ, which is the
    # point of publishing both.
    scope_rows_by_metric = {
        "count_share": count,
        "strict_intermediation_value_share": value,
    }
    for infix, metric in BREADTH_METRICS:
        scope_rows = scope_rows_by_metric[metric]
        eligibility = _endpoint_eligibility(contributions, metric, scope_rows["pooled"])
        lines.extend(
            [
                f"\\newcommand{{\\Locked{infix}Pairs}}"
                f"{{{_units(int(eligibility['locked_pairs']))}}}",
                f"\\newcommand{{\\Locked{infix}CommonPairs}}"
                f"{{{_units(int(eligibility['common_pairs']))}}}",
                f"\\newcommand{{\\Locked{infix}PairShare}}"
                f"{{{_share(float(eligibility['pair_share']))}}}",
                f"\\newcommand{{\\Locked{infix}WeightBase}}"
                f"{{{_share(float(eligibility['weight_baseline']))}}}",
                f"\\newcommand{{\\Locked{infix}WeightEnd}}"
                f"{{{_share(float(eligibility['weight_comparison']))}}}",
            ]
        )
        for prefix, _component in ELIGIBILITY_MARGINS:
            statistics = eligibility[prefix]
            lines.extend(
                [
                    f"\\newcommand{{\\Locked{infix}{prefix}}}"
                    f"{{{_contribution_pp(float(statistics['locked_pp']))}}}",
                    f"\\newcommand{{\\Open{infix}{prefix}}}"
                    f"{{{_contribution_pp(float(statistics['open_pp']))}}}",
                    f"\\newcommand{{\\Locked{infix}{prefix}Share}}"
                    f"{{{_share(float(statistics['locked_share']))}}}",
                ]
            )
        # What the choice-live remainder of each margin actually is. The
        # eligibility split says how much of the rotation runs through corridors
        # with no intermediary to choose; this says that almost all of the rest
        # runs through corridors with a stablecoin already at an endpoint.
        endpoints = _open_corridor_endpoints(contributions, metric, eligibility)
        for class_prefix, _ in OPEN_ENDPOINT_CLASSES:
            statistics = endpoints[class_prefix]
            lines.extend(
                [
                    f"\\newcommand{{\\{class_prefix}{infix}Pairs}}"
                    f"{{{_units(int(statistics['pairs']))}}}",
                    f"\\newcommand{{\\{class_prefix}{infix}WeightBase}}"
                    f"{{{_share(float(statistics['weight_baseline']))}}}",
                    f"\\newcommand{{\\{class_prefix}{infix}WeightEnd}}"
                    f"{{{_share(float(statistics['weight_comparison']))}}}",
                    f"\\newcommand{{\\{class_prefix}{infix}ShareBase}}"
                    f"{{{_share(float(statistics['share_baseline']))}}}",
                    f"\\newcommand{{\\{class_prefix}{infix}ShareEnd}}"
                    f"{{{_share(float(statistics['share_comparison']))}}}",
                    f"\\newcommand{{\\{class_prefix}{infix}Within}}"
                    f"{{{_contribution_pp(float(statistics['within_pp']))}}}",
                ]
            )
            for prefix, _component in ELIGIBILITY_MARGINS:
                lines.extend(
                    [
                        f"\\newcommand{{\\{class_prefix}{infix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics[prefix]))}}}",
                        f"\\newcommand{{\\{class_prefix}{infix}{prefix}Share}}"
                        f"{{{_share(float(statistics[f'{prefix}Share']))}}}",
                    ]
                )
        # Only the entry margin needs its own corridor count: the reweighting
        # rows are the continuing pairs already reported as `Pairs`.
        lines.append(
            f"\\newcommand{{\\OtherEnd{infix}NewPairPairs}}"
            f"{{{_units(int(endpoints['NewPairOtherPairs']))}}}"
        )
        lines.append(
            f"\\newcommand{{\\StableEnd{infix}NewPairPairs}}"
            f"{{{_units(int(endpoints['NewPairStablePairs']))}}}"
        )
        # The same split inside each integration scope, plus that scope's own
        # margin total, so a slide or a sentence never pairs a scope share with
        # the pooled margin it is not a share of.
        for suffix, scope in ELIGIBILITY_SCOPES:
            row = scope_rows[scope]
            scoped_eligibility = _endpoint_eligibility(
                contributions, metric, row, scope
            )
            for prefix, _component in ELIGIBILITY_MARGINS:
                statistics = scoped_eligibility[prefix]
                lines.extend(
                    [
                        f"\\newcommand{{\\Pair{infix}{suffix}{prefix}}}"
                        f"{{{_scope_margin_total(row, prefix, statistics)}}}",
                        f"\\newcommand{{\\Locked{infix}{suffix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics['locked_pp']))}}}",
                        f"\\newcommand{{\\Open{infix}{suffix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics['open_pp']))}}}",
                        f"\\newcommand{{\\Locked{infix}{suffix}{prefix}Share}}"
                        f"{{{_share(float(statistics['locked_share']))}}}",
                    ]
                )
        # The netted exclusive term read as corridor replacement: one activity
        # mass, two cohorts, and the routing rate of each. The open rates are the
        # ones an economic reading may use.
        for suffix, scope in COHORT_SCOPES:
            cohort = _support_cohorts(contributions, metric, scope_rows[scope], scope)
            lines.extend(
                [
                    f"\\newcommand{{\\Cohort{infix}{suffix}Mass}}"
                    f"{{{_share(float(cohort["mass_share"]))}}}",
                    f"\\newcommand{{\\Cohort{infix}{suffix}Net}}"
                    f"{{{_contribution_pp(float(cohort["net_pp"]))}}}",
                ]
            )
            for prefix, _component, _weight, _share_column, _sign in SUPPORT_COHORTS:
                statistics = cohort[prefix]
                lines.extend(
                    [
                        f"\\newcommand{{\\Cohort{infix}{suffix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics['margin_pp']))}}}",
                        f"\\newcommand{{\\Cohort{infix}{suffix}{prefix}Share}}"
                        f"{{{_share(float(statistics['stable_share']))}}}",
                        f"\\newcommand{{\\Cohort{infix}{suffix}{prefix}OpenShare}}"
                        f"{{{_share(float(statistics['open_stable_share']))}}}",
                        f"\\newcommand{{\\Cohort{infix}{suffix}{prefix}OpenWeight}}"
                        f"{{{_share(float(statistics['open_weight']))}}}",
                    ]
                )
            if suffix:
                continue
            # Why the two cohorts route differently: because they are different
            # markets, or because the same kind of market routes differently.
            # Pooled only -- the scoped cohort rates above answer a question
            # about integration, and pairing a scope weight with the pooled gap
            # is exactly the confusion the scope suffix exists to prevent.
            replacement = _cohort_endpoint_margins(contributions, metric, cohort)
            lines.extend(
                [
                    f"\\newcommand{{\\Replace{infix}Composition}}"
                    f"{{{_contribution_pp(float(replacement['composition_pp']))}}}",
                    f"\\newcommand{{\\Replace{infix}Rate}}"
                    f"{{{_contribution_pp(float(replacement['rate_pp']))}}}",
                    f"\\newcommand{{\\Replace{infix}CompositionShare}}"
                    f"{{{_share(float(replacement['composition_share']))}}}",
                    f"\\newcommand{{\\Replace{infix}RateShare}}"
                    f"{{{_share(float(replacement['rate_share']))}}}",
                ]
            )
            for name in COHORT_ENDPOINT_CLASSES:
                statistics = replacement[name]
                lines.extend(
                    [
                        f"\\newcommand{{\\Replace{infix}{name}ExitPairs}}"
                        f"{{{_units(int(statistics['exit_pairs']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}EnterPairs}}"
                        f"{{{_units(int(statistics['enter_pairs']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}ExitWeight}}"
                        f"{{{_share(float(statistics['exit_weight']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}EnterWeight}}"
                        f"{{{_share(float(statistics['enter_weight']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}ExitRate}}"
                        f"{{{_share(float(statistics['exit_rate']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}EnterRate}}"
                        f"{{{_share(float(statistics['enter_rate']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}Composition}}"
                        f"{{{_contribution_pp(float(statistics['composition_pp']))}}}",
                        f"\\newcommand{{\\Replace{infix}{name}Rate}}"
                        f"{{{_contribution_pp(float(statistics['rate_pp']))}}}",
                    ]
                )
        # The support-mass term as its two factors: how much activity migrated
        # between the two blocks, and what this decomposition prices that
        # migration at.
        for suffix, scope in BLOCK_SCOPES:
            factors = _support_mass_factors(scope_rows[scope], metric, scope)
            lines.extend(
                [
                    f"\\newcommand{{\\Block{infix}{suffix}Term}}"
                    f"{{{_signed_pp(factors['term'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}Shift}}"
                    f"{{{_signed_pp(factors['shift'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}Gap}}"
                    f"{{{_signed_pp(factors['gap'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}CommonBase}}"
                    f"{{{_share(factors['common_baseline'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}CommonEnd}}"
                    f"{{{_share(factors['common_comparison'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}CommonMid}}"
                    f"{{{_share(factors['common_mid'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}ExclusiveMid}}"
                    f"{{{_share(factors['exclusive_mid'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}WeightBase}}"
                    f"{{{_share(factors['weight_baseline'])}}}",
                    f"\\newcommand{{\\Block{infix}{suffix}WeightEnd}}"
                    f"{{{_share(factors['weight_comparison'])}}}",
                ]
            )
    return "\n".join(lines) + "\n"


def run(
    *,
    decomposition_path: Path = DECOMPOSITION,
    fixed_effects_path: Path = FIXED_EFFECTS,
    usdt_integration_path: Path = USDT_INTEGRATION,
    contributions_path: Path = CONTRIBUTIONS,
    support_path: Path = SUPPORT,
    output_path: Path = DECK_VALUES,
) -> int:
    provenance_path = require_certified_presentation_source(decomposition_path)
    support_provenance = require_certified_presentation_source(support_path)
    fixed_effects_provenance = require_certified_presentation_source(
        fixed_effects_path
    )
    usdt_integration_provenance = require_certified_presentation_source(
        usdt_integration_path
    )
    contributions_provenance = require_certified_presentation_source(contributions_path)
    decomposition = pd.read_json(decomposition_path, lines=True)
    fixed_effects = pd.read_json(fixed_effects_path, lines=True)
    usdt_integration = pd.read_json(usdt_integration_path, lines=True)
    # Only the pooled 2024--2026 count rows reach a slide; reading the whole
    # 4.6M-row ledger just to name three pairs is avoidable memory pressure.
    contributions = pd.read_parquet(
        contributions_path,
        columns=[
            "metric",
            "reporting_scope",
            "baseline_year",
            "comparison_year",
            "src",
            "tgt",
            "stable_share_baseline",
            "stable_share_comparison",
            "pair_weight_baseline",
            "pair_weight_comparison",
            "denominator_baseline",
            "denominator_comparison",
            "contribution_component",
            "contribution_pp",
            "aggregate_mass_share_midpoint",
            "aggregate_total_change",
            "allocation_scope",
            "mechanism_status",
        ],
    )
    support = pd.read_json(support_path, lines=True)
    rendered = render_pair_decomposition_deck_values(
        decomposition, fixed_effects, usdt_integration, contributions, support
    )
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    stamp(
        output_path,
        code_sources=CODE_SOURCES,
        inputs=[
            decomposition_path,
            provenance_path,
            fixed_effects_path,
            fixed_effects_provenance,
            usdt_integration_path,
            usdt_integration_provenance,
            contributions_path,
            contributions_provenance,
            support_path,
            support_provenance,
        ],
        rows=(
            len(decomposition)
            + len(fixed_effects)
            + len(usdt_integration)
            + len(contributions)
            + len(support)
        ),
        notes=(
            "Presentation macros for the exact descriptive pair-composition "
            "accounting, the matched-market estimate, one named "
            "source--destination pair per aggregate margin, and the split of "
            "each composition margin on WETH-endpoint eligibility, the "
            "endpoint composition of the choice-live remainder of each margin, "
            "the netted exclusive-pair term read as one activity mass against two "
            "corridor cohorts' routing rates, and the three market-incidence "
            "support classes the Panel A bridge is formed from; evidence "
            "status and identities remain source-only."
        ),
    )
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decomposition", type=Path, default=DECOMPOSITION)
    parser.add_argument("--fixed-effects", type=Path, default=FIXED_EFFECTS)
    parser.add_argument("--usdt-integration", type=Path, default=USDT_INTEGRATION)
    parser.add_argument("--contributions", type=Path, default=CONTRIBUTIONS)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(
        decomposition_path=args.decomposition,
        fixed_effects_path=args.fixed_effects,
        usdt_integration_path=args.usdt_integration,
        contributions_path=args.contributions,
        support_path=args.support,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
