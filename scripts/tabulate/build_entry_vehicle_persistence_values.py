#!/usr/bin/env python3
"""Build paper and deck macros for post-entry vehicle persistence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


MODELS = OUTPUT_DIR / "exhibits" / "entry_vehicle_persistence_models.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "entry_vehicle_persistence_support.jsonl"
VALUES = OUTPUT_DIR / "exhibits" / "entry_vehicle_persistence_values.tex"
CONTROLS = (
    "is_2026,stable_endpoint,log_entry_routes,"
    "entry_direct_share,entry_complex_share"
)


@dataclass(frozen=True)
class ValueSpec:
    key: str
    model_id: str
    table_id: str
    window_id: str
    weighting: str
    minimum_entry_routes: int | None
    retrading_required: bool


CONTROLLED_SPECS: tuple[ValueSpec, ...] = (
    ValueSpec(
        "early_pair",
        "m2_early_pair_controls",
        "post_entry_stable_share",
        "days_1_30",
        "equal_pair",
        1,
        True,
    ),
    ValueSpec(
        "early_activity",
        "m3_early_activity_controls",
        "post_entry_stable_share",
        "days_1_30",
        "post_entry_route_activity",
        1,
        True,
    ),
    ValueSpec(
        "late_pair",
        "m5_late_pair_controls",
        "post_entry_stable_share",
        "days_31_120",
        "equal_pair",
        1,
        True,
    ),
    ValueSpec(
        "late_activity",
        "m6_late_activity_controls",
        "post_entry_stable_share",
        "days_31_120",
        "post_entry_route_activity",
        1,
        True,
    ),
)

RETRADE_SPECS: tuple[ValueSpec, ...] = (
    ValueSpec(
        "early_retrade",
        "r1_early_retrade_controls",
        "post_entry_retrade_probability",
        "days_1_30",
        "equal_pair",
        None,
        False,
    ),
    ValueSpec(
        "late_retrade",
        "r2_late_retrade_controls",
        "post_entry_retrade_probability",
        "days_31_120",
        "equal_pair",
        None,
        False,
    ),
)

ROBUSTNESS_SPECS: tuple[ValueSpec, ...] = (
    ValueSpec(
        "early_min_five",
        "m7_early_pair_controls_min5",
        "post_entry_stable_share",
        "days_1_30",
        "equal_pair",
        5,
        True,
    ),
    ValueSpec(
        "early_min_ten",
        "m8_early_pair_controls_min10",
        "post_entry_stable_share",
        "days_1_30",
        "equal_pair",
        10,
        True,
    ),
    ValueSpec(
        "late_min_five",
        "m9_late_pair_controls_min5",
        "post_entry_stable_share",
        "days_31_120",
        "equal_pair",
        5,
        True,
    ),
    ValueSpec(
        "late_min_ten",
        "m10_late_pair_controls_min10",
        "post_entry_stable_share",
        "days_31_120",
        "equal_pair",
        10,
        True,
    ),
)

VALUE_SPECS = (*CONTROLLED_SPECS, *RETRADE_SPECS, *ROBUSTNESS_SPECS)


def _one_model(models: pd.DataFrame, spec: ValueSpec) -> pd.Series:
    selected = models[
        models["model_id"].eq(spec.model_id)
        & models["predictor"].eq("entry_stable_share")
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one entry-stable-share row for {spec.model_id}; "
            f"found {len(selected)}"
        )
    return selected.iloc[0]


def _one_support(support: pd.DataFrame, window_id: str) -> pd.Series:
    selected = support[
        support["window_id"].eq(window_id)
        & support["entry_year"].astype(str).eq("all")
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one pooled support row for {window_id}; found {len(selected)}"
        )
    return selected.iloc[0]


def _validate(
    models: pd.DataFrame,
    support: pd.DataFrame,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    required_models = {
        "record_type",
        "table_id",
        "model_id",
        "window_id",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "effect_pp_per_10pp",
        "standard_error_pp_per_10pp",
        "observations",
        "entry_date_clusters",
        "weighting",
        "minimum_entry_routes",
        "controls_included",
        "controls",
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
        raise ValueError(f"persistence models lack columns: {missing_models}")
    if missing_support:
        raise ValueError(f"persistence support lacks columns: {missing_support}")

    rows = {spec.key: _one_model(models, spec) for spec in VALUE_SPECS}
    supports = {
        window_id: _one_support(support, window_id)
        for window_id in ("days_1_30", "days_31_120")
    }
    for spec in VALUE_SPECS:
        row = rows[spec.key]
        expected_record_type = (
            "post_entry_retrade_model_coefficient"
            if not spec.retrading_required
            else "post_entry_persistence_model_coefficient"
        )
        expected = {
            "record_type": expected_record_type,
            "table_id": spec.table_id,
            "window_id": spec.window_id,
            "weighting": spec.weighting,
            "covariance_id": "entry_date_cluster_cr1",
            "common_entry_calendar_cutoff_mm_dd": "03-02",
            "inference_status": "provisional_descriptive",
            "outcome": (
                "post_stable_share"
                if spec.retrading_required
                else "retraded"
            ),
        }
        for field, value in expected.items():
            if str(row[field]) != value:
                raise ValueError(f"{spec.model_id} has unexpected {field}")
        if not bool(row["controls_included"]):
            raise ValueError(f"{spec.model_id} must include the declared controls")
        if str(row["controls"]) != CONTROLS:
            raise ValueError(f"{spec.model_id} has the wrong control set")
        if bool(row["retrading_required"]) != spec.retrading_required:
            raise ValueError(f"{spec.model_id} has the wrong retrading sample")
        if not bool(row["entry_day_excluded"]):
            raise ValueError(f"{spec.model_id} includes the entry day")
        if int(row["complete_through_day"]) != 120:
            raise ValueError(f"{spec.model_id} lacks complete 120-day follow-up")
        if spec.minimum_entry_routes is not None and int(
            row["minimum_entry_routes"]
        ) != spec.minimum_entry_routes:
            raise ValueError(f"{spec.model_id} has the wrong entry-route threshold")

        reported = np.asarray(
            [
                row["coefficient"],
                row["standard_error"],
                row["effect_pp_per_10pp"],
                row["standard_error_pp_per_10pp"],
                row["observations"],
                row["entry_date_clusters"],
            ],
            dtype=float,
        )
        if not np.isfinite(reported).all() or float(row["standard_error"]) < 0:
            raise ValueError(f"{spec.model_id} has a nonfinite estimate")
        if not np.isclose(
            float(row["effect_pp_per_10pp"]),
            10.0 * float(row["coefficient"]),
        ) or not np.isclose(
            float(row["standard_error_pp_per_10pp"]),
            10.0 * float(row["standard_error"]),
        ):
            raise ValueError(f"{spec.model_id} has inconsistent percentage-point scaling")
        if int(row["observations"]) <= 0 or int(row["entry_date_clusters"]) <= 0:
            raise ValueError(f"{spec.model_id} has invalid sample counts")

    for window_id, pooled in supports.items():
        if (
            not bool(pooled["entry_day_excluded"])
            or int(pooled["complete_through_day"]) != 120
            or str(pooled["common_entry_calendar_cutoff_mm_dd"]) != "03-02"
        ):
            raise ValueError(f"{window_id} support has inconsistent sample construction")
        rate = float(pooled["retrade_rate"])
        eligible = int(pooled["eligible_pairs"])
        retrading = int(pooled["retrading_pairs"])
        if eligible <= 0 or retrading < 0 or retrading > eligible:
            raise ValueError(f"{window_id} support has invalid pair counts")
        if not np.isclose(rate, retrading / eligible):
            raise ValueError(f"{window_id} support has an inconsistent retrading rate")

        pair_key = "early_pair" if window_id == "days_1_30" else "late_pair"
        activity_key = (
            "early_activity" if window_id == "days_1_30" else "late_activity"
        )
        retrade_key = (
            "early_retrade" if window_id == "days_1_30" else "late_retrade"
        )
        for key in (pair_key, activity_key):
            row = rows[key]
            if (
                int(row["observations"]) != retrading
                or int(row["eligible_pairs"]) != eligible
                or int(row["retrading_pairs"]) != retrading
            ):
                raise ValueError(f"{key} and pooled support disagree on pair counts")
        retrade_row = rows[retrade_key]
        if (
            int(retrade_row["observations"]) != eligible
            or int(retrade_row["eligible_pairs"]) != eligible
            or int(retrade_row["retrading_pairs"]) != retrading
            or not np.isclose(float(retrade_row["retrade_rate"]), rate)
        ):
            raise ValueError(
                f"{retrade_key} and pooled support disagree on pair counts"
            )

    if int(rows["early_pair"]["entry_date_clusters"]) != int(
        rows["late_pair"]["entry_date_clusters"]
    ):
        raise ValueError("controlled pair models disagree on entry-date clusters")
    return rows, supports


def _signed_pp(value: object) -> str:
    value = float(value)
    if abs(value) < 0.005:
        return "$0.00$ pp"
    return f"${value:+.2f}$ pp"


def _unsigned_pp(value: object) -> str:
    return f"${float(value):.2f}$ pp"


def _percent(value: object) -> str:
    return f"{100.0 * float(value):.1f}\\%"


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}".replace(",", "{,}")


def render_entry_vehicle_persistence_values(
    models: pd.DataFrame,
    support: pd.DataFrame,
) -> str:
    """Render macros from the controlled estimates and pooled support rows."""

    rows, supports = _validate(models, support)

    def estimate_macros(prefix: str, key: str) -> list[str]:
        row = rows[key]
        return [
            f"\\newcommand{{\\{prefix}EffectPerTen}}{{{_signed_pp(row['effect_pp_per_10pp'])}}}",
            f"\\newcommand{{\\{prefix}SEPerTen}}{{{_unsigned_pp(row['standard_error_pp_per_10pp'])}}}",
        ]

    lines = [
        "% Generated by scripts/tabulate/build_entry_vehicle_persistence_values.py; do not edit.",
        "% Effects report the percentage-point outcome change for 10 pp higher entry stablecoin share.",
        *estimate_macros("EntryPersistenceEarlyPair", "early_pair"),
        *estimate_macros("EntryPersistenceEarlyActivity", "early_activity"),
        *estimate_macros("EntryPersistenceLatePair", "late_pair"),
        *estimate_macros("EntryPersistenceLateActivity", "late_activity"),
        f"\\newcommand{{\\EntryPersistenceEarlyRetradeRate}}{{{_percent(supports['days_1_30']['retrade_rate'])}}}",
        f"\\newcommand{{\\EntryPersistenceLateRetradeRate}}{{{_percent(supports['days_31_120']['retrade_rate'])}}}",
        *estimate_macros("EntryPersistenceEarlyRetrade", "early_retrade"),
        *estimate_macros("EntryPersistenceLateRetrade", "late_retrade"),
        f"\\newcommand{{\\EntryPersistenceEntrants}}{{{_integer(supports['days_1_30']['eligible_pairs'])}}}",
        f"\\newcommand{{\\EntryPersistenceEarlyPairs}}{{{_integer(rows['early_pair']['observations'])}}}",
        f"\\newcommand{{\\EntryPersistenceLatePairs}}{{{_integer(rows['late_pair']['observations'])}}}",
        f"\\newcommand{{\\EntryPersistenceEntryDates}}{{{_integer(rows['early_pair']['entry_date_clusters'])}}}",
        *estimate_macros("EntryPersistenceEarlyMinFive", "early_min_five"),
        *estimate_macros("EntryPersistenceEarlyMinTen", "early_min_ten"),
        *estimate_macros("EntryPersistenceLateMinFive", "late_min_five"),
        *estimate_macros("EntryPersistenceLateMinTen", "late_min_ten"),
        f"\\newcommand{{\\EntryPersistenceEarlyMinFivePairs}}{{{_integer(rows['early_min_five']['observations'])}}}",
        f"\\newcommand{{\\EntryPersistenceEarlyMinTenPairs}}{{{_integer(rows['early_min_ten']['observations'])}}}",
        f"\\newcommand{{\\EntryPersistenceLateMinFivePairs}}{{{_integer(rows['late_min_five']['observations'])}}}",
        f"\\newcommand{{\\EntryPersistenceLateMinTenPairs}}{{{_integer(rows['late_min_ten']['observations'])}}}",
        "",
    ]
    return "\n".join(lines)


def run(
    *,
    models_path: Path = MODELS,
    support_path: Path = SUPPORT,
    values_path: Path = VALUES,
) -> int:
    rendered = render_entry_vehicle_persistence_values(
        pd.read_json(models_path, lines=True),
        pd.read_json(support_path, lines=True),
    )
    with atomic_output(values_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    print(f"wrote {values_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=MODELS)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--values", type=Path, default=VALUES)
    args = parser.parse_args()
    return run(
        models_path=args.models,
        support_path=args.support,
        values_path=args.values,
    )


if __name__ == "__main__":
    raise SystemExit(main())
