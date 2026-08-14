"""Pure validation and TeX rendering for the venue-coverage table."""

from __future__ import annotations

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
    """Validate eight-venue annual rows and return annual plus pooled shares."""

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
    """Render the 2020--2026 eight-venue market-coverage comparison."""

    lines = [
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lrrrrrrrr@{}}",
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
