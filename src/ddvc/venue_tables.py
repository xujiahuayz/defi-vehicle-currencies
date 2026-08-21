"""Pure validation and TeX rendering for the venue-coverage and rival-scope tables.

The module owns the appendix venue-coverage table and the Section 5 rival tables
that compare a restricted scope with an unrestricted one: excess use by venue
pricing family, and route structure in symmetric windows around dated public
router releases.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


VENUE_ORDER = (
    "uniswap_v1",
    "uniswap_v2",
    "uniswap_v3",
    "uniswap_v4",
    "sushiswap_v2",
    "sushiswap_v3",
    "curve",
    "balancer",
    "fluid",
)
VENUE_HEADERS = (
    "Uni V1",
    "Uni V2",
    "Uni V3",
    "Uni V4",
    "Sushi V2",
    "Sushi V3",
    "Curve",
    "Balancer",
    "Fluid",
)
DISPLAY_YEARS = tuple(str(year) for year in range(2020, 2027))


def _number(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} is missing or nonnumeric")
    value = float(value)
    if value < 0:
        raise ValueError(f"{field} must be nonnegative")
    return value


def venue_coverage_values(
    rows: Iterable[Mapping[str, object]],
) -> list[tuple[str, list[float]]]:
    """Validate nine-source annual rows and return annual plus pooled shares."""

    selected: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in rows:
        year = str(row.get("year"))
        venue = str(row.get("venue"))
        if year not in DISPLAY_YEARS or venue not in VENUE_ORDER:
            continue
        key = (year, venue)
        if key in selected:
            raise ValueError(f"duplicate venue-coverage row: {year}/{venue}")
        selected[key] = row

    expected = {(year, venue) for year in DISPLAY_YEARS for venue in VENUE_ORDER}
    missing = sorted(expected - set(selected))
    if missing:
        raise ValueError(f"venue-coverage table is missing {missing[0][0]}/{missing[0][1]}")

    rendered: list[tuple[str, list[float]]] = []
    pooled_volume = {venue: 0.0 for venue in VENUE_ORDER}
    for year in DISPLAY_YEARS:
        shares = [_number(selected[(year, venue)], "share_pct") for venue in VENUE_ORDER]
        if abs(sum(shares) - 100.0) > 0.02:
            raise ValueError(f"venue shares do not sum to 100 in {year}: {sum(shares):.6f}")
        rendered.append((year, shares))
        for venue in VENUE_ORDER:
            pooled_volume[venue] += _number(selected[(year, venue)], "usd_volume")

    total_volume = sum(pooled_volume.values())
    if total_volume <= 0:
        raise ValueError("pooled venue volume must be positive")
    pooled = [100.0 * pooled_volume[venue] / total_volume for venue in VENUE_ORDER]
    if abs(sum(pooled) - 100.0) > 1e-8:
        raise ValueError("pooled venue shares do not sum to 100")
    rendered.append(("Pooled", pooled))
    return rendered


def render_venue_coverage(rows: Iterable[Mapping[str, object]]) -> str:
    """Render the 2020--2026 nine-source observed-volume comparison."""

    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lrrrrrrrrr@{}}",
        r"\toprule",
        r"\multicolumn{10}{@{}l}{\emph{Panel A: shares within the nine retained source series}} \\",
        r"\midrule",
        "Year & " + " & ".join(VENUE_HEADERS) + r" \\",
        r"\midrule",
    ]
    values = venue_coverage_values(rows)
    for index, (year, shares) in enumerate(values):
        if year == "Pooled" and index:
            lines.append(r"\midrule")
        lines.append(year + " & " + " & ".join(f"{value:.2f}" for value in shares) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def market_coverage_values(
    rows: Iterable[Mapping[str, object]],
) -> list[tuple[str, float]]:
    """Validate and order the external Ethereum DEX-volume coverage series."""

    selected: dict[int, Mapping[str, object]] = {}
    for row in rows:
        year = row.get("year")
        if year not in range(2020, 2027):
            continue
        if int(year) in selected:
            raise ValueError(f"duplicate market-coverage row: {year}")
        selected[int(year)] = row
    missing = sorted(set(range(2020, 2027)) - set(selected))
    if missing:
        raise ValueError(f"market-coverage table is missing {missing[0]}")
    values: list[tuple[str, float]] = []
    for year in range(2020, 2027):
        row = selected[year]
        share = _number(row, "coverage_share")
        if share > 1:
            raise ValueError(f"market coverage exceeds one in {year}")
        expected_period = "H1" if year == 2026 else "full_year"
        if row.get("period") != expected_period:
            raise ValueError(f"market coverage has the wrong period label in {year}")
        values.append(("2026 H1" if year == 2026 else str(year), 100 * share))
    total_selected = sum(_number(row, "selected_usd") for row in selected.values())
    total_market = sum(_number(row, "ethereum_dex_usd") for row in selected.values())
    if total_market <= 0:
        raise ValueError("pooled market coverage lacks positive volume")
    values.append(("Pooled", 100 * total_selected / total_market))
    return values


def render_market_coverage(rows: Iterable[Mapping[str, object]]) -> str:
    """Render the compact external-volume panel placed below source shares."""

    values = market_coverage_values(rows)
    return "\n".join(
        [
            r"\vspace{0.16cm}",
            r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lrrrrrrrr@{}}",
            r"\multicolumn{9}{@{}l}{\emph{Panel B: selected exchange families as a share of total Ethereum DEX volume}} \\",
            r"\midrule",
            "Period & " + " & ".join(label for label, _value in values) + r" \\",
            r"Share (\%) & " + " & ".join(f"{value:.1f}" for _label, value in values) + r" \\",
            r"\bottomrule",
            r"\end{tabular*}",
        ]
    ) + "\n"


# The pricing-family rival compares scopes in which every leg of a route component
# belongs to one venue family. Curve is carried so that an empty column is visible
# rather than silently dropped: a scope with no intermediary episode identifies no
# ratio, and the table must say so instead of printing a blank cell.
RIVAL_SCOPE_ORDER = ("all_venues", "constant_product_only", "balancer_only", "curve_only")
RIVAL_SCOPE_HEADERS = {
    "all_venues": "All venues",
    "constant_product_only": "Constant product",
    "balancer_only": "Balancer",
    "curve_only": "Curve",
}
RIVAL_ASSET_ORDER = ("stable", "native")
RIVAL_ASSET_HEADERS = {"stable": "Stablecoins", "native": "Native asset"}
# A scope-year identifies no ratio for two economically different reasons, and the
# table states which one applies rather than printing the same blank for both.
NO_ROUTES = "no routes"
NO_INTERMEDIATION = "no intermediation"
SUPPORT_LABELS = {
    "no_intermediation": NO_INTERMEDIATION,
    "no_endpoint_demand": "no endpoint demand",
}


def _ratio(row: Mapping[str, object], field: str) -> float | None:
    """Return a finite positive excess-use ratio, or None when unidentified."""

    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} is nonnumeric")
    value = float(value)
    if not math.isfinite(value):
        return None
    if value < 0:
        raise ValueError(f"{field} must be nonnegative")
    return value


def venue_technology_rival_values(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, list[tuple[str, list[tuple[float, float] | str]]]]:
    """Validate scope-year excess-use rows and order them for display.

    Returns one list of (year, cells) rows per candidate asset type, one cell per
    venue scope in ``RIVAL_SCOPE_ORDER``. An identified cell is a (count, value)
    pair; any other cell is the label naming why that scope-year identifies no
    ratio, so an absent venue is never displayed as an empty one.
    """

    selected: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for row in rows:
        year = str(row.get("year"))
        scope = str(row.get("scope"))
        asset = str(row.get("asset_type"))
        if year not in DISPLAY_YEARS or scope not in RIVAL_SCOPE_ORDER:
            continue
        if asset not in RIVAL_ASSET_ORDER:
            continue
        key = (year, scope, asset)
        if key in selected:
            raise ValueError(f"duplicate venue-rival row: {year}/{scope}/{asset}")
        selected[key] = row

    rendered: dict[str, list[tuple[str, list[tuple[float, float] | str]]]] = {}
    for asset in RIVAL_ASSET_ORDER:
        panel: list[tuple[str, list[tuple[float, float] | str]]] = []
        for year in DISPLAY_YEARS:
            cells: list[tuple[float, float] | str] = []
            for scope in RIVAL_SCOPE_ORDER:
                row = selected.get((year, scope, asset))
                if row is None:
                    # A venue family with no route component that year is absent
                    # from the exhibit; that is not the same as having no
                    # intermediation among the components it does contribute.
                    cells.append(NO_ROUTES)
                    continue
                status = str(row.get("support_status"))
                if status == "identified":
                    count = _ratio(row, "vehicle_excess_use_count_ratio")
                    value = _ratio(row, "vehicle_excess_use_ratio")
                    if count is None or value is None:
                        raise ValueError(
                            f"{year}/{scope}/{asset} is labelled identified but has no ratio"
                        )
                    cells.append((count, value))
                    continue
                if status not in SUPPORT_LABELS:
                    raise ValueError(f"unknown support status {status!r} in {year}/{scope}")
                cells.append(SUPPORT_LABELS[status])
            if all(isinstance(cell, str) for cell in cells):
                raise ValueError(f"venue-rival table has no support in {year} for {asset}")
            panel.append((year, cells))
        if not panel:
            raise ValueError(f"venue-rival table is missing every year for {asset}")
        rendered[asset] = panel
    return rendered


def render_venue_technology_rival(rows: Iterable[Mapping[str, object]]) -> str:
    """Render excess use by venue pricing family, 2020--2026."""

    panels = venue_technology_rival_values(rows)
    columns = "l" + "rr" * len(RIVAL_SCOPE_ORDER)
    group = " & ".join(
        rf"\multicolumn{{2}}{{c}}{{{RIVAL_SCOPE_HEADERS[scope]}}}"
        for scope in RIVAL_SCOPE_ORDER
    )
    spans = " ".join(
        rf"\cmidrule(lr){{{2 * index + 2}-{2 * index + 3}}}"
        for index in range(len(RIVAL_SCOPE_ORDER))
    )
    lines = [
        rf"\begin{{tabular*}}{{\linewidth}}{{@{{\extracolsep{{\fill}}}}{columns}@{{}}}}",
        r"\toprule",
        rf"& {group} \\",
        spans,
        "Year & " + " & ".join(["Count & Value"] * len(RIVAL_SCOPE_ORDER)) + r" \\",
    ]
    for index, asset in enumerate(RIVAL_ASSET_ORDER):
        lines.append(r"\midrule")
        lines.append(
            rf"\multicolumn{{{1 + 2 * len(RIVAL_SCOPE_ORDER)}}}{{@{{}}l}}"
            rf"{{\emph{{Panel {chr(ord('A') + index)}: {RIVAL_ASSET_HEADERS[asset]}}}}} \\"
        )
        for year, cells in panels[asset]:
            rendered_cells: list[str] = []
            for cell in cells:
                if isinstance(cell, str):
                    rendered_cells.append(rf"\multicolumn{{2}}{{c}}{{{cell}}}")
                    continue
                rendered_cells.extend(f"{value:.2f}" for value in cell)
            lines.append(year + " & " + " & ".join(rendered_cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


ROUTER_EVENT_ORDER = (
    "auto_router_v1",
    "cross_version_auto_router",
    "universal_router",
)
ROUTER_EVENT_HEADERS = {
    "auto_router_v1": "Auto Router",
    "cross_version_auto_router": "Cross-version Auto Router",
    "universal_router": "Universal Router",
}
# Displayed route-structure moments. A share is rendered in percentage points; a
# level is a mean per indirect route and keeps two decimals, because the movement
# the subsection reports is of the order of one hundredth of a leg.
ROUTER_MOMENTS = (
    ("economic_multileg_share", "Indirect", "share"),
    ("intermediated_share", "Intermediated", "share"),
    ("cross_venue_share", "Cross-exchange", "share"),
    ("mean_legs", "Legs", "level"),
    ("mean_venues", "Exchanges", "level"),
    ("over_two_legs_share", "Over two legs", "share"),
)
ROUTER_MOMENT_ORDER = tuple(field for field, _label, _kind in ROUTER_MOMENTS)
ROUTER_PERIODS = ("pre", "post")
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def router_event_date_text(iso_date: str) -> str:
    """Render an ISO release date in the manuscript's month-day-year form."""

    year, month, day = (int(part) for part in iso_date.split("-"))
    return f"{MONTH_NAMES[month - 1]} {day}, {year}"


