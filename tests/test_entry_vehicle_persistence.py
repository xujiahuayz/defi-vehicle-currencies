from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_entry_vehicle_persistence import (
    build_post_entry_panel,
    fit_persistence_models,
    fit_retrade_models,
    sample_support,
)


def _row(
    date: str | pd.Timestamp,
    src: str,
    tgt: str,
    *,
    entry: bool,
    stable: int,
    native: int,
    direct: int = 0,
    complex_routes: int = 0,
) -> dict[str, object]:
    primary = stable + native
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "market_route_count": primary + direct + complex_routes,
        "primary_choice_route_count": primary,
        "stable_choice_route_count": stable,
        "native_choice_route_count": native,
        "direct_route_count": direct,
        "multiple_intermediary_route_count": complex_routes,
        "split_or_join_route_count": 0,
        "nonsequential_two_leg_route_count": 0,
        "pair_entry_on_day": entry,
    }


def test_post_entry_panel_excludes_entry_day_and_splits_disjoint_windows(
    tmp_path,
) -> None:
    native_eth = "0x0000000000000000000000000000000000000000"
    rows = [
        _row("2024-01-01", "a", "b", entry=True, stable=100, native=0),
        _row("2024-01-02", "a", "b", entry=False, stable=1, native=9),
        _row("2024-01-31", "a", "b", entry=False, stable=2, native=8),
        _row("2024-02-01", "a", "b", entry=False, stable=7, native=3),
        _row("2024-04-30", "a", "b", entry=False, stable=9, native=1),
        _row("2024-05-01", "a", "b", entry=False, stable=10, native=0),
        _row("2024-01-01", "c", "d", entry=True, stable=0, native=5),
        _row("2024-03-03", "e", "f", entry=True, stable=4, native=1),
        _row("2024-03-04", "e", "f", entry=False, stable=3, native=2),
        _row("2024-01-01", native_eth, "z", entry=True, stable=0, native=5),
        _row("2024-01-02", native_eth, "z", entry=False, stable=0, native=5),
    ]
    path = tmp_path / "pair_support.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)

    panel = build_post_entry_panel(
        path,
        sample_end=pd.Timestamp("2026-06-30"),
        entry_years=(2024,),
    )
    early = panel[panel["window_id"].eq("days_1_30")].set_index("src")
    late = panel[panel["window_id"].eq("days_31_120")].set_index("src")

    assert early.loc["a", "post_primary_routes"] == pytest.approx(20.0)
    assert early.loc["a", "post_stable_routes"] == pytest.approx(3.0)
    assert early.loc["a", "post_stable_share"] == pytest.approx(3 / 20)
    assert late.loc["a", "post_primary_routes"] == pytest.approx(20.0)
    assert late.loc["a", "post_stable_routes"] == pytest.approx(16.0)
    assert late.loc["a", "post_stable_share"] == pytest.approx(16 / 20)
    assert not bool(early.loc["c", "retraded"])
    assert np.isnan(early.loc["c", "post_stable_share"])
    assert not bool(late.loc["c", "retraded"])
    assert "e" not in set(panel["src"])
    assert native_eth not in set(panel["src"])
    assert panel["common_entry_calendar_cutoff_mm_dd"].eq("03-02").all()


def test_support_reports_retrading_and_both_weighted_means() -> None:
    panel = pd.DataFrame(
        [
            {
                "window_id": "days_1_30",
                "window_start_day": 1,
                "window_end_day": 30,
                "entry_year": 2024,
                "entry_date": pd.Timestamp("2024-01-01"),
                "sample_end": pd.Timestamp("2026-06-30"),
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "retraded": True,
                "post_primary_routes": 9.0,
                "post_active_days": 2,
                "post_stable_share": 1.0,
            },
            {
                "window_id": "days_1_30",
                "window_start_day": 1,
                "window_end_day": 30,
                "entry_year": 2024,
                "entry_date": pd.Timestamp("2024-01-02"),
                "sample_end": pd.Timestamp("2026-06-30"),
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "retraded": True,
                "post_primary_routes": 1.0,
                "post_active_days": 1,
                "post_stable_share": 0.0,
            },
            {
                "window_id": "days_1_30",
                "window_start_day": 1,
                "window_end_day": 30,
                "entry_year": 2024,
                "entry_date": pd.Timestamp("2024-01-03"),
                "sample_end": pd.Timestamp("2026-06-30"),
                "common_entry_calendar_cutoff_mm_dd": "03-02",
                "retraded": False,
                "post_primary_routes": 0.0,
                "post_active_days": 0,
                "post_stable_share": np.nan,
            },
        ]
    )
    result = sample_support(panel)
    total = result[result["entry_year"].eq("all")].iloc[0]

    assert total["eligible_pairs"] == 3
    assert total["retrading_pairs"] == 2
    assert total["nonretrading_pairs"] == 1
    assert total["retrade_rate"] == pytest.approx(2 / 3)
    assert total["equal_pair_stable_share"] == pytest.approx(0.5)
    assert total["activity_weighted_stable_share"] == pytest.approx(0.9)
    assert bool(total["entry_day_excluded"])
    assert total["common_entry_calendar_cutoff_mm_dd"] == "03-02"


