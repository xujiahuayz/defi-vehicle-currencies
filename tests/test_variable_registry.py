from __future__ import annotations

import unittest
from pathlib import Path

from ddvc.paper_tables import _latex_escape, validate_output_stem
from ddvc.variable_registry import (
    NOTATION_DEFINITIONS,
    OBSERVATIONS_TABLE_COLUMNS,
    SUMMARY_SPECS,
    VARIABLE_SPECS,
)


class VariableRegistryTests(unittest.TestCase):
    def test_registered_columns_are_unique(self) -> None:
        columns = [spec.column for spec in VARIABLE_SPECS]
        self.assertEqual(len(columns), len(set(columns)))

    def test_summary_specs_are_observation_columns(self) -> None:
        observation_columns = set(OBSERVATIONS_TABLE_COLUMNS)
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.column, observation_columns)
            self.assertIsNotNone(spec.summary_unit, spec.column)
        self.assertIn("direct_quote_quality_median", {spec.column for spec in SUMMARY_SPECS})

    def test_summary_statistics_use_canonical_registry_notation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        renderer = (
            root / "scripts" / "tabulate" / "render_summary_statistics.py"
        ).read_text(encoding="utf-8")
        self.assertIn("spec.notation", renderer)
        self.assertNotIn("summary_label", renderer)
        rendered_path = root / "output" / "tables" / "summary_statistics.tex"
        preview_path = root / "output" / "tables" / "summary_statistics.pdf"
        self.assertEqual(rendered_path.exists(), preview_path.exists())
        if not rendered_path.exists():
            return
        rendered = rendered_path.read_text(encoding="utf-8")
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.notation, rendered, spec.column)

    def test_core_bridge_and_route_cost_variables_are_registered(self) -> None:
        columns = set(OBSERVATIONS_TABLE_COLUMNS)
        self.assertLessEqual(
            {
                "bridge_share",
                "all_route_bridge_share",
                "vol_share",
                "lp_capital_share",
                "direct_available_share",
                "direct_quote_quality_median",
                "no_direct_vehicle_available_share",
                "direct_cost_advantage_median",
            },
            columns,
        )

    def test_count_and_value_dominance_have_identical_support_variants(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        expected = {
            "intermediate_count_share_within_20pct",
            "endpoint_count_share_within_20pct",
            "vehicle_excess_use_count_ratio_within_20pct",
            "intermediate_share_within_20pct",
            "endpoint_share_within_20pct",
            "vehicle_excess_use_ratio_within_20pct",
        }
        self.assertTrue(expected.issubset(by_column))
        for column in expected:
            spec = by_column[column]
            self.assertIn("20", spec.notation)
            self.assertIn("vehicle_excess_use_daily.parquet", spec.source)

    def test_transaction_frontier_efficiency_variables_are_registered(self) -> None:
        columns = {spec.column for spec in VARIABLE_SPECS}
        self.assertLessEqual(
            {
                "chosen_validation_error_bps",
                "chosen_validation_max_abs_error_bps",
                "within_reach_search_regret_bps",
                "reach_increment_bps",
                "path_choice_increment_bps",
                "public_path_regret_bps",
                "direct_omission_bps",
            },
            columns,
        )

    def test_notation_key_defines_route_indices_and_superscripts(self) -> None:
        notation = " ".join(item.notation for item in NOTATION_DEFINITIONS)
        definitions = " ".join(item.definition for item in NOTATION_DEFINITIONS)
        for symbol in [
            "$i,\\ o$",
            "$k$",
            "$h$",
            "$\\ell,\\ p,\\ p'$",
            "$t,\\ u,\\ w$",
            "$d,\\ \\mu$",
            "$c$",
            "$q$",
            "$r$",
        ]:
            self.assertIn(symbol, notation)
        self.assertIn(r"superscripts $D$ and $I$", definitions)
        self.assertIn(r"superscript $I$ denotes indirect", definitions)

    def test_paper_route_notation_uses_input_output_endpoints(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry_text = " ".join(
            item.notation + " " + item.definition for item in NOTATION_DEFINITIONS
        )
        # Repointed from paper/jfe_detailed_outline.md, deleted when the node G
        # spine superseded it. The check is on the paper-facing document, whichever
        # file currently holds that role.
        paper_text = (root / "docs" / "paper-spine.md").read_text(encoding="utf-8")
        rendered_text = (root / "output" / "tables" / "variable_notation.tex").read_text(
            encoding="utf-8"
        )
        canonical_text = " ".join([registry_text, paper_text, rendered_text])

        self.assertIn(r"$(i,o)$ is an ordered input--output pair", registry_text)
        self.assertIn(r"$i\to k\to o$", registry_text)
        self.assertIn(r"$O^{D}_{i,o,q,t},\ O^{I}_{i,o,k,q,t}$", registry_text)
        self.assertIn(r"N^{\mathrm{in}}_{k,t}", registry_text)
        self.assertIn(r"N^{\mathrm{out}}_{k,t}", registry_text)
        self.assertIn(r"\mathrm{LegVol}^{\mathrm{in}}_{k,t}", registry_text)
        self.assertIn(r"\mathrm{Vol}^{\mathrm{in}}_{k,t}", registry_text)

        for retired in [
            "source-to-sink",
            "source-sink",
            "source or sink",
            r"$i,\ j$",
            r"(i,j)",
            r"\{i,j\}",
            r"N^{\mathrm{src}}",
            r"N^{\mathrm{sink}}",
            r"\mathrm{Vol}^{\mathrm{src}}",
            r"\mathrm{Vol}^{\mathrm{sink}}",
        ]:
            self.assertNotIn(retired, canonical_text)

    def test_symbol_definitions_run_broad_to_narrow(self) -> None:
        by_notation = {item.notation: item.definition for item in NOTATION_DEFINITIONS}

        bridge_definition = by_notation[
            r"$\mathrm{IVol}_t,\ \mathrm{IVol}_{k,t}$"
        ]
        self.assertLess(
            bridge_definition.index(r"$\mathrm{IVol}_t"),
            bridge_definition.index(r"$\mathrm{IVol}_{k,t}"),
        )
        self.assertIn(
            r"$0\le\mathrm{IVol}_{k,t}\le\mathrm{IVol}_t$",
            bridge_definition,
        )
        self.assertNotIn(r"\sum", bridge_definition)

        volume_definition = by_notation[r"$\mathrm{Vol}_t,\ \mathrm{DVol}_t$"]
        self.assertIn(
            r"$0\le\mathrm{DVol}_t\le\mathrm{Vol}_t$",
            volume_definition,
        )

        pair_volume_definition = by_notation[
            r"$\mathrm{Vol}_{i,o,t},\ \mathrm{IVol}_{i,o,t},\ \mathrm{IVol}_{i,o,k,t}$"
        ]
        self.assertIn(
            r"$0\le\mathrm{IVol}_{i,o,k,t}\le\mathrm{IVol}_{i,o,t}"
            r"\le\mathrm{Vol}_{i,o,t}$",
            pair_volume_definition,
        )

        pair_definition = by_notation[r"$\mathcal A_t,\ \mathcal A^k_t,\ \mathcal M^k_t$"]
        self.assertIn(
            r"$\mathcal M^k_t\subseteq\mathcal A^k_t\subseteq\mathcal A_t$",
            pair_definition,
        )

        settlement_definition = by_notation[r"$\mathcal{R}^{\mathrm{transfer}}_{k,w}$"]
        self.assertIn(
            r"$\mathcal R^{\mathrm{transfer}}_{k,w}\subseteq\mathcal R_{k,w}$",
            settlement_definition,
        )

    def test_route_units_count_routes_not_legs(self) -> None:
        by_notation = {item.notation: item.definition for item in NOTATION_DEFINITIONS}
        route_definition = by_notation[r"$r$"]
        count_definition = by_notation[
            r"$N_t,\ N^{\mathrm{in}}_{k,t},\ N^{\mathrm{out}}_{k,t}$"
        ]
        self.assertIn(r"contributes one $r$ regardless of its number of legs", route_definition)
        self.assertIn("not their individual legs", count_definition)

    def test_indicators_put_the_condition_in_the_subscript(self) -> None:
        notation = " ".join(item.notation for item in NOTATION_DEFINITIONS)
        formulas = " ".join(spec.formula for spec in VARIABLE_SPECS)
        self.assertIn(r"\mathbf{1}_{\{\cdot\}}", notation)
        self.assertIn(r"\mathbf{1}_{\{\mathrm{Stress}_{t}\ge 0.08\}}", formulas)
        self.assertNotIn(r"\mathbf{1}\{", notation + formulas)

    def test_volume_share_uses_the_unambiguous_name(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        self.assertIn("vol_share", by_column)
        self.assertEqual(by_column["vol_share"].notation, r"$\mathrm{VolShare}_{k,t}$")
        self.assertNotIn("vshare", by_column)

    def test_each_quantity_has_one_canonical_symbol(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        expected = {
            "bridge_volume_usd": r"$\mathrm{IVol}_{k,t}$",
            "daily_all_route_volume_usd": r"$\mathrm{Vol}_t$",
            "daily_indirect_route_volume_usd": r"$\mathrm{IVol}_t$",
            "vehicle_linked_capital_usd": r"$C_{k,t}$",
            "delta_bridge_share_t7": r"$\Delta_{\tau}\mathrm{VehicleShare}_{k,t}$",
        }
        for column, symbol in expected.items():
            with self.subTest(column=column):
                self.assertEqual(by_column[column].notation, symbol)

        notations = [spec.notation for spec in VARIABLE_SPECS]
        self.assertEqual(len(notations), len(set(notations)))
        notation_text = " ".join(notations)
        for duplicate_alias in [
            r"\mathrm{AllRouteVolume}",
            r"\mathrm{IndirectRouteVolume}",
            r"\mathrm{VehicleVolume}",
            r"\mathrm{VehicleLiquidity}",
            r"\mathrm{FutureVehicleShare}",
        ]:
            self.assertNotIn(duplicate_alias, notation_text)

    def test_proposed_rq_design_variables_are_registered_but_not_materialized(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        expected = {
            "actual_vehicle_share": r"$\mathrm{VehicleShare}_{i,o,k,t}$",
            "pair_indirect_route_share": r"$\mathrm{IndirectRouteShare}_{i,o,t}$",
            "pair_candidate_vehicle_coverage": (
                r"$\mathrm{Coverage}^{\mathcal K}_{i,o,t}$"
            ),
            "pair_vehicle_hhi": r"$\mathrm{VehicleHHI}_{i,o,t}$",
            "any_indirect_available": r"$\mathrm{AnyIndirectAvailable}_{i,o,q,t}$",
            "pair_direct_quote_quality": r"$\mathrm{DirectQuoteQuality}_{i,o,q,t}$",
            "pair_indirect_quote_quality": r"$\mathrm{IndirectQuoteQuality}_{i,o,k,q,t}$",
            "pair_direct_fee_cost": r"$C^{D,\mathrm{fee}}_{i,o,q,t}$",
            "pair_direct_price_impact_cost": r"$C^{D,\mathrm{impact}}_{i,o,q,t}$",
            "pair_direct_gas_cost": r"$C^{D,\mathrm{gas}}_{i,o,q,t}$",
            "pair_indirect_fee_cost": r"$C^{I,\mathrm{fee}}_{i,o,k,q,t}$",
            "pair_indirect_price_impact_cost": r"$C^{I,\mathrm{impact}}_{i,o,k,q,t}$",
            "pair_indirect_gas_cost": r"$C^{I,\mathrm{gas}}_{i,o,k,q,t}$",
            "candidate_downside_stress": r"$\mathrm{CandidateStress}_{k,t}$",
            "incumbent_vehicle": r"$\mathrm{Incumbent}_{i,o,k,t}$",
            "challenger_cost_edge": r"$\mathrm{ChallengerCostEdge}_{i,o,q,t}$",
            "vehicle_switch": r"$\mathrm{VehicleSwitch}_{i,o,q,t,\tau}$",
            "pre_v3_direct_constraint": r"$\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}$",
            "post_v3": r"$\mathrm{PostV3}_{t}$",
            "vehicle_capital_factor_loo": r"$\mathrm{VehicleCapitalFactor}_{p,k,t}$",
            "market_capital_factor_loo": r"$\mathrm{MarketCapitalFactor}_{p,t}$",
            "pool_vehicle_route_share": r"$\mathrm{VehicleRouteShare}_{p,k,t}$",
            "lp_active_capital_usd": r"$L_{a,p,t}$",
            "lp_pool_capital_share": r"$w_{a,p,t}$",
            "lp_net_flow_usd": r"$F^{\mathrm{LP}}_{a,p,t}$",
            "lp_fee_yield": r"$\mathrm{LPFeeYield}_{a,p,t}$",
            "lp_lvr": r"$\mathrm{LVR}_{a,p,t}$",
            "lp_net_return": r"$\mathrm{LPNetReturn}_{a,p,t}$",
            "lp_other_pool_return": r"$R^{\mathrm{other}}_{a,-p,t}$",
            "lp_predicted_other_pool_shock": r"$Z^{\mathrm{other}}_{a,-p,t}$",
            "pool_lp_wealth_shock": r"$\mathrm{LPWealthShock}_{p,t}$",
            "lp_provider_overlap": r"$\mathrm{LPOverlap}_{p,p',t}$",
            "pair_all_in_direct_cost": r"$C^{D}_{i,o,q,t}$",
            "pair_all_in_indirect_cost": r"$C^{I}_{i,o,k,q,t}$",
            "pair_all_in_direct_cost_advantage": r"$\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$",
            "all_in_direct_cost_advantage_median": (
                r"$\mathrm{AllInDirectCostAdvantage}_{k,t,q}$"
            ),
            "v4_route": r"$\mathrm{V4}_{r}$",
            "v4_route_share": r"$\mathrm{V4RouteShare}_{c}$",
            "pre_v4_pair_indirect_route_share": r"$\mathrm{PreV4IndirectShare}_{i,o}$",
            "post_v4": r"$\mathrm{PostV4}_{t}$",
            "pre_v3_pair_volatility": r"$\sigma^{\mathrm{pre}}_{i,o}$",
            "pool_band_depth_capital_efficiency": r"$\eta^{\mathrm{Band}}_{p,t,b,d}$",
            "physical_vehicle_movement_usd": r"$M_{r,k}$",
            "physical_settlement_intensity": r"$\mathrm{SettlementIntensity}_{r,k}$",
            "vehicle_capital_turnover": r"$\mathrm{VehicleTurnover}_{k,t}$",
            "pre_v4_pool_vehicle_route_exposure": (
                r"$\mathrm{VehicleRouteExposure}^{\mathrm{pre}}_{p,k}$"
            ),
        }
        for column, notation in expected.items():
            with self.subTest(column=column):
                self.assertIn(column, by_column)
                self.assertEqual(by_column[column].notation, notation)
                self.assertFalse(by_column[column].in_observations_table)
                self.assertNotIn(column, OBSERVATIONS_TABLE_COLUMNS)

    def test_revised_rq_measurements_have_explicit_constructions(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        expected_units = {
            "pair_all_in_direct_cost": "Fraction",
            "pair_all_in_indirect_cost": "Fraction",
            "pair_all_in_direct_cost_advantage": "Fraction",
            "pair_direct_fee_cost": "Fraction",
            "pair_direct_price_impact_cost": "Fraction",
            "pair_direct_gas_cost": "Fraction",
            "pair_indirect_fee_cost": "Fraction",
            "pair_indirect_price_impact_cost": "Fraction",
            "pair_indirect_gas_cost": "Fraction",
            "lp_active_capital_usd": "USD",
            "lp_net_flow_usd": "USD per day",
            "lp_fee_yield": "Daily fraction",
            "lp_lvr": "Daily fraction",
            "lp_net_return": "Daily fraction",
            "lp_predicted_other_pool_shock": "Daily return fraction",
            "physical_vehicle_movement_usd": "USD",
            "physical_settlement_intensity": "USD transferred per gross vehicle-leg USD",
            "vehicle_capital_turnover": "USD vehicle volume per USD deposited capital per day",
        }
        for column, unit in expected_units.items():
            with self.subTest(column=column):
                self.assertEqual(by_column[column].unit, unit)
                self.assertTrue(by_column[column].construction)

        self.assertEqual(by_column["lp_active_capital_usd"].formula, "")
        self.assertEqual(by_column["lp_net_flow_usd"].formula, "")
        self.assertEqual(by_column["physical_vehicle_movement_usd"].formula, "")
        self.assertIn(
            r"C^{I}_{i,o,k,q,t}-C^{D}_{i,o,q,t}",
            by_column["pair_all_in_direct_cost_advantage"].formula,
        )
        self.assertIn(
            r"\mathrm{LPFeeYield}_{a,p,t}-\mathrm{LVR}_{a,p,t}",
            by_column["lp_net_return"].formula,
        )
        self.assertIn(
            r"M_{r,k}",
            by_column["physical_settlement_intensity"].formula,
        )
        self.assertIn(
            r"\omega_{a,x,-p,t-1}R_{x,t}",
            by_column["lp_predicted_other_pool_shock"].formula,
        )
        self.assertIn(
            r"Z^{\mathrm{other}}_{a,-p,t}",
            by_column["pool_lp_wealth_shock"].formula,
        )

    def test_pair_vehicle_hhi_is_conditional_on_candidate_coverage(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        coverage = by_column["pair_candidate_vehicle_coverage"]
        concentration = by_column["pair_vehicle_hhi"]
        self.assertIn(
            r"\sum_{k\in\mathcal K\setminus\{i,o\}}\mathrm{VehicleShare}_{i,o,k,t}",
            coverage.formula,
        )
        self.assertIn(
            r"\mathrm{Coverage}^{\mathcal K}_{i,o,t}",
            concentration.formula,
        )
        self.assertIn("renormalizing their shares to sum to one", concentration.construction)

    def test_challenger_is_selected_and_ranked_by_all_in_cost(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        challenger = by_column["challenger_cost_edge"]
        self.assertEqual(
            challenger.formula,
            r"$C^I_{i,o,k^\star,q,t}-C^I_{i,o,h^\star,q,t}$",
        )
        self.assertIn("All-in cost advantage", challenger.construction)
        self.assertNotIn(r"O^I", challenger.formula)

        incumbent_objects = next(
            item for item in NOTATION_DEFINITIONS if r"h^\star_{i,o,q,t}" in item.notation
        )
        self.assertIn("smallest", incumbent_objects.definition)
        self.assertIn(r"$C^I_{i,o,h,q,t}$", incumbent_objects.definition)

    def test_pre_v4_pair_share_uses_only_positive_volume_days(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        pre_share = by_column["pre_v4_pair_indirect_route_share"]
        self.assertIn(r"\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}", pre_share.formula)
        self.assertIn("positive-volume days", pre_share.construction)

        architecture = next(
            item
            for item in NOTATION_DEFINITIONS
            if r"\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}" in item.notation
        )
        self.assertIn(
            r"$\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}\subseteq"
            r"\mathcal T^{\mathrm{V4}}_{\mathrm{pre}}$",
            architecture.definition,
        )
        self.assertIn(r"$\mathrm{Vol}_{i,o,t}>0$", architecture.definition)

    def test_formula_cells_are_blank_or_actual_calculations(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        registered_notations = {spec.notation for spec in VARIABLE_SPECS}
        for column in [
            "bridge_volume_usd",
            "daily_indirect_route_volume_usd",
        ]:
            self.assertEqual(by_column[column].formula, "")

        for spec in VARIABLE_SPECS:
            if not spec.formula:
                continue
            self.assertTrue(spec.formula.startswith("$"), spec.column)
            self.assertNotEqual(spec.notation, spec.formula, spec.column)
            self.assertNotIn(spec.formula, registered_notations, spec.column)
            self.assertNotIn(r"\equiv", spec.formula, spec.column)

    def test_dynamic_notation_is_parameterized_and_ends_at_t(self) -> None:
        by_notation = {item.notation: item for item in NOTATION_DEFINITIONS}
        tau = by_notation[r"$\tau$"]
        delta = by_notation[r"$\Delta_{\tau}$"]
        self.assertEqual(tau.unit, "Days")
        self.assertEqual(delta.unit, "")
        self.assertIn("selected ex ante for each dynamic specification", tau.definition)
        self.assertIn(r"\Delta_\tau X_t=X_t-X_{t-\tau}", delta.definition)

        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        change = by_column["delta_bridge_share_t7"]
        self.assertEqual(
            change.formula,
            r"$\mathrm{VehicleShare}_{k,t}-\mathrm{VehicleShare}_{k,t-\tau}$",
        )
        canonical_text = " ".join(
            [spec.notation + " " + spec.formula for spec in VARIABLE_SPECS]
            + [item.notation + " " + item.definition for item in NOTATION_DEFINITIONS]
        )
        self.assertNotIn(r"\mathrm{VehicleShare}_{k,t+", canonical_text)
        self.assertNotIn(r"\Delta_{7}", canonical_text)

    def test_architecture_pair_universe_is_fixed_before_v3(self) -> None:
        by_notation = {item.notation: item for item in NOTATION_DEFINITIONS}
        architecture = next(
            item
            for item in NOTATION_DEFINITIONS
            if r"\mathcal P^{\mathrm{V3}}_q" in item.notation
        )
        self.assertIn("fixed 180-calendar-day window", architecture.definition)
        self.assertIn("positive realized route volume on at least 30 days", architecture.definition)
        self.assertIn("independent of post-V3 activity", architecture.definition)

        settlement = by_notation[r"$\mathcal R^3_c,\ \mathcal R^4_c$"]
        self.assertIn("A matched stratum has both sets nonempty", settlement.definition)

    def test_quote_universe_has_an_explicit_sample_rule(self) -> None:
        by_notation = {item.notation: item for item in NOTATION_DEFINITIONS}
        definition = by_notation[r"$\mathcal{P}_{k,t,q}$"].definition
        for required in [
            "200 largest",
            r"\texttt{single}",
            r"\texttt{coherent}",
            r"$k\notin\{i,o\}$",
            "at least three finite token-side",
            "USD-per-token observations",
            "at least 75 percent",
            "fivefold band",
            "volume-weighted median inside that consensus band",
            "does not require either quote to execute",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, definition)
        self.assertNotIn(r"\\texttt", definition)
        self.assertNotIn("eligible", definition.lower())

    def test_network_formulas_reuse_existing_route_symbols(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        count_formula = by_column["betweenness_centrality"].formula
        volume_formula = by_column["volume_weighted_betweenness"].formula
        self.assertIn(r"N^{I}_{k,t}", count_formula)
        self.assertIn(r"N_t", count_formula)
        self.assertIn(r"\mathrm{IVol}_{k,t}", volume_formula)
        self.assertIn(r"\mathrm{Vol}_t", volume_formula)

        symbol_key = " ".join(item.notation for item in NOTATION_DEFINITIONS)
        for duplicate_symbol in [
            r"N^{\mathrm{mid}}_{k,t}",
            r"N^{\mathrm{route}}_t",
            r"N^B_t",
            r"\mathrm{Vol}^{\mathrm{mid}}_{k,t}",
            r"\mathrm{Vol}^{\mathrm{route}}_t",
            r"\mathrm{Betweenness}^{\mathrm{vol}}",
        ]:
            self.assertNotIn(duplicate_symbol, symbol_key)

    def test_route_alternative_uses_indirect_not_vehicle_notation(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        expected = {
            "vehicle_available_share": r"$\mathrm{IndirectAvailable}_{k,t,q}$",
            "no_direct_vehicle_available_share": r"$\mathrm{IndirectOnlyAvailable}_{k,t,q}$",
            "vehicle_beats_direct_share": r"$\mathrm{IndirectBeatsDirect}_{k,t,q}$",
            "direct_cost_advantage_median": r"$\mathrm{DirectCostAdvantage}_{k,t,q}$",
        }
        for column, notation in expected.items():
            with self.subTest(column=column):
                self.assertEqual(by_column[column].notation, notation)

        symbol_key = " ".join(
            item.notation + " " + item.definition for item in NOTATION_DEFINITIONS
        )
        formulas = " ".join(spec.formula for spec in VARIABLE_SPECS)
        for retired_symbol in [
            r"N^{\mathrm{route}}_t",
            r"N^B_t",
            r"\mathcal V_{k,t,q}",
            r"\mathcal{V}_{k,t,q}",
            r"V_{i,o,k,q,t}",
            r"O^V_{i,o,k,q,t}",
            r"O^{V}_{i,o,k,q,t}",
        ]:
            self.assertNotIn(retired_symbol, symbol_key + formulas)

        retained_vehicle_notation = " ".join(spec.notation for spec in VARIABLE_SPECS)
        self.assertIn(r"\mathrm{VehicleShare}_{k,t}", retained_vehicle_notation)
        self.assertIn(r"\mathrm{MainVehiclePairShare}_{k,t}", retained_vehicle_notation)

    def test_total_volume_uses_descriptive_notation(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        total = by_column["daily_all_route_volume_usd"]
        self.assertEqual(total.notation, r"$\mathrm{Vol}_t$")
        self.assertEqual(total.formula, r"$\mathrm{DVol}_t+\mathrm{IVol}_t$")
        self.assertNotIn(r"$A_t$", [spec.notation for spec in VARIABLE_SPECS])

    def test_candidate_linked_capital_has_an_explicit_allocation_rule(self) -> None:
        by_notation = {item.notation: item.definition for item in NOTATION_DEFINITIONS}
        candidate_definition = by_notation[r"$\mathcal K$"]
        pool_definition = by_notation[r"$\mathcal L_t,\ \mathcal L_{k,t},\ m_p$"]
        capital_definition = by_notation[r"$\mathrm{Capital}_{p,t},\ C_{k,t}$"]
        for token in ["WETH", "USDC", "USDT", "DAI", "WBTC"]:
            self.assertIn(token, candidate_definition)
        self.assertNotIn("FRAX", candidate_definition)
        self.assertIn(r"$m_p\in\{1,2\}$", pool_definition)
        self.assertIn(r"$\mathcal L_{k,t}\subseteq\mathcal L_t$", pool_definition)
        self.assertIn("exact token contracts", pool_definition)
        self.assertIn("protocols whose deposited-capital contract", pool_definition)
        self.assertIn("one half to each", capital_definition)

        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        formula = by_column["vehicle_linked_capital_usd"].formula
        self.assertEqual(
            formula,
            r"$\displaystyle\sum_{p\in\mathcal L_{k,t}}\frac{\mathrm{Capital}_{p,t}}{m_p}$",
        )

    def test_thin_direct_is_a_quote_quality_subset(self) -> None:
        symbol_key = " ".join(item.definition for item in NOTATION_DEFINITIONS)
        self.assertIn("thin-direct subset", symbol_key)
        self.assertNotIn("thin-direct support", symbol_key)

        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        construction = by_column["thin_direct_share"].construction
        self.assertIn(r"$O^D_{i,o,q,t}/q<0.9$", construction)
        self.assertIn("quote-quality proxy", construction)
        self.assertIn("not a direct measure", construction)

        root = Path(__file__).resolve().parents[1]
        decomposition = (
            root / "scripts" / "run_claim_defense_analytics.py"
        ).read_text(encoding="utf-8")
        self.assertIn("direct_quality < 0.90", decomposition)
        self.assertIn("direct_quality >= 0.90", decomposition)
        self.assertIn("isfinite(direct_quality)", decomposition)
        self.assertIn("isfinite(direct_cost_advantage)", decomposition)
        self.assertIn('ROUTE_COST_MEMORY_LIMIT = "900MB"', decomposition)
        self.assertNotIn("0.995", decomposition)

    def test_every_auxiliary_formula_symbol_is_defined(self) -> None:
        formulas = " ".join(spec.formula for spec in VARIABLE_SPECS)
        symbol_key = " ".join(
            item.notation + " " + item.definition for item in NOTATION_DEFINITIONS
        )
        required_symbols = {
            r"\mathrm{Vol}_t": r"\mathrm{Vol}_t",
            r"\mathrm{IVol}_{k,t}": r"\mathrm{IVol}_{k,t}",
            r"\mathrm{IVol}_t": r"\mathrm{IVol}_t",
            r"N^{I}_{k,t}": r"N^I_{k,t}",
            r"N^{I}_{t}": r"N^I_t",
            r"\mathcal A^{k}_{t}": r"\mathcal A^k_t",
            r"\mathcal A_t": r"\mathcal A_t",
            r"\mathcal M^{k}_{t}": r"\mathcal M^k_t",
            r"\mathrm{LegVol}^{\mathrm{in}}": r"\mathrm{LegVol}^{\mathrm{in}}",
            r"\mathrm{LegVol}^{\mathrm{out}}": r"\mathrm{LegVol}^{\mathrm{out}}",
            r"N_t": r"$N_t,\ N^{\mathrm{in}}_{k,t}",
            r"N^{\mathrm{in}}": r"N^{\mathrm{in}}",
            r"N^{\mathrm{out}}": r"N^{\mathrm{out}}",
            r"\mathrm{Vol}^{\mathrm{in}}": r"\mathrm{Vol}^{\mathrm{in}}",
            r"\mathrm{Vol}^{\mathrm{out}}": r"\mathrm{Vol}^{\mathrm{out}}",
            r"\mathrm{DVol}_t": r"\mathrm{DVol}_t",
            r"\ell": r"$\ell,\ p,\ p'$",
            r"p\in": r"$\ell,\ p,\ p'$",
            r"C_{k,t}": r"C_{k,t}",
            r"\mathcal L_{k,t}": r"\mathcal L_{k,t}",
            r"\mathrm{Capital}_{p,t}": r"\mathrm{Capital}_{p,t}",
            r"m_p": r"m_p",
            r"\mathcal K": r"\mathcal K",
            r"\mathcal P_{k,t,q}": r"\mathcal{P}_{k,t,q}",
            r"\mathcal D_{k,t,q}": r"\mathcal{D}_{k,t,q}",
            r"\mathcal I_{k,t,q}": r"\mathcal{I}_{k,t,q}",
            r"\mathcal C_{k,t,q}": r"\mathcal{C}_{k,t,q}",
            r"\mathcal T_{k,t,q}": r"\mathcal{T}_{k,t,q}",
            r"\mathcal W_{k,t,q}": r"\mathcal{W}_{k,t,q}",
            r"/q": r"$q$",
            r"O^D_{i,o,q,t}": r"O^{D}_{i,o,q,t}",
            r"\Delta C^D_{i,o,k,q,t}": r"\Delta C^D_{i,o,k,q,t}",
            r"R^{\mathrm{WETH}}_t": r"R^{\mathrm{WETH}}_t",
        }
        for formula_symbol, key_symbol in required_symbols.items():
            with self.subTest(symbol=formula_symbol):
                self.assertIn(formula_symbol, formulas)
                self.assertIn(key_symbol, symbol_key)

        registered_variables = " ".join(spec.notation for spec in VARIABLE_SPECS)
        named_inputs = {
            r"\mathrm{Stress}_{t}": r"$\mathrm{Stress}_{t}$",
            r"\mathrm{VehicleShare}_{k,t": r"$\mathrm{VehicleShare}_{k,t}$",
        }
        for formula_symbol, registered_symbol in named_inputs.items():
            with self.subTest(named_input=formula_symbol):
                self.assertIn(formula_symbol, formulas)
                self.assertIn(registered_symbol, registered_variables)

    def test_proposed_design_formula_inputs_are_canonical(self) -> None:
        formulas = " ".join(spec.formula for spec in VARIABLE_SPECS)
        canonical_key = " ".join(
            [item.notation + " " + item.definition for item in NOTATION_DEFINITIONS]
            + [spec.notation for spec in VARIABLE_SPECS]
        )
        required = {
            r"\mathrm{IVol}_{i,o,k,t}": r"\mathrm{IVol}_{i,o,k,t}",
            r"\mathrm{Vol}_{i,o,t}": r"\mathrm{Vol}_{i,o,t}",
            r"I_{i,o,k,q,t}": r"I_{i,o,k,q,t}",
            r"O^I_{i,o,k,q,t}": r"O^{I}_{i,o,k,q,t}",
            r"R_{k,t}": r"$R_{x,t},\ R_{k,t}$",
            r"\sigma^{(30)}_{k,t-1}": r"$\sigma^{(30)}_{k,t-1}$",
            r"k^\star": r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
            r"h^\star": r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
            r"\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}": (
                r"$t^{\mathrm{V3}}_0,\ \mathcal T^{\mathrm{V3}}_{\mathrm{pre}},\ "
                r"\mathcal P^{\mathrm{V3}}_q$"
            ),
            r"\mathcal L_t": r"$\mathcal L_t,\ \mathcal L_{k,t},\ m_p$",
            r"\mathcal R^4_c": r"$\mathcal R^3_c,\ \mathcal R^4_c$",
        }
        for formula_symbol, key_symbol in required.items():
            with self.subTest(symbol=formula_symbol):
                self.assertIn(formula_symbol, formulas)
                self.assertIn(key_symbol, canonical_key)

    def test_variable_units_are_measurement_units_not_observation_levels(self) -> None:
        for spec in VARIABLE_SPECS:
            unit = spec.unit.lower()
            self.assertNotIn("candidate vehicle", unit, spec.column)
            self.assertNotIn("token x", unit, spec.column)
            self.assertNotIn("token-day", unit, spec.column)

    def test_direct_cost_advantage_is_an_explicit_fraction(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        spec = by_column["direct_cost_advantage_median"]
        self.assertEqual(spec.name, "Direct cost advantage")
        self.assertEqual(spec.unit, "Fraction")
        self.assertEqual(spec.summary_unit, "Fraction")
        self.assertIn(r"\Delta C^D_{i,o,k,q,t}", spec.formula)
        self.assertIn("positive values favor the direct route", spec.construction)

        by_notation = {item.notation: item for item in NOTATION_DEFINITIONS}
        common_support = by_notation[r"$\mathcal{C}_{k,t,q}$"]
        self.assertIn(
            r"$\mathcal C_{k,t,q}=\mathcal D_{k,t,q}\cap\mathcal I_{k,t,q}$",
            common_support.definition,
        )
        pair_measure = by_notation[r"$\Delta C^D_{i,o,k,q,t}$"]
        self.assertEqual(pair_measure.unit, "Fraction")
        self.assertIn(
            r"$(O^{D}_{i,o,q,t}-O^{I}_{i,o,k,q,t})/O^{D}_{i,o,q,t}$",
            pair_measure.definition,
        )

        canonical_text = " ".join(
            [spec.column, spec.notation, spec.formula, spec.construction]
            + [item.notation + " " + item.definition for item in NOTATION_DEFINITIONS]
        )
        for retired in [
            "RouteCostAdvantage",
            "route_cost_advantage",
            "vehicle_route_advantage",
            "Basis points",
        ]:
            self.assertNotIn(retired, canonical_text)

    def test_share_notation_uses_fractions_not_probability_operator(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        self.assertTrue(
            all(r"\Pr" not in spec.notation + spec.formula for spec in VARIABLE_SPECS)
        )
        for column in [
            "direct_available_share",
            "vehicle_available_share",
            "no_direct_vehicle_available_share",
            "vehicle_beats_direct_share",
            "thin_direct_share",
        ]:
            self.assertIn(r"\frac", by_column[column].formula)

    def test_regression_notation_is_separate_from_construction_formula(self) -> None:
        for spec in VARIABLE_SPECS:
            self.assertTrue(spec.notation.startswith("$"), spec.column)
            if spec.formula:
                self.assertTrue(spec.formula.startswith("$"), spec.column)
                self.assertNotEqual(spec.notation, spec.formula, spec.column)

    def test_dynamic_registry_uses_only_exact_canonical_horizons(self) -> None:
        registry = Path("src/ddvc/variable_registry.py").read_text(encoding="utf-8")
        self.assertIn(r"$\tau\in\{1,7,30,120\}$ by exact calendar date", registry)
        self.assertNotIn(r"$\tau\in\{1,14,30\}$", registry)

    def test_variable_notation_renderer_uses_automatic_column_widths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "tabulate" / "render_variable_notation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(r"\begin{tabularx}{\linewidth}", text)
        self.assertIn('table_row("Variable", "Formula", "Unit", "Data column", "Definition")', text)
        self.assertNotIn(r"p{0.", text)
        self.assertNotIn("noqa: E402", text)

    def test_new_process_and_tabulate_scripts_are_direct_runners(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "scripts" / "process" / "build_observations_table.py",
            root / "scripts" / "process" / "build_raw_data_inventory.py",
            root / "scripts" / "process" / "build_cex_reference_support.py",
            *sorted((root / "scripts" / "tabulate").glob("render_*.py")),
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn('if __name__ == "__main__"', text)

    def test_tabulate_scripts_write_tabular_fragments_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = sorted((root / "scripts" / "tabulate").glob("render_*.py"))
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(r"\begin{table}", text)
            self.assertNotIn(r"\caption{", text)
            self.assertNotIn(r"\label{", text)
            self.assertNotIn("Notes:", text)

        for stem in [
            "data_coverage",
            "sample_coverage",
            "variable_notation",
        ]:
            rendered = (root / "output" / "tables" / f"{stem}.tex").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("Notes:", rendered, stem)

        # The summary table is intentionally absent when its current observation
        # input is unavailable; a stale generated fragment must not satisfy this
        # structural check.
        summary = root / "output" / "tables" / "summary_statistics.tex"
        if summary.exists():
            self.assertNotIn("Notes:", summary.read_text(encoding="utf-8"))

    def test_tabulate_outputs_are_tex_pdf_only_and_unnumbered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = sorted((root / "scripts" / "tabulate").glob("render_*.py"))
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(".to_csv(", text)
            self.assertNotIn(".read_csv(", text)
            self.assertNotIn("table_00_", text)
            self.assertNotIn("table_01_", text)

    def test_table_artifact_logging_is_centralized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tabulate = root / "scripts" / "tabulate"
        helper = (root / "src" / "ddvc" / "paper_tables.py").read_text(encoding="utf-8")
        self.assertEqual(helper.count('LOGGER.info("wrote %s"'), 2)
        for script in tabulate.glob("render_*.py"):
            self.assertNotIn('print(f"wrote', script.read_text(encoding="utf-8"), script.name)

    def test_paper_table_writer_escapes_comparison_symbols(self) -> None:
        self.assertEqual(_latex_escape("p <0.001"), r"p \ensuremath{<}0.001")
        self.assertEqual(_latex_escape(">0.025"), r"\ensuremath{>}0.025")

    def test_source_does_not_generate_csv_artifacts(self) -> None:
        """No generated CSV anywhere in the pipeline. `scripts/verify/` is not the pipeline.

        The exemption is narrow and is justified by what those files are: independent
        verifiers that shell out to a reference implementation, export a transient
        sample, parse the estimate back and delete the transient. The CEX-reference
        adapters have narrow exemptions for reading immutable external source files:
        the published CEX replication archive and the retained Etherscan daily-price
        input to the stress design. Both write only Parquet or JSONL. Nothing under
        `output/` depends on one of them having run, so a tab-separated handoff to
        `Rscript` produces no artifact this rule exists to prevent. Everything else
        under `scripts/` and `src/` stays under the absolute ban.
        """

        root = Path(__file__).resolve().parents[1]
        exempt = root / "scripts" / "verify"
        read_only_csv_adapters = {
            root / "src" / "ddvc" / "analysis" / "cex_reference.py",
            root / "scripts" / "run_stress_reallocation_e0.py",
        }
        for base in [root / "scripts", root / "src"]:
            for path in base.rglob("*.py"):
                if exempt in path.parents:
                    continue
                text = path.read_text(encoding="utf-8")
                msg = str(path.relative_to(root))
                self.assertNotIn(".to_csv(", text, msg)
                if path not in read_only_csv_adapters:
                    self.assertNotIn(".read_csv(", text, msg)
                    self.assertNotIn(".csv", text, msg)

    def test_paper_table_writer_does_not_emit_data_sidecars(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "src" / "ddvc" / "paper_tables.py").read_text(encoding="utf-8")
        writer = text.split("def _write_table(", 1)[1]
        self.assertNotIn(".to_pickle(", writer)
        self.assertNotIn(".to_parquet(", writer)

    def test_obsolete_variable_construction_table_has_no_live_owner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "run_core_rq_experiments.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("def variable_construction_table()", text)
        self.assertFalse((root / "output" / "tables" / "variable_construction.tex").exists())
        self.assertFalse((root / "output" / "tables" / "variable_construction.pdf").exists())
        self.assertTrue((root / "output" / "tables" / "variable_notation.tex").exists())

    def test_obsolete_p2_results_have_no_live_producer(self) -> None:
        root = Path(__file__).resolve().parents[1]
        producers = (
            "scripts/run_core_rq_experiments.py",
            "scripts/run_empirical_proposition_tests.py",
            "scripts/run_robustness_tests.py",
            "scripts/build_jfe_main_tables.py",
            "scripts/run_jfe_remaining_blocker_fixes.py",
            "scripts/build_paper_exhibits.py",
        )
        source = "\n".join(
            (root / relative).read_text(encoding="utf-8") for relative in producers
        )
        for obsolete in (
            "p2_liquidity_route_feedback",
            "p2_dynamic_predictability",
            "p2_dynamic_persistence",
            "lp_allocation_feedback",
            "liquidity_stickiness",
            "liquidity_robustness",
            "liquidity_formation_tests",
            "bridge_stickiness_tests",
        ):
            self.assertNotIn(obsolete, source)
        self.assertFalse((root / "scripts" / "run_p2_dynamic_persistence.py").exists())
        self.assertFalse((root / "scripts" / "run_lp_supply_flow_tests.py").exists())
        self.assertTrue(
            (root / "scripts" / "build_liquidity_capital_flow_panels.py").exists()
        )

    def test_output_artifact_stems_must_not_encode_table_or_figure_numbers(self) -> None:
        self.assertEqual(validate_output_stem("summary_statistics"), "summary_statistics")
        for stem in [
            "table_01_summary_statistics",
            "table_m08_variable_construction",
            "table_r21_stress_event_definition",
            "figure_02_bridge_vs_volume_share",
        ]:
            with self.assertRaises(ValueError):
                validate_output_stem(stem)

    def test_gitignore_does_not_hide_paper_facing_outputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertNotIn("output/tables/", ignore)
        self.assertNotIn("output/figures/", ignore)
        self.assertNotIn("output/exhibits/", ignore)
        self.assertNotIn("paper/*.pdf", ignore)


if __name__ == "__main__":
    unittest.main()
