#!/usr/bin/env python3
"""Render appendix evidence on V3 pool maturity and launch-period activity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


RESULTS = OUTPUT_DIR / "exhibits" / "v3_lp_launch_supply.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "v3_lp_launch_supply_support.jsonl"
VALUES_OUTPUT = OUTPUT_DIR / "exhibits" / "v3_lp_launch_supply_values.tex"

BASELINE_PERIOD = "2024H1"
COMPARISON_PERIOD = "2026H1"
AGE_BINS = ("0-7", "8-30", "31-90", ">90")
AGE_LABELS = {
    "0-7": "0--7",
    "8-30": "8--30",
    "31-90": "31--90",
    ">90": "More than 90",
}
HORIZONS = (30, 90)

TABLE_NOTE = (
    "Pool age counts days from the first retained Uniswap V3 pool-day. The "
    "sample contains spokes with exactly one WETH, DAI, USDC, or USDT side and "
    "a nonvehicle endpoint; stable-facing combines DAI, USDC, and USDT. "
    "Addition actions are positive Uniswap V3 liquidity additions. Panel A "
    "allocates the increase in stable-facing addition actions across age bins. "
    "Panel B reports the stable-facing share among stable-facing and WETH-facing "
    "actions. Panel C classifies transaction origins using their full retained "
    "V3 history; transaction origin measures participation, while ownership and "
    "project affiliation remain outside the data. Panel D forms a separate "
    "2026 H1 cohort for each horizon. Active pools have a retained pool-day "
    "during the 15-day window beginning at the horizon. Activity shares weight "
    "pools by addition actions on days 0--7. Net flow equals vehicle-side "
    "additions minus removals from day 8 through the horizon and is divided by "
    "vehicle-side additions on days 0--7. Pool age dates observed pool formation "
    "and is distinct from token issuance."
)


@dataclass(frozen=True)
class LaunchSupplySummary:
    age_rows: tuple[tuple[str, float, float, float], ...]
    stable_action_increase: float
    full_stable_share_baseline: float
    full_stable_share_comparison: float
    full_stable_share_change_pp: float
    older_than_seven_stable_share_baseline: float
    older_than_seven_stable_share_comparison: float
    older_than_seven_stable_share_change_pp: float
    continuing_action_share: float
    continuing_flow_share: float
    repeated_or_multipool_action_share: float
    repeated_or_multipool_flow_share: float
    one_day_one_pool_action_share: float
    one_day_one_pool_flow_share: float
    followup_rows: tuple[tuple[int, float, float, float], ...]


def _select_one(
    frame: pd.DataFrame,
    selector: dict[str, object],
    *,
    description: str,
) -> pd.Series:
    selected = frame
    for column, expected in selector.items():
        if column not in selected.columns:
            raise ValueError(f"{description} lacks selector column: {column}")
        selected = selected.loc[selected[column].eq(expected)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {description} row for {selector}; found {len(selected)}"
        )
    return selected.iloc[0]


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    description: str,
) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{description} lacks columns: {missing}")


def _finite(values: list[object], *, description: str) -> np.ndarray:
    numeric = np.asarray([float(value) for value in values], dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError(f"{description} contains nonfinite values")
    return numeric


def _validate_support(support: pd.DataFrame) -> None:
    required = {
        "record_type",
        "missing_pool_inception_rows",
        "negative_pool_age_rows",
        "full_sample_spoke_pools",
    }
    _require_columns(support, required, description="V3 launch-supply support")
    row = _select_one(
        support,
        {"record_type": "v3_lp_launch_supply_support"},
        description="V3 launch-supply support",
    )
    _finite(
        [
            row["missing_pool_inception_rows"],
            row["negative_pool_age_rows"],
            row["full_sample_spoke_pools"],
        ],
        description="V3 launch-supply support",
    )
    if int(row["missing_pool_inception_rows"]) != 0:
        raise ValueError("V3 launch-supply rows lack pool-inception matches")
    if int(row["negative_pool_age_rows"]) != 0:
        raise ValueError("V3 launch-supply rows contain negative pool ages")
    if int(row["full_sample_spoke_pools"]) <= 0:
        raise ValueError("V3 launch-supply support contains no spoke pools")


def _stable_share(frame: pd.DataFrame) -> float:
    totals = frame.groupby("vehicle_type", observed=True)[
        "addition_action_events"
    ].sum()
    if set(totals.index) != {"WETH", "stable"}:
        raise ValueError("V3 pool-age rows must contain WETH and stable supply")
    denominator = float(totals.sum())
    if denominator <= 0:
        raise ValueError("V3 pool-age addition actions must be positive")
    return float(totals["stable"]) / denominator


def _summarize_age(results: pd.DataFrame) -> dict[str, object]:
    age = results.loc[results["record_type"].eq("v3_lp_supply_by_pool_age")]
    required = {
        "record_type",
        "period",
        "vehicle_type",
        "pool_age_bin",
        "addition_action_events",
    }
    _require_columns(age, required, description="V3 pool-age results")

    cells: dict[tuple[str, str, str], pd.Series] = {}
    for period in (BASELINE_PERIOD, COMPARISON_PERIOD):
        for vehicle_type in ("WETH", "stable"):
            for age_bin in AGE_BINS:
                row = _select_one(
                    age,
                    {
                        "period": period,
                        "vehicle_type": vehicle_type,
                        "pool_age_bin": age_bin,
                    },
                    description="V3 pool-age result",
                )
                value = _finite(
                    [row["addition_action_events"]],
                    description="V3 pool-age result",
                )[0]
                if value < 0:
                    raise ValueError("V3 pool-age addition actions must be nonnegative")
                cells[(period, vehicle_type, age_bin)] = row

    stable_baseline = {
        age_bin: float(cells[(BASELINE_PERIOD, "stable", age_bin)]["addition_action_events"])
        for age_bin in AGE_BINS
    }
    stable_comparison = {
        age_bin: float(cells[(COMPARISON_PERIOD, "stable", age_bin)]["addition_action_events"])
        for age_bin in AGE_BINS
    }
    stable_action_increase = sum(stable_comparison.values()) - sum(
        stable_baseline.values()
    )
    if stable_action_increase <= 0:
        raise ValueError("stable-facing addition actions must rise across the periods")
    age_rows = tuple(
        (
            age_bin,
            stable_baseline[age_bin],
            stable_comparison[age_bin],
            (stable_comparison[age_bin] - stable_baseline[age_bin])
            / stable_action_increase,
        )
        for age_bin in AGE_BINS
    )
    if not np.isclose(sum(row[3] for row in age_rows), 1.0, atol=1e-12, rtol=0.0):
        raise ValueError("V3 pool-age contributions do not reconcile")

    period_frames = {
        period: age.loc[age["period"].eq(period)]
        for period in (BASELINE_PERIOD, COMPARISON_PERIOD)
    }
    full_baseline = _stable_share(period_frames[BASELINE_PERIOD])
    full_comparison = _stable_share(period_frames[COMPARISON_PERIOD])
    older_baseline = _stable_share(
        period_frames[BASELINE_PERIOD].loc[
            ~period_frames[BASELINE_PERIOD]["pool_age_bin"].eq("0-7")
        ]
    )
    older_comparison = _stable_share(
        period_frames[COMPARISON_PERIOD].loc[
            ~period_frames[COMPARISON_PERIOD]["pool_age_bin"].eq("0-7")
        ]
    )
    return {
        "age_rows": age_rows,
        "stable_action_increase": stable_action_increase,
        "full_stable_share_baseline": full_baseline,
        "full_stable_share_comparison": full_comparison,
        "full_stable_share_change_pp": 100.0 * (full_comparison - full_baseline),
        "older_than_seven_stable_share_baseline": older_baseline,
        "older_than_seven_stable_share_comparison": older_comparison,
        "older_than_seven_stable_share_change_pp": 100.0
        * (older_comparison - older_baseline),
    }


def _summarize_origins(results: pd.DataFrame) -> dict[str, float]:
    origins = results.loc[results["record_type"].eq("v3_lp_origin_history")]
    required = {
        "record_type",
        "period",
        "vehicle_type",
        "endpoint_period_membership",
        "origin_history_class",
        "addition_action_events",
        "screened_candidate_side_flow_usd",
    }
    _require_columns(origins, required, description="V3 origin-history results")
    selected = origins.loc[
        origins["period"].eq(COMPARISON_PERIOD)
        & origins["vehicle_type"].eq("stable")
    ].copy()
    if selected.empty:
        raise ValueError("V3 origin-history results lack 2026 H1 stable-facing rows")
    if selected.duplicated(
        ["endpoint_period_membership", "origin_history_class"]
    ).any():
        raise ValueError("V3 origin-history results contain duplicate classes")
    allowed_membership = {"continuing", "period-specific"}
    allowed_history = {
        "one-day/one-pool",
        "repeat-day/one-pool",
        "multi-pool",
    }
    if not set(selected["endpoint_period_membership"]).issubset(allowed_membership):
        raise ValueError("V3 origin-history results contain an unknown period class")
    if not set(selected["origin_history_class"]).issubset(allowed_history):
        raise ValueError("V3 origin-history results contain an unknown history class")

    numeric = selected[
        ["addition_action_events", "screened_candidate_side_flow_usd"]
    ].astype(float)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("V3 origin-history results contain nonfinite values")
    totals = numeric.sum()
    if (totals <= 0).any():
        raise ValueError("V3 origin-history action and flow totals must be positive")

    continuing = selected["endpoint_period_membership"].eq("continuing")
    one_day = selected["endpoint_period_membership"].eq(
        "period-specific"
    ) & selected["origin_history_class"].eq("one-day/one-pool")
    repeated_or_multipool = selected["endpoint_period_membership"].eq(
        "period-specific"
    ) & ~selected["origin_history_class"].eq("one-day/one-pool")
    for mask, label in (
        (continuing, "continuing"),
        (one_day, "one-day/one-pool"),
        (repeated_or_multipool, "repeated-or-multipool"),
    ):
        if not bool(mask.any()):
            raise ValueError(f"V3 origin-history results lack {label} observations")

    def share(mask: pd.Series, column: str) -> float:
        return float(selected.loc[mask, column].sum()) / float(totals[column])

    return {
        "continuing_action_share": share(continuing, "addition_action_events"),
        "continuing_flow_share": share(
            continuing, "screened_candidate_side_flow_usd"
        ),
        "repeated_or_multipool_action_share": share(
            repeated_or_multipool, "addition_action_events"
        ),
        "repeated_or_multipool_flow_share": share(
            repeated_or_multipool, "screened_candidate_side_flow_usd"
        ),
        "one_day_one_pool_action_share": share(one_day, "addition_action_events"),
        "one_day_one_pool_flow_share": share(
            one_day, "screened_candidate_side_flow_usd"
        ),
    }


def _summarize_followup(
    results: pd.DataFrame,
) -> tuple[tuple[int, float, float, float], ...]:
    followup = results.loc[results["record_type"].eq("v3_lp_launch_followup")]
    required = {
        "record_type",
        "period",
        "vehicle_type",
        "horizon_days",
        "launch_pools",
        "action_weighted_active_pool_share",
        "post_launch_net_to_launch_flow",
    }
    _require_columns(followup, required, description="V3 launch follow-up results")
    rows: list[tuple[int, float, float, float]] = []
    for horizon in HORIZONS:
        row = _select_one(
            followup,
            {
                "period": COMPARISON_PERIOD,
                "vehicle_type": "stable",
                "horizon_days": horizon,
            },
            description="V3 stable-facing launch follow-up",
        )
        launch_pools, active_share, net_flow_ratio = _finite(
            [
                row["launch_pools"],
                row["action_weighted_active_pool_share"],
                row["post_launch_net_to_launch_flow"],
            ],
            description="V3 stable-facing launch follow-up",
        )
        if launch_pools <= 0:
            raise ValueError("V3 launch follow-up must contain pools")
        if not 0.0 <= active_share <= 1.0:
            raise ValueError("V3 launch follow-up activity share is outside [0,1]")
        rows.append((horizon, launch_pools, active_share, net_flow_ratio))
    return tuple(rows)


def summarize_v3_lp_launch_supply(
    results: pd.DataFrame,
    support: pd.DataFrame,
) -> LaunchSupplySummary:
    """Validate the analysis exhibit and return the appendix quantities."""

    _validate_support(support)
    age = _summarize_age(results)
    origins = _summarize_origins(results)
    followup_rows = _summarize_followup(results)
    return LaunchSupplySummary(
        **age,
        **origins,
        followup_rows=followup_rows,
    )


def _integer(value: float) -> str:
    return f"{int(round(value)):,}"


def _tex_integer(value: float) -> str:
    return _integer(value).replace(",", "{,}")


def _percent(value: float, digits: int = 1) -> str:
    return f"{100.0 * value:.{digits}f}"


def _tex_percent(value: float, digits: int = 1) -> str:
    return f"{_percent(value, digits)}\\%"


def _pp(value: float) -> str:
    return f"{value:+.2f}"


def _tex_pp(value: float) -> str:
    return f"${value:+.2f}$ pp"


def _macro(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def render_v3_lp_launch_supply(
    results: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Render a compact four-panel appendix table."""

    summary = summarize_v3_lp_launch_supply(results, support)
    lines = [
        r"\textit{Panel A. Stable-facing addition growth by pool age}",
        r"\par\smallskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.7\hsize\raggedright\arraybackslash}X*{3}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"Pool age [days] & Addition actions, 2024 H1 & Addition actions, 2026 H1 & Share of increase [\%] \\",
        r"\midrule",
    ]
    for age_bin, baseline, comparison, increase_share in summary.age_rows:
        lines.append(
            f"{AGE_LABELS[age_bin]} & {_integer(baseline)} & "
            f"{_integer(comparison)} & "
            f"{_percent(increase_share)} " + r"\\"
        )
    lines.extend(
        [
            r"\midrule",
            "Total & "
            f"{_integer(sum(row[1] for row in summary.age_rows))} & "
            f"{_integer(sum(row[2] for row in summary.age_rows))} & 100.0 "
            + r"\\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel B. Stable-facing share across pool-age restrictions}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.7\hsize\raggedright\arraybackslash}X*{3}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Pool-age restriction & \multicolumn{2}{c}{Stable-facing share [\%]} & Change [pp] \\",
            r"\cmidrule(lr){2-3}",
            r"& 2024 H1 & 2026 H1 & 2024 H1--2026 H1 \\",
            r"\midrule",
            "All pool ages & "
            f"{_percent(summary.full_stable_share_baseline)} & "
            f"{_percent(summary.full_stable_share_comparison)} & "
            f"{_pp(summary.full_stable_share_change_pp)} "
            + r"\\",
            "Older than 7 days & "
            f"{_percent(summary.older_than_seven_stable_share_baseline)} & "
            f"{_percent(summary.older_than_seven_stable_share_comparison)} & "
            f"{_pp(summary.older_than_seven_stable_share_change_pp)} "
            + r"\\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel C. Transaction-origin participation in stable-facing additions, 2026 H1}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.5\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Transaction-origin history & Share of actions [\%] & Share of vehicle-side USD additions [\%] \\",
            r"\midrule",
            "Present in both comparison periods & "
            f"{_percent(summary.continuing_action_share, 2)} & "
            f"{_percent(summary.continuing_flow_share, 2)} "
            + r"\\",
            "Present only in 2026 H1; repeated days or multiple pools & "
            f"{_percent(summary.repeated_or_multipool_action_share, 2)} & "
            f"{_percent(summary.repeated_or_multipool_flow_share, 2)} "
            + r"\\",
            "Present only in 2026 H1; one day and one pool & "
            f"{_percent(summary.one_day_one_pool_action_share, 2)} & "
            f"{_percent(summary.one_day_one_pool_flow_share, 2)} "
            + r"\\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel D. Later activity among stable-facing pools first observed in 2026 H1}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.5\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Horizon & 30 days & 90 days \\",
            r"\midrule",
            "Pools in horizon-specific cohort & "
            + " & ".join(_integer(row[1]) for row in summary.followup_rows)
            + r" \\",
            "Action-weighted active-pool share [\\%] & "
            + " & ".join(_percent(row[2]) for row in summary.followup_rows)
            + r" \\",
            "Net vehicle-side USD flow / initial additions [\\%] & "
            + " & ".join(f"{100.0 * row[3]:+.2f}" for row in summary.followup_rows)
            + r" \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def render_v3_lp_launch_supply_values(
    results: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Return prose-ready TeX values from the appendix comparisons."""

    summary = summarize_v3_lp_launch_supply(results, support)
    age = {row[0]: row for row in summary.age_rows}
    followup = {row[0]: row for row in summary.followup_rows}
    lines = [
        "% Generated by scripts/tabulate/render_v3_lp_launch_supply.py; do not edit.",
        _macro("VThreeLPLaunchBaselinePeriod", "2024 H1"),
        _macro("VThreeLPLaunchComparisonPeriod", "2026 H1"),
        _macro(
            "VThreeLPLaunchStableActionIncrease",
            _tex_integer(summary.stable_action_increase),
        ),
        _macro("VThreeLPLaunchWeekIncreaseShare", _tex_percent(age["0-7"][3])),
        _macro("VThreeLPMaturePoolIncreaseShare", _tex_percent(age[">90"][3])),
        _macro(
            "VThreeLPLaunchFullStableShareBaseline",
            _tex_percent(summary.full_stable_share_baseline),
        ),
        _macro(
            "VThreeLPLaunchFullStableShareComparison",
            _tex_percent(summary.full_stable_share_comparison),
        ),
        _macro(
            "VThreeLPLaunchFullStableShareChange",
            _tex_pp(summary.full_stable_share_change_pp),
        ),
        _macro(
            "VThreeLPExLaunchStableShareBaseline",
            _tex_percent(summary.older_than_seven_stable_share_baseline),
        ),
        _macro(
            "VThreeLPExLaunchStableShareComparison",
            _tex_percent(summary.older_than_seven_stable_share_comparison),
        ),
        _macro(
            "VThreeLPExLaunchStableShareChange",
            _tex_pp(summary.older_than_seven_stable_share_change_pp),
        ),
        _macro(
            "VThreeLPOneDayOnePoolActionShare",
            _tex_percent(summary.one_day_one_pool_action_share, 2),
        ),
        _macro(
            "VThreeLPOneDayOnePoolFlowShare",
            _tex_percent(summary.one_day_one_pool_flow_share, 2),
        ),
        _macro(
            "VThreeLPRepeatedOrMultipoolActionShare",
            _tex_percent(summary.repeated_or_multipool_action_share, 2),
        ),
        _macro(
            "VThreeLPThirtyDayLaunchCohortPools",
            _tex_integer(followup[30][1]),
        ),
        _macro(
            "VThreeLPNinetyDayLaunchCohortPools",
            _tex_integer(followup[90][1]),
        ),
        _macro(
            "VThreeLPThirtyDayActivePoolShare",
            _tex_percent(followup[30][2]),
        ),
        _macro(
            "VThreeLPNinetyDayActivePoolShare",
            _tex_percent(followup[90][2]),
        ),
        _macro(
            "VThreeLPThirtyDayNetFlowRatio",
            _tex_percent(followup[30][3], 2),
        ),
        _macro(
            "VThreeLPNinetyDayNetFlowRatio",
            _tex_percent(followup[90][3], 2),
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "v3_lp_launch_supply",
        render_v3_lp_launch_supply(results, support),
        preview_width="8.5in",
    )
    with atomic_output(VALUES_OUTPUT) as temporary:
        temporary.write_text(
            render_v3_lp_launch_supply_values(results, support),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
