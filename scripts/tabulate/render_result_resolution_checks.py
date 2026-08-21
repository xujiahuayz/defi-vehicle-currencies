#!/usr/bin/env python3
"""Render the adjacent-window, endpoint-unit, and priced-challenger checks."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


ADJACENT = OUTPUT_DIR / "exhibits/vehicle_transition_adjacent_year_decomposition.jsonl"
ENDPOINT = OUTPUT_DIR / "exhibits/vehicle_transition_nonvehicle_endpoint_decomposition.jsonl"
PRICE = OUTPUT_DIR / "exhibits/entry_vehicle_exact_price_alignment.jsonl"
VALUES = OUTPUT_DIR / "exhibits/result_resolution_values.tex"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _pp(value: float) -> str:
    return f"${float(value) * 100:+.1f}$"


def _pct(value: float) -> str:
    return f"{float(value) * 100:.1f}"


def _integer(value: object) -> str:
    return f"{int(value):,}".replace(",", "{,}")


def _validate_decomposition(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
        "identity_error",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} decomposition lacks columns: {missing}")
    if pd.to_numeric(frame["identity_error"], errors="raise").abs().max() > 1e-9:
        raise ValueError(f"{label} decomposition identity does not close")
    return frame


def render_adjacent_year_rotation(results: pd.DataFrame) -> str:
    data = _validate_decomposition(results, label="adjacent-year")
    data = data[
        data["metric"].eq("count_share")
        & data["reporting_scope"].eq("pooled")
    ].sort_values("baseline_year", kind="stable")
    if data.empty:
        raise ValueError("adjacent-year count decomposition is empty")
    pairs = list(
        zip(data["baseline_year"].astype(int), data["comparison_year"].astype(int))
    )
    if any(end != start + 1 for start, end in pairs):
        raise ValueError("adjacent-year table contains a nonconsecutive comparison")
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}l*{5}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"H1 comparison & Total & Within pair & Trading reallocation & Support shift & Pair entry/exit \\",
        r"\midrule",
    ]
    for row in data.itertuples(index=False):
        lines.append(
            f"{int(row.baseline_year)}--{int(row.comparison_year)} & "
            f"{_pp(row.total_change)} & {_pp(row.within_common)} & "
            f"{_pp(row.common_pair_reweighting)} & {_pp(row.common_support_mass)} & "
            f"{_pp(row.exclusive_pair_contribution)} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def render_nonvehicle_endpoint_rotation(results: pd.DataFrame) -> str:
    data = _validate_decomposition(results, label="nonvehicle-endpoint")
    data = data[data["reporting_scope"].eq("pooled")]
    rows = (
        ("Route count", _single(data, metric="count_share")),
        ("Supported value", _single(data, metric="strict_intermediation_value_share")),
    )
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{7}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r" & 2024 H1 & 2026 H1 & Total & Within pair & Trading reallocation & Support shift & Pair entry/exit \\",
        r"\midrule",
    ]
    for label, row in rows:
        lines.append(
            f"{label} & {_pct(row['baseline_stable_share'])} & "
            f"{_pct(row['comparison_stable_share'])} & {_pp(row['total_change'])} & "
            f"{_pp(row['within_common'])} & {_pp(row['common_pair_reweighting'])} & "
            f"{_pp(row['common_support_mass'])} & {_pp(row['exclusive_pair_contribution'])} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def _alignment_cell(row: pd.Series) -> str:
    return rf"{_pct(row['incumbent_vehicle_share'])} [{_integer(row['observations'])}]"


def render_entry_price_alignment(results: pd.DataFrame) -> str:
    data = results[
        results["record_type"].eq("entry_price_leader_alignment")
        & results["horizon_days"].eq(120)
    ]
    if data.empty:
        raise ValueError("120-day entry-price alignment is empty")
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{4}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r" & \multicolumn{2}{c}{Route weighted} & \multicolumn{2}{c}{Pair-day weighted} \\",
        r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
        r"Vehicle at pair entry & Incumbent leads & Challenger leads & Incumbent leads & Challenger leads \\",
        r"\midrule",
    ]
    labels = (("All pairs", "pooled"), ("Native", "native"), ("Stablecoin", "stable"))
    for label, entry_type in labels:
        cells = []
        for weighting in ("route", "pair_day"):
            for relation in ("incumbent", "challenger"):
                cells.append(
                    _alignment_cell(
                        _single(
                            data,
                            weighting=weighting,
                            entry_vehicle_type=entry_type,
                            price_leader_relation=relation,
                        )
                    )
                )
        lines.append(
            f"{label} & " + " & ".join(cells) + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def render_rotation_values(
    adjacent: pd.DataFrame,
    endpoint: pd.DataFrame,
) -> list[str]:
    adjacent_count = _validate_decomposition(adjacent, label="adjacent-year")
    adjacent_count = adjacent_count[
        adjacent_count["metric"].eq("count_share")
        & adjacent_count["reporting_scope"].eq("pooled")
    ]
    largest_increase = adjacent_count.loc[adjacent_count["total_change"].idxmax()]
    largest_decline = adjacent_count.loc[adjacent_count["total_change"].idxmin()]
    smallest_within = adjacent_count.loc[adjacent_count["within_common"].idxmin()]
    largest_within = adjacent_count.loc[adjacent_count["within_common"].idxmax()]
    endpoint_data = _validate_decomposition(endpoint, label="nonvehicle-endpoint")
    endpoint_count = _single(
        endpoint_data, metric="count_share", reporting_scope="pooled"
    )
    endpoint_value = _single(
        endpoint_data,
        metric="strict_intermediation_value_share",
        reporting_scope="pooled",
    )
    return [
        "% Generated by scripts/tabulate/render_result_resolution_checks.py; do not edit.",
        f"\\newcommand{{\\AdjacentLargestIncreaseYears}}{{{int(largest_increase['baseline_year'])}--{int(largest_increase['comparison_year'])}}}",
        f"\\newcommand{{\\AdjacentLargestIncrease}}{{{_pp(largest_increase['total_change'])} pp}}",
        f"\\newcommand{{\\AdjacentLargestDeclineYears}}{{{int(largest_decline['baseline_year'])}--{int(largest_decline['comparison_year'])}}}",
        f"\\newcommand{{\\AdjacentLargestDecline}}{{{_pp(largest_decline['total_change'])} pp}}",
        f"\\newcommand{{\\AdjacentWithinMin}}{{{_pp(smallest_within['within_common'])} pp}}",
        f"\\newcommand{{\\AdjacentWithinMax}}{{{_pp(largest_within['within_common'])} pp}}",
        f"\\newcommand{{\\NonvehicleEndpointStableBase}}{{{_pct(endpoint_count['baseline_stable_share'])}\\%}}",
        f"\\newcommand{{\\NonvehicleEndpointStableEnd}}{{{_pct(endpoint_count['comparison_stable_share'])}\\%}}",
        f"\\newcommand{{\\NonvehicleEndpointStableChange}}{{{_pp(endpoint_count['total_change'])} pp}}",
        f"\\newcommand{{\\NonvehicleEndpointCountExclusive}}{{{_pp(endpoint_count['exclusive_pair_contribution'])} pp}}",
        f"\\newcommand{{\\NonvehicleEndpointValueBase}}{{{_pct(endpoint_value['baseline_stable_share'])}\\%}}",
        f"\\newcommand{{\\NonvehicleEndpointValueEnd}}{{{_pct(endpoint_value['comparison_stable_share'])}\\%}}",
        f"\\newcommand{{\\NonvehicleEndpointValueChange}}{{{_pp(endpoint_value['total_change'])} pp}}",
        f"\\newcommand{{\\NonvehicleEndpointValueExclusive}}{{{_pp(endpoint_value['exclusive_pair_contribution'])} pp}}",
    ]


def render_values(
    adjacent: pd.DataFrame,
    endpoint: pd.DataFrame,
    price: pd.DataFrame,
) -> str:
    challenger = _single(
        price,
        record_type="entry_price_leader_alignment",
        horizon_days=120,
        weighting="route",
        entry_vehicle_type="pooled",
        price_leader_relation="challenger",
    )
    incumbent = _single(
        price,
        record_type="entry_price_leader_alignment",
        horizon_days=120,
        weighting="route",
        entry_vehicle_type="pooled",
        price_leader_relation="incumbent",
    )
    lines = render_rotation_values(adjacent, endpoint)
    lines.extend([
        f"\\newcommand{{\\PriceChallengerIncumbentRetention}}{{{_pct(challenger['incumbent_vehicle_share'])}\\%}}",
        f"\\newcommand{{\\PriceChallengerRoutes}}{{{_integer(challenger['observations'])}}}",
        f"\\newcommand{{\\PriceChallengerPairs}}{{{_integer(challenger['pairs'])}}}",
        f"\\newcommand{{\\PriceIncumbentLeaderRetention}}{{{_pct(incumbent['incumbent_vehicle_share'])}\\%}}",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    adjacent = pd.read_json(ADJACENT, lines=True)
    endpoint = pd.read_json(ENDPOINT, lines=True)
    price = pd.read_json(PRICE, lines=True)
    write_table_artifacts(
        "adjacent_year_vehicle_rotation",
        render_adjacent_year_rotation(adjacent),
        preview_width="7.5in",
    )
    write_table_artifacts(
        "nonvehicle_endpoint_rotation",
        render_nonvehicle_endpoint_rotation(endpoint),
        preview_width="7.5in",
    )
    write_table_artifacts(
        "entry_vehicle_price_alignment",
        render_entry_price_alignment(price),
        preview_width="7.5in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(render_values(adjacent, endpoint, price), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
