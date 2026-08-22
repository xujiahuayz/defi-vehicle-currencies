#!/usr/bin/env python3
"""Render the primary stablecoin-circulation and LP estimates."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits/stablecoin_supply_lp_models.jsonl"


def _row(results: pd.DataFrame, model_id: str) -> pd.Series:
    selected = results[
        results["record_type"].eq("stablecoin_supply_lp_coefficient")
        & results["model_id"].eq(model_id)
        & results["predictor"].eq("supply_growth_per_10pct")
        & results["supply_measure"].eq("asset_wide")
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one primary stablecoin-supply row for {model_id}")
    row = selected.iloc[0]
    if int(row["family_hypotheses"]) != 4 or pd.isna(row["p_value_holm"]):
        raise ValueError(f"primary multiplicity fields are missing for {model_id}")
    return row


def _cell(estimate: float, standard_error: float, digits: int) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${estimate:+.{digits}f}$"
        r"\\"
        f"$({standard_error:.{digits}f})$"
        r"\end{tabular}"
    )


def _p(value: object) -> str:
    return f"{float(value):.3f}"


def _n(value: object) -> str:
    return f"{int(value):,}"


def render_stablecoin_supply_lp(results: pd.DataFrame) -> str:
    core_capital = _row(results, "capital_growth_stable_core_asset_wide_supply")
    spoke_capital = _row(results, "capital_growth_stable_spoke_asset_wide_supply")
    core_formation = _row(results, "formation_stable_core_asset_wide_supply")
    spoke_formation = _row(results, "formation_stable_spoke_asset_wide_supply")

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xcc@{}}",
        r"\toprule",
        r" & Stablecoin core & Stablecoin spoke \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. Next-month log capital growth}} \\",
        r"Circulating-supply growth [per 10\%] & "
        + _cell(float(core_capital["coefficient"]), float(core_capital["standard_error"]), 4)
        + " & "
        + _cell(float(spoke_capital["coefficient"]), float(spoke_capital["standard_error"]), 4)
        + r" \\",
        "Holm-adjusted $p$-value & "
        + _p(core_capital["p_value_holm"])
        + " & "
        + _p(spoke_capital["p_value_holm"])
        + r" \\",
        "Observations & "
        + _n(core_capital["observations"])
        + " & "
        + _n(spoke_capital["observations"])
        + r" \\",
        r"\addlinespace",
        r"\multicolumn{3}{@{}l}{\textit{Panel B. First material link in the next month}} \\",
        r"Circulating-supply growth [pp per 10\%] & "
        + _cell(
            float(core_formation["coefficient_pp"]),
            float(core_formation["standard_error_pp"]),
            4,
        )
        + " & "
        + _cell(
            float(spoke_formation["coefficient_pp"]),
            float(spoke_formation["standard_error_pp"]),
            4,
        )
        + r" \\",
        "Holm-adjusted $p$-value & "
        + _p(core_formation["p_value_holm"])
        + " & "
        + _p(spoke_formation["p_value_holm"])
        + r" \\",
        "Observations & "
        + _n(core_formation["observations"])
        + " & "
        + _n(spoke_formation["observations"])
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "stablecoin_supply_lp",
        render_stablecoin_supply_lp(results),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
