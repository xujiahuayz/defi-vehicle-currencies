from __future__ import annotations

import math

import pandas as pd

from ddvc.analysis.bridge_adoption_risk_set import (
    adoption_support_rows,
    estimate_adoption_models,
    prepare_adoption_risk_panel,
)


def _risk_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    first_native = pd.Timestamp("2023-12-01")
    for pair_number in range(40):
        adopter = pair_number < 20
        adoption_week = 5 + pair_number % 2
        final_week = adoption_week if adopter else 7
        for week_number in range(final_week + 1):
            week_start = pd.Timestamp("2024-01-01") + pd.Timedelta(
                weeks=week_number
            )
            adoption_date = (
                pd.Timestamp("2024-01-01")
                + pd.Timedelta(weeks=adoption_week, days=2)
                if adopter
                else pd.NaT
            )
            stable_depth = (
                5.0
                + 3.0 * week_number
                + (30.0 if adopter and week_number >= adoption_week - 1 else 0.0)
                + 0.2 * pair_number
            )
            lead_stable_depth = stable_depth + 2.0 + (pair_number % 3)
            rows.append(
                {
                    "pair_id": f"src-{pair_number}|tgt-{pair_number}",
                    "src": f"src-{pair_number}",
                    "tgt": f"tgt-{pair_number}",
                    "week_start": week_start,
                    "first_native_date": first_native,
                    "first_stable_date": adoption_date,
                    "prior_native_routes": 20.0 + pair_number + week_number,
                    "prior_native_active_days": 4 + week_number % 3,
                    "stable_weak_leg_usd": stable_depth,
                    "weth_weak_leg_usd": 100.0 + pair_number,
                    "lead_stable_weak_leg_usd": lead_stable_depth,
                    "lead_weth_weak_leg_usd": 102.0 + pair_number,
                }
            )
    rows[0]["stable_weak_leg_usd"] = 0.0
    return pd.DataFrame(rows)


def test_risk_panel_retains_zero_depth_and_nonadopters() -> None:
    panel = prepare_adoption_risk_panel(_risk_rows())
    assert panel["stable_weak_leg_usd"].eq(0).any()
    assert panel.loc[panel["stable_weak_leg_usd"].eq(0), "stable_depth_share"].eq(
        0
    ).all()
    assert panel.groupby("pair_id")["adopted_this_week"].sum().max() == 1
    assert panel.groupby("pair_id")["adopted_this_week"].sum().eq(0).sum() == 20

    support = adoption_support_rows(
        panel,
        min_prior_native_routes=10,
        min_prior_native_active_days=3,
    ).iloc[0]
    assert support["pairs"] == 40
    assert support["adopting_pairs"] == 20
    assert support["never_adopting_pairs"] == 20
    assert support["censored_before_observed_adoption_pairs"] == 0
    assert support["zero_stable_depth_pair_weeks"] == 1
    assert support["adoptions_with_positive_stable_depth"] == 20


def test_risk_panel_rejects_post_adoption_rows() -> None:
    rows = _risk_rows()
    first_pair = rows["pair_id"].eq("src-0|tgt-0")
    extra = rows[first_pair].iloc[-1].copy()
    extra["week_start"] = pd.Timestamp("2024-02-12")
    rows = pd.concat([rows, extra.to_frame().T], ignore_index=True)
    try:
        prepare_adoption_risk_panel(rows)
    except ValueError as error:
        assert "follow first stablecoin use" in str(error)
    else:
        raise AssertionError("post-adoption weeks must not enter the risk set")


def test_risk_models_include_preweek_and_time_reversal_estimands() -> None:
    panel = prepare_adoption_risk_panel(_risk_rows())
    results = estimate_adoption_models(
        panel,
        min_observations=100,
        min_clusters=5,
    )
    observed = set(zip(results["model_id"], results["predictor"], strict=False))
    assert (
        "m1_preweek_relative_depth",
        "stable_depth_share_10pp",
    ) in observed
    assert (
        "m3_future_depth_time_reversal",
        "lead_stable_depth_share_10pp",
    ) in observed
    assert (
        "m4_preweek_and_future_depth",
        "stable_depth_share_10pp",
    ) in observed
    assert (
        "m4_preweek_and_future_depth",
        "lead_stable_depth_share_10pp",
    ) in observed
    assert results["pair_weeks"].min() >= 100
    assert results["pairs"].eq(40).all()
    assert results["coefficient"].map(math.isfinite).all()
