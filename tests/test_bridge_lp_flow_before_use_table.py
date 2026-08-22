from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_bridge_lp_flow_before_use import (
    ACCELERATION_WINDOW,
    OUTCOMES,
    PRIMARY_SAMPLE,
    SUPPORT_DESIGN,
    render_bridge_lp_flow_before_use,
)


def _results() -> list[dict[str, object]]:
    contrasts = {
        "add_flow_usd": (
            0.953386,
            0.236128,
            8.334874e-5,
            -0.603129,
            0.215744,
            0.005811274,
            163,
            162,
        ),
        "seed_add_flow_usd": (
            2.135282,
            0.377992,
            7.147969e-8,
            -3.670514,
            0.305298,
            3.616650e-24,
            163,
            162,
        ),
        "net_add_flow_usd": (
            3.603671,
            1.286112,
            0.005706328,
            -2.708029,
            1.140973,
            0.01881011,
            162,
            161,
        ),
    }
    rows: list[dict[str, object]] = []
    for outcome in OUTCOMES:
        (
            week_two_estimate,
            week_two_se,
            week_two_p,
            week_one_estimate,
            week_one_se,
            week_one_p,
            observations,
            clusters,
        ) = contrasts[outcome.name]
        rows.extend(
            [
                {
                    "record_type": "event_path_contrast",
                    "sample": PRIMARY_SAMPLE,
                    "outcome": outcome.name,
                    "transformation": outcome.transformation,
                    "event_bin": "pre_week_2",
                    "event_bin_index": -2,
                    "reference_bin": "pre_week_4",
                    "relative_day_start": -14,
                    "relative_day_end": -8,
                    "window": None,
                    "first_use_day_excluded": None,
                    "estimate": week_two_estimate,
                    "standard_error": week_two_se,
                    "p_value": week_two_p,
                    "observations": observations,
                    "ordered_pair_clusters": clusters,
                },
                {
                    "record_type": "pre_use_acceleration",
                    "sample": PRIMARY_SAMPLE,
                    "outcome": outcome.name,
                    "transformation": outcome.transformation,
                    "event_bin": None,
                    "event_bin_index": None,
                    "reference_bin": None,
                    "relative_day_start": None,
                    "relative_day_end": None,
                    "window": ACCELERATION_WINDOW,
                    "first_use_day_excluded": True,
                    "estimate": week_one_estimate,
                    "standard_error": week_one_se,
                    "p_value": week_one_p,
                    "observations": observations,
                    "ordered_pair_clusters": clusters,
                },
            ]
        )
    return rows


def _support() -> list[dict[str, object]]:
    return [
        {
            "record_type": "bridge_lp_flow_before_use_support",
            "eligible_delayed_bridge_events": 260,
            "events": 259,
            "events_with_both_v2_family_legs_by_first_use": 259,
            "events_with_both_v2_family_legs_strictly_prior": 254,
            "strict_prior_two_leg_events": 254,
            "ordered_pairs": 258,
            "first_event_date": "2020-06-21",
            "last_event_date": "2025-02-05",
            "pre_days": 28,
            "post_days": 7,
            "complete_usd_event_day_share": 0.9247,
            **SUPPORT_DESIGN,
        }
    ]


def test_bridge_lp_flow_table_reports_selected_raw_contrasts_and_support() -> None:
    rendered = render_bridge_lp_flow_before_use(
        pd.DataFrame(_results()), pd.DataFrame(_support())
    )

    assert r"\begin{tabularx}{\linewidth}" in rendered
    assert r"Week $-2$ minus week $-4$" in rendered
    assert r"Week $-1$ minus mean of weeks $-4$ to $-2$" in rendered
    assert "$+0.953$" in rendered
    assert "$-0.603$" in rendered
    assert "$+2.135$" in rendered
    assert r"$8.33\times 10^{-5}$" in rendered
    assert r"$3.62\times 10^{-24}$" in rendered
    assert "Raw $p$-value" in rendered
    assert "163 & 163 & 162" in rendered
    assert "162 & 162 & 161" in rendered
    assert "Eligible delayed events" in rendered
    assert "Both legs active before first use" in rendered
    assert r"\multicolumn{3}{r}{260}" in rendered
    assert r"\multicolumn{3}{r}{254}" in rendered
    assert "Ordered endpoint pairs" not in rendered
    assert "^{*" not in rendered


def test_bridge_lp_flow_table_rejects_missing_selected_contrast() -> None:
    rows = [
        row
        for row in _results()
        if not (
            row["record_type"] == "pre_use_acceleration"
            and row["outcome"] == "net_add_flow_usd"
        )
    ]
    with pytest.raises(ValueError, match="expected one bridge LP-flow row"):
        render_bridge_lp_flow_before_use(
            pd.DataFrame(rows), pd.DataFrame(_support())
        )


def test_bridge_lp_flow_table_rejects_changed_timing_or_support_scope() -> None:
    rows = _results()
    rows[0]["relative_day_start"] = -13
    with pytest.raises(ValueError, match="changed timing"):
        render_bridge_lp_flow_before_use(
            pd.DataFrame(rows), pd.DataFrame(_support())
        )

    support = _support()
    support[0]["events_with_both_v2_family_legs_strictly_prior"] = 253
    with pytest.raises(ValueError, match="support counts are inconsistent"):
        render_bridge_lp_flow_before_use(
            pd.DataFrame(_results()), pd.DataFrame(support)
        )
