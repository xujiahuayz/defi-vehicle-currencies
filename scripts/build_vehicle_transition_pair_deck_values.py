#!/usr/bin/env python3
"""Build presentation macros from the current vehicle-pair evidence."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from ddvc.asset_types import WETH, classify
from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_certified_presentation_source
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output


DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
FIXED_EFFECTS = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
USDT_INTEGRATION = OUTPUT_DIR / "exhibits" / "e0_usdt_integration_decomposition.jsonl"
CONTRIBUTIONS = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_contributions.parquet"
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


def _pairs(value: int) -> str:
    return f"{int(value):,}"


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
    )
    for left, right, label in checks:
        if not math.isclose(left, right, abs_tol=1e-12):
            raise ValueError(f"market-incidence decomposition does not reconcile {label}")
    return row


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
) -> str:
    """Render empirical cells while keeping evidence identity out of the PDF."""
    count = _scope_rows(decomposition, "count_share")
    value = _scope_rows(decomposition, "strict_intermediation_value_share")
    market = _market_incidence_row(decomposition)
    matched_count = _matched_market_row(fixed_effects, "count_share")
    matched_value = _matched_market_row(
        fixed_effects, "strict_intermediation_value_share"
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
                    f"{{{_pairs(int(statistics['gain_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}LossPairs}}"
                    f"{{{_pairs(int(statistics['loss_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}GrossUp}}"
                    f"{{{_contribution_pp(float(statistics['gross_up']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}GrossDown}}"
                    f"{{{_contribution_pp(float(statistics['gross_down']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}TopShare}}"
                    f"{{{_share(float(statistics['top_share']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}HalfPairs}}"
                    f"{{{_pairs(int(statistics['half_pairs']))}}}",
                    f"\\newcommand{{\\{prefix}{infix}NinetyPairs}}"
                    f"{{{_pairs(int(statistics['ninety_pairs']))}}}",
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
                f"{{{_pairs(int(eligibility['locked_pairs']))}}}",
                f"\\newcommand{{\\Locked{infix}CommonPairs}}"
                f"{{{_pairs(int(eligibility['common_pairs']))}}}",
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
        # The same split inside each integration scope, plus that scope's own
        # reweighting total, so a slide or a sentence never pairs a scope share
        # with the pooled margin it is not a share of.
        for suffix, scope in ELIGIBILITY_SCOPES:
            row = scope_rows[scope]
            scoped_eligibility = _endpoint_eligibility(
                contributions, metric, row, scope
            )
            lines.append(
                f"\\newcommand{{\\Pair{infix}{suffix}Reweight}}"
                f"{{{_signed_pp(float(row['common_pair_reweighting']))}}}"
            )
            for prefix, _component in ELIGIBILITY_MARGINS:
                statistics = scoped_eligibility[prefix]
                lines.extend(
                    [
                        f"\\newcommand{{\\Locked{infix}{suffix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics['locked_pp']))}}}",
                        f"\\newcommand{{\\Open{infix}{suffix}{prefix}}}"
                        f"{{{_contribution_pp(float(statistics['open_pp']))}}}",
                        f"\\newcommand{{\\Locked{infix}{suffix}{prefix}Share}}"
                        f"{{{_share(float(statistics['locked_share']))}}}",
                    ]
                )
    return "\n".join(lines) + "\n"


def run(
    *,
    decomposition_path: Path = DECOMPOSITION,
    fixed_effects_path: Path = FIXED_EFFECTS,
    usdt_integration_path: Path = USDT_INTEGRATION,
    contributions_path: Path = CONTRIBUTIONS,
    output_path: Path = DECK_VALUES,
) -> int:
    provenance_path = require_certified_presentation_source(decomposition_path)
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
            "aggregate_total_change",
            "allocation_scope",
            "mechanism_status",
        ],
    )
    rendered = render_pair_decomposition_deck_values(
        decomposition, fixed_effects, usdt_integration, contributions
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
        ],
        rows=(
            len(decomposition)
            + len(fixed_effects)
            + len(usdt_integration)
            + len(contributions)
        ),
        notes=(
            "Presentation macros for the exact descriptive pair-composition "
            "accounting, the matched-market estimate, one named "
            "source--destination pair per aggregate margin, and the split of "
            "each composition margin on WETH-endpoint eligibility; evidence "
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
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(
        decomposition_path=args.decomposition,
        fixed_effects_path=args.fixed_effects,
        usdt_integration_path=args.usdt_integration,
        contributions_path=args.contributions,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
