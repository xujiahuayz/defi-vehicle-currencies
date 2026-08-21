"""Render shared paper/deck macros from current route exhibits."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output
from ddvc.fetch.sources import ROUTE_SOURCE_FAMILIES
from ddvc.venue_tables import routing_window_values


EXHIBITS = OUTPUT_DIR / "exhibits"
ROTATION = EXHIBITS / "intermediation_complexity_rival.jsonl"
INTEGRATION = EXHIBITS / "intermediation_integration_interaction.jsonl"
TOKEN_INTEGRATION = EXHIBITS / "intermediation_token_integration_interaction.jsonl"
INTEGRATION_WITHIN_DAY = EXHIBITS / "integration_date_fe_ladder.jsonl"
EXCESS_USE = EXHIBITS / "vehicle_excess_use.jsonl"
VENUE_RIVAL = EXHIBITS / "venue_technology_rival.jsonl"
ROUTER_WINDOWS = EXHIBITS / "routing_technology_windows.jsonl"
EXCESS_USE_TRANSITION = EXHIBITS / "vehicle_excess_use_transition.jsonl"
ROUTING_SERIES = EXHIBITS / "cross_venue_routing_series.jsonl"
ROUTING_INFERENCE = EXHIBITS / "cross_venue_routing_inference.jsonl"
ROUTE_QUALITY = EXHIBITS / "unified_route_quality.jsonl"
OUTPUT = EXHIBITS / "presentation_values.tex"
INPUTS = (
    ROTATION,
    INTEGRATION,
    TOKEN_INTEGRATION,
    INTEGRATION_WITHIN_DAY,
    EXCESS_USE,
    EXCESS_USE_TRANSITION,
    ROUTING_SERIES,
    ROUTING_INFERENCE,
    VENUE_RIVAL,
    ROUTE_QUALITY,
    ROUTER_WINDOWS,
)
CODE_SOURCES = [
    "src/ddvc/presentation_values.py",
    "src/ddvc/venue_tables.py",
    "scripts/tabulate/render_presentation_values.py",
]
# The within-day integration ladder is displayed on one routing basis and one
# support band. Exact two-leg routes carry the paper's one-intermediary dominance
# object, and the 20 percent coherence band is the value measure the rest of the
# venue-span passage already uses, so the displayed cells match their neighbours.
WITHIN_DAY_BASIS = "exact_two_leg"
WITHIN_DAY_SUPPORT = "within_20pct"


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


# The within-day ladder already carries its outcome in percentage points, so its
# display must not rescale a second time.
def _pp_points(value: float, decimals: int = 2) -> str:
    return f"${value:+.{decimals}f}$ pp"


def _se_points(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f} pp"


def _interval_points(lower: float, upper: float, decimals: int = 1) -> str:
    return f"$[{lower:+.{decimals}f}, {upper:+.{decimals}f}]$"


COMPLEXITY_CELLS = (
    "single_venue_two_leg",
    "cross_venue_two_leg",
    "single_venue_more_than_two_legs",
    "cross_venue_more_than_two_legs",
)


def _weakest_complexity_cell(
    rotation: pd.DataFrame, *, weighting: str, value_support: str
) -> pd.Series:
    """Return the smallest 2024-to-2026 change among the four scope-complexity cells.

    Raises when any cell fails to rise, because the prose reports the set of
    cells jointly and the smallest member stands for all four.
    """

    cells = [
        _one(
            rotation,
            baseline_year=2024,
            comparison_year=2026,
            routing_scope=scope,
            weighting=weighting,
            value_support=value_support,
            transformation="share_level",
        )
        for scope in COMPLEXITY_CELLS
    ]
    for cell in cells:
        _finite(cell, "change", "hac_standard_error")
        if float(cell["change"]) <= 0:
            raise ValueError(
                "complexity rival no longer rises in every exchange-span by "
                f"route-complexity cell: {cell['routing_scope']} changed by "
                f"{float(cell['change']):+.4f}"
            )
    return min(cells, key=lambda cell: float(cell["change"]))


def _venue_scope_rise(
    venue_rival: pd.DataFrame, *, scope: str, asset_type: str
) -> tuple[pd.Series, pd.Series]:
    """Return the 2024 and 2026 excess-use rows for one venue pricing scope.

    Raises when the scope-year is not identified, because an unidentified scope
    supports no ratio and the prose reports the endpoints as a movement.
    """

    endpoints = []
    for year in (2024, 2026):
        row = _one(venue_rival, scope=scope, asset_type=asset_type, year=year)
        if str(row["support_status"]) != "identified":
            raise ValueError(
                f"venue rival scope {scope} is {row['support_status']} in {year}"
            )
        _finite(
            row,
            "vehicle_excess_use_count_ratio",
            "vehicle_excess_use_ratio",
            "intermediate_routes_support",
        )
        endpoints.append(row)
    return endpoints[0], endpoints[1]


def _require_curve_carries_no_intermediation(venue_rival: pd.DataFrame) -> None:
    """Refuse the prose claim unless every all-Curve scope-year lacks intermediation.

    The subsection states that route components confined to the stable-specialised
    invariant contain no intermediary episode in any year of the sample. That is a
    support statement about the exhibit, so it is checked rather than asserted.
    """

    curve = venue_rival.loc[venue_rival["scope"].eq("curve_only")]
    if curve.empty:
        raise ValueError("venue rival exhibit lacks the curve_only scope")
    supported = curve.loc[~curve["support_status"].eq("no_intermediation")]
    if not supported.empty:
        year = int(supported.iloc[0]["year"])
        raise ValueError(
            "all-Curve route components now carry intermediation in "
            f"{year}; the venue-technology sentence no longer holds"
        )
    episodes = float(curve["intermediate_routes_support"].fillna(0).sum())
    if episodes != 0:
        raise ValueError(f"all-Curve scope reports {episodes:.0f} intermediary episodes")


# Ceilings that make the router-release sentences falsifiable. The subsection says
# that intermediation never steps up at a release and that path length never moves
# by as much as five hundredths of a leg; both are bounds on the observed windows,
# so the macros are withheld entirely if either bound is breached.
ROUTER_MAX_INTERMEDIATION_RISE = 0.01
ROUTER_MAX_LEG_MOVEMENT = 0.05


def _router_window_changes(router_windows: pd.DataFrame) -> list[dict[str, object]]:
    """Return the ordered per-release window changes behind the router sentences.

    Raises when the release windows stop supporting the three claims the
    subsection makes about them: that no release is followed by a materially
    higher incidence of intermediation, that mean path length is nearly
    unchanged at every release, and that exchange span is the margin that does
    move. Each is a statement about the observed windows, so each is checked.
    """

    windows = routing_window_values(router_windows.to_dict("records"))
    changes = [
        {
            "event": event,
            "event_date": event_date,
            "window_days": days,
            "pre": pre,
            "post": post,
            "intermediated": post["intermediated_share"] - pre["intermediated_share"],
            "legs": post["mean_legs"] - pre["mean_legs"],
            "cross_venue": post["cross_venue_share"] - pre["cross_venue_share"],
        }
        for event, event_date, days, pre, post in windows
    ]
    worst = max(changes, key=lambda change: float(change["intermediated"]))
    if float(worst["intermediated"]) >= ROUTER_MAX_INTERMEDIATION_RISE:
        raise ValueError(
            "intermediation now steps up at a router release: "
            f"{worst['event']} changes by {100 * float(worst['intermediated']):+.2f} pp"
        )
    if sum(1 for change in changes if float(change["intermediated"]) < 0) < 2:
        raise ValueError("intermediation no longer falls at a majority of router releases")
    longest = max(changes, key=lambda change: abs(float(change["legs"])))
    if abs(float(longest["legs"])) >= ROUTER_MAX_LEG_MOVEMENT:
        raise ValueError(
            "mean path length now moves materially at a router release: "
            f"{longest['event']} changes by {float(longest['legs']):+.4f} legs"
        )
    if sum(1 for change in changes if float(change["cross_venue"]) > 0) < 2:
        raise ValueError(
            "exchange span no longer widens at a majority of router releases; the "
            "subsection's integration reading no longer holds"
        )
    return changes


def _pvalue(value: float) -> str:
    coefficient, exponent = f"{value:.2e}".split("e")
    return f"${coefficient}\\times10^{{{int(exponent)}}}$"


def render_presentation_values(
    rotation: pd.DataFrame,
    integration: pd.DataFrame,
    token_integration: pd.DataFrame,
    integration_within_day: pd.DataFrame,
    excess_use: pd.DataFrame,
    excess_use_transition: pd.DataFrame,
    routing_series: pd.DataFrame,
    routing_inference: pd.DataFrame,
    venue_rival: pd.DataFrame,
    route_quality: pd.DataFrame,
    router_windows: pd.DataFrame,
) -> str:
    """Bind display macros to unique rows in the direct exhibits."""

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
    multileg_count = _one(
        rotation,
        baseline_year=2024,
        comparison_year=2026,
        routing_scope="more_than_two_legs",
        weighting="episode",
        value_support="all_routes",
        transformation="share_level",
    )
    multileg_value = _one(
        rotation,
        baseline_year=2024,
        comparison_year=2026,
        routing_scope="more_than_two_legs",
        weighting="value",
        value_support="within_20pct",
        transformation="share_level",
    )
    for row in (count, value, multileg_count, multileg_value):
        _finite(
            row,
            "baseline_daily_mean",
            "comparison_daily_mean",
            "change",
            "hac_standard_error",
            "p_value_holm",
        )

    # Within-day integration gap. Each cell is selected by its full scientific
    # identity rather than by row order, so a count magnitude can never be printed
    # in a value sentence. The count rung is displayed precisely because it does
    # not separate from zero: the standing rule requires the negated side of a
    # "not X, but Y" statement to carry its own interval in the same units.
    def _within_day(weighting: str, spec: str, term: str) -> pd.Series:
        return _one(
            integration_within_day,
            routing_basis=WITHIN_DAY_BASIS,
            value_support=WITHIN_DAY_SUPPORT if weighting == "value" else "all_routes",
            weighting=weighting,
            transformation="share_level",
            spec=spec,
            term=term,
        )

    within_day_value = _within_day("value", "R2 + date FE", "cross_venue")
    within_day_count = _within_day("episode", "R2 + date FE", "cross_venue")
    within_day_weighted = _within_day(
        "value", "R3 + date FE, weighted by cell units", "cross_venue"
    )
    within_day_first = _within_day("value", "R5 + date FE x year", "cross_venue_2020")
    within_day_trough = _within_day("value", "R5 + date FE x year", "cross_venue_2023")
    within_day_last = _within_day("value", "R5 + date FE x year", "cross_venue_2026")
    for row in (
        within_day_value,
        within_day_count,
        within_day_weighted,
        within_day_first,
        within_day_trough,
        within_day_last,
    ):
        _finite(row, "beta", "se", "ci_lower", "ci_upper")
    within_day_days = int(within_day_value["supported_days"])

    # The rival test is the joint statement that every exchange-span by
    # route-complexity cell moves the same way, so the displayed cell is the
    # weakest one and the producer refuses to render a false "all four" claim.
    weakest_count = _weakest_complexity_cell(
        rotation, weighting="episode", value_support="all_routes"
    )
    weakest_value = _weakest_complexity_cell(
        rotation, weighting="value", value_support="within_20pct"
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

    # Venue pricing-family rival. The discriminating scope is the constant-product
    # family, whose invariant is common to every venue in it and unchanged over the
    # sample; Curve is the stable-specialised comparison and identifies no ratio.
    _require_curve_carries_no_intermediation(venue_rival)
    venue_all_base, venue_all_end = _venue_scope_rise(
        venue_rival, scope="all_venues", asset_type="stable"
    )
    venue_cp_base, venue_cp_end = _venue_scope_rise(
        venue_rival, scope="constant_product_only", asset_type="stable"
    )
    _, venue_cp_native_end = _venue_scope_rise(
        venue_rival, scope="constant_product_only", asset_type="native"
    )
    cp_count_change = float(venue_cp_end["vehicle_excess_use_count_ratio"]) - float(
        venue_cp_base["vehicle_excess_use_count_ratio"]
    )
    cp_value_change = float(venue_cp_end["vehicle_excess_use_ratio"]) - float(
        venue_cp_base["vehicle_excess_use_ratio"]
    )
    if cp_count_change <= 0 or cp_value_change <= 0:
        raise ValueError(
            "stable excess use no longer rises in the constant-product scope: "
            f"count {cp_count_change:+.4f}, value {cp_value_change:+.4f}"
        )
    all_value_change = float(venue_all_end["vehicle_excess_use_ratio"]) - float(
        venue_all_base["vehicle_excess_use_ratio"]
    )
    if all_value_change <= 0:
        raise ValueError("stable excess use no longer rises across all venues")
    # The prose states that restricting to the unchanged pricing rule strengthens
    # rather than weakens the value rotation. Refuse the whole macro set if that
    # comparison ever reverses, so the sentence cannot outlive the data.
    if cp_value_change <= all_value_change:
        raise ValueError(
            "the constant-product restriction no longer strengthens the value "
            f"rotation: {cp_value_change:+.4f} against {all_value_change:+.4f}"
        )
    cp_episode_share = float(venue_cp_end["intermediate_routes_support"]) / float(
        venue_all_end["intermediate_routes_support"]
    )
    # Support scale for the Balancer composition diagnostic. The support column is
    # constant within a scope-year, so one row per scope-year carries the count.
    scope_support = (
        venue_rival.loc[venue_rival["asset_type"].eq("stable")]
        .set_index("scope")["intermediate_routes_support"]
        .fillna(0)
    )
    balancer_peak = float(scope_support.loc["balancer_only"].max())
    cp_peak = float(scope_support.loc["constant_product_only"].max())
    if not 0 < balancer_peak < cp_peak:
        raise ValueError(
            "the Balancer diagnostic is no longer small relative to the "
            f"constant-product scope: {balancer_peak:.0f} against {cp_peak:.0f}"
        )

    # Router-release windows. Descriptive market-wide composition either side of a
    # dated public release; there is no untreated group, so nothing here is a
    # treatment effect and the macros carry only levels and observed changes.
    router = _router_window_changes(router_windows)
    router_window_days = {int(change["window_days"]) for change in router}
    if len(router_window_days) != 1:
        raise ValueError("router releases no longer share one window length")
    router_largest_rise = max(float(change["intermediated"]) for change in router)
    router_largest_leg = max(abs(float(change["legs"])) for change in router)

    routes = routing_series.copy()
    route_dates = pd.to_datetime(routes["date"], errors="raise")
    route_start = route_dates.min()
    route_end = route_dates.max()
    if pd.isna(route_start) or pd.isna(route_end):
        raise ValueError("cross-venue routing series lacks a finite sample span")
    if len(route_quality) != 1:
        raise ValueError(
            f"route quality exhibit requires one aggregate row; found {len(route_quality)}"
        )
    quality = route_quality.iloc[0]
    _finite(
        quality,
        "calendar_days",
        "raw_rows",
        "output_rows",
        "missing_sources",
    )
    calendar_days = int(quality["calendar_days"])
    raw_rows = int(quality["raw_rows"])
    usable_legs = int(quality["output_rows"])
    missing_source_days = int(quality["missing_sources"])
    if calendar_days != (route_end - route_start).days + 1:
        raise ValueError(
            "route quality calendar-day count disagrees with the routing-series span"
        )
    if raw_rows <= 0:
        raise ValueError("route quality exhibit lacks a positive raw-swap count")
    route_deployments = len(ROUTE_SOURCE_FAMILIES)
    if route_deployments <= 0:
        raise ValueError("route source registry has no principal-panel deployments")
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
        "% Generated by scripts/tabulate/render_presentation_values.py.",
        "% Generated from the direct exhibit inputs listed in INPUTS.",
        f"\\newcommand{{\\RoutePanelRawSwaps}}{{{raw_rows / 1_000_000:.0f} million}}",
        f"\\newcommand{{\\RoutePanelRawSwapsExact}}{{{raw_rows:,}}}",
        f"\\newcommand{{\\RoutePanelUsableLegsExact}}{{{usable_legs:,}}}",
        f"\\newcommand{{\\RoutePanelMissingSourceDays}}{{{missing_source_days:,}}}",
        f"\\newcommand{{\\RoutePanelCalendarDates}}{{{calendar_days:,}}}",
        f"\\newcommand{{\\RoutePanelDeploymentCount}}{{{route_deployments}}}",
        f"\\newcommand{{\\RoutePanelSpan}}{{{route_start.strftime('%B %Y')}--{route_end.strftime('%B %Y')}}}",
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
        f"\\newcommand{{\\MultiLegCountBase}}{{{_share(float(multileg_count['baseline_daily_mean']))}}}",
        f"\\newcommand{{\\MultiLegCountEnd}}{{{_share(float(multileg_count['comparison_daily_mean']))}}}",
        f"\\newcommand{{\\MultiLegCountChange}}{{{_pp(float(multileg_count['change']), 1)}}}",
        f"\\newcommand{{\\MultiLegCountSE}}{{{_se_pp(float(multileg_count['hac_standard_error']))}}}",
        f"\\newcommand{{\\MultiLegValueBase}}{{{_share(float(multileg_value['baseline_daily_mean']))}}}",
        f"\\newcommand{{\\MultiLegValueEnd}}{{{_share(float(multileg_value['comparison_daily_mean']))}}}",
        f"\\newcommand{{\\MultiLegValueChange}}{{{_pp(float(multileg_value['change']), 1)}}}",
        f"\\newcommand{{\\MultiLegValueSE}}{{{_se_pp(float(multileg_value['hac_standard_error']))}}}",
        f"\\newcommand{{\\WeakestComplexityCountChange}}{{{_pp(float(weakest_count['change']), 1)}}}",
        f"\\newcommand{{\\WeakestComplexityCountSE}}{{{_se_pp(float(weakest_count['hac_standard_error']))}}}",
        f"\\newcommand{{\\WeakestComplexityValueChange}}{{{_pp(float(weakest_value['change']), 1)}}}",
        f"\\newcommand{{\\WeakestComplexityValueSE}}{{{_se_pp(float(weakest_value['hac_standard_error']))}}}",
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
        f"\\newcommand{{\\WithinDayVenueGapValue}}{{{_pp_points(float(within_day_value['beta']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapValueSE}}{{{_se_points(float(within_day_value['se']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapValueCI}}{{{_interval_points(float(within_day_value['ci_lower']), float(within_day_value['ci_upper']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapCount}}{{{_pp_points(float(within_day_count['beta']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapCountSE}}{{{_se_points(float(within_day_count['se']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapCountCI}}{{{_interval_points(float(within_day_count['ci_lower']), float(within_day_count['ci_upper']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapWeighted}}{{{_pp_points(float(within_day_weighted['beta']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapWeightedSE}}{{{_se_points(float(within_day_weighted['se']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapFirst}}{{{_pp_points(float(within_day_first['beta']), 1)}}}",
        f"\\newcommand{{\\WithinDayVenueGapTrough}}{{{_pp_points(float(within_day_trough['beta']), 1)}}}",
        f"\\newcommand{{\\WithinDayVenueGapTroughCI}}{{{_interval_points(float(within_day_trough['ci_lower']), float(within_day_trough['ci_upper']))}}}",
        f"\\newcommand{{\\WithinDayVenueGapLast}}{{{_pp_points(float(within_day_last['beta']), 1)}}}",
        f"\\newcommand{{\\WithinDayVenueGapDays}}{{{within_day_days:,}}}",
        f"\\newcommand{{\\VenueAllStableCountBase}}{{{float(venue_all_base['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueAllStableCountEnd}}{{{float(venue_all_end['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueAllStableValueBase}}{{{float(venue_all_base['vehicle_excess_use_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueAllStableValueEnd}}{{{float(venue_all_end['vehicle_excess_use_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueCPStableCountBase}}{{{float(venue_cp_base['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueCPStableCountEnd}}{{{float(venue_cp_end['vehicle_excess_use_count_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueCPStableValueBase}}{{{float(venue_cp_base['vehicle_excess_use_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueCPStableValueEnd}}{{{float(venue_cp_end['vehicle_excess_use_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueCPNativeValueEnd}}{{{float(venue_cp_native_end['vehicle_excess_use_ratio']):.2f}}}",
        f"\\newcommand{{\\VenueAllStableValueChange}}{{${all_value_change:+.2f}$}}",
        f"\\newcommand{{\\VenueCPStableValueChange}}{{${cp_value_change:+.2f}$}}",
        f"\\newcommand{{\\VenueCPEpisodeShare}}{{{_share(cp_episode_share)}}}",
        f"\\newcommand{{\\VenueBalancerPeakEpisodes}}{{{balancer_peak:,.0f}}}",
        f"\\newcommand{{\\VenueCPPeakEpisodes}}{{{cp_peak:,.0f}}}",
        f"\\newcommand{{\\RouterWindowDays}}{{{router_window_days.pop()}}}",
        f"\\newcommand{{\\RouterReleaseCount}}{{{len(router)}}}",
        f"\\newcommand{{\\RouterIntermediationBase}}{{{_share(float(router[0]['pre']['intermediated_share']))}}}",
        f"\\newcommand{{\\RouterIntermediationEnd}}{{{_share(float(router[-1]['post']['intermediated_share']))}}}",
        f"\\newcommand{{\\RouterIntermediationOne}}{{{_pp(float(router[0]['intermediated']), 1)}}}",
        f"\\newcommand{{\\RouterIntermediationTwo}}{{{_pp(float(router[1]['intermediated']), 1)}}}",
        f"\\newcommand{{\\RouterIntermediationThree}}{{{_pp(float(router[2]['intermediated']), 1)}}}",
        f"\\newcommand{{\\RouterLargestIntermediationRise}}{{{_pp(router_largest_rise, 1)}}}",
        f"\\newcommand{{\\RouterLargestLegMovement}}{{{router_largest_leg:.3f}}}",
        f"\\newcommand{{\\RouterCrossBase}}{{{_share(float(router[0]['pre']['cross_venue_share']))}}}",
        f"\\newcommand{{\\RouterCrossOne}}{{{_pp(float(router[0]['cross_venue']), 1)}}}",
        f"\\newcommand{{\\RouterCrossTwo}}{{{_pp(float(router[1]['cross_venue']), 1)}}}",
        f"\\newcommand{{\\RouterCrossThree}}{{{_pp(float(router[2]['cross_venue']), 1)}}}",
        f"\\newcommand{{\\RouterCrossEnd}}{{{_share(float(router[-1]['post']['cross_venue_share']))}}}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    frames: list[pd.DataFrame] = []
    for path in INPUTS:
        require_presentation_source(path)
        frames.append(pd.read_json(path, lines=True))
    rendered = render_presentation_values(*frames)
    with atomic_output(OUTPUT) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
