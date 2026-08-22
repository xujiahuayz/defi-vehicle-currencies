from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_eth_stress_supply_transmission import (
    CHAIN_CELLS,
    LP_ROWS,
    STRESS_COLUMNS,
    TABLE_NOTE,
    render_eth_stress_supply_transmission,
    render_eth_stress_supply_transmission_values,
)


def _lp_models() -> pd.DataFrame:
    effects = {
        ("EthStressVThreeAdditions", "stable_x_eth_realized_volatility"): (
            0.004531,
            0.002364,
            0.056467,
            0.225869,
        ),
        ("EthStressVThreeAdditions", "stable_x_eth_decline"): (
            0.004054,
            0.006499,
            0.533341,
            1.0,
        ),
        ("EthStressVThreeWithdrawals", "stable_x_eth_realized_volatility"): (
            0.004434,
            0.002313,
            0.056383,
            0.225531,
        ),
        ("EthStressVThreeWithdrawals", "stable_x_eth_decline"): (
            0.000152,
            0.006367,
            0.981025,
            1.0,
        ),
        ("EthStressVThreeNetSupply", "stable_x_eth_realized_volatility"): (
            0.000266,
            0.000403,
            0.508742,
            1.0,
        ),
        ("EthStressVThreeNetSupply", "stable_x_eth_decline"): (
            0.002740,
            0.001138,
            0.01678557,
            0.0671423,
        ),
        ("EthStressVTwoNetLiquidity", "stable_x_eth_realized_volatility"): (
            0.000256,
            0.000246,
            0.298715,
            0.597430,
        ),
        ("EthStressVTwoNetLiquidity", "stable_x_eth_decline"): (
            -0.000164,
            0.000778,
            0.833569,
            0.833569,
        ),
    }
    rows: list[dict[str, object]] = []
    for definition in LP_ROWS:
        for predictor, _, _ in STRESS_COLUMNS:
            coefficient, standard_error, p_value, holm_p_value = effects[
                (definition.macro_prefix, predictor)
            ]
            v3 = definition.venue == "uniswap_v3"
            rows.append(
                {
                    "record_type": "lp_stable_demand_stress_coefficient",
                    "venue": definition.venue,
                    "outcome_name": definition.outcome_name,
                    "outcome": definition.outcome,
                    "multiplicity_family": definition.family,
                    "predictor": predictor,
                    "coefficient": coefficient,
                    "standard_error": standard_error,
                    "p_value": p_value,
                    "holm_p_value": holm_p_value,
                    "focal_family_member": True,
                    "effect_unit": (
                        "per_10pp_higher_annualized_weekly_eth_volatility"
                        if predictor == "stable_x_eth_realized_volatility"
                        else "per_0p10_log_point_eth_price_fall"
                    ),
                    "material_capital_usd": 50_000.0,
                    "observations": 51_086 if v3 else 19_844,
                    "pools": 1_410 if v3 else 559,
                    "weeks": 238 if v3 else 313,
                    "fixed_effects": "endpoint_x_week+pool",
                    "covariance": "pool_and_week_cluster_cr1",
                    "stress_timing": "week_t_monday_through_sunday",
                    "outcome_timing": "week_t_plus_1",
                    "conditioning": (
                        "prior_four_week_fee_yield+pair_relative_volatility+"
                        "additions+withdrawals+pool_capital+pool_age"
                    ),
                    "interpretation": (
                        "predictive_stablecoin_minus_weth_lp_supply_response"
                    ),
                    "route_use_variables": "none",
                }
            )
    return pd.DataFrame(rows)


def _lp_support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "lp_stable_demand_stress_sample_support",
                "venue": "uniswap_v2",
                "comparison": (
                    "stablecoin_leg_minus_weth_leg_for_same_endpoint_week"
                ),
                "route_use_variables": "none",
                "observations": 19_844,
                "pools": 559,
                "weeks": 313,
            },
            {
                "record_type": "lp_stable_demand_stress_sample_support",
                "venue": "uniswap_v3",
                "comparison": (
                    "stablecoin_leg_minus_weth_leg_for_same_endpoint_week"
                ),
                "route_use_variables": "none",
                "observations": 51_086,
                "pools": 1_410,
                "weeks": 238,
            },
        ]
    )


def _chain_models() -> pd.DataFrame:
    values = {
        "EthStressDeclineRelativeDepth": (-0.000488, 0.023812, 0.983700, 1.0),
        "EthStressDeclineOutput": (0.001536, 0.010525, 0.884384, 1.0),
        "EthStressDeclineChoice": (0.000698, 0.002475, 0.778847, 1.0),
        "EthStressDepthOutput": (0.190952, 0.028980, 6.27e-9, float("nan")),
        "EthStressDepthChoice": (0.028735, 0.004963, 1.71e-7, float("nan")),
        "EthStressOutputChoice": (0.103345, 0.006891, 7.59e-24, float("nan")),
    }
    rows: list[dict[str, object]] = []
    for definition in CHAIN_CELLS:
        coefficient, standard_error, p_value, holm_p_value = values[
            definition.macro_prefix
        ]
        rows.append(
            {
                "record_type": "eth_stress_executability_regression",
                "model_id": definition.model_id,
                "outcome": definition.outcome,
                "predictor": definition.predictor,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "p_value": p_value,
                "holm_p_value": holm_p_value,
                "observations": 24_313,
                "ordered_pairs": 915,
                "dates": 73,
                "fixed_effects": "ordered_pair+calendar_month",
                "time_controls": "linear_calendar_time_in_years",
                "date_effects": (
                    "not_absorbed_marketwide_eth_return_is_date_level"
                ),
                "covariance": "ordered_pair_and_exact_date_cluster_cr1",
                "stress_timing": (
                    "canonical_weth_return_days_minus_30_through_minus_1"
                ),
                "exact_route_state": (
                    "same_pair_notional_pretrade_state_and_public_venue_set"
                ),
                "causal_interpretation": False,
            }
        )
    return pd.DataFrame(rows)


