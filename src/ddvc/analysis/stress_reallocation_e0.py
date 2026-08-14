"""Provisional route reallocation around independently measured ETH moves.

The package selects daily ETH moves from an off-chain reference series and
starts each route window only after that daily observation is complete.  It
keeps ordered source--destination pairs fixed from the pre-event period and is
descriptive: realised routes do not reveal the alternatives available to a
router, and ex-post event selection does not identify a causal shock effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import linear_sum_assignment

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.asset_types import classify
from ddvc.endpoint_candidate_composition import INCLUDED, _component_frame


CALENDAR_PROTOCOL_REGIMES = (
    ("pre_uniswap_v3", None, pd.Timestamp("2021-05-05")),
    (
        "uniswap_v3_pre_merge",
        pd.Timestamp("2021-05-05"),
        pd.Timestamp("2022-09-15"),
    ),
    (
        "post_merge_pre_uniswap_v4",
        pd.Timestamp("2022-09-15"),
        pd.Timestamp("2025-01-31"),
    ),
    ("uniswap_v4_era", pd.Timestamp("2025-01-31"), None),
)


@dataclass(frozen=True)
class StressDesign:
    daily_threshold: float = 0.08
    cluster_gap_days: int = 14
    event_count_per_direction: int = 20
    hours_before: int = 24
    hours_after: int = 24
    minimum_pre_hours: int = 6
    support_sensitivity_hours: tuple[int, ...] = (3, 12)
    randomization_repetitions: int = 49_999

    @property
    def all_support_thresholds(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                (self.minimum_pre_hours, *self.support_sensitivity_hours)
            )
        )


def prepare_etherscan_daily_reference(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate the retained Etherscan chart and impose conservative timing.

    Etherscan labels each row with the UTC date over which the daily price is
    formed.  We therefore make the observation available at 00:00 UTC on the
    following date.  The alignment is independently checked against CoinGecko
    by :func:`compare_daily_reference_sources`.
    """

    required = {"Date(UTC)", "UnixTimeStamp", "Value"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"daily ETH reference lacks columns: {missing}")
    frame = raw.loc[:, ["Date(UTC)", "UnixTimeStamp", "Value"]].copy()
    frame["observation_date"] = pd.to_datetime(
        frame["Date(UTC)"], errors="raise"
    ).dt.normalize()
    timestamp_date = pd.to_datetime(
        pd.to_numeric(frame["UnixTimeStamp"], errors="raise"),
        unit="s",
        utc=True,
    ).dt.tz_localize(None).dt.normalize()
    if not (timestamp_date.to_numpy() == frame["observation_date"].to_numpy()).all():
        raise ValueError("Etherscan date labels disagree with their Unix timestamps")
    frame["eth_usd"] = pd.to_numeric(frame["Value"], errors="raise")
    frame = frame.loc[frame["eth_usd"].gt(0)].sort_values("observation_date")
    if frame.empty or frame["observation_date"].duplicated().any():
        raise ValueError("daily ETH reference is empty or duplicates a date")
    gaps = frame["observation_date"].diff().dt.days.dropna()
    if not gaps.eq(1).all():
        first = frame.loc[gaps.ne(1).reindex(frame.index, fill_value=False)].iloc[0]
        raise ValueError(
            "daily ETH reference is not consecutive at "
            f"{first['observation_date']:%Y-%m-%d}"
        )
    frame["available_date"] = frame["observation_date"] + pd.Timedelta(days=1)
    frame["available_at_utc"] = frame["available_date"].map(
        lambda value: int(value.tz_localize("UTC").timestamp())
    )
    frame["event_hour"] = frame["available_at_utc"] // 3600
    frame["daily_log_return"] = np.log(frame["eth_usd"]).diff()
    return frame[
        [
            "observation_date",
            "available_date",
            "available_at_utc",
            "event_hour",
            "eth_usd",
            "daily_log_return",
        ]
    ].reset_index(drop=True)


