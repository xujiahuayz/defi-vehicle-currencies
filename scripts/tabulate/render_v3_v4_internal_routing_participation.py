#!/usr/bin/env python3
"""Render the V3/V4 internal-routing participation comparison."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits/v3_v4_internal_routing_participation.jsonl"
OUTCOMES = {
    "near_log1p_incumbent_actions": "Incumbent actions, days 1 to 30",
    "late_log1p_first_active_origins": "First-active origins, days 31 to 120",
}
PRIMARY = "primary_common_routing_180"
STATE = "primary_common_routing_180_volatility_state"
CALENDAR_VARIANTS = {
    "common_routing_90_on_primary_calendar": "Mature dates",
    "common_routing_90_early_calendar": "Early dates",
    "common_routing_90": "Pooled dates",
}


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(
    estimate: float,
    standard_error: float,
    p_value: float | None = None,
) -> str:
    stars = _stars(p_value) if p_value is not None else ""
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${estimate:+.3f}{stars}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def _ordered(sample: pd.DataFrame) -> dict[str, pd.Series]:
    if set(sample["outcome"]) != set(OUTCOMES) or len(sample) != len(OUTCOMES):
        raise ValueError("V3/V4 internal-routing table has an incomplete outcome family")
    return {outcome: sample[sample["outcome"].eq(outcome)].iloc[0] for outcome in OUTCOMES}


def render_v3_v4_internal_routing_participation(results: pd.DataFrame) -> str:
    required = {
        "record_type",
        "sample_variant",
        "outcome",
        "v3_slope_per_10pp",
        "v3_standard_error_per_10pp",
        "v4_slope_per_10pp",
        "v4_standard_error_per_10pp",
        "v4_minus_v3_per_10pp",
        "v4_minus_v3_standard_error_per_10pp",
        "v4_minus_v3_holm_p_value",
        "candidate_days",
        "date_clusters",
        "v3_state_interaction_per_10pp_per_1sd",
        "v3_state_interaction_standard_error",
        "v4_state_interaction_per_10pp_per_1sd",
        "v4_state_interaction_standard_error",
        "v4_minus_v3_state_interaction_per_10pp_per_1sd",
        "v4_minus_v3_state_interaction_standard_error",
        "v4_minus_v3_state_interaction_holm_p_value",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V3/V4 internal-routing results lack columns: {missing}")
    level_rows = results[
        results["record_type"].eq(
            "v3_v4_internal_routing_participation_regression"
        )
    ]
    primary = _ordered(level_rows[level_rows["sample_variant"].eq(PRIMARY)])
    state_rows = results[
        results["record_type"].eq(
            "v3_v4_internal_routing_volatility_regression"
        )
        & results["sample_variant"].eq(STATE)
    ]
    state = _ordered(state_rows)
    calendars = {
        variant: _ordered(level_rows[level_rows["sample_variant"].eq(variant)])
        for variant in CALENDAR_VARIANTS
    }

    rows = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{2}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        " & " + " & ".join(OUTCOMES.values()) + r" \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. Mature common calendar}} \\",
    ]
    for label, estimate, standard_error, p_value in (
        ("V3 internal-routing slope", "v3_slope_per_10pp", "v3_standard_error_per_10pp", None),
        ("V4 internal-routing slope", "v4_slope_per_10pp", "v4_standard_error_per_10pp", None),
        ("V4 minus V3", "v4_minus_v3_per_10pp", "v4_minus_v3_standard_error_per_10pp", "v4_minus_v3_holm_p_value"),
    ):
        cells = [
            _cell(
                float(primary[outcome][estimate]),
                float(primary[outcome][standard_error]),
                float(primary[outcome][p_value]) if p_value else None,
            )
            for outcome in OUTCOMES
        ]
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    rows.extend(
        [
            r"\addlinespace",
            r"\multicolumn{3}{@{}l}{\textit{Panel B. Interaction with persistent volatility}} \\",
        ]
    )
    for label, estimate, standard_error, p_value in (
        (
            r"V3 routing $\times$ volatility",
            "v3_state_interaction_per_10pp_per_1sd",
            "v3_state_interaction_standard_error",
            None,
        ),
        (
            r"V4 routing $\times$ volatility",
            "v4_state_interaction_per_10pp_per_1sd",
            "v4_state_interaction_standard_error",
            None,
        ),
        (
            "V4 minus V3",
            "v4_minus_v3_state_interaction_per_10pp_per_1sd",
            "v4_minus_v3_state_interaction_standard_error",
            "v4_minus_v3_state_interaction_holm_p_value",
        ),
    ):
        cells = [
            _cell(
                float(state[outcome][estimate]),
                float(state[outcome][standard_error]),
                float(state[outcome][p_value]) if p_value else None,
            )
            for outcome in OUTCOMES
        ]
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    rows.extend(
        [
            r"\addlinespace",
            r"\multicolumn{3}{@{}l}{\textit{Panel C. V4 minus V3 with 90-day history}} \\",
        ]
    )
    for variant, label in CALENDAR_VARIANTS.items():
        cells = [
            _cell(
                float(calendars[variant][outcome]["v4_minus_v3_per_10pp"]),
                float(
                    calendars[variant][outcome][
                        "v4_minus_v3_standard_error_per_10pp"
                    ]
                ),
                float(calendars[variant][outcome]["v4_minus_v3_holm_p_value"]),
            )
            for outcome in OUTCOMES
        ]
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    observations = int(primary[next(iter(OUTCOMES))]["candidate_days"])
    clusters = int(primary[next(iter(OUTCOMES))]["date_clusters"])
    rows.extend(
        [
            r"\midrule",
            "Primary vehicle-days / dates & "
            + f"\\multicolumn{{2}}{{r}}{{{observations:,} / {clusters:,}}} \\\\",
            r"Vehicle and date effects & \multicolumn{2}{r}{Yes} \\",
            r"Protocol-specific activity controls & \multicolumn{2}{r}{Yes} \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v3_v4_internal_routing_participation",
        render_v3_v4_internal_routing_participation(results),
        preview_width="7.6in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