def test_models_publish_conventional_columns_and_require_retrading() -> None:
    rows: list[dict[str, object]] = []
    for day in range(1, 61):
        entry_date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=day - 1)
        for pair_index in range(3):
            entry_share = 0.10 + 0.20 * pair_index + 0.002 * day
            for window_id, start_day, end_day, shift in (
                ("days_1_30", 1, 30, 0.02),
                ("days_31_120", 31, 120, 0.06),
            ):
                retraded = pair_index != 2 or day % 5 != 0
                activity = float(2 + day + pair_index) if retraded else 0.0
                rows.append(
                    {
                        "entry_date": entry_date,
                        "window_id": window_id,
                        "window_start_day": start_day,
                        "window_end_day": end_day,
                        "entry_year": 2024 + 2 * (day % 2),
                        "sample_end": pd.Timestamp("2026-06-30"),
                        "common_entry_calendar_cutoff_mm_dd": "03-02",
                        "retraded": retraded,
                        "post_primary_routes": activity,
                        "post_active_days": int(retraded),
                        "post_stable_share": (
                            0.10 + 0.70 * entry_share + shift
                            if retraded
                            else np.nan
                        ),
                        "entry_stable_share": entry_share,
                        "entry_primary_routes": float(5 + day + pair_index),
                        "is_2026": float(day % 2),
                        "stable_endpoint": float(pair_index == 1),
                        "log_entry_routes": np.log1p(5 + day + pair_index),
                        "entry_direct_share": 0.02 * ((day + pair_index) % 4),
                        "entry_complex_share": 0.03 * ((day + 2 * pair_index) % 5),
                    }
                )
    panel = pd.DataFrame(rows)
    result = fit_persistence_models(
        panel,
        min_observations=100,
        min_clusters=30,
    )

    assert result["column_order"].nunique() == 10
    assert set(result["weighting"]) == {
        "equal_pair",
        "post_entry_route_activity",
    }
    assert result["entry_day_excluded"].all()
    assert result["retrading_required"].all()
    assert result["entry_state_measurement"].eq("entry_day_only").all()
    assert result["inference_status"].eq("provisional_descriptive").all()
    key = result[
        result["model_id"].eq("m5_late_pair_controls")
        & result["predictor"].eq("entry_stable_share")
    ].iloc[0]
    expected_retraders = int(
        panel[
            panel["window_id"].eq("days_31_120") & panel["retraded"]
        ].shape[0]
    )
    assert key["observations"] == expected_retraders
    assert key["coefficient"] == pytest.approx(0.70, abs=0.03)
    assert key["effect_pp_per_10pp"] == pytest.approx(
        10.0 * key["coefficient"]
    )
    assert np.isfinite(key["standard_error"])
    assert set(
        result.loc[
            result["specification_role"].eq("entry_route_threshold_robustness"),
            "minimum_entry_routes",
        ]
    ) == {5, 10}

    retrade = fit_retrade_models(
        panel,
        min_observations=100,
        min_clusters=30,
    )
    late = retrade[
        retrade["model_id"].eq("r2_late_retrade_controls")
        & retrade["predictor"].eq("entry_stable_share")
    ].iloc[0]
    eligible = int(panel[panel["window_id"].eq("days_31_120")].shape[0])
    assert late["observations"] == eligible
    assert not bool(late["retrading_required"])
    assert late["dependent_mean"] == pytest.approx(
        panel.loc[panel["window_id"].eq("days_31_120"), "retraded"].mean()
    )

    with pytest.raises(ValueError, match="nonfinite regression fit"):
        fit_persistence_models(
            panel,
            min_observations=1_000_000,
            min_clusters=30,
        )
