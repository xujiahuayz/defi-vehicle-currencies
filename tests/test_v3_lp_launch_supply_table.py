from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_lp_launch_supply import (
    TABLE_NOTE,
    render_v3_lp_launch_supply,
    render_v3_lp_launch_supply_values,
)


AGE_ACTIONS = {
    ("2024H1", "WETH"): (45_266, 25_111, 33_914, 147_437),
    ("2024H1", "stable"): (2_827, 1_922, 4_122, 14_371),
    ("2026H1", "WETH"): (21_750, 4_995, 4_225, 84_400),
    ("2026H1", "stable"): (6_891, 4_224, 11_700, 68_430),
}
AGE_BINS = ("0-7", "8-30", "31-90", ">90")


def _results() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (period, vehicle_type), actions in AGE_ACTIONS.items():
        for age_bin, action_count in zip(AGE_BINS, actions, strict=True):
            rows.append(
                {
                    "record_type": "v3_lp_supply_by_pool_age",
                    "period": period,
                    "vehicle_type": vehicle_type,
                    "pool_age_bin": age_bin,
                    "addition_action_events": action_count,
                }
            )

    rows.extend(
        [
            {
                "record_type": "v3_lp_origin_history",
                "period": "2026H1",
                "vehicle_type": "stable",
                "endpoint_period_membership": "continuing",
                "origin_history_class": "multi-pool",
                "addition_action_events": 17_806,
                "screened_candidate_side_flow_usd": 6_335_082_000.0,
            },
            {
                "record_type": "v3_lp_origin_history",
                "period": "2026H1",
                "vehicle_type": "stable",
                "endpoint_period_membership": "continuing",
                "origin_history_class": "repeat-day/one-pool",
                "addition_action_events": 25,
                "screened_candidate_side_flow_usd": 53_830.3,
            },
            {
                "record_type": "v3_lp_origin_history",
                "period": "2026H1",
                "vehicle_type": "stable",
                "endpoint_period_membership": "period-specific",
                "origin_history_class": "multi-pool",
                "addition_action_events": 41_495,
                "screened_candidate_side_flow_usd": 856_969_100.0,
            },
            {
                "record_type": "v3_lp_origin_history",
                "period": "2026H1",
                "vehicle_type": "stable",
                "endpoint_period_membership": "period-specific",
                "origin_history_class": "one-day/one-pool",
                "addition_action_events": 3_269,
                "screened_candidate_side_flow_usd": 46_985_400.0,
            },
            {
                "record_type": "v3_lp_origin_history",
                "period": "2026H1",
                "vehicle_type": "stable",
                "endpoint_period_membership": "period-specific",
                "origin_history_class": "repeat-day/one-pool",
                "addition_action_events": 28_650,
                "screened_candidate_side_flow_usd": 2_356_576_000.0,
            },
            {
                "record_type": "v3_lp_launch_followup",
                "period": "2026H1",
                "vehicle_type": "stable",
                "horizon_days": 30,
                "launch_pools": 437,
                "action_weighted_active_pool_share": 0.833305,
                "post_launch_net_to_launch_flow": -0.012171,
            },
            {
                "record_type": "v3_lp_launch_followup",
                "period": "2026H1",
                "vehicle_type": "stable",
                "horizon_days": 90,
                "launch_pools": 255,
                "action_weighted_active_pool_share": 0.690449,
                "post_launch_net_to_launch_flow": -0.003951,
            },
        ]
    )
    return pd.DataFrame(rows)


def _support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "v3_lp_launch_supply_support",
                "missing_pool_inception_rows": 0,
                "negative_pool_age_rows": 0,
                "full_sample_spoke_pools": 60_859,
            }
        ]
    )


def test_v3_lp_launch_supply_renders_decisive_maturity_bounds() -> None:
    rendered = render_v3_lp_launch_supply(_results(), _support())

    assert "Panel A. Stable-facing addition growth by pool age" in rendered
    assert "0--7 & 2,827 & 6,891 & 6.0" in rendered
    assert "More than 90 & 14,371 & 68,430 & 79.5" in rendered
    assert "Total & 23,242 & 91,245 & 100.0" in rendered
    assert "All pool ages & 8.5 & 44.2 & +35.71" in rendered
    assert "Older than 7 days & 9.0 & 47.4 & +38.40" in rendered
    assert (
        "Present only in 2026 H1; one day and one pool & 3.58 & 0.49"
        in rendered
    )
    assert "Action-weighted active-pool share [\\%] & 83.3 & 69.0" in rendered
    assert "Net vehicle-side USD flow / initial additions [\\%] & -1.22 & -0.40" in rendered


def test_v3_lp_launch_supply_values_cover_prose_inputs() -> None:
    values = render_v3_lp_launch_supply_values(_results(), _support())

    assert r"\newcommand{\VThreeLPLaunchStableActionIncrease}{68{,}003}" in values
    assert r"\newcommand{\VThreeLPLaunchWeekIncreaseShare}{6.0\%}" in values
    assert r"\newcommand{\VThreeLPMaturePoolIncreaseShare}{79.5\%}" in values
    assert r"\newcommand{\VThreeLPExLaunchStableShareBaseline}{9.0\%}" in values
    assert r"\newcommand{\VThreeLPExLaunchStableShareComparison}{47.4\%}" in values
    assert r"\newcommand{\VThreeLPExLaunchStableShareChange}{$+38.40$ pp}" in values
    assert r"\newcommand{\VThreeLPOneDayOnePoolActionShare}{3.58\%}" in values
    assert r"\newcommand{\VThreeLPOneDayOnePoolFlowShare}{0.49\%}" in values
    assert r"\newcommand{\VThreeLPThirtyDayActivePoolShare}{83.3\%}" in values
    assert r"\newcommand{\VThreeLPNinetyDayActivePoolShare}{69.0\%}" in values
    assert r"\newcommand{\VThreeLPThirtyDayNetFlowRatio}{-1.22\%}" in values
    assert r"\newcommand{\VThreeLPNinetyDayNetFlowRatio}{-0.40\%}" in values


def test_v3_lp_launch_supply_values_have_unique_macro_names() -> None:
    values = render_v3_lp_launch_supply_values(_results(), _support())
    commands = [line for line in values.splitlines() if line.startswith(r"\newcommand")]
    names = [line.split("{")[1].removeprefix("\\") for line in commands]

    assert len(commands) == 20
    assert len(names) == len(set(names))


def test_v3_lp_launch_supply_rejects_incomplete_pool_age_cells() -> None:
    results = _results()
    results = results.loc[
        ~(
            results["record_type"].eq("v3_lp_supply_by_pool_age")
            & results["period"].eq("2026H1")
            & results["vehicle_type"].eq("stable")
            & results["pool_age_bin"].eq(">90")
        )
    ]
    with pytest.raises(ValueError, match="expected one V3 pool-age result row"):
        render_v3_lp_launch_supply(results, _support())


def test_v3_lp_launch_supply_rejects_incomplete_pool_inception_join() -> None:
    support = _support()
    support.loc[0, "missing_pool_inception_rows"] = 1
    with pytest.raises(ValueError, match="lack pool-inception matches"):
        render_v3_lp_launch_supply(_results(), support)


def test_v3_lp_launch_supply_language_is_audience_facing() -> None:
    audience_text = (
        render_v3_lp_launch_supply(_results(), _support()) + " " + TABLE_NOTE
    ).lower()
    for banned in (
        "candidate",
        "screen",
        "claim",
        "diagnos",
        "workflow",
        "pipeline",
        "rather than",
        " not ",
    ):
        assert banned not in audience_text
