from __future__ import annotations

import pandas as pd
import pytest

from ddvc.analysis.pair_turnover_lifecycle import (
    summarize_pair_turnover_lifecycle,
    validate_exclusive_totals,
)


def _contribution(
    src: str,
    tgt: str,
    status: str,
    contribution: float,
) -> dict[str, object]:
    baseline = 10.0 if status == "baseline_exclusive" else 0.0
    comparison = 10.0 if status == "comparison_exclusive" else 0.0
    return {
        "metric": "count_share",
        "source_column": "route_count",
        "reporting_scope": "pooled",
        "baseline_year": 2024,
        "comparison_year": 2026,
        "src": src,
        "tgt": tgt,
        "support_status": status,
        "contribution_share": contribution,
        "denominator_baseline": baseline,
        "denominator_comparison": comparison,
        "stable_baseline": baseline / 2,
        "stable_comparison": comparison / 2,
    }


def _history(
    src: str,
    tgt: str,
    first: str,
    last: str,
    *,
    baseline_market: float,
    comparison_market: float,
) -> dict[str, object]:
    return {
        "metric": "count_share",
        "source_column": "route_count",
        "src": src,
        "tgt": tgt,
        "first_observed_date": pd.Timestamp(first),
        "last_observed_date": pd.Timestamp(last),
        "positive_days": 2,
        "baseline_market_route_count": baseline_market,
        "comparison_market_route_count": comparison_market,
    }


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    contributions = pd.DataFrame(
        [
            _contribution("a", "b", "comparison_exclusive", 0.10),
            _contribution("c", "d", "comparison_exclusive", 0.20),
            _contribution("e", "f", "comparison_exclusive", 0.03),
            _contribution("g", "h", "baseline_exclusive", -0.04),
            _contribution("i", "j", "baseline_exclusive", -0.05),
        ]
    )
    histories = pd.DataFrame(
        [
            _history(
                "a",
                "b",
                "2025-04-01",
                "2026-06-01",
                baseline_market=0,
                comparison_market=10,
            ),
            _history(
                "c",
                "d",
                "2026-02-01",
                "2026-05-01",
                baseline_market=0,
                comparison_market=10,
            ),
            _history(
                "e",
                "f",
                "2023-03-01",
                "2026-05-01",
                baseline_market=0,
                comparison_market=10,
            ),
            _history(
                "g",
                "h",
                "2020-01-01",
                "2024-05-01",
                baseline_market=10,
                comparison_market=0,
            ),
            _history(
                "i",
                "j",
                "2023-01-01",
                "2025-09-01",
                baseline_market=10,
                comparison_market=0,
            ),
        ]
    )
    return contributions, histories


def _rows(result: pd.DataFrame, level: str) -> pd.DataFrame:
    return result[result["aggregation_level"].eq(level)].set_index(
        "lifecycle_category"
    )


def test_split_distinguishes_pair_entry_from_reactivation() -> None:
    contributions, histories = _fixture()
    result = summarize_pair_turnover_lifecycle(contributions, histories)
    detail = _rows(result, "detail")
    assert set(detail.index) == {
        "first_endpoint_pair_observed_between_windows",
        "first_endpoint_pair_observed_in_comparison_window",
        "endpoint_pair_reactivated",
        "endpoint_pair_last_observed_by_baseline_window_end",
        "endpoint_pair_last_observed_between_windows",
    }
    lifecycle = _rows(result, "lifecycle_group")
    assert lifecycle.loc[
        "first_endpoint_pair_observed_after_baseline_window", "contribution_share"
    ] == pytest.approx(0.30)
    assert lifecycle.loc[
        "endpoint_pair_reactivated", "contribution_share"
    ] == pytest.approx(0.03)
    assert lifecycle.loc[
        "endpoint_pair_last_observed_before_comparison_window",
        "contribution_share",
    ] == pytest.approx(-0.09)


