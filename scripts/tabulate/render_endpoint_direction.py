#!/usr/bin/env python3
"""Render endpoint-direction and stable-intermediary contributions."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


ENDPOINT = OUTPUT_DIR / "exhibits/endpoint_direction_decomposition.jsonl"
STABLE = OUTPUT_DIR / "exhibits/stable_stable_vehicle_decomposition.jsonl"
ROBUSTNESS = OUTPUT_DIR / "exhibits/stable_stable_vehicle_robustness.jsonl"


def _pp(value: object) -> str:
    return f"{100.0 * float(value):+.1f}"


def _one(frame: pd.DataFrame, **selectors: object) -> pd.Series:
    selected = frame.copy()
    for column, value in selectors.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {selectors}, found {len(selected)}")
    return selected.iloc[0]


def render_table(
    endpoint: pd.DataFrame,
    stable: pd.DataFrame,
    robustness: pd.DataFrame,
) -> str:
    """Return a compact two-panel contribution table."""

    if set(endpoint["common_calendar_days"]) != {181}:
        raise ValueError("endpoint-direction table requires 181 common days")
    if set(stable["common_calendar_days"]) != {181}:
        raise ValueError("stable-intermediary table requires 181 common days")
    if set(robustness["common_calendar_days"]) != {181}:
        raise ValueError("stable-intermediary robustness requires 181 common days")

    metric_names = {
        "count_share": "Route count",
        "strict_intermediation_value_share": "Routed value",
    }
    channels = (
        ("All other pairs", ("other_endpoints",)),
        ("One native, one stable endpoint", ("native_to_stable", "stable_to_native")),
        ("Two stable endpoints", ("stable_to_stable",)),
    )

    channel_values: dict[str, list[float]] = {}
    totals: list[float] = []
    for metric in metric_names:
        rows = endpoint[endpoint["metric"].eq(metric)]
        if len(rows) != 5:
            raise ValueError(f"expected five endpoint groups for {metric}")
        totals.append(float(rows["overall_stable_share_change"].iloc[0]))
        for label, groups in channels:
            value = float(
                rows.loc[
                    rows["endpoint_group"].isin(groups),
                    "stable_share_contribution_change",
                ].sum()
            )
            channel_values.setdefault(label, []).append(value)

    stable_values: dict[str, list[float]] = {}
    for metric in metric_names:
        rows = stable[stable["metric"].eq(metric)]
        if set(rows["intermediary_group"]) != {
            "native",
            "usdt",
            "usdc",
            "dai",
            "other_stable",
        }:
            raise ValueError(f"stable-intermediary groups are incomplete for {metric}")
        usdt = _one(rows, intermediary_group="usdt")
        other = rows[rows["intermediary_group"].isin({"usdc", "dai", "other_stable"})]
        stable_values.setdefault("USDT", []).append(
            float(usdt["stable_share_contribution_change"])
        )
        stable_values.setdefault("USDC, DAI, and other stablecoins", []).append(
            float(other["stable_share_contribution_change"].sum())
        )

    value_robustness = robustness[
        robustness["metric"].eq("strict_intermediation_value_share")
    ].set_index("year")
    if set(value_robustness.index) != {2024, 2026}:
        raise ValueError("stable-intermediary robustness lacks an endpoint year")
    trimmed = float(
        value_robustness.loc[2026, "top_decile_trimmed_mean_stable_contribution"]
        - value_robustness.loc[2024, "top_decile_trimmed_mean_stable_contribution"]
    )
    pooled = float(
        value_robustness.loc[2026, "pooled_mass_stable_contribution"]
        - value_robustness.loc[2024, "pooled_mass_stable_contribution"]
    )

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrr@{}}",
        r"\toprule",
        rf" & {metric_names['count_share']} [pp] & {metric_names['strict_intermediation_value_share']} [pp] \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. Contribution by endpoint direction}} \\",
    ]
    for label, values in channel_values.items():
        lines.append(f"{label} & {_pp(values[0])} & {_pp(values[1])} \\\\")
    lines.extend(
        [
            r"\midrule",
            f"Total stablecoin-share change & {_pp(totals[0])} & {_pp(totals[1])} \\\\",
            r"\addlinespace[0.6em]",
            r"\multicolumn{3}{@{}l}{\textit{Panel B. Stablecoin identity within two-stable-endpoint pairs}} \\",
        ]
    )
    for label, values in stable_values.items():
        lines.append(f"{label} & {_pp(values[0])} & {_pp(values[1])} \\\\")
    stable_totals = [
        sum(values[index] for values in stable_values.values()) for index in range(2)
    ]
    lines.extend(
        [
            r"\midrule",
            f"All stablecoin intermediaries & {_pp(stable_totals[0])} & {_pp(stable_totals[1])} \\\\",
            f"Top-decile-trimmed daily mean & -- & {_pp(trimmed)} \\\\",
            f"Pooled route-value weighting & -- & {_pp(pooled)} \\\\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    endpoint = pd.read_json(ENDPOINT, lines=True)
    stable = pd.read_json(STABLE, lines=True)
    robustness = pd.read_json(ROBUSTNESS, lines=True)
    write_table_artifacts(
        "endpoint_direction",
        render_table(endpoint, stable, robustness),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
