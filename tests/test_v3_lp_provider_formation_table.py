from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_v3_lp_provider_formation import (
    MODEL_COLUMNS,
    PRIMARY_FAMILY_ID,
    TABLE_NOTE,
    render_v3_lp_provider_formation,
    render_v3_lp_provider_formation_values,
)


def _decomposition() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "lp_add_actions",
                "baseline_period": "2024H1",
                "comparison_period": "2026H1",
                "baseline_stable_share": 0.0845256,
                "comparison_stable_share": 0.4416185,
                "total_change_pp": 35.7093,
                "within_continuing_origin_change_pp": 7.6980,
                "continuing_origin_reweighting_pp": 0.0124,
                "period_specific_origin_entry_exit_pp": 27.9988,
                "identity_error": 0.0,
            },
            {
                "metric": "screened_candidate_side_usd_flow",
                "baseline_period": "2024H1",
                "comparison_period": "2026H1",
                "baseline_stable_share": 0.0805215,
                "comparison_stable_share": 0.4153355,
                "total_change_pp": 33.4814,
                "within_continuing_origin_change_pp": 15.8598,
                "continuing_origin_reweighting_pp": -0.0456,
                "period_specific_origin_entry_exit_pp": 17.6673,
                "identity_error": 1e-16,
            },
        ]
    )


def _support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "origin_vehicle_network_and_valuation_support",
                "period": "2024H1",
                "vehicle_type": "stable",
                "active_origins": 3841,
                "flow_reliable": True,
            },
            {
                "record_type": "origin_vehicle_network_and_valuation_support",
                "period": "2024H1",
                "vehicle_type": "WETH",
                "active_origins": 27112,
                "flow_reliable": True,
            },
            {
                "record_type": "origin_vehicle_network_and_valuation_support",
                "period": "2026H1",
                "vehicle_type": "stable",
                "active_origins": 8721,
                "flow_reliable": True,
            },
            {
                "record_type": "origin_vehicle_network_and_valuation_support",
                "period": "2026H1",
                "vehicle_type": "WETH",
                "active_origins": 8696,
                "flow_reliable": True,
            },
        ]
    )


def _models() -> pd.DataFrame:
    coefficients = (0.0799294, 0.0306662, 0.0774354, 0.1598459)
    standard_errors = (0.0089307, 0.0091975, 0.0590205, 0.0730136)
    raw_p_values = (0.0001, 0.0009, 0.0100, 0.0010)
    adjusted_p_values = (0.0004, 0.0026, 0.1897, 0.0574)
    rows: list[dict[str, object]] = []
    for index, model in enumerate(MODEL_COLUMNS):
        broad = index < 2
        rows.append(
            {
                "model_id": model.model_id,
                "material_tvl_usd": 50_000.0,
                "lookback_days": 90,
                "supply_week_offset": 0,
                "coefficient": coefficients[index],
                "standard_error": standard_errors[index],
                "p_value": raw_p_values[index],
                "holm_adjusted_p_value": adjusted_p_values[index],
                "observations": 258_048 if broad else 24_396,
                "pool_clusters": 6_197 if broad else 1_807,
                "transaction_origin_clusters": 43_473 if broad else 6_312,
                "event_origin_fixed_effects": 64_512 if broad else 8_132,
                "candidate_quarter_fixed_effects": 84 if broad else 63,
                "outcome_mean": 0.25 if broad else 1 / 3,
                "inference": "two_way_pool_and_transaction_origin_clustered",
                "family_id": PRIMARY_FAMILY_ID,
                "family_size": 4,
                "specification_role": "primary",
            }
        )
    return pd.DataFrame(rows)