def compare_daily_reference_sources(
    primary: pd.DataFrame, comparator: pd.DataFrame
) -> dict[str, float | int | str]:
    """Check Etherscan daily closes against independently retained CoinGecko.

    CoinGecko timestamps the same end-of-day observation at the following UTC
    boundary.  Accordingly, its ``date`` joins to Etherscan's conservative
    ``available_date`` rather than its observation label.
    """

    required = {"date", "eth_price_usd"}
    missing = sorted(required - set(comparator.columns))
    if missing:
        raise ValueError(f"daily ETH comparator lacks columns: {missing}")
    other = comparator.loc[:, ["date", "eth_price_usd"]].copy()
    other["date"] = pd.to_datetime(other["date"], errors="raise").dt.normalize()
    other["eth_price_usd"] = pd.to_numeric(
        other["eth_price_usd"], errors="raise"
    )
    other = other.loc[other["eth_price_usd"].gt(0)].drop_duplicates("date")
    overlap = primary.merge(
        other,
        left_on="available_date",
        right_on="date",
        how="inner",
        validate="one_to_one",
    )
    if len(overlap) < 60:
        raise ValueError("independent daily ETH sources overlap on fewer than 60 dates")
    level_correlation = float(
        overlap[["eth_usd", "eth_price_usd"]].corr().iloc[0, 1]
    )
    return_correlation = float(
        np.log(overlap[["eth_usd", "eth_price_usd"]]).diff().corr().iloc[0, 1]
    )
    relative = (overlap["eth_usd"] / overlap["eth_price_usd"] - 1).abs()
    diagnostics: dict[str, float | int | str] = {
        "overlap_days": len(overlap),
        "overlap_start": overlap["date"].min().strftime("%Y-%m-%d"),
        "overlap_end": overlap["date"].max().strftime("%Y-%m-%d"),
        "level_correlation": level_correlation,
        "log_return_correlation": return_correlation,
        "median_absolute_relative_difference": float(relative.median()),
        "p99_absolute_relative_difference": float(relative.quantile(0.99)),
        "alignment": "etherscan observation date plus one day equals CoinGecko date",
    }
    if (
        level_correlation < 0.99
        or return_correlation < 0.99
        or diagnostics["median_absolute_relative_difference"] > 0.01
        or diagnostics["p99_absolute_relative_difference"] > 0.03
    ):
        raise ValueError(
            "retained daily ETH sources fail the price-agreement thresholds"
        )
    return diagnostics