def _chain_support() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "eth_stress_executability_support",
                "depth_interpretation": (
                    "mark_to_market_pool_state_not_provider_flow"
                ),
                "depth_measure": (
                    "prior_calendar_v2_sushiv2_weak_leg_deposited_usd_capital"
                ),
                "output_interpretation": (
                    "exact_executable_output_same_pretrade_state"
                ),
                "choice_interpretation": (
                    "realised_vehicle_family_conditional_both_feasible"
                ),
                "lp_withdrawal_interpretation": (
                    "measured_separately_not_in_this_output"
                ),
                "common_positive_depth_rows": 24_973,
                "common_positive_depth_share_of_contestable": 0.475196,
                "median_input_usd": 2_000.0,
            }
        ]
    )


def test_eth_stress_supply_transmission_renders_two_compact_panels() -> None:
    rendered = render_eth_stress_supply_transmission(
        _lp_models(), _lp_support(), _chain_models(), _chain_support()
    )

    assert "Panel A. Stablecoin-minus-WETH liquidity-supply responses" in rendered
    assert "ETH price fall [0.10 log point]" in rendered
    assert "10 pp ETH decline" not in rendered
    assert "v3 additions" in rendered
    assert "v2 net liquidity units" in rendered
    assert "$+0.0027^{*}$" in rendered
    assert "$+0.0045^{" not in rendered
    assert "Panel B. ETH-price declines, weak-leg capital, quotes, and route use" in rendered
    assert r"ETH price fall, days $-30$ to $-1$ [0.10 log point]" in rendered
    assert "$-0.0005$" in rendered
    assert "$+19.10^{***}$" in rendered
    assert "$+2.87^{***}$" in rendered
    assert "$+10.33^{***}$" in rendered
    assert "24,313 & 24,313 & 24,313" in rendered


def test_primary_chain_and_capital_price_choice_links_use_separate_holm_families() -> None:
    chain = _chain_models()
    chain.loc[
        chain["model_id"].eq("m1_relative_usd_depth"), "p_value"
    ] = 0.001
    conditional = chain["model_id"].isin(
        [
            "m4_output_advantage_conditioned_on_depth",
            "m5_realised_choice_conditioned_on_output_and_depth",
        ]
    )
    chain.loc[conditional, "p_value"] = 0.04
    rendered = render_eth_stress_supply_transmission(
        _lp_models(), _lp_support(), chain, _chain_support()
    )

    assert "$-0.0005^{" not in rendered
    assert "$+19.10^{" not in rendered
    assert "$+2.87^{" not in rendered
    assert "$+10.33^{" not in rendered


def test_generated_values_cover_supply_and_transmission_results() -> None:
    values = render_eth_stress_supply_transmission_values(
        _lp_models(), _lp_support(), _chain_models(), _chain_support()
    )

    assert (
        r"\newcommand{\EthStressVThreeNetSupplyDeclineEffect}{$+0.0027$}"
        in values
    )
    assert (
        r"\newcommand{\EthStressVThreeNetSupplyDeclineRawP}{$p=0.017$}"
        in values
    )
    assert (
        r"\newcommand{\EthStressVThreeNetSupplyDeclineHolmP}{$p=0.067$}"
        in values
    )
    assert (
        r"\newcommand{\EthStressVThreeNetSupplyDeclineHolmValue}{$0.067$}"
        in values
    )
    assert (
        r"\newcommand{\EthStressDeclineRelativeDepthEffect}{$-0.0005$}"
        in values
    )
    assert (
        r"\newcommand{\EthStressDepthOutputEffect}{$+19.10$ bp}" in values
    )
    assert (
        r"\newcommand{\EthStressOutputChoiceEffect}{$+10.33$ pp}" in values
    )
    assert r"\newcommand{\EthStressExecutionN}{24{,}313}" in values
    assert r"\newcommand{\EthStressPositiveDepthCoverage}{47.5\%}" in values


def test_generated_values_have_unique_macro_names() -> None:
    values = render_eth_stress_supply_transmission_values(
        _lp_models(), _lp_support(), _chain_models(), _chain_support()
    )
    commands = [line for line in values.splitlines() if line.startswith(r"\newcommand")]
    names = [line.split("{")[1].removeprefix("\\") for line in commands]

    assert len(names) == len(set(names))


def test_note_states_inference_and_accounting_boundary() -> None:
    lowered = TABLE_NOTE.lower()
    assert "mark-to-market pool state" in lowered
    assert "panel a measures provider flows" in lowered
    assert "endpoint-by-week and pool fixed effects" in lowered
    assert "cluster standard errors by pool and week" in lowered
    assert "pair and month-of-year fixed effects" in lowered
    assert "cluster standard errors by pair and exact date" in lowered
    assert "raw $p=0.017$ and holm $p=0.067$" in lowered
    assert "addition and withdrawal components are individually imprecise" in lowered
    assert "separate holm family" in lowered


def test_renderer_rejects_changed_v3_decline_net_inference() -> None:
    models = _lp_models()
    mask = (
        models["venue"].eq("uniswap_v3")
        & models["outcome_name"].eq("net_supply")
        & models["predictor"].eq("stable_x_eth_decline")
    )
    models.loc[mask, "holm_p_value"] = 0.20

    with pytest.raises(ValueError, match="Holm p-value changed"):
        render_eth_stress_supply_transmission(
            models, _lp_support(), _chain_models(), _chain_support()
        )
