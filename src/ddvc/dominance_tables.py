"""Pure selectors and TeX renderers for the manuscript's dominance tables."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


NEWCOMMAND = re.compile(
    r"^\\newcommand\{\\(?P<name>[A-Za-z]+)\}\{(?P<value>.*)\}$"
)


def _unique(
    rows: Iterable[Mapping[str, object]],
    *,
    name: str,
    **criteria: object,
) -> Mapping[str, object]:
    selected = [
        row
        for row in rows
        if all(row.get(field) == expected for field, expected in criteria.items())
    ]
    if len(selected) != 1:
        description = ", ".join(f"{field}={value}" for field, value in criteria.items())
        raise ValueError(f"{name} requires exactly one row ({description}); found {len(selected)}")
    return selected[0]


def _number(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} is missing or nonnumeric")
    return float(value)


def parse_newcommands(text: str) -> dict[str, str]:
    """Read one-line generated LaTeX macros without evaluating TeX."""

    macros: dict[str, str] = {}
    for line in text.splitlines():
        match = NEWCOMMAND.match(line.strip())
        if match:
            name = match.group("name")
            if name in macros:
                raise ValueError(f"duplicate generated macro: {name}")
            macros[name] = match.group("value")
    return macros


def _require_macros(macros: Mapping[str, str], names: Iterable[str]) -> None:
    missing = sorted(set(names) - set(macros))
    if missing:
        raise ValueError(f"generated presentation macros are missing: {', '.join(missing)}")


def _pct(value: float, digits: int = 1) -> str:
    return f"{100 * value:.{digits}f}\\%"


def _signed_pp(value: float, digits: int = 1) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-digits):
        points = 0.0
    return f"${points:+.{digits}f}$"


def _unsigned_pp(value: float, digits: int = 2) -> str:
    return f"${100 * value:.{digits}f}$"


def _without_pp(value: str) -> str:
    """Remove a presentation macro's trailing unit when the table declares it."""

    return re.sub(r"\s+pp$", "", value.strip())


def _estimate_se_pp(row: Mapping[str, object]) -> str:
    estimate = 100 * _number(row, "coefficient")
    standard_error = 100 * _number(row, "standard_error")
    return "$" + f"{estimate:+.2f}\\ ({standard_error:.2f})$"


def render_dominance_rotation(rows: Iterable[Mapping[str, object]]) -> str:
    """Render the two-leg count and dollar-weighted endpoint-year estimates."""

    records = list(rows)
    common = {
        "baseline_year": 2024,
        "comparison_year": 2026,
        "routing_scope": "two_leg",
        "share_denominator": "native_plus_stable",
        "transformation": "share_level",
    }
    count = _unique(
        records,
        name="dominance rotation count estimate",
        **common,
        weighting="episode",
        value_support="all_routes",
    )
    value = _unique(
        records,
        name="dominance rotation value estimate",
        **common,
        weighting="value",
        value_support="within_20pct",
    )
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrr@{}}",
        r"\toprule",
        r"Stablecoin share among native and stable intermediaries & 2024 & 2026 & Change [pp] (s.e.) \\",
        r"\midrule",
        "Route count & "
        + _pct(_number(count, "baseline_daily_mean"))
        + " & "
        + _pct(_number(count, "comparison_daily_mean"))
        + " & "
        + _signed_pp(_number(count, "change"))
        + r" ("
        + _unsigned_pp(_number(count, "hac_standard_error"))
        + r") \\",
        r"Dollar-weighted routes (20\% agreement) & "
        + _pct(_number(value, "baseline_daily_mean"))
        + " & "
        + _pct(_number(value, "comparison_daily_mean"))
        + " & "
        + _signed_pp(_number(value, "change"))
        + r" ("
        + _unsigned_pp(_number(value, "hac_standard_error"))
        + r") \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines) + "\n"


PAIR_ACCOUNTING_MACROS = (
    "MarketSupportBridge",
    "VehicleRoleSupportBridge",
    "MarketActivityReweight",
    "VehicleIncidenceReweight",
    "WithinPairStableShare",
    "MarketBridgeTotal",
    # The midpoint common/exclusive identity, reported for both measures. Its
    # count terms were previously prose-only even though Section 3.2 interprets
    # each of them, and its row labels must stay distinguishable from the
    # Shapley bridge above: the two factorisations decompose the same route-count
    # total over different mass (all market activity against native-plus-stable
    # choice mass), so no component of one equals a component of the other.
    "PairPooledWithin",
    "PairPooledReweight",
    "PairPooledSupportMass",
    "PairPooledExclusive",
    "PairPooledTotal",
    "PairValueWithin",
    "PairValueReweight",
    "PairValueSupportMass",
    "PairValueExclusive",
    "PairValueTotal",
    "MarginWithinGainPairs",
    "MarginWithinLossPairs",
    "MarginWithinGrossUp",
    "MarginWithinGrossDown",
    "MarginWithinValueGainPairs",
    "MarginWithinValueLossPairs",
    "MarginWithinValueGrossUp",
    "MarginWithinValueGrossDown",
)