def select_reference_events(
    prices: pd.DataFrame,
    design: StressDesign,
    *,
    sample_start: str = "2020-01-01",
    sample_end: str = "2026-06-01",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select symmetric moves using direct magnitude-priority calendar spacing.

    Candidates are considered from largest to smallest absolute return, with
    date as the deterministic tie-breaker.  A candidate is excluded only when
    it lies directly within ``cluster_gap_days`` calendar days of an already
    accepted higher-priority candidate.  A chain of nearby events cannot make
    two events more than the declared distance apart collide.
    """

    sample = prices.loc[
        prices["observation_date"].between(
            pd.Timestamp(sample_start), pd.Timestamp(sample_end)
        )
        & prices["daily_log_return"].abs().ge(design.daily_threshold)
    ].copy()
    sample["event_type"] = np.where(
        sample["daily_log_return"].lt(0), "drawdown", "rally"
    )
    sample["shock_magnitude"] = sample["daily_log_return"].abs()
    if sample.empty:
        raise ValueError("daily ETH reference supplies no threshold events")

    ranked_candidates = sample.sort_values(
        ["shock_magnitude", "observation_date"],
        ascending=[False, True],
        kind="stable",
    )
    accepted: list[pd.Series] = []
    excluded: list[dict[str, object]] = []
    for priority_rank, (_index, row) in enumerate(
        ranked_candidates.iterrows(), 1
    ):
        conflicts = [
            prior
            for prior in accepted
            if abs(
                (row["observation_date"] - prior["observation_date"]).days
            )
            <= design.cluster_gap_days
        ]
        if conflicts:
            reference = min(
                conflicts,
                key=lambda prior: (
                    abs(
                        (
                            row["observation_date"]
                            - prior["observation_date"]
                        ).days
                    ),
                    -float(prior["shock_magnitude"]),
                    prior["observation_date"],
                ),
            )
            distance = abs(
                (
                    row["observation_date"]
                    - reference["observation_date"]
                ).days
            )
            excluded.append(
                {
                    "observation_date": row["observation_date"],
                    "event_type": row["event_type"],
                    "daily_log_return": row["daily_log_return"],
                    "shock_magnitude": row["shock_magnitude"],
                    "reason": (
                        "direct_calendar_collision_with_higher_priority_move"
                    ),
                    "collision_reference_date": reference[
                        "observation_date"
                    ],
                    "collision_reference_daily_log_return": reference[
                        "daily_log_return"
                    ],
                    "collision_reference_shock_magnitude": reference[
                        "shock_magnitude"
                    ],
                    "calendar_distance_days": distance,
                    "collision_distance_rule_days": design.cluster_gap_days,
                    "selection_rule": (
                        "descending_absolute_return_then_date; direct "
                        f"plus_or_minus_{design.cluster_gap_days}_calendar_days"
                    ),
                }
            )
            continue
        winner = row.copy()
        winner["selection_priority_rank"] = priority_rank
        accepted.append(winner)

    winners_frame = pd.DataFrame(accepted)
    direction_counts = winners_frame.groupby("event_type").size()
    if set(direction_counts.index) != {"drawdown", "rally"}:
        raise ValueError("daily ETH reference does not support both event directions")
    symmetric_cap = min(
        design.event_count_per_direction, int(direction_counts.min())
    )
    selected_frames: list[pd.DataFrame] = []
    for event_type, direction in winners_frame.groupby("event_type", sort=True):
        ranked = direction.sort_values(
            ["shock_magnitude", "observation_date"], ascending=[False, True]
        )
        selected_frames.append(ranked.head(symmetric_cap))
        for _index, row in ranked.iloc[symmetric_cap:].iterrows():
            excluded.append(
                {
                    "observation_date": row["observation_date"],
                    "event_type": event_type,
                    "daily_log_return": row["daily_log_return"],
                    "shock_magnitude": row["shock_magnitude"],
                    "reason": "outside_direction_event_count_cap",
                    "collision_reference_date": pd.NaT,
                    "collision_reference_daily_log_return": np.nan,
                    "collision_reference_shock_magnitude": np.nan,
                    "calendar_distance_days": np.nan,
                    "collision_distance_rule_days": design.cluster_gap_days,
                    "selection_rule": "symmetric_direction_event_count_cap",
                }
            )
    selected = pd.concat(selected_frames, ignore_index=True).sort_values(
        "observation_date"
    )
    if excluded:
        retained_dates = set(selected["observation_date"])
        for record in excluded:
            reference = record.get("collision_reference_date")
            record["collision_reference_retained_after_direction_cap"] = bool(
                pd.notna(reference) and reference in retained_dates
            )
    keep = [
        "observation_date",
        "available_date",
        "available_at_utc",
        "event_hour",
        "eth_usd",
        "daily_log_return",
        "event_type",
        "shock_magnitude",
        "selection_priority_rank",
    ]
    exclusions = pd.DataFrame(excluded)
    if not exclusions.empty:
        exclusions = exclusions.sort_values("observation_date").reset_index(drop=True)
    return selected[keep].reset_index(drop=True), exclusions


def calendar_protocol_regime(value: object) -> str:
    """Map an event date to a disclosed coarse protocol/calendar regime."""

    date = pd.Timestamp(value).tz_localize(None).normalize()
    for name, start, end in CALENDAR_PROTOCOL_REGIMES:
        if (start is None or date >= start) and (end is None or date < end):
            return name
    raise RuntimeError(f"calendar regime is undefined for {date:%Y-%m-%d}")


def direction_comparability_diagnostic(
    events: pd.DataFrame,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Measure direction imbalance and, when supported, form bounded matches.

    Matching is exact on the coarse protocol/calendar regime and minimizes the
    absolute ETH-move magnitude distance within each regime.  It is a
    diagnostic sample restriction, not an identification strategy.
    """

    required = {"event", "event_type", "daily_log_return"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(
            f"direction comparability lacks columns: {', '.join(missing)}"
        )
    sample = events.loc[:, sorted(required)].drop_duplicates("event").copy()
    if sample["event"].duplicated().any():
        raise ValueError("direction comparability duplicates an event")
    sample["shock_magnitude"] = sample["daily_log_return"].abs()
    sample["calendar_protocol_regime"] = sample["event"].map(
        calendar_protocol_regime
    )
    directions = {
        name: frame.sort_values("event", kind="stable").reset_index(drop=True)
        for name, frame in sample.groupby("event_type", sort=True)
    }
    if set(directions) != {"drawdown", "rally"}:
        raise ValueError("direction comparability requires drawdowns and rallies")
    drawdown = directions["drawdown"]
    rally = directions["rally"]

    def standardized_difference(left: pd.Series, right: pd.Series) -> float:
        pooled_variance = (
            (len(left) - 1) * left.var(ddof=1)
            + (len(right) - 1) * right.var(ddof=1)
        ) / (len(left) + len(right) - 2)
        pooled_sd = math.sqrt(float(pooled_variance))
        return (
            float((left.mean() - right.mean()) / pooled_sd)
            if pooled_sd > 0
            else 0.0
        )

    magnitude_low = max(
        float(drawdown["shock_magnitude"].min()),
        float(rally["shock_magnitude"].min()),
    )
    magnitude_high = min(
        float(drawdown["shock_magnitude"].max()),
        float(rally["shock_magnitude"].max()),
    )
    in_common = sample["shock_magnitude"].between(
        magnitude_low, magnitude_high
    )
    common_counts = (
        sample.loc[in_common].groupby("event_type").size().to_dict()
    )
    regime_counts = pd.crosstab(
        sample["calendar_protocol_regime"], sample["event_type"]
    ).reindex(columns=["drawdown", "rally"], fill_value=0)
    shares = regime_counts.div(regime_counts.sum(axis=0), axis=1)
    regime_total_variation = float(
        0.5 * (shares["drawdown"] - shares["rally"]).abs().sum()
    )
    common_regimes = regime_counts.index[
        regime_counts["drawdown"].gt(0) & regime_counts["rally"].gt(0)
    ].tolist()
    matching_eligible = bool(
        min(len(drawdown), len(rally)) >= 8
        and min(
            int(common_counts.get("drawdown", 0)),
            int(common_counts.get("rally", 0)),
        )
        >= 8
        and len(common_regimes) >= 3
    )

    matched_events: list[str] = []
    matched_pairs = 0
    matched_magnitude_gaps: list[float] = []
    if matching_eligible:
        for regime in common_regimes:
            left = drawdown.loc[
                drawdown["calendar_protocol_regime"].eq(regime)
            ].reset_index(drop=True)
            right = rally.loc[
                rally["calendar_protocol_regime"].eq(regime)
            ].reset_index(drop=True)
            cost = np.abs(
                left["shock_magnitude"].to_numpy()[:, None]
                - right["shock_magnitude"].to_numpy()[None, :]
            )
            left_index, right_index = linear_sum_assignment(cost)
            matched_events.extend(left.iloc[left_index]["event"].astype(str))
            matched_events.extend(right.iloc[right_index]["event"].astype(str))
            matched_magnitude_gaps.extend(cost[left_index, right_index].tolist())
            matched_pairs += len(left_index)
    matched = sample.loc[sample["event"].isin(matched_events)]
    matched_smd = float("nan")
    if matched_pairs:
        matched_smd = standardized_difference(
            matched.loc[
                matched["event_type"].eq("drawdown"), "shock_magnitude"
            ],
            matched.loc[
                matched["event_type"].eq("rally"), "shock_magnitude"
            ],
        )

    diagnostic: dict[str, object] = {
        "row_type": "direction_comparability",
        "event_type": "drawdown_vs_rally",
        "measure": "event_selection",
        "minimum_pre_hours": np.nan,
        "specification": "diagnostic",
        "estimand": "direction_sample_comparability",
        "drawdown_events": len(drawdown),
        "rally_events": len(rally),
        "drawdown_mean_shock_magnitude": float(
            drawdown["shock_magnitude"].mean()
        ),
        "rally_mean_shock_magnitude": float(rally["shock_magnitude"].mean()),
        "shock_magnitude_standardized_difference": standardized_difference(
            drawdown["shock_magnitude"], rally["shock_magnitude"]
        ),
        "magnitude_common_support_low": magnitude_low,
        "magnitude_common_support_high": magnitude_high,
        "drawdown_events_in_magnitude_common_support": int(
            common_counts.get("drawdown", 0)
        ),
        "rally_events_in_magnitude_common_support": int(
            common_counts.get("rally", 0)
        ),
        "calendar_protocol_regime_total_variation": regime_total_variation,
        "calendar_protocol_regime_counts": regime_counts.to_json(
            orient="index"
        ),
        "calendar_protocol_regime_definitions": "|".join(
            f"{name}:{start.date() if start is not None else '-inf'}--"
            f"{end.date() if end is not None else '+inf'}"
            for name, start, end in CALENDAR_PROTOCOL_REGIMES
        ),
        "matching_eligible": matching_eligible,
        "matching_decision": (
            "run exact-regime minimum-magnitude-distance matched FE diagnostic"
            if matching_eligible
            else "no matched model; expose direction imbalance and narrow interpretation"
        ),
        "matched_event_pairs": matched_pairs,
        "matched_events": "|".join(sorted(set(matched_events))),
        "matched_mean_absolute_magnitude_gap": (
            float(np.mean(matched_magnitude_gaps))
            if matched_magnitude_gaps
            else np.nan
        ),
        "matched_shock_magnitude_standardized_difference": matched_smd,
        "interpretation": (
            "direction comparison remains descriptive; matching is exact on the coarse "
            "calendar/protocol regime and minimizes disclosed move-magnitude differences"
            if matching_eligible
            else "direction comparison is not comparable enough for a matched sensitivity"
        ),
    }
    return diagnostic, tuple(sorted(set(matched_events)))


def exact_hourly_choices(legs: pd.DataFrame, day: str) -> pd.DataFrame:
    """Reduce one released route day to exact two-leg native/stable choices."""

    components = _component_frame(legs, day)
    columns = [
        "hour",
        "src",
        "tgt",
        "candidate_type",
        "candidate_symbol",
        "route_count",
        "within_20pct_routes",
        "within_20pct_value_usd",
    ]
    if components.empty:
        return pd.DataFrame(columns=columns)
    included = components.loc[components["selection_reason"].eq(INCLUDED)].copy()
    if included.empty:
        return pd.DataFrame(columns=columns)
    timestamps = legs.groupby(
        ["tx_hash", "component_id"], as_index=False
    )["timestamp_utc"].min()
    included = included.merge(
        timestamps,
        on=["tx_hash", "component_id"],
        how="left",
        validate="one_to_one",
    )
    included["hour"] = (
        pd.to_numeric(included["timestamp_utc"], errors="raise") // 3600
    ).astype("int64")
    included["route_count"] = 1
    included["within_20pct_routes"] = included["within_20pct"].astype("int64")
    included["within_20pct_value_usd"] = np.where(
        included["within_20pct"], included["candidate_value_usd"], 0.0
    )
    return (
        included.groupby(
            ["hour", "src", "tgt", "candidate_type", "candidate_symbol"],
            as_index=False,
            sort=True,
        )[["route_count", "within_20pct_routes", "within_20pct_value_usd"]]
        .sum()[columns]
    )


def fixed_support_panel(
    choices: pd.DataFrame,
    *,
    event: str,
    event_type: str,
    event_hour: int,
    daily_log_return: float,
    design: StressDesign,
) -> pd.DataFrame:
    """Build pair-hour observations from support fixed before price availability."""

    selected = choices.loc[
        choices["hour"].between(
            event_hour - design.hours_before,
            event_hour + design.hours_after - 1,
        )
    ].copy()
    selected["pair"] = selected["src"] + ">" + selected["tgt"]
    pre = selected.loc[selected["hour"].lt(event_hour)]
    minimum = min(design.all_support_thresholds)
    support = pre.groupby("pair", as_index=False).agg(
        active_pre_hours=("hour", "nunique"),
        native_pre=(
            "route_count",
            lambda values: float(
                values[
                    pre.loc[values.index, "candidate_type"].eq("native")
                ].sum()
            ),
        ),
        stable_pre=(
            "route_count",
            lambda values: float(
                values[
                    pre.loc[values.index, "candidate_type"].eq("stable")
                ].sum()
            ),
        ),
    )
    support = support.loc[
        support["active_pre_hours"].ge(minimum)
        & support["native_pre"].gt(0)
        & support["stable_pre"].gt(0)
    ]
    selected = selected.merge(
        support[["pair"]], on="pair", how="inner", validate="many_to_one"
    )
    selected["event"] = event
    selected["event_type"] = event_type
    selected["event_hour"] = event_hour
    selected["daily_log_return"] = daily_log_return
    selected["relative_hour"] = selected["hour"] - event_hour
    return selected


def _pair_period(panel: pd.DataFrame, measure: str) -> pd.DataFrame:
    frame = panel.copy()
    frame["period"] = np.where(frame["relative_hour"].lt(0), "pre", "post")
    grouped = frame.groupby(
        ["pair", "src", "tgt", "period", "candidate_type"], as_index=False
    )[measure].sum()
    wide = grouped.pivot_table(
        index=["pair", "src", "tgt"],
        columns=["period", "candidate_type"],
        values=measure,
        aggfunc="sum",
        fill_value=0.0,
    )
    for key in (
        ("pre", "native"),
        ("pre", "stable"),
        ("post", "native"),
        ("post", "stable"),
    ):
        if key not in wide:
            wide[key] = 0.0
    wide.columns = [
        f"{period}_{candidate}" for period, candidate in wide.columns
    ]
    return wide.reset_index()


def _measure_supported_panel(
    panel: pd.DataFrame, measure: str, minimum_pre_hours: int
) -> pd.DataFrame:
    """Fix measure-specific pair support using only pre-event observations."""

    pre = panel.loc[panel["relative_hour"].lt(0) & panel[measure].gt(0)]
    support = pre.groupby("pair", as_index=False).agg(
        active_pre_hours=("hour", "nunique"),
        native_pre=(
            measure,
            lambda values: float(
                values[
                    pre.loc[values.index, "candidate_type"].eq("native")
                ].sum()
            ),
        ),
        stable_pre=(
            measure,
            lambda values: float(
                values[
                    pre.loc[values.index, "candidate_type"].eq("stable")
                ].sum()
            ),
        ),
    )
    support = support.loc[
        support["active_pre_hours"].ge(minimum_pre_hours)
        & support["native_pre"].gt(0)
        & support["stable_pre"].gt(0)
    ]
    return panel.merge(
        support[["pair"]], on="pair", how="inner", validate="many_to_one"
    )


def decompose_event(
    panel: pd.DataFrame,
    measure: str,
    *,
    minimum_pre_hours: int = 6,
) -> dict[str, float | int | str]:
    """Separate pair exit, activity reweighting, and continuing-pair substitution.

    The exact sequential identity first removes inactive pairs while holding
    surviving pairs at pre-event activity weights and shares, then applies the
    post-event activity weights among survivors, and finally applies their
    post-event native shares.
    """

    supported = _measure_supported_panel(panel, measure, minimum_pre_hours)
    wide = _pair_period(supported, measure)
    if wide.empty:
        raise ValueError("stress decomposition has no pre-supported pairs")
    for period in ("pre", "post"):
        wide[f"{period}_total"] = (
            wide[f"{period}_native"] + wide[f"{period}_stable"]
        )
    pre_total = float(wide["pre_total"].sum())
    post_total = float(wide["post_total"].sum())
    if pre_total <= 0 or post_total <= 0:
        raise ValueError("stress decomposition requires positive pre and post activity")
    wide["s0"] = wide["pre_native"] / wide["pre_total"]
    wide["continuing"] = wide["post_total"].gt(0)
    continuing = wide.loc[wide["continuing"]].copy()
    continuing_pre_total = float(continuing["pre_total"].sum())
    if continuing_pre_total <= 0:
        raise ValueError("all pre-supported pairs exit after the event")
    continuing["s1"] = continuing["post_native"] / continuing["post_total"]

    baseline = float((wide["pre_total"] / pre_total * wide["s0"]).sum())
    after_exit = float(
        (
            continuing["pre_total"]
            / continuing_pre_total
            * continuing["s0"]
        ).sum()
    )
    after_reweighting = float(
        (continuing["post_total"] / post_total * continuing["s0"]).sum()
    )
    comparison = float(
        (continuing["post_total"] / post_total * continuing["s1"]).sum()
    )
    pair_exit = after_exit - baseline
    activity_reweighting = after_reweighting - after_exit
    within = comparison - after_reweighting
    residual = comparison - baseline - pair_exit - activity_reweighting - within
    if not math.isclose(residual, 0.0, abs_tol=1e-10):
        raise RuntimeError("stress reallocation decomposition is not exact")
    return {
        "measure": measure,
        "minimum_pre_hours": minimum_pre_hours,
        "pairs": len(wide),
        "continuing_pairs": int(wide["continuing"].sum()),
        "exited_pairs": int((~wide["continuing"]).sum()),
        "exited_pair_pre_activity_share": float(
            wide.loc[~wide["continuing"], "pre_total"].sum() / pre_total
        ),
        "pre_activity": pre_total,
        "post_activity": post_total,
        "baseline_native_share": baseline,
        "post_native_share": comparison,
        "native_share_change": comparison - baseline,
        "pair_exit_composition": pair_exit,
        "continuing_pair_activity_reallocation": activity_reweighting,
        "continuing_pair_intermediary_substitution": within,
        "decomposition_residual": residual,
    }


def conditional_role_composition(
    choices: pd.DataFrame,
    *,
    event_hour: int,
    measure: str,
    design: StressDesign,
) -> dict[str, float]:
    """Describe intermediary and endpoint composition in the broader route sample.

    This deliberately is not called a role-separation test.  The broader route
    population can change across the window, so the comparison is a conditional
    composition diagnostic rather than a fixed-market substitution estimate.
    """

    frame = choices.loc[
        choices["hour"].between(
            event_hour - design.hours_before,
            event_hour + design.hours_after - 1,
        )
    ].copy()
    frame["period"] = np.where(frame["hour"].lt(event_hour), "pre", "post")

    def ratio(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator > 0 else float("nan")

    def shares(period: str) -> tuple[float, float]:
        sample = frame.loc[frame["period"].eq(period)]
        intermediary = sample.groupby("candidate_type")[measure].sum()
        native_intermediary = float(intermediary.get("native", 0.0))
        stable_intermediary = float(intermediary.get("stable", 0.0))
        intermediary_share = ratio(
            native_intermediary, native_intermediary + stable_intermediary
        )

        rows: list[tuple[str, float]] = []
        for row in sample.itertuples(index=False):
            value = float(getattr(row, measure))
            for endpoint in (row.src, row.tgt):
                _symbol, kind = classify(endpoint)
                if kind in {"native", "stable"}:
                    rows.append((kind, value))
        if not rows:
            return intermediary_share, float("nan")
        endpoint = pd.DataFrame(rows, columns=["kind", "value"]).groupby("kind")[
            "value"
        ].sum()
        native_endpoint = float(endpoint.get("native", 0.0))
        stable_endpoint = float(endpoint.get("stable", 0.0))
        endpoint_share = ratio(native_endpoint, native_endpoint + stable_endpoint)
        return intermediary_share, endpoint_share

    intermediary_pre, endpoint_pre = shares("pre")
    intermediary_post, endpoint_post = shares("post")
    return {
        "broad_intermediary_native_share_pre": intermediary_pre,
        "broad_intermediary_native_share_post": intermediary_post,
        "broad_intermediary_native_share_change": intermediary_post
        - intermediary_pre,
        "endpoint_native_share_pre": endpoint_pre,
        "endpoint_native_share_post": endpoint_post,
        "endpoint_native_share_change": endpoint_post - endpoint_pre,
        "intermediary_minus_endpoint_change": (
            intermediary_post - intermediary_pre - endpoint_post + endpoint_pre
        ),
    }


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:8], "big")


def one_sample_small_cluster_inference(
    values: np.ndarray,
    *,
    label: str,
    repetitions: int = 49_999,
) -> dict[str, float | int | str]:
    """Return conventional, sign, and wild sign-flip inference across events."""

    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample)]
    n = len(sample)
    if n < 2:
        return {
            "events": n,
            "estimate": float(sample.mean()) if n else float("nan"),
            "standard_error": float("nan"),
            "t_statistic": float("nan"),
            "p_value": float("nan"),
            "sign_test_p_value": float("nan"),
            "wild_sign_flip_p_value": float("nan"),
            "wild_repetitions": 0,
        }
    estimate = float(sample.mean())
    standard_error = float(stats.sem(sample))
    if standard_error == 0 and estimate == 0:
        return {
            "events": n,
            "estimate": 0.0,
            "standard_error": 0.0,
            "t_statistic": 0.0,
            "p_value": 1.0,
            "sign_test_p_value": 1.0,
            "wild_sign_flip_p_value": 1.0,
            "wild_repetitions": repetitions,
        }
    t_statistic = (
        estimate / standard_error
        if standard_error > 0
        else math.copysign(float("inf"), estimate)
    )
    p_value = float(2 * stats.t.sf(abs(t_statistic), n - 1))
    nonzero = sample[sample != 0]
    sign_p = (
        float(stats.binomtest(int((nonzero > 0).sum()), len(nonzero), 0.5).pvalue)
        if len(nonzero)
        else 1.0
    )

    observed = abs(t_statistic)
    hits = 0
    completed = 0
    generator = np.random.default_rng(_seed(label))
    while completed < repetitions:
        batch = min(5_000, repetitions - completed)
        signs = generator.choice(np.array([-1.0, 1.0]), size=(batch, n))
        draws = signs * sample
        means = draws.mean(axis=1)
        sem = draws.std(axis=1, ddof=1) / math.sqrt(n)
        wild_t = np.divide(
            means,
            sem,
            out=np.zeros_like(means),
            where=sem > 0,
        )
        hits += int((np.abs(wild_t) >= observed - 1e-15).sum())
        completed += batch
    return {
        "events": n,
        "estimate": estimate,
        "standard_error": standard_error,
        "t_statistic": t_statistic,
        "p_value": p_value,
        "sign_test_p_value": sign_p,
        "wild_sign_flip_p_value": (hits + 1) / (repetitions + 1),
        "wild_repetitions": repetitions,
    }


