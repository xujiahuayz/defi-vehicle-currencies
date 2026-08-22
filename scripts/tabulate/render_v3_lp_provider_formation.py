#!/usr/bin/env python3
"""Render the provider-side rotation and pool-formation evidence."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


DECOMPOSITION_RESULTS = (
    OUTPUT_DIR / "exhibits" / "v3_lp_origin_supply_decomposition.jsonl"
)
DECOMPOSITION_SUPPORT = (
    OUTPUT_DIR / "exhibits" / "v3_lp_origin_supply_support.jsonl"
)
SPECIALIZATION_RESULTS = (
    OUTPUT_DIR / "exhibits" / "v3_lp_provider_specialization_models.jsonl"
)

PRIMARY_FAMILY_ID = "v3_provider_specialization_50000_90d_formation_m1_m4"
BASELINE_PERIOD = "2024H1"
COMPARISON_PERIOD = "2026H1"

TABLE_NOTE = (
    "Panel A decomposes the 2024 H1--2026 H1 change in the stable-facing share "
    "of positive Uniswap V3 liquidity additions on spokes with exactly one of "
    "WETH, DAI, USDC, or USDT. Stable-facing combines DAI, USDC, and USDT. "
    "Vehicle-side USD additions value the amount of the vehicle token; the "
    "fraction excluded for missing prices or implausibly large values is below "
    "1 percent in every period--vehicle cell. Panel B studies the first week in "
    "which a pool reaches \\$50,000 of reported TVL. For each transaction origin "
    "supplying that pool, the dependent variable equals one for the pool's actual "
    "vehicle and zero for the alternatives. Prior supply occurs during the "
    "preceding 90 days and excludes the focal pool and every pool paired with the "
    "focal endpoint. Columns (1)--(2) compare WETH, DAI, USDC, and USDT; columns "
    "(3)--(4) compare DAI, USDC, and USDT during stable-facing pool formation. A "
    "stablecoin core pool pairs two of DAI, USDC, and USDT. Coefficients and "
    "standard errors are in percentage points. Models absorb pool-formation by "
    "transaction-origin and vehicle by calendar-quarter fixed effects. Standard "
    "errors are two-way clustered by pool and transaction origin. Stars use "
    "Holm-adjusted p-values across the four columns: * $p<0.10$, ** $p<0.05$, and "
    "*** $p<0.01$. Transaction origin is a participation proxy, not beneficial "
    "ownership. "
    "The observed pool set supports an associational interpretation because each "
    "market participant's full opportunity set is unobserved."
)


@dataclass(frozen=True)
class DecompositionRow:
    metric: str
    label: str


DECOMPOSITION_ROWS: tuple[DecompositionRow, ...] = (
    DecompositionRow("lp_add_actions", "Liquidity-addition actions"),
    DecompositionRow(
        "screened_candidate_side_usd_flow",
        "Vehicle-side USD additions",
    ),
)


@dataclass(frozen=True)
class ModelColumn:
    model_id: str
    row_label: str


MODEL_COLUMNS: tuple[ModelColumn, ...] = (
    ModelColumn(
        "m1_prior_vehicle_network_indicator",
        "Prior same-vehicle supply outside focal endpoint",
    ),
    ModelColumn(
        "m2_log_prior_vehicle_network_endpoints",
        r"Log prior same-vehicle endpoint breadth, $\ln(1+n)$",
    ),
    ModelColumn(
        "m3_stable_spoke_prior_same_token_core_indicator",
        "Prior same-stablecoin core supply",
    ),
    ModelColumn(
        "m4_stable_spoke_log_prior_same_token_core_pools",
        r"Log prior same-stablecoin core-pool breadth, $\ln(1+n)$",
    ),
)


def _select_one(
    frame: pd.DataFrame,
    selector: dict[str, object],
    *,
    description: str,
) -> pd.Series:
    selected = frame
    for column, expected in selector.items():
        if column not in selected.columns:
            raise ValueError(f"{description} lacks selector column: {column}")
        selected = selected.loc[selected[column].eq(expected)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {description} row for {selector}; found {len(selected)}"
        )
    return selected.iloc[0]


def _stars(adjusted_p_value: float) -> str:
    if adjusted_p_value < 0.01:
        return "^{***}"
    if adjusted_p_value < 0.05:
        return "^{**}"
    if adjusted_p_value < 0.10:
        return "^{*}"
    return ""


def _pp(value: object, *, signed: bool = False) -> str:
    numeric = float(value)
    prefix = "+" if signed and numeric >= 0 else ""
    return f"{prefix}{numeric:.2f}"


def _pct(value: object) -> str:
    return f"{100.0 * float(value):.1f}"


def _int(value: object) -> str:
    return f"{int(round(float(value))):,}"


def _model_cell(row: pd.Series) -> str:
    coefficient_pp = 100.0 * float(row["coefficient"])
    standard_error_pp = 100.0 * float(row["standard_error"])
    adjusted_p = float(row["holm_adjusted_p_value"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${coefficient_pp:+.2f}{_stars(adjusted_p)}$"
        r"\\"
        f"$({standard_error_pp:.2f})$"
        r"\end{tabular}"
    )


def _validate_decomposition(decomposition: pd.DataFrame) -> list[pd.Series]:
    required = {
        "metric",
        "baseline_period",
        "comparison_period",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change_pp",
        "within_continuing_origin_change_pp",
        "continuing_origin_reweighting_pp",
        "period_specific_origin_entry_exit_pp",
        "identity_error",
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(f"V3 provider decomposition lacks columns: {missing}")

    selected: list[pd.Series] = []
    for table_row in DECOMPOSITION_ROWS:
        row = _select_one(
            decomposition,
            {
                "metric": table_row.metric,
                "baseline_period": BASELINE_PERIOD,
                "comparison_period": COMPARISON_PERIOD,
            },
            description="V3 provider decomposition",
        )
        numeric = row[
            [
                "baseline_stable_share",
                "comparison_stable_share",
                "total_change_pp",
                "within_continuing_origin_change_pp",
                "continuing_origin_reweighting_pp",
                "period_specific_origin_entry_exit_pp",
                "identity_error",
            ]
        ].astype(float)
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError("V3 provider decomposition contains nonfinite values")
        if not np.isclose(float(row["identity_error"]), 0.0, atol=1e-10, rtol=0.0):
            raise ValueError("V3 provider decomposition identity does not reconcile")
        selected.append(row)
    return selected


def _validate_support(support: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    required = {
        "record_type",
        "period",
        "vehicle_type",
        "active_origins",
        "flow_reliable",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        raise ValueError(f"V3 provider support lacks columns: {missing}")
    cells: dict[tuple[str, str], pd.Series] = {}
    for period in (BASELINE_PERIOD, COMPARISON_PERIOD):
        for vehicle_type in ("stable", "WETH"):
            row = _select_one(
                support,
                {
                    "record_type": "origin_vehicle_network_and_valuation_support",
                    "period": period,
                    "vehicle_type": vehicle_type,
                },
                description="V3 provider support",
            )
            if not bool(row["flow_reliable"]):
                raise ValueError(
                    "V3 provider USD additions fail the declared valuation bound"
                )
            if not np.isfinite(float(row["active_origins"])):
                raise ValueError("V3 provider support has nonfinite origin counts")
            cells[(period, vehicle_type)] = row
    return cells


def _validate_models(models: pd.DataFrame) -> list[pd.Series]:
    required = {
        "model_id",
        "material_tvl_usd",
        "lookback_days",
        "supply_week_offset",
        "coefficient",
        "standard_error",
        "holm_adjusted_p_value",
        "observations",
        "pool_clusters",
        "transaction_origin_clusters",
        "event_origin_fixed_effects",
        "candidate_quarter_fixed_effects",
        "outcome_mean",
        "inference",
        "family_id",
        "family_size",
        "specification_role",
    }
    missing = sorted(required - set(models.columns))
    if missing:
        raise ValueError(f"V3 provider-formation models lack columns: {missing}")

    selected: list[pd.Series] = []
    for model in MODEL_COLUMNS:
        row = _select_one(
            models,
            {
                "model_id": model.model_id,
                "material_tvl_usd": 50_000.0,
                "lookback_days": 90,
                "supply_week_offset": 0,
                "family_id": PRIMARY_FAMILY_ID,
                "specification_role": "primary",
            },
            description="V3 provider-formation model",
        )
        numeric = row[
            [
                "coefficient",
                "standard_error",
                "holm_adjusted_p_value",
                "observations",
                "pool_clusters",
                "transaction_origin_clusters",
                "event_origin_fixed_effects",
                "candidate_quarter_fixed_effects",
                "outcome_mean",
            ]
        ].astype(float)
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError("V3 provider-formation model contains nonfinite values")
        if int(round(float(row["family_size"]))) != len(MODEL_COLUMNS):
            raise ValueError("V3 provider-formation Holm family must contain four models")
        if row["inference"] != "two_way_pool_and_transaction_origin_clustered":
            raise ValueError("V3 provider-formation model has unexpected inference")
        selected.append(row)
    return selected


def _blank_model_cells() -> list[str]:
    return [""] * len(MODEL_COLUMNS)


def _stat_row(label: str, values: list[str]) -> str:
    return f"{label} & " + " & ".join(values) + r" \\"


def render_v3_lp_provider_formation(
    decomposition: pd.DataFrame,
    support: pd.DataFrame,
    models: pd.DataFrame,
) -> str:
    """Render the two-panel provider-side exhibit from machine-readable results."""

    decomposition_rows = _validate_decomposition(decomposition)
    support_cells = _validate_support(support)
    model_rows = _validate_models(models)

    lines = [
        r"\textit{Panel A. Stable-facing liquidity supply}",
        r"\par\smallskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=2.2\hsize\raggedright\arraybackslash}X*{6}{>{\hsize=0.8\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"& \multicolumn{2}{c}{Stable-facing share [\%]} & \multicolumn{4}{c}{Change [pp]} \\ ",
        r"\cmidrule(lr){2-3}\cmidrule(l){4-7}",
        r"Supply measure & 2024 H1 & 2026 H1 & Total & \shortstack{Within\\continuing origins} & Reallocation & \shortstack{Period-specific\\origins} \\ ",
        r"\midrule",
    ]
    for definition, row in zip(DECOMPOSITION_ROWS, decomposition_rows, strict=True):
        lines.append(
            f"{definition.label} & {_pct(row['baseline_stable_share'])} & "
            f"{_pct(row['comparison_stable_share'])} & "
            f"{_pp(row['total_change_pp'], signed=True)} & "
            f"{_pp(row['within_continuing_origin_change_pp'], signed=True)} & "
            f"{_pp(row['continuing_origin_reweighting_pp'], signed=True)} & "
            f"{_pp(row['period_specific_origin_entry_exit_pp'], signed=True)} "
            + r"\\"
        )
    lines.extend(
        [
            r"\midrule",
            "Active transaction origins, stable-facing & "
            f"{_int(support_cells[(BASELINE_PERIOD, 'stable')]['active_origins'])} & "
            f"{_int(support_cells[(COMPARISON_PERIOD, 'stable')]['active_origins'])} & "
            + " & ".join([""] * 4)
            + r" \\",
            "Active transaction origins, WETH-facing & "
            f"{_int(support_cells[(BASELINE_PERIOD, 'WETH')]['active_origins'])} & "
            f"{_int(support_cells[(COMPARISON_PERIOD, 'WETH')]['active_origins'])} & "
            + " & ".join([""] * 4)
            + r" \\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel B. Prior vehicle experience and pool formation}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.8\hsize\raggedright\arraybackslash}X*{4}{>{\hsize=0.8\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"& (1) & (2) & (3) & (4) \\ ",
            r"Compared vehicles & \multicolumn{2}{c}{WETH, DAI, USDC, USDT} & \multicolumn{2}{c}{DAI, USDC, USDT} \\ ",
            r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
            r"\midrule",
        ]
    )
    for index, model in enumerate(MODEL_COLUMNS):
        values = _blank_model_cells()
        values[index] = _model_cell(model_rows[index])
        lines.append(_stat_row(model.row_label, values))
    lines.extend(
        [
            r"\midrule",
            _stat_row(
                r"Dependent-variable mean [\%]",
                [_pct(row["outcome_mean"]) for row in model_rows],
            ),
            _stat_row(
                "Observations",
                [_int(row["observations"]) for row in model_rows],
            ),
            _stat_row(
                "Pool clusters",
                [_int(row["pool_clusters"]) for row in model_rows],
            ),
            _stat_row(
                "Transaction-origin clusters",
                [_int(row["transaction_origin_clusters"]) for row in model_rows],
            ),
            _stat_row(
                r"Pool formation $\times$ transaction-origin effects",
                ["Yes"] * len(MODEL_COLUMNS),
            ),
            _stat_row(
                r"Vehicle $\times$ calendar-quarter effects",
                ["Yes"] * len(MODEL_COLUMNS),
            ),
            _stat_row(
                "Two-way clustered standard errors",
                ["Pool, origin"] * len(MODEL_COLUMNS),
            ),
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    decomposition = pd.read_json(DECOMPOSITION_RESULTS, lines=True)
    support = pd.read_json(DECOMPOSITION_SUPPORT, lines=True)
    models = pd.read_json(SPECIALIZATION_RESULTS, lines=True)
    write_table_artifacts(
        "v3_lp_provider_formation",
        render_v3_lp_provider_formation(decomposition, support, models),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
