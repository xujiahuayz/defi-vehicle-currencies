#!/usr/bin/env python3
"""Render LP-flow timing before first observed stablecoin-route use."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/bridge_lp_flow_before_use_support.jsonl"
PRIMARY_SAMPLE = "both_v2_family_legs_strictly_before_first_use"
ACCELERATION_WINDOW = (
    "days_minus_7_to_minus_1_vs_days_minus_28_to_minus_8"
)


@dataclass(frozen=True)
class Outcome:
    name: str
    heading: str
    transformation: str
    transformation_label: str


OUTCOMES: tuple[Outcome, ...] = (
    Outcome(
        "add_flow_usd",
        "LP additions",
        "log1p",
        r"$\ln(1+\mathrm{USD})$",
    ),
    Outcome(
        "seed_add_flow_usd",
        "First-active-day additions",
        "log1p",
        r"$\ln(1+\mathrm{USD})$",
    ),
    Outcome(
        "net_add_flow_usd",
        "Net LP additions",
        "asinh",
        r"$\operatorname{asinh}(\mathrm{USD})$",
    ),
)


@dataclass(frozen=True)
class Contrast:
    record_type: str
    label: str
    event_bin: str | None = None
    reference_bin: str | None = None
    window: str | None = None


CONTRASTS: tuple[Contrast, ...] = (
    Contrast(
        "event_path_contrast",
        r"Week $-2$ minus week $-4$",
        event_bin="pre_week_2",
        reference_bin="pre_week_4",
    ),
    Contrast(
        "pre_use_acceleration",
        r"Week $-1$ minus mean of weeks $-4$ to $-2$",
        window=ACCELERATION_WINDOW,
    ),
)


SUPPORT_DESIGN = {
    "event_source": (
        "existing_first_persistent_stable_bridge_events_from_"
        "load_bridge_establishment_event_panel"
    ),
    "pool_scope": (
        "all_uniswap_v2_and_sushiswap_v2_pools_on_the_exact_two_"
        "endpoint_stablecoin_token_pairs_active_by_first_use"
    ),
    "pool_attribution_boundary": (
        "route_reconstruction_retains_venues_and_token_legs_but_not_"
        "executed_pool_addresses"
    ),
    "seeding_definition": (
        "actual_mint_flow_on_first_active_day_in_retained_v2_family_"
        "panel;_not_verified_contract_deployment"
    ),
    "temporal_boundary": (
        "pre_use_statistics_end_at_day_minus_1;day_zero_reported_"
        "separately;candidate_identity_fixed_from_first_use_day"
    ),
    "selection_boundary": (
        "bridge_events_inherit_future_30_day_persistent_support_"
        "selection;timing_results_are_descriptive"
    ),
}


def _integer(value: object, field: str) -> int:
    numeric = float(value)
    if not np.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise ValueError(f"bridge LP-flow support has invalid {field}")
    return int(numeric)


def _p_value(value: object) -> str:
    p_value = float(value)
    if not np.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
        raise ValueError("bridge LP-flow contrast has invalid raw p-value")
    if p_value != 0.0 and p_value < 0.0001:
        mantissa, exponent = f"{p_value:.2e}".split("e")
        return rf"${mantissa}\times 10^{{{int(exponent)}}}$"
    return f"{p_value:.4f}"


def _selected_row(
    results: pd.DataFrame,
    outcome: Outcome,
    contrast: Contrast,
) -> pd.Series:
    selected = results[
        results["sample"].eq(PRIMARY_SAMPLE)
        & results["record_type"].eq(contrast.record_type)
        & results["outcome"].eq(outcome.name)
        & results["transformation"].eq(outcome.transformation)
    ].copy()
    if contrast.event_bin is not None:
        selected = selected[
            selected["event_bin"].eq(contrast.event_bin)
            & selected["reference_bin"].eq(contrast.reference_bin)
        ]
    if contrast.window is not None:
        selected = selected[selected["window"].eq(contrast.window)]
    if len(selected) != 1:
        raise ValueError(
            "expected one bridge LP-flow row for "
            f"{outcome.name} / {contrast.record_type}; found {len(selected)}"
        )
    row = selected.iloc[0]
    for field in ("estimate", "standard_error"):
        if not np.isfinite(float(row[field])):
            raise ValueError(f"bridge LP-flow contrast has invalid {field}")
    if float(row["standard_error"]) <= 0:
        raise ValueError("bridge LP-flow contrast requires a positive standard error")
    _p_value(row["p_value"])
    observations = _integer(row["observations"], "observations")
    clusters = _integer(row["ordered_pair_clusters"], "ordered-pair clusters")
    if observations == 0 or clusters == 0 or clusters > observations:
        raise ValueError("bridge LP-flow contrast has invalid estimation support")
    if contrast.event_bin is not None:
        if (
            int(row["event_bin_index"]) != -2
            or int(row["relative_day_start"]) != -14
            or int(row["relative_day_end"]) != -8
        ):
            raise ValueError("week -2 bridge LP-flow contrast has changed timing")
    else:
        excluded = row["first_use_day_excluded"]
        if pd.isna(excluded) or not bool(excluded):
            raise ValueError("pre-use bridge LP-flow contrast includes day zero")
    return row


def _support_row(support: pd.DataFrame) -> pd.Series:
    required = {
        "record_type",
        "eligible_delayed_bridge_events",
        "events",
        "events_with_both_v2_family_legs_by_first_use",
        "events_with_both_v2_family_legs_strictly_prior",
        "strict_prior_two_leg_events",
        "ordered_pairs",
        "first_event_date",
        "last_event_date",
        "pre_days",
        "post_days",
        "complete_usd_event_day_share",
        *SUPPORT_DESIGN,
    }
    missing = sorted(required - set(support.columns))
    if missing:
        raise ValueError(f"bridge LP-flow support lacks fields: {missing}")
    selected = support[
        support["record_type"].eq("bridge_lp_flow_before_use_support")
    ]
    if len(selected) != 1:
        raise ValueError(
            "expected one bridge LP-flow support row; "
            f"found {len(selected)}"
        )
    row = selected.iloc[0]
    for field, expected in SUPPORT_DESIGN.items():
        if row[field] != expected:
            raise ValueError(f"bridge LP-flow support has changed {field}")
    if _integer(row["pre_days"], "pre_days") != 28:
        raise ValueError("bridge LP-flow support requires a 28-day pre-window")
    if _integer(row["post_days"], "post_days") != 7:
        raise ValueError("bridge LP-flow support requires a 7-day post-window")

    eligible = _integer(
        row["eligible_delayed_bridge_events"], "eligible event count"
    )
    events = _integer(row["events"], "selected event count")
    by_first_use = _integer(
        row["events_with_both_v2_family_legs_by_first_use"],
        "both-legs-by-first-use count",
    )
    strict = _integer(
        row["events_with_both_v2_family_legs_strictly_prior"],
        "strict-prior two-leg count",
    )
    strict_alias = _integer(
        row["strict_prior_two_leg_events"], "strict-prior event count"
    )
    pairs = _integer(row["ordered_pairs"], "ordered-pair count")
    if not (eligible >= events == by_first_use >= strict == strict_alias):
        raise ValueError("bridge LP-flow support counts are inconsistent")
    if pairs > events:
        raise ValueError("bridge LP-flow ordered-pair count exceeds events")
    complete_share = float(row["complete_usd_event_day_share"])
    if not np.isfinite(complete_share) or not 0.0 <= complete_share <= 1.0:
        raise ValueError("bridge LP-flow support has invalid USD coverage")
    first_date = pd.to_datetime(row["first_event_date"], errors="coerce")
    last_date = pd.to_datetime(row["last_event_date"], errors="coerce")
    if pd.isna(first_date) or pd.isna(last_date) or first_date > last_date:
        raise ValueError("bridge LP-flow support has invalid event dates")
    return row


def render_bridge_lp_flow_before_use(
    results: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Return selected LP-flow changes before first stablecoin-route use."""

    required_results = {
        "record_type",
        "sample",
        "outcome",
        "transformation",
        "event_bin",
        "event_bin_index",
        "reference_bin",
        "relative_day_start",
        "relative_day_end",
        "window",
        "first_use_day_excluded",
        "estimate",
        "standard_error",
        "p_value",
        "observations",
        "ordered_pair_clusters",
    }
    missing = sorted(required_results - set(results.columns))
    if missing:
        raise ValueError(f"bridge LP-flow results lack fields: {missing}")

    support_row = _support_row(support)
    rows = {
        (contrast.record_type, outcome.name): _selected_row(
            results, outcome, contrast
        )
        for contrast in CONTRASTS
        for outcome in OUTCOMES
    }
    for outcome in OUTCOMES:
        first = rows[(CONTRASTS[0].record_type, outcome.name)]
        second = rows[(CONTRASTS[1].record_type, outcome.name)]
        if (
            int(first["observations"]) != int(second["observations"])
            or int(first["ordered_pair_clusters"])
            != int(second["ordered_pair_clusters"])
        ):
            raise ValueError(
                f"bridge LP-flow contrasts use different support for {outcome.name}"
            )
        if int(first["observations"]) > int(support_row["events"]):
            raise ValueError("bridge LP-flow estimation exceeds selected events")
        if int(first["ordered_pair_clusters"]) > int(support_row["ordered_pairs"]):
            raise ValueError("bridge LP-flow estimation exceeds selected pairs")

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=1.45\hsize\raggedright\arraybackslash}X"
        r"*{3}{>{\hsize=0.85\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        "Pre-use difference & "
        + " & ".join(outcome.heading for outcome in OUTCOMES)
        + r" \\",
        "Transformation & "
        + " & ".join(outcome.transformation_label for outcome in OUTCOMES)
        + r" \\",
        r"\midrule",
    ]
    for contrast_index, contrast in enumerate(CONTRASTS):
        selected = [
            rows[(contrast.record_type, outcome.name)] for outcome in OUTCOMES
        ]
        if contrast_index:
            lines.append(r"\addlinespace")
        lines.extend(
            [
                contrast.label
                + " & "
                + " & ".join(
                    f"${float(row['estimate']):+.3f}$" for row in selected
                )
                + r" \\",
                "Clustered s.e. & "
                + " & ".join(
                    f"$({float(row['standard_error']):.3f})$"
                    for row in selected
                )
                + r" \\",
                "Raw $p$-value & "
                + " & ".join(_p_value(row["p_value"]) for row in selected)
                + r" \\",
            ]
        )
    first_rows = [
        rows[(CONTRASTS[0].record_type, outcome.name)] for outcome in OUTCOMES
    ]
    lines.extend(
        [
            r"\midrule",
            "Estimation events & "
            + " & ".join(f"{int(row['observations']):,}" for row in first_rows)
            + r" \\",
            "Ordered-pair clusters & "
            + " & ".join(
                f"{int(row['ordered_pair_clusters']):,}" for row in first_rows
            )
            + r" \\",
            r"\addlinespace",
            "Eligible delayed events & "
            + rf"\multicolumn{{3}}{{r}}{{{int(support_row['eligible_delayed_bridge_events']):,}}} \\",
            "Both legs active by first use & "
            + rf"\multicolumn{{3}}{{r}}{{{int(support_row['events']):,}}} \\",
            "Both legs active before first use & "
            + rf"\multicolumn{{3}}{{r}}{{{int(support_row['strict_prior_two_leg_events']):,}}} \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "bridge_lp_flow_before_use",
        render_bridge_lp_flow_before_use(results, support),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