def _holm_adjust(p_values: pd.Series) -> pd.Series:
    adjusted = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    if valid.empty:
        return adjusted
    running = 0.0
    count = len(valid)
    for rank, (index, value) in enumerate(valid.items()):
        running = max(running, min(1.0, (count - rank) * float(value)))
        adjusted.loc[index] = running
    return adjusted


def summarize_event_estimates(
    events: pd.DataFrame,
    *,
    repetitions: int = 49_999,
) -> pd.DataFrame:
    """Summarize identical drawdown and rally estimators with small-N inference."""

    estimands = (
        "native_share_change",
        "pair_exit_composition",
        "continuing_pair_activity_reallocation",
        "continuing_pair_intermediary_substitution",
    )
    rows: list[dict[str, object]] = []
    group_columns = ["event_type", "measure", "minimum_pre_hours"]
    for keys, frame in events.groupby(group_columns, sort=True):
        event_type, measure, minimum_pre_hours = keys
        specification = (
            "primary"
            if int(minimum_pre_hours) == 6
            else f"pre_support_{int(minimum_pre_hours)}_hours"
        )
        for estimand in estimands:
            label = "|".join(map(str, (*keys, estimand)))
            inference = one_sample_small_cluster_inference(
                frame[estimand].to_numpy(float),
                label=label,
                repetitions=repetitions,
            )
            rows.append(
                {
                    "row_type": "event_mean",
                    "event_type": event_type,
                    "measure": measure,
                    "minimum_pre_hours": int(minimum_pre_hours),
                    "specification": specification,
                    "estimand": estimand,
                    **inference,
                    "primary_inference": "wild_sign_flip_t_across_events",
                    "family_id": (
                        "stress_direction_x_measure_x_four_margins"
                        if specification == "primary"
                        else "pre_route_support_sensitivity"
                    ),
                }
            )
    results = pd.DataFrame(rows)
    primary = results["specification"].eq("primary")
    results["wild_p_holm_exploratory_family"] = np.nan
    results.loc[primary, "wild_p_holm_exploratory_family"] = _holm_adjust(
        results.loc[primary, "wild_sign_flip_p_value"]
    )
    return results


