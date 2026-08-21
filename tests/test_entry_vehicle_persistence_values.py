from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_entry_vehicle_persistence_values import (
    CONTROLS,
    VALUE_SPECS,
    render_entry_vehicle_persistence_values,
)


def _models() -> pd.DataFrame:
    effects = {
        "early_pair": (8.92, 0.15),
        "early_activity": (8.55, 0.72),
        "late_pair": (8.40, 0.18),
        "late_activity": (9.00, 0.50),
        "early_retrade": (0.30, 0.08),
        "late_retrade": (0.98, 0.08),
        "early_min_five": (9.70, 0.19),
        "early_min_ten": (9.65, 0.32),
        "late_min_five": (9.31, 0.44),
        "late_min_ten": (9.35, 0.60),
    }
    robustness_counts = {
        "early_min_five": (2_192, 1_629, 115),
        "early_min_ten": (775, 671, 93),
        "late_min_five": (2_192, 885, 100),
        "late_min_ten": (775, 452, 80),
    }
    rows: list[dict[str, object]] = []
    for spec in VALUE_SPECS:
        effect, standard_error_effect = effects[spec.key]
        late = spec.window_id == "days_31_120"
        pooled_retraders = 19_405 if late else 30_547
        pooled_eligible = 157_262
        if spec.key in robustness_counts:
            eligible, retraders, clusters = robustness_counts[spec.key]
        else:
            eligible, retraders, clusters = (
                pooled_eligible,
                pooled_retraders,
                123,
            )
        observations = eligible if not spec.retrading_required else retraders
        rows.append(
            {
                "record_type": (
                    "post_entry_persistence_model_coefficient"
                    if spec.retrading_required
                    else "post_entry_retrade_model_coefficient"
                ),
                "table_id": spec.table_id,
                "model_id": spec.model_id,
                "window_id": spec.window_id,
                "outcome": (
                    "post_stable_share"
                    if spec.retrading_required
                    else "retraded"
                ),
                "predictor": "entry_stable_share",
                "coefficient": effect / 10.0,
                "standard_error": standard_error_effect / 10.0,
                "effect_pp_per_10pp": effect,
                "standard_error_pp_per_10pp": standard_error_effect,
                "observations": observations,
                "entry_date_clusters": clusters,
                "weighting": spec.weighting,
                "minimum_entry_routes": spec.minimum_entry_routes,
                "controls_included": True,
                "controls": CONTROLS,
                "covariance_id": "entry_date_cluster_cr1",
                "eligible_pairs": eligible,
                "retrading_pairs": retraders,
                "retrade_rate": retraders / eligible,
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "entry_day_excluded": True,
                "retrading_required": spec.retrading_required,
                "complete_through_day": 120,
                "inference_status": "provisional_descriptive",
            }
        )
    return pd.DataFrame(rows)


def _support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "post_entry_persistence_support",
                "window_id": window_id,
                "entry_year": "all",
                "eligible_pairs": 157_262,
                "retrading_pairs": retraders,
                "retrade_rate": retraders / 157_262,
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "entry_day_excluded": True,
                "complete_through_day": 120,
            }
            for window_id, retraders in (
                ("days_1_30", 30_547),
                ("days_31_120", 19_405),
            )
        ]
    )


def test_persistence_values_bind_main_retrade_and_robustness_estimates() -> None:
    rendered = render_entry_vehicle_persistence_values(_models(), _support())

    expected = {
        "EntryPersistenceEarlyPairEffectPerTen": "$+8.92$ pp",
        "EntryPersistenceEarlyActivityEffectPerTen": "$+8.55$ pp",
        "EntryPersistenceLatePairEffectPerTen": "$+8.40$ pp",
        "EntryPersistenceLateActivityEffectPerTen": "$+9.00$ pp",
        "EntryPersistenceEarlyRetradeRate": r"19.4\%",
        "EntryPersistenceLateRetradeRate": r"12.3\%",
        "EntryPersistenceEarlyRetradeEffectPerTen": "$+0.30$ pp",
        "EntryPersistenceLateRetradeEffectPerTen": "$+0.98$ pp",
        "EntryPersistenceEntrants": r"157{,}262",
        "EntryPersistenceEarlyPairs": r"30{,}547",
        "EntryPersistenceLatePairs": r"19{,}405",
        "EntryPersistenceEntryDates": "123",
        "EntryPersistenceEarlyMinFiveEffectPerTen": "$+9.70$ pp",
        "EntryPersistenceEarlyMinTenEffectPerTen": "$+9.65$ pp",
        "EntryPersistenceLateMinFiveEffectPerTen": "$+9.31$ pp",
        "EntryPersistenceLateMinTenEffectPerTen": "$+9.35$ pp",
        "EntryPersistenceEarlyMinFivePairs": r"1{,}629",
        "EntryPersistenceLateMinTenPairs": "452",
    }
    for macro, value in expected.items():
        assert f"\\newcommand{{\\{macro}}}{{{value}}}" in rendered
    assert "Effects report the percentage-point outcome change for 10 pp" in rendered


def test_persistence_values_reject_missing_estimate() -> None:
    models = _models()
    models = models[~models["model_id"].eq("m10_late_pair_controls_min10")]
    with pytest.raises(ValueError, match="expected one entry-stable-share row"):
        render_entry_vehicle_persistence_values(models, _support())


def test_persistence_values_reject_inconsistent_scaling() -> None:
    models = _models()
    models.loc[
        models["model_id"].eq("m2_early_pair_controls"),
        "effect_pp_per_10pp",
    ] = 4.0
    with pytest.raises(ValueError, match="percentage-point scaling"):
        render_entry_vehicle_persistence_values(models, _support())