def test_v3_lp_provider_formation_renders_both_panels() -> None:
    rendered = render_v3_lp_provider_formation(
        _decomposition(), _support(), _models()
    )

    assert "Panel A. Stable-facing liquidity additions" in rendered
    assert "Panel B. Prior vehicle experience and pool formation" in rendered
    assert "Supplied vehicle is the pool's actual vehicle [0/1]" in rendered
    assert r"Outcome mean [\%]" in rendered
    assert r"Period-\\specific" in rendered
    assert "Origin entry/exit" not in rendered
    assert "Liquidity-addition actions & 8.5 & 44.2 & +35.71" in rendered
    assert "Vehicle-side USD additions & 8.1 & 41.5 & +33.48" in rendered
    assert "+0.01" in rendered
    assert "-0.05" in rendered
    assert "Active transaction origins, stable-facing & 3,841 & 8,721" in rendered
    assert "$+7.99^{***}$" in rendered
    assert "$+3.07^{***}$" in rendered
    assert "$+7.74$" in rendered
    assert "$+15.98^{*}$" in rendered
    assert "258,048" in rendered
    assert "43,473" in rendered
    assert "Pool, origin" in rendered


def test_stars_follow_holm_adjustment_not_raw_p_values() -> None:
    rendered = render_v3_lp_provider_formation(
        _decomposition(), _support(), _models()
    )

    # Column (3) has a raw p-value below 5 percent but an adjusted p-value of 0.19.
    assert "$+7.74$" in rendered
    assert "$+7.74^{" not in rendered
    # Column (4) has an adjusted p-value between 5 and 10 percent.
    assert "$+15.98^{*}$" in rendered


def test_v3_lp_provider_formation_values_cover_prose_inputs() -> None:
    values = render_v3_lp_provider_formation_values(
        _decomposition(), _support(), _models()
    )

    assert r"\newcommand{\VThreeLPBaselinePeriod}{2024 H1}" in values
    assert (
        r"\newcommand{\VThreeLPAddActionBaselineStableShare}{8.5\%}" in values
    )
    assert (
        r"\newcommand{\VThreeLPAddActionStableShareChange}{$+35.71$ pp}"
        in values
    )
    assert (
        r"\newcommand{\VThreeLPAddActionPeriodSpecificOrigins}{$+28.00$ pp}"
        in values
    )
    assert (
        r"\newcommand{\VThreeLPUSDFlowContinuingOriginReallocation}{$-0.05$ pp}"
        in values
    )
    assert (
        r"\newcommand{\VThreeLPStableFacingOriginsComparison}{8{,}721}"
        in values
    )
    assert (
        r"\newcommand{\VThreeLPSameVehicleSupplyEffect}{$+7.99$ pp}" in values
    )
    assert r"\newcommand{\VThreeLPSameVehicleSupplySE}{$0.89$ pp}" in values
    assert (
        r"\newcommand{\VThreeLPSameVehicleSupplyHolmP}{$p<0.001$}" in values
    )
    assert (
        r"\newcommand{\VThreeLPSameVehicleSupplyN}{258{,}048}" in values
    )
    assert (
        r"\newcommand{\VThreeLPSameStablecoinCoreSupplyHolmP}{$p=0.190$}"
        in values
    )
    assert (
        r"\newcommand{\VThreeLPSameStablecoinCoreBreadthHolmP}{$p=0.057$}"
        in values
    )


def test_v3_lp_provider_formation_values_have_unique_macro_names() -> None:
    values = render_v3_lp_provider_formation_values(
        _decomposition(), _support(), _models()
    )
    commands = [line for line in values.splitlines() if line.startswith(r"\newcommand")]
    names = [line.split("{")[1].removeprefix("\\") for line in commands]

    assert len(commands) == 48
    assert len(names) == len(set(names))


def test_v3_lp_provider_formation_rejects_incomplete_primary_family() -> None:
    with pytest.raises(ValueError, match="expected one V3 provider-formation model"):
        render_v3_lp_provider_formation(
            _decomposition(), _support(), _models().iloc[:-1]
        )


def test_v3_lp_provider_formation_rejects_unreliable_usd_values() -> None:
    support = _support()
    support.loc[
        support["period"].eq("2024H1") & support["vehicle_type"].eq("stable"),
        "flow_reliable",
    ] = False
    with pytest.raises(ValueError, match="valuation bound"):
        render_v3_lp_provider_formation(_decomposition(), support, _models())


def test_table_language_avoids_internal_research_terms() -> None:
    rendered = render_v3_lp_provider_formation(
        _decomposition(), _support(), _models()
    )
    audience_text = (rendered + " " + TABLE_NOTE).lower()
    for banned in ("candidate", "screen", "claim", "diagnos", "workflow"):
        assert banned not in audience_text