def _finite_moment(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"router window row has nonnumeric {field}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"router window row has non-finite {field}")
    return value


def routing_window_values(
    rows: Iterable[Mapping[str, object]],
) -> list[tuple[str, str, int, dict[str, float], dict[str, float]]]:
    """Validate the symmetric pre/post router-release windows and order them.

    Returns one ``(event, event date, window days, pre, post)`` tuple per release
    in ``ROUTER_EVENT_ORDER``, each period carrying every moment in
    ``ROUTER_MOMENT_ORDER``.

    Two structural facts are enforced rather than asserted downstream. The two
    periods of a release must span the same number of observed calendar days, so
    a change is not a difference in window length. Displayed moments come from
    the balanced five-venue perimeter, which holds the venue set fixed by
    construction. Full-market rows remain in the machine-readable exhibit as a
    sensitivity comparison; they need not equal the balanced rows after V1 is
    admitted to the historical panel, but both scopes must describe the same
    event date and symmetric windows.
    """

    selected: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for row in rows:
        key = (str(row.get("event")), str(row.get("period")), str(row.get("scope")))
        if key[0] not in ROUTER_EVENT_ORDER or key[1] not in ROUTER_PERIODS:
            continue
        if key[2] not in ("full", "balanced"):
            continue
        if key in selected:
            raise ValueError(f"duplicate router window row: {'/'.join(key)}")
        selected[key] = row

    ordered: list[tuple[str, str, int, dict[str, float], dict[str, float]]] = []
    for event in ROUTER_EVENT_ORDER:
        periods: list[dict[str, float]] = []
        calendar_days: set[int] = set()
        event_dates: set[str] = set()
        window_days: set[int] = set()
        for period in ROUTER_PERIODS:
            row = selected.get((event, period, "full"))
            balanced = selected.get((event, period, "balanced"))
            if row is None or balanced is None:
                raise ValueError(f"router window exhibit lacks {event} {period}")
            for field in ("calendar_days", "window_days"):
                if int(row.get(field, 0)) != int(balanced.get(field, 0)):
                    raise ValueError(
                        f"router window {event} {period} disagrees across scopes on {field}"
                    )
            full_event_date = str(row.get("event_date"))[:10]
            balanced_event_date = str(balanced.get("event_date"))[:10]
            if full_event_date != balanced_event_date:
                raise ValueError(
                    f"router window {event} {period} disagrees across scopes on event_date"
                )
            moments = {
                field: _finite_moment(balanced, field)
                for field in ROUTER_MOMENT_ORDER
            }
            days = int(balanced.get("calendar_days", 0))
            if days <= 0:
                raise ValueError(f"router window {event} {period} observes no day")
            calendar_days.add(days)
            event_dates.add(balanced_event_date)
            window_days.add(int(balanced.get("window_days", 0)))
            periods.append(moments)
        if len(calendar_days) != 1:
            raise ValueError(
                f"router windows around {event} span unequal observed calendars: "
                f"{sorted(calendar_days)}"
            )
        if len(event_dates) != 1 or len(window_days) != 1:
            raise ValueError(f"router windows around {event} disagree on their definition")
        ordered.append(
            (event, event_dates.pop(), calendar_days.pop(), periods[0], periods[1])
        )
    return ordered


def render_routing_technology_windows(rows: Iterable[Mapping[str, object]]) -> str:
    """Render route structure before and after each public router release."""

    windows = routing_window_values(rows)
    headers = [label for _field, label, _kind in ROUTER_MOMENTS]
    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}l" + "r" * len(headers) + r"@{}}",
        r"\toprule",
        "& " + " & ".join(headers) + r" \\",
    ]

    def cell(value: float, kind: str, *, signed: bool) -> str:
        if kind == "share":
            rendered = f"{100 * value:+.1f}" if signed else f"{100 * value:.1f}"
        else:
            rendered = f"{value:+.2f}" if signed else f"{value:.2f}"
        return f"${rendered}$" if signed else rendered

    for index, (event, event_date, days, pre, post) in enumerate(windows):
        lines.append(r"\midrule")
        lines.append(
            rf"\multicolumn{{{1 + len(headers)}}}{{@{{}}l}}{{\emph{{Panel "
            rf"{chr(ord('A') + index)}: {ROUTER_EVENT_HEADERS[event]}, "
            rf"{router_event_date_text(event_date)} ({days} days each side)}}}} \\"
        )
        for label, moments in (("Before", pre), ("After", post)):
            lines.append(
                label
                + " & "
                + " & ".join(
                    cell(moments[field], kind, signed=False)
                    for field, _label, kind in ROUTER_MOMENTS
                )
                + r" \\"
            )
        lines.append(
            "Change & "
            + " & ".join(
                cell(post[field] - pre[field], kind, signed=True)
                for field, _label, kind in ROUTER_MOMENTS
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"
