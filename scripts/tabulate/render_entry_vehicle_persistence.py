#!/usr/bin/env python3
"""Render post-entry vehicle persistence and subsequent-trading regressions."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


MODELS = OUTPUT_DIR / "exhibits" / "entry_vehicle_persistence_models.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "entry_vehicle_persistence_support.jsonl"


@dataclass(frozen=True)
class PersistenceColumn:
    model_id: str
    window_id: str
    controls: bool
    activity_weighted: bool


MAIN_COLUMNS: tuple[PersistenceColumn, ...] = (
    PersistenceColumn("m1_early_pair", "days_1_30", False, False),
    PersistenceColumn("m2_early_pair_controls", "days_1_30", True, False),
    PersistenceColumn("m3_early_activity_controls", "days_1_30", True, True),
    PersistenceColumn("m4_late_pair", "days_31_120", False, False),
    PersistenceColumn("m5_late_pair_controls", "days_31_120", True, False),
    PersistenceColumn("m6_late_activity_controls", "days_31_120", True, True),
)

RETRADE_COLUMNS: tuple[PersistenceColumn, ...] = (
    PersistenceColumn("r1_early_retrade_controls", "days_1_30", True, False),
    PersistenceColumn("r2_late_retrade_controls", "days_31_120", True, False),
)

ROBUSTNESS_COLUMNS: tuple[PersistenceColumn, ...] = (
    PersistenceColumn("m7_early_pair_controls_min5", "days_1_30", True, False),
    PersistenceColumn("m8_early_pair_controls_min10", "days_1_30", True, False),
    PersistenceColumn("m9_late_pair_controls_min5", "days_31_120", True, False),
    PersistenceColumn("m10_late_pair_controls_min10", "days_31_120", True, False),
)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def _select_model(models: pd.DataFrame, model_id: str) -> pd.Series:
    selected = models[
        models["model_id"].eq(model_id)
        & models["predictor"].eq("entry_stable_share")
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one entry-stable-share row for {model_id}; found {len(selected)}"
        )
    return selected.iloc[0]


def _select_support(support: pd.DataFrame, window_id: str) -> pd.Series:
    selected = support[
        support["window_id"].eq(window_id)
        & support["entry_year"].astype(str).eq("all")
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one pooled support row for {window_id}; found {len(selected)}"
        )
    return selected.iloc[0]


def _validate_inputs(
    models: pd.DataFrame,
    support: pd.DataFrame,
    declared: tuple[PersistenceColumn, ...],
) -> None:
    required_models = {
        "record_type",
        "table_id",
        "model_id",
        "window_id",
        "predictor",
        "effect_pp_per_10pp",
        "standard_error_pp_per_10pp",
        "p_value",
        "observations",
        "entry_date_clusters",
        "r_squared",
        "dependent_mean",
        "weighting",
        "minimum_entry_routes",
        "controls_included",
        "covariance_id",
        "eligible_pairs",
        "retrading_pairs",
        "retrade_rate",
        "common_entry_calendar_cutoff_mm_dd",
        "entry_day_excluded",
        "retrading_required",
        "complete_through_day",
        "inference_status",
    }
    required_support = {
        "record_type",
        "window_id",
        "entry_year",
        "eligible_pairs",
        "retrading_pairs",
        "retrade_rate",
        "common_entry_calendar_cutoff_mm_dd",
        "entry_day_excluded",
        "complete_through_day",
    }
    missing_models = sorted(required_models - set(models.columns))
    missing_support = sorted(required_support - set(support.columns))
    if missing_models:
        raise ValueError(f"persistence results lack required columns: {missing_models}")
    if missing_support:
        raise ValueError(f"persistence support lacks required columns: {missing_support}")

    selected = pd.DataFrame(
        [_select_model(models, column.model_id) for column in declared]
    )
    if not selected["entry_day_excluded"].astype(bool).all():
        raise ValueError("post-entry outcomes must exclude the entry day")
    if not selected["complete_through_day"].eq(120).all():
        raise ValueError("post-entry outcomes require complete 120-day follow-up")
    if not selected["common_entry_calendar_cutoff_mm_dd"].eq("03-02").all():
        raise ValueError("post-entry cohorts must share the March 2 cutoff")
    if not selected["covariance_id"].eq("entry_date_cluster_cr1").all():
        raise ValueError("persistence regressions require entry-date CR1 covariance")
    if not selected["inference_status"].eq("provisional_descriptive").all():
        raise ValueError("persistence table requires descriptive estimates")

    main_ids = {
        column.model_id
        for column in declared
        if column not in RETRADE_COLUMNS
    }
    main = selected[selected["model_id"].isin(main_ids)]
    retrade = selected[
        selected["model_id"].isin(
            {
                column.model_id
                for column in declared
                if column in RETRADE_COLUMNS
            }
        )
    ]
    if not main["retrading_required"].astype(bool).all():
        raise ValueError("stable-share regressions must condition on subsequent trading")
    if retrade["retrading_required"].astype(bool).any():
        raise ValueError("subsequent-trading regressions must retain all entrants")

    for column in declared:
        row = _select_model(models, column.model_id)
        if str(row["window_id"]) != column.window_id:
            raise ValueError(f"{column.model_id} has the wrong follow-up window")
        if bool(row["controls_included"]) != column.controls:
            raise ValueError(f"{column.model_id} has the wrong control set")
        expected_weighting = (
            "post_entry_route_activity" if column.activity_weighted else "equal_pair"
        )
        if str(row["weighting"]) != expected_weighting:
            raise ValueError(f"{column.model_id} has the wrong weighting")

    for window_id in ("days_1_30", "days_31_120"):
        pooled = _select_support(support, window_id)
        if not bool(pooled["entry_day_excluded"]):
            raise ValueError("persistence support must exclude the entry day")
        if int(pooled["complete_through_day"]) != 120:
            raise ValueError("persistence support requires 120 complete days")
        if str(pooled["common_entry_calendar_cutoff_mm_dd"]) != "03-02":
            raise ValueError("persistence support must use the March 2 cutoff")
        model_id = (
            "m2_early_pair_controls"
            if window_id == "days_1_30"
            else "m5_late_pair_controls"
        )
        if model_id in {column.model_id for column in declared}:
            main_row = _select_model(models, model_id)
            for field in ("eligible_pairs", "retrading_pairs"):
                if int(main_row[field]) != int(pooled[field]):
                    raise ValueError(
                        f"persistence model and support disagree on {field}"
                    )
            if (
                abs(
                    float(main_row["retrade_rate"])
                    - float(pooled["retrade_rate"])
                )
                > 1e-12
            ):
                raise ValueError(
                    "persistence model and support disagree on retrading rate"
                )


def _estimate_cell(row: pd.Series) -> str:
    effect = float(row["effect_pp_per_10pp"])
    standard_error = float(row["standard_error_pp_per_10pp"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.2f})$"
        r"\end{tabular}"
    )


def _cells(rows: list[pd.Series], formatter) -> str:
    return " & ".join(formatter(row) for row in rows)


def _yes_no(value: object) -> str:
    return "Yes" if bool(value) else "No"


def _main_panel(models: pd.DataFrame) -> str:
    selected = [_select_model(models, column.model_id) for column in MAIN_COLUMNS]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.6\hsize\raggedright\arraybackslash}X*{6}{>{\hsize=.9\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{7}{@{}l}{\textit{Panel A. Stablecoin route share among pairs that trade again}} \\",
        r" & \multicolumn{3}{c}{Days 1--30} & \multicolumn{3}{c}{Days 31--120} \\",
        r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
        r" & (1) & (2) & (3) & (4) & (5) & (6) \\",
        r"\midrule",
        "Entry stablecoin share [effect pp per 10 pp] & "
        + _cells(selected, _estimate_cell)
        + r" \\",
        r"\addlinespace",
        "Controls & "
        + _cells(selected, lambda row: _yes_no(row["controls_included"]))
        + r" \\",
        "Route-activity weights & "
        + _cells(
            selected,
            lambda row: "Yes"
            if str(row["weighting"]) == "post_entry_route_activity"
            else "No",
        )
        + r" \\",
        "Observations (pairs) & "
        + _cells(selected, lambda row: _integer(row["observations"]))
        + r" \\",
        "Entry-date clusters & "
        + _cells(selected, lambda row: _integer(row["entry_date_clusters"]))
        + r" \\",
        "Mean stablecoin share [pp] & "
        + _cells(selected, lambda row: f"{100.0 * float(row['dependent_mean']):.2f}")
        + r" \\",
        r"$R^2$ & "
        + _cells(selected, lambda row: f"{float(row['r_squared']):.3f}")
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines)


def _retrade_panel(models: pd.DataFrame) -> str:
    selected = [_select_model(models, column.model_id) for column in RETRADE_COLUMNS]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.8\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=.6\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{3}{@{}l}{\textit{Panel B. Subsequent-trading incidence among all entrants}} \\",
        r" & Days 1--30 & Days 31--120 \\",
        r"\midrule",
        "Entry stablecoin share [effect pp per 10 pp] & "
        + _cells(selected, _estimate_cell)
        + r" \\",
        "Controls & "
        + _cells(selected, lambda row: _yes_no(row["controls_included"]))
        + r" \\",
        "Observations (pairs) & "
        + _cells(selected, lambda row: _integer(row["observations"]))
        + r" \\",
        "Entry-date clusters & "
        + _cells(selected, lambda row: _integer(row["entry_date_clusters"]))
        + r" \\",
        "Mean retrading rate [pp] & "
        + _cells(selected, lambda row: f"{100.0 * float(row['dependent_mean']):.2f}")
        + r" \\",
        r"$R^2$ & "
        + _cells(selected, lambda row: f"{float(row['r_squared']):.3f}")
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines)


def _robustness_panel(models: pd.DataFrame) -> str:
    selected = [_select_model(models, column.model_id) for column in ROBUSTNESS_COLUMNS]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.6\hsize\raggedright\arraybackslash}X*{4}{>{\hsize=.85\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{5}{@{}l}{\textit{Stablecoin route share among entrants with greater first-day activity}} \\",
        r" & \multicolumn{2}{c}{Days 1--30} & \multicolumn{2}{c}{Days 31--120} \\",
        r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
        r"Minimum first-day routes & 5 & 10 & 5 & 10 \\",
        r"\midrule",
        "Entry stablecoin share [effect pp per 10 pp] & "
        + _cells(selected, _estimate_cell)
        + r" \\",
        "Observations (retrading pairs) & "
        + _cells(selected, lambda row: _integer(row["observations"]))
        + r" \\",
        "Eligible entrants & "
        + _cells(selected, lambda row: _integer(row["eligible_pairs"]))
        + r" \\",
        "Entry-date clusters & "
        + _cells(selected, lambda row: _integer(row["entry_date_clusters"]))
        + r" \\",
        r"Pair controls and equal-pair weights & \multicolumn{4}{c}{Yes} \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return "\n".join(lines)


def render_entry_vehicle_persistence(
    models: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Render the main post-entry share and retrading-incidence estimates."""

    _validate_inputs(models, support, (*MAIN_COLUMNS, *RETRADE_COLUMNS))
    return "\n\n\\vspace{0.65em}\n\n".join(
        (
            _main_panel(models),
            _retrade_panel(models),
        )
    ) + "\n"


def render_entry_vehicle_persistence_robustness(
    models: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Render first-day route-count threshold checks."""

    _validate_inputs(models, support, ROBUSTNESS_COLUMNS)
    return _robustness_panel(models) + "\n"


def main() -> int:
    models = pd.read_json(MODELS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "entry_vehicle_persistence",
        render_entry_vehicle_persistence(models, support),
        preview_width="8.5in",
    )
    write_table_artifacts(
        "entry_vehicle_persistence_robustness",
        render_entry_vehicle_persistence_robustness(models, support),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
