"""Pure validation and TeX rendering for the venue-coverage and venue-rival tables."""

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
