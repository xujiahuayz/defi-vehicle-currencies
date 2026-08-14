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


def _estimate_se_pp(row: Mapping[str, object]) -> str:
    estimate = 100 * _number(row, "coefficient")
    standard_error = 100 * _number(row, "standard_error")
    return "$" + f"{estimate:+.2f}\\ ({standard_error:.2f})$"


def render_dominance_rotation(rows: Iterable[Mapping[str, object]]) -> str:
    """Render the two-leg count and supported-value endpoint-year estimates."""

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
        r"Stable share among native and stable vehicles & 2024 & 2026 & Change (s.e.) \\",
        r"\midrule",
        "Route count & "
        + _pct(_number(count, "baseline_daily_mean"))
        + " & "
        + _pct(_number(count, "comparison_daily_mean"))
        + " & "
        + _signed_pp(_number(count, "change"))
        + r" pp ("
        + _unsigned_pp(_number(count, "hac_standard_error"))
        + r" pp) \\",
        r"Supported routed value (20\% agreement) & "
        + _pct(_number(value, "baseline_daily_mean"))
        + " & "
        + _pct(_number(value, "comparison_daily_mean"))
        + " & "
        + _signed_pp(_number(value, "change"))
        + r" pp ("
        + _unsigned_pp(_number(value, "hac_standard_error"))
        + r" pp) \\",
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
    "PairValueWithin",
    "PairValueReweight",
    "PairValueSupportMass",
    "PairValueExclusive",
    "PairValueTotal",
)


def render_pair_composition(
    macros: Mapping[str, str],
    fixed_effect_rows: Iterable[Mapping[str, object]],
) -> str:
    """Render accounting panels and the three fixed-effect regression rows."""

    _require_macros(macros, PAIR_ACCOUNTING_MACROS)
    records = list(fixed_effect_rows)
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
            r"20\% agreement sample, supported-value share",
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
        r"Component or specification & Estimate (clustered s.e.) & Obs. \\",
        r"\midrule",
        r"\multicolumn{3}{l}{\emph{Panel A. Route-count share: five-factor allocation}} \\",
        f"Pairs entering or leaving the sample & {macros['MarketSupportBridge']} & \\\\",
        f"Pairs gaining or losing a vehicle route & {macros['VehicleRoleSupportBridge']} & \\\\",
        f"Trading shifts across continuing pairs & {macros['MarketActivityReweight']} & \\\\",
        f"Change in how often continuing pairs use a vehicle & {macros['VehicleIncidenceReweight']} & \\\\",
        f"Stablecoin share within continuing vehicle-using pairs & {macros['WithinPairStableShare']} & \\\\",
        r"\midrule",
        f"Total route-count change & {macros['MarketBridgeTotal']} & \\\\",
        r"\addlinespace",
        r"\multicolumn{3}{l}{\emph{Panel B. Supported-value share: pair accounting}} \\",
        f"Stablecoin share within continuing pairs & {macros['PairValueWithin']} & \\\\",
        f"Trading shifts across continuing pairs & {macros['PairValueReweight']} & \\\\",
        f"Weight of continuing versus year-specific pairs & {macros['PairValueSupportMass']} & \\\\",
        f"Pairs entering or leaving the sample & {macros['PairValueExclusive']} & \\\\",
        r"\midrule",
        f"Total supported-value change & {macros['PairValueTotal']} & \\\\",
        r"\addlinespace",
        r"\multicolumn{3}{l}{\emph{Panel C. Ordered-pair $\times$ month-day $\times$ realised-scope fixed-effect regressions}} \\",
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
    """Render the provisional USDT endpoint-year presentation binding."""

    _require_macros(macros, USDT_TABLE_MACROS)
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr@{}}",
        r"\toprule",
        r" & 2024 & 2026 \\",
        r"\midrule",
        f"Count excess use & {macros['USDTCountExcessBase']} & {macros['USDTCountExcessEnd']} \\\\",
        f"Value-weighted excess use & {macros['USDTValueExcessBase']} & {macros['USDTValueExcessEnd']} \\\\",
        "Value-weighted intermediary minus endpoint share & "
        + macros["USDTEndpointGapBase"]
        + " & "
        + macros["USDTEndpointGapEnd"]
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines) + "\n"