def test_newly_active_support_includes_first_observations_and_reactivations() -> None:
    contributions, histories = _fixture()
    support = _rows(
        summarize_pair_turnover_lifecycle(contributions, histories),
        "endpoint_support",
    )
    assert support.loc["newly_active_in_comparison_window", "pair_count"] == 3
    assert support.loc[
        "newly_active_in_comparison_window", "contribution_share"
    ] == pytest.approx(0.33)
    assert support.loc[
        "absent_in_comparison_window", "contribution_share"
    ] == pytest.approx(-0.09)


def test_every_rollup_is_exactly_additive() -> None:
    contributions, histories = _fixture()
    result = summarize_pair_turnover_lifecycle(contributions, histories)
    for level in (
        "detail",
        "lifecycle_group",
        "endpoint_support",
        "exclusive_total",
    ):
        observed = result.loc[
            result["aggregation_level"].eq(level), "contribution_share"
        ].sum()
        assert observed == pytest.approx(0.24)


def test_registered_exclusive_term_must_match_lifecycle_total() -> None:
    contributions, histories = _fixture()
    lifecycle = summarize_pair_turnover_lifecycle(contributions, histories)
    decomposition = pd.DataFrame(
        [
            {
                "metric": "count_share",
                "reporting_scope": "pooled",
                "formula_id": "midpoint_common_exclusive_support_v1",
                "exclusive_pair_contribution": 0.24,
            }
        ]
    )
    validate_exclusive_totals(lifecycle, decomposition)
    decomposition.loc[0, "exclusive_pair_contribution"] = 0.23
    with pytest.raises(RuntimeError, match="does not reproduce"):
        validate_exclusive_totals(lifecycle, decomposition)


def test_missing_history_is_rejected() -> None:
    contributions, histories = _fixture()
    with pytest.raises(ValueError, match="lacks history"):
        summarize_pair_turnover_lifecycle(contributions, histories.iloc[:-1])


def test_history_inconsistent_with_endpoint_support_is_rejected() -> None:
    contributions, histories = _fixture()
    history = histories.copy()
    mask = history["src"].eq("g") & history["tgt"].eq("h")
    history.loc[mask, "last_observed_date"] = pd.Timestamp("2026-02-01")
    with pytest.raises(ValueError, match="inconsistent with endpoint support"):
        summarize_pair_turnover_lifecycle(contributions, history)


def test_vehicle_role_turnover_is_separate_from_endpoint_pair_turnover() -> None:
    contributions, histories = _fixture()
    extra_contributions = pd.DataFrame(
        [
            _contribution("k", "l", "comparison_exclusive", 0.06),
            _contribution("m", "n", "baseline_exclusive", -0.02),
        ]
    )
    extra_histories = pd.DataFrame(
        [
            _history(
                "k",
                "l",
                "2020-01-01",
                "2026-06-01",
                baseline_market=10,
                comparison_market=10,
            ),
            _history(
                "m",
                "n",
                "2020-01-01",
                "2026-06-01",
                baseline_market=10,
                comparison_market=10,
            ),
        ]
    )
    result = summarize_pair_turnover_lifecycle(
        pd.concat([contributions, extra_contributions], ignore_index=True),
        pd.concat([histories, extra_histories], ignore_index=True),
    )
    detail = _rows(result, "detail")
    assert detail.loc[
        "vehicle_role_activated_in_continuing_endpoint_pair",
        "contribution_share",
    ] == pytest.approx(0.06)
    assert detail.loc[
        "vehicle_role_lapsed_in_continuing_endpoint_pair",
        "contribution_share",
    ] == pytest.approx(-0.02)
    lifecycle = _rows(result, "lifecycle_group")
    assert lifecycle.loc[
        "vehicle_role_turnover_in_continuing_endpoint_pairs",
        "contribution_share",
    ] == pytest.approx(0.04)


def test_common_pair_contribution_is_rejected() -> None:
    contributions, histories = _fixture()
    altered = contributions.copy()
    altered.loc[0, "support_status"] = "common"
    with pytest.raises(ValueError, match="common-pair"):
        summarize_pair_turnover_lifecycle(altered, histories)
