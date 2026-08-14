from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
from unittest import mock

import numpy as np
import pandas as pd
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_stable_frequency_value_dynamics_e0.py"
SPEC = importlib.util.spec_from_file_location("stable_frequency_value_dynamics_e0", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def synthetic_panel(days: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(19)
    date = pd.date_range("2024-01-01", periods=days, freq="D")
    count_gap = np.clip(np.sin(np.arange(days) / 19) * 0.35 + rng.normal(0, 0.04, days), -0.8, 0.8)
    value_gap = np.zeros(days)
    for index in range(1, days):
        value_gap[index] = 0.55 * value_gap[index - 1] + 0.30 * count_gap[index - 1] + rng.normal(0, 0.03)
    count_total = np.full(days, 10_000.0)
    value_total = np.full(days, 10_000_000.0)
    return pd.DataFrame(
        {
            "date": date,
            "cnt_two_leg_stable": count_total,
            "cnt_two_leg_USDT": count_total * (0.48 + count_gap / 2),
            "cnt_two_leg_USDC": count_total * (0.48 - count_gap / 2),
            "usd_within_20pct_two_leg_stable": value_total,
            "usd_within_20pct_two_leg_USDT": value_total * (0.48 + value_gap / 2),
            "usd_within_20pct_two_leg_USDC": value_total * (0.48 - value_gap / 2),
        }
    )


def test_daily_gaps_recover_declared_denominators() -> None:
    panel = synthetic_panel()
    result = MODULE.daily_gaps(panel)
    expected_count = (
        panel["cnt_two_leg_USDT"] - panel["cnt_two_leg_USDC"]
    ) / panel["cnt_two_leg_stable"]
    expected_value = (
        panel["usd_within_20pct_two_leg_USDT"]
        - panel["usd_within_20pct_two_leg_USDC"]
    ) / panel["usd_within_20pct_two_leg_stable"]
    np.testing.assert_allclose(result["count_gap"], expected_count)
    np.testing.assert_allclose(result["strict_value_gap"], expected_value)


def test_horizon_join_uses_exact_calendar_days() -> None:
    data = MODULE.daily_gaps(synthetic_panel())
    sample = MODULE.horizon_sample(data, 7, "count_to_value")
    assert len(sample) == len(data) - 7
    assert sample["future_date"].sub(sample["date"]).dt.days.eq(7).all()


def test_dynamic_fit_detects_count_to_value_prediction() -> None:
    data = MODULE.daily_gaps(synthetic_panel())
    estimate = MODULE.fit_dynamic(MODULE.horizon_sample(data, 1, "count_to_value"))
    assert estimate["coefficient"] > 0
    assert estimate["p_value"] < 0.05
    assert estimate["claim_boundary"].startswith("predictive_descriptive")


def test_method_ledger_rejects_unidentified_battery() -> None:
    methods = MODULE.method_assessment().set_index("method")
    assert methods.loc["dynamic_OLS_with_actual_calendar_HAC", "status"] == "selected"
    assert methods.loc["difference_in_differences_or_event_study", "status"] == "not_identified"
    assert methods.loc["survival_or_discrete_time_hazard", "status"] == "rejected_for_this_estimand"


def test_holm_adjustment_compares_directions_within_each_horizon() -> None:
    result = MODULE.result_frame(synthetic_panel())
    estimates = result[result["row_type"].eq("dynamic_estimate")]
    for _horizon, family in estimates.groupby("horizon_days", sort=False):
        expected = MODULE.holm_adjusted_pvalues(family["p_value"])
        np.testing.assert_allclose(
            family["p_value_holm_within_horizon"], expected
        )


def test_stale_input_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "result.jsonl"
        blocker = mock.MagicMock()
        blocker.__enter__.side_effect = RuntimeError("stale")
        with mock.patch.object(MODULE, "current_artifacts", return_value=blocker):
            with pytest.raises(RuntimeError, match="stale"):
                MODULE.run(Path(directory) / "input.parquet", output)
        assert not output.exists()
