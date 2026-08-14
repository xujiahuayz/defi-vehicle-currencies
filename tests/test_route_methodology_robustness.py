from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_route_methodology_robustness import (
    clustered_ecdf_randomisation,
    conventional_ks_rejection,
    grouped_binomial_fixed_effects,
    paired_calendar_comparison,
)


def panel() -> pd.DataFrame:
    rows = []
    for pair_index in range(8):
        for day in range(1, 7):
            for scope in ("single_venue", "cross_venue"):
                for metric in ("count_share", "matched_strict_count_share"):
                    for year, stable in ((2024, 2 + pair_index % 2), (2026, 6 + pair_index % 2)):
                        native = 10 - stable
                        rows.append(
                            {
                                "metric": metric,
                                "year": year,
                                "date": pd.Timestamp(year, 1, day),
                                "src": f"s{pair_index}",
                                "tgt": f"t{pair_index}",
                                "month_day": f"01-{day:02d}",
                                "integration_scope": scope,
                                "native": native,
                                "stable": stable,
                                "denominator": 10,
                                "stable_share": stable / 10,
                            }
                        )
    return pd.DataFrame(rows)


def test_grouped_binomial_detects_positive_odds_change_without_expansion() -> None:
    result = grouped_binomial_fixed_effects(panel(), "count_share")
    assert result["coefficient"] > 0
    assert result["odds_ratio"] > 1
    assert result["observations"] == 192
    assert result["matched_cells"] == 96
    assert result["separated_cells_excluded"] == 0


def test_paired_calendar_reports_ordinary_and_hac_t() -> None:
    rows = paired_calendar_comparison(panel(), "count_share", hac_lag=2)
    assert [row["method"] for row in rows] == ["paired_calendar_t", "paired_calendar_hac_t"]
    assert all(np.isclose(row["coefficient"], 0.4) for row in rows)
    assert all("calendar-day ratio of total stable" in row["estimand"] for row in rows)
    assert all("activity_reallocation_across_cells" in row["interpretation"] for row in rows)


def test_clustered_ecdf_randomisation_is_reproducible() -> None:
    result, draws = clustered_ecdf_randomisation(
        panel(), "count_share", weighting="symmetric_denominator_mass", replications=19, seed=7
    )
    result_again, draws_again = clustered_ecdf_randomisation(
        panel(), "count_share", weighting="symmetric_denominator_mass", replications=19, seed=7
    )
    assert result["coefficient"] > 0
    assert result["replications"] == 19
    assert result["distribution_weighting"] == "symmetric_denominator_mass"
    pd.testing.assert_frame_equal(draws, draws_again)
    assert result == result_again


def test_conventional_ks_is_recorded_as_rejected_not_authority() -> None:
    result = conventional_ks_rejection(panel(), "count_share")
    assert result["coefficient"] > 0
    assert result["interpretation"] == "rejected_inference_diagnostic_statistic_only"
    assert "cluster sign-randomised" in result["rejection_reason"]