def render_pair_composition(
    macros: Mapping[str, str],
    fixed_effect_rows: Iterable[Mapping[str, object]],
) -> str:
    """Render accounting panels and the three fixed-effect regression rows."""

    _require_macros(macros, PAIR_ACCOUNTING_MACROS)
    records = list(fixed_effect_rows)
    display = {name: _without_pp(value) for name, value in macros.items()}
    common = {
        "baseline_year": 2024,
        "comparison_year": 2026,
        "estimator_id": "weighted_stable_share_saturated_pair_month_day_scope_fe_v1",
        "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
        "estimand_scope": "common_pair_month_day_realised_integration_scope",
        "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
    }
    regressions = [
        (
            "All two-leg routes, count share",
            _unique(records, name="all-route count fixed effect", **common, metric="count_share"),
        ),
        (
            r"20\% agreement sample, count share",
            _unique(
                records,
                name="supported count fixed effect",
                **common,
                metric="matched_strict_count_share",
            ),
        ),
        (
            r"20\% agreement sample, dollar-weighted share",
            _unique(
                records,
                name="supported value fixed effect",
                **common,
                metric="strict_intermediation_value_share",
            ),
        ),
    ]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr@{}}",
        r"\toprule",
        r"Component or estimate & Estimate [pp] & Obs. \\",
        r"\midrule",
        r"\multicolumn{3}{l}{\emph{Panel A. Route-count share: market activity and"
        r" vehicle incidence}} \\",
        f"Ultimate pairs entering or leaving the sample & {display['MarketSupportBridge']} & \\\\",
        f"Ultimate pairs gaining or losing a vehicle route & {display['VehicleRoleSupportBridge']} & \\\\",
        f"Market activity shifting across continuing ultimate pairs & {display['MarketActivityReweight']} & \\\\",
        f"Change in how often continuing ultimate pairs use a vehicle & {display['VehicleIncidenceReweight']} & \\\\",
        f"Stablecoin share within continuing vehicle-using ultimate pairs & {display['WithinPairStableShare']} & \\\\",
        r"\midrule",
        f"Total route-count change & {display['MarketBridgeTotal']} & \\\\",
        r"\addlinespace",
        r"\multicolumn{3}{l}{\emph{Panel B. Route-count share: continuing and"
        r" year-specific ultimate pairs}} \\",
        f"Net stablecoin-share change within continuing ultimate pairs & {display['PairPooledWithin']} & \\\\",
        r"\quad Ultimate pairs moving toward stablecoins ("
        + display["MarginWithinGainPairs"]
        + f") & {display['MarginWithinGrossUp']} & \\\\",
        r"\quad Ultimate pairs moving toward native assets ("
        + display["MarginWithinLossPairs"]
        + f") & {display['MarginWithinGrossDown']} & \\\\",
        f"Vehicle activity shifting across continuing ultimate pairs & {display['PairPooledReweight']} & \\\\",
        f"Weight of continuing versus year-specific ultimate pairs & {display['PairPooledSupportMass']} & \\\\",
        f"Ultimate pairs traded in only one year & {display['PairPooledExclusive']} & \\\\",
        r"\midrule",
        f"Total route-count change & {display['PairPooledTotal']} & \\\\",
        r"\addlinespace",
        r"\multicolumn{3}{l}{\emph{Panel C. Dollar-weighted share: continuing and"
        r" year-specific ultimate pairs}} \\",
        f"Net stablecoin-share change within continuing ultimate pairs & {display['PairValueWithin']} & \\\\",
        r"\quad Ultimate pairs moving toward stablecoins ("
        + display["MarginWithinValueGainPairs"]
        + f") & {display['MarginWithinValueGrossUp']} & \\\\",
        r"\quad Ultimate pairs moving toward native assets ("
        + display["MarginWithinValueLossPairs"]
        + f") & {display['MarginWithinValueGrossDown']} & \\\\",
        f"Vehicle activity shifting across continuing ultimate pairs & {display['PairValueReweight']} & \\\\",
        f"Weight of continuing versus year-specific ultimate pairs & {display['PairValueSupportMass']} & \\\\",
        f"Ultimate pairs traded in only one year & {display['PairValueExclusive']} & \\\\",
        r"\midrule",
        f"Total change in dollar-weighted share & {display['PairValueTotal']} & \\\\",
        r"\addlinespace",
        r"\multicolumn{3}{l}{\emph{Panel D. Matched ordered ultimate-pair estimates}} \\",
        r"\midrule",
    ]
    for label, row in regressions:
        lines.append(
            f"{label} & {_estimate_se_pp(row)}"
            f" & {int(_number(row, 'observations')):,} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}"])
    return "\n".join(lines) + "\n"


USDT_TABLE_MACROS = (
    "USDTCountExcessBase",
    "USDTCountExcessEnd",
    "USDTValueExcessBase",
    "USDTValueExcessEnd",
    "USDTEndpointGapBase",
    "USDTEndpointGapEnd",
)


def render_usdt_transition(macros: Mapping[str, str]) -> str:
    """Render the current USDT route-endpoint presentation table."""

    _require_macros(macros, USDT_TABLE_MACROS)
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr@{}}",
        r"\toprule",
        r" & 2024 & 2026 \\",
        r"\midrule",
        "Count excess-use ratio (2024 full year; 2026 January--June) & "
        + macros["USDTCountExcessBase"]
        + " & "
        + macros["USDTCountExcessEnd"]
        + r" \\",
        "Value-weighted excess-use ratio (2024 full year; 2026 January--June) & "
        + macros["USDTValueExcessBase"]
        + " & "
        + macros["USDTValueExcessEnd"]
        + r" \\",
        "Paired January--June intermediary minus route-endpoint share [pp] & "
        + _without_pp(macros["USDTEndpointGapBase"])
        + " & "
        + _without_pp(macros["USDTEndpointGapEnd"])
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines) + "\n"
