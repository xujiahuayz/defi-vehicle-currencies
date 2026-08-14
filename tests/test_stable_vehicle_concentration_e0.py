from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import pytest

from scripts import run_stable_vehicle_concentration_e0 as concentration


def _panel() -> pd.DataFrame:
    rows = []
    for year, shares in (
        (2024, {"USDT": 20, "USDC": 30, "DAI": 10, "other": 40}),
        (2025, {"USDT": 30, "USDC": 30, "DAI": 10, "other": 30}),
        (2026, {"USDT": 50, "USDC": 30, "DAI": 10, "other": 10}),
    ):
        for date in pd.date_range(f"{year}-01-01", periods=40):
            rows.append(
                {
                    "date": date,
                    "cnt_stable": 100,
                    "cnt_USDT": shares["USDT"],
                    "cnt_USDC": shares["USDC"],
                    "cnt_DAI": shares["DAI"],
                    "cnt_two_leg_stable": 100,
                    "cnt_two_leg_USDT": shares["USDT"],
                    "cnt_two_leg_USDC": shares["USDC"],
                    "cnt_two_leg_DAI": shares["DAI"],
                    "usd_within_20pct_two_leg_stable": 200,
                    "usd_within_20pct_two_leg_USDT": shares["USDT"] * 2,
                    "usd_within_20pct_two_leg_USDC": shares["USDC"] * 2,
                    "usd_within_20pct_two_leg_DAI": shares["DAI"] * 2,
                }
            )
    return pd.DataFrame(rows)


def test_daily_concentration_bounds_residual_token_identity() -> None:
    daily = concentration.daily_concentration(_panel())
    first = daily.iloc[0]
    assert first["usdt_usdc_cr2"] == pytest.approx(0.5)
    assert first["hhi_lower_bound"] == pytest.approx(0.2**2 + 0.3**2 + 0.1**2)
    assert first["hhi_upper_bound"] == pytest.approx(
        0.2**2 + 0.3**2 + 0.1**2 + 0.4**2
    )


def test_concentration_result_reports_magnitude_and_dependence_aware_change() -> None:
    result = concentration.concentration_results(_panel())
    support = result[result["record_type"].eq("support")].iloc[0]
    assert "Newey-West" in support["inference"]
    assert "2025 is excluded" in support["inference"]
    assert "unavailable" in support["count_companion_status"]
    assert "A rising CR2 is not called rising concentration" in support[
        "cr2_hhi_distinction"
    ]
    assert "enters only the HHI bounds" in support["residual_use"]
    assert "Griffin and Shams" in support["empirical_finance_benchmark"]
    assert "does not identify succession" in support["claim_limit"]

    aggregate = result[
        result["record_type"].eq("aggregate_magnitude")
        & result["measure"].eq("episode_count_exact_two_leg_all_support")
    ].set_index("year")
    assert aggregate.loc[2024, "usdt_usdc_cr2"] == pytest.approx(0.5)
    assert aggregate.loc[2026, "usdt_usdc_cr2"] == pytest.approx(0.8)
    assert "other_stable_share" not in result
    assert "named_stable_coverage" not in result

    changes = result[
        result["record_type"].eq("endpoint_change")
        & result["measure"].eq("episode_count_exact_two_leg_all_support")
        & result["primary_bandwidth"].fillna(False)
    ].set_index("metric")
    assert set(changes.index) == {
        "usdt_usdc_cr2",
        "hhi_lower_bound",
        "hhi_upper_bound",
    }
    assert changes.loc["usdt_usdc_cr2", "change"] == pytest.approx(0.3)
    assert set(changes["days"]) == {80}
    assert changes["hac_standard_error"].notna().all()
    assert changes["p_value_holm"].notna().all()

    value_changes = result[
        result["record_type"].eq("endpoint_change")
        & result["measure"].eq("value_exact_two_leg_within_20pct")
        & result["primary_bandwidth"].fillna(False)
    ].set_index("metric")
    assert value_changes.loc["usdt_usdc_cr2", "change"] == pytest.approx(0.3)
    assert set(
        result.loc[result["record_type"].eq("endpoint_change"), "hac_lag_days"]
    ) == {7, 14, 30, 60}
    support = result[result["record_type"].eq("measure_support")]
    assert set(support["inference_weighting"]) == {
        "equal-weighted daily concentration"
    }
    assert set(support["magnitude_weighting"]) == {"pooled within endpoint year"}


def test_named_counts_cannot_exceed_all_stable_episodes() -> None:
    panel = _panel()
    panel.loc[0, "cnt_two_leg_USDT"] = 101
    with pytest.raises(ValueError, match="exceed"):
        concentration.daily_concentration(panel)


def test_intervening_year_cannot_change_endpoint_only_inference() -> None:
    first = concentration.concentration_results(_panel())
    changed = _panel()
    is_2025 = changed["date"].dt.year.eq(2025)
    changed.loc[is_2025, "cnt_two_leg_USDT"] = 99
    changed.loc[is_2025, "cnt_two_leg_USDC"] = 0
    changed.loc[is_2025, "cnt_two_leg_DAI"] = 0
    second = concentration.concentration_results(changed)
    columns = [
        "measure",
        "metric",
        "hac_lag_days",
        "change",
        "hac_standard_error",
        "p_value",
    ]
    pd.testing.assert_frame_equal(
        first.loc[first["record_type"].eq("endpoint_change"), columns].reset_index(drop=True),
        second.loc[second["record_type"].eq("endpoint_change"), columns].reset_index(drop=True),
    )


def test_main_leases_current_owner_and_binds_output_provenance(monkeypatch) -> None:
    observed = []
    written = []

    @contextmanager
    def current(inputs, *, consumer):
        observed.append((tuple(inputs), consumer))
        yield

    monkeypatch.setattr(concentration, "current_artifacts", current)
    monkeypatch.setattr(concentration.pd, "read_parquet", lambda _path: _panel())
    monkeypatch.setattr(
        concentration,
        "write_exhibit",
        lambda frame, path, **kwargs: written.append((frame, path, kwargs)),
    )
    assert concentration.main() == 0
    assert observed == [
        ((concentration.INPUT,), "stable-vehicle concentration E0")
    ]
    assert written[0][1] == concentration.OUTPUT
    assert written[0][2]["inputs"] == [concentration.INPUT]
    assert (
        "scripts/run_stable_vehicle_concentration_e0.py"
        in written[0][2]["code_sources"]
    )


def test_main_refuses_stale_input_without_rewriting_output(monkeypatch) -> None:
    @contextmanager
    def stale(*_args, **_kwargs):
        raise RuntimeError("stale source")
        yield

    written = []
    monkeypatch.setattr(concentration, "current_artifacts", stale)
    monkeypatch.setattr(
        concentration,
        "write_exhibit",
        lambda *_args, **_kwargs: written.append(True),
    )
    assert concentration.main() == 2
    assert written == []