def fit_direction_fixed_effects(
    panel: pd.DataFrame,
    measure: str,
    *,
    minimum_pre_hours: int = 6,
    specification: str | None = None,
    minimum_observations: int = 100,
    minimum_clusters: int = 8,
    randomization_repetitions: int = 49_999,
) -> dict[str, float | int | str]:
    """Compare the post-window change after drawdowns with that after rallies.

    Event-by-pair fixed effects absorb each comparison's level; relative-hour
    fixed effects absorb the common intraday profile.  The interaction is a
    descriptive differential, not a causal event-study coefficient.
    """

    if specification is None:
        specification = (
            "primary"
            if minimum_pre_hours == 6
            else f"pre_support_{minimum_pre_hours}_hours"
        )
    supported_frames = []
    for _event, frame in panel.groupby("event", sort=False):
        supported = _measure_supported_panel(
            frame, measure, minimum_pre_hours
        )
        if not supported.empty:
            supported_frames.append(supported)
    if not supported_frames:
        raise ValueError(
            "direction fixed effects have no measure-supported event panels"
        )
    supported = pd.concat(supported_frames, ignore_index=True)
    grouped = supported.groupby(
        [
            "event",
            "event_type",
            "pair",
            "hour",
            "relative_hour",
            "candidate_type",
        ],
        as_index=False,
    )[measure].sum()
    wide = grouped.pivot_table(
        index=["event", "event_type", "pair", "hour", "relative_hour"],
        columns="candidate_type",
        values=measure,
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for candidate in ("native", "stable"):
        if candidate not in wide:
            wide[candidate] = 0.0
    wide["weight"] = wide["native"] + wide["stable"]
    wide = wide.loc[wide["weight"].gt(0)].copy()
    wide["native_share"] = wide["native"] / wide["weight"]
    wide["drawdown_post"] = (
        wide["event_type"].eq("drawdown") & wide["relative_hour"].ge(0)
    ).astype(float)
    wide["event_pair"] = wide["event"] + "|" + wide["pair"]
    residual = absorb_fixed_effects(
        wide[["native_share", "drawdown_post"]],
        wide["event_pair"],
        wide["relative_hour"],
        weights=wide["weight"],
    )
    fit = ols_clustered(
        residual["native_share"],
        residual[["drawdown_post"]],
        wide["event"],
        add_constant=False,
        absorbed_groups=(wide["event_pair"], wide["relative_hour"]),
        min_observations=minimum_observations,
        min_clusters=minimum_clusters,
        weights=wide["weight"],
    )

    x = residual["drawdown_post"].to_numpy(float)
    y = residual["native_share"].to_numpy(float)
    weight = wide["weight"].to_numpy(float)
    score_frame = pd.DataFrame(
        {"event": wide["event"].to_numpy(), "score": weight * x * y}
    )
    scores = score_frame.groupby("event", sort=True)["score"].sum().to_numpy()
    observed_score = abs(scores.sum())
    generator = np.random.default_rng(
        _seed(
            f"direction-fe|{measure}|{minimum_pre_hours}|{specification}"
        )
    )
    hits = 0
    completed = 0
    while completed < randomization_repetitions:
        batch = min(5_000, randomization_repetitions - completed)
        signs = generator.choice(
            np.array([-1.0, 1.0]), size=(batch, len(scores))
        )
        draws = np.abs(signs @ scores)
        hits += int((draws >= observed_score - 1e-15).sum())
        completed += batch
    return {
        "row_type": "direction_fixed_effect",
        "event_type": "drawdown_minus_rally",
        "measure": measure,
        "minimum_pre_hours": minimum_pre_hours,
        "specification": specification,
        "estimand": "differential_post_native_share",
        "estimate": float(fit.beta[0]),
        "standard_error": float(fit.standard_errors[0]),
        "t_statistic": float(fit.t_statistics[0]),
        "p_value": float(fit.p_values[0]),
        "wild_sign_flip_p_value": (hits + 1)
        / (randomization_repetitions + 1),
        "events": fit.n_clusters,
        "observations": fit.n_observations,
        "fixed_effects": "event_by_ordered_pair and relative_hour",
        "primary_inference": "event_cluster_score_sign_flip",
        "family_id": "stress_direction_fixed_effect_measure_x_support",
    }


# Backward-readable alias for callers of the rejected first draft.  The name is
# deliberately conditional: it must not be presented as a role-separation test.
role_separation_event = conditional_role_composition
