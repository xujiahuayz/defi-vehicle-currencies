from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "tabulate"))

from ddvc.variable_registry import (
    NOTATION_DEFINITIONS,
    OBSERVATIONS_TABLE_COLUMNS,
    SUMMARY_SPECS,
    VARIABLE_SPECS,
)
from build_paper_exhibits import _latex_escape
from utils import validate_output_stem


class VariableRegistryTests(unittest.TestCase):
    def test_registered_columns_are_unique(self) -> None:
        columns = [spec.column for spec in VARIABLE_SPECS]
        self.assertEqual(len(columns), len(set(columns)))

    def test_summary_specs_are_observation_columns(self) -> None:
        observation_columns = set(OBSERVATIONS_TABLE_COLUMNS)
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.column, observation_columns)
            self.assertIsNotNone(spec.summary_unit, spec.column)
        self.assertIn("direct_depth_median", {spec.column for spec in SUMMARY_SPECS})

    def test_summary_statistics_use_canonical_registry_notation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        renderer = (
            root / "scripts" / "tabulate" / "render_summary_statistics.py"
        ).read_text(encoding="utf-8")
        rendered = (root / "output" / "tables" / "summary_statistics.tex").read_text(
            encoding="utf-8"
        )
        self.assertIn("spec.notation", renderer)
        self.assertNotIn("summary_label", renderer)
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.notation, rendered, spec.column)

    def test_core_bridge_and_route_cost_variables_are_registered(self) -> None:
        columns = set(OBSERVATIONS_TABLE_COLUMNS)
        self.assertLessEqual(
            {
                "bridge_share",
                "all_route_bridge_share",
                "vol_share",
                "lp_concentration",
                "direct_available_share",
                "direct_depth_median",
                "no_direct_vehicle_available_share",
                "direct_cost_advantage_median",
                "settlement_transfer_incidence",
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
            "$g$",
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
        paper_text = (root / "paper" / "jfe_detailed_outline.md").read_text(
            encoding="utf-8"
        )
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
            "vehicle_linked_liquidity_usd": r"$L_{k,t}$",
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
            "any_indirect_available": r"$\mathrm{AnyIndirectAvailable}_{i,o,q,t}$",
            "pair_direct_depth": r"$\mathrm{DirectDepth}_{i,o,q,t}$",
            "pair_indirect_depth": r"$\mathrm{IndirectDepth}_{i,o,k,q,t}$",
            "candidate_downside_stress": r"$\mathrm{CandidateStress}_{k,t}$",
            "incumbent_vehicle": r"$\mathrm{Incumbent}_{i,o,k,t}$",
            "challenger_cost_edge": r"$\mathrm{ChallengerCostEdge}_{i,o,q,t}$",
            "vehicle_switch": r"$\mathrm{VehicleSwitch}_{i,o,q,t,\tau}$",
            "pre_v3_direct_constraint": r"$\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}$",
            "post_v3": r"$\mathrm{PostV3}_{t}$",
            "vehicle_factor_loo": r"$\mathrm{VehicleLiquidityFactor}_{p,k,t}$",
            "market_factor_loo": r"$\mathrm{MarketLiquidityFactor}_{p,t}$",
            "has_matching_transfer": r"$\mathrm{Transfer}_{r,k}$",
            "v4_route": r"$\mathrm{V4}_{r}$",
            "v4_route_share": r"$\mathrm{V4RouteShare}_{g}$",
        }
        for column, notation in expected.items():
            with self.subTest(column=column):
                self.assertIn(column, by_column)
                self.assertEqual(by_column[column].notation, notation)
                self.assertFalse(by_column[column].in_observations_table)
                self.assertNotIn(column, OBSERVATIONS_TABLE_COLUMNS)

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

        settlement = by_notation[r"$\mathcal R^3_g,\ \mathcal R^4_g$"]
        self.assertIn("A matched cell has both sets nonempty", settlement.definition)

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
            "realized-USD-volume-weighted median",
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

    def test_candidate_linked_liquidity_has_an_explicit_allocation_rule(self) -> None:
        by_notation = {item.notation: item.definition for item in NOTATION_DEFINITIONS}
        candidate_definition = by_notation[r"$\mathcal K$"]
        pool_definition = by_notation[r"$\mathcal L_t,\ \mathcal L_{k,t},\ m_p$"]
        liquidity_definition = by_notation[r"$\mathrm{TVL}_{p,t},\ L_{k,t}$"]
        for token in ["WETH", "USDC", "USDT", "DAI", "WBTC"]:
            self.assertIn(token, candidate_definition)
        self.assertNotIn("FRAX", candidate_definition)
        self.assertIn(r"$m_p\in\{1,2\}$", pool_definition)
        self.assertIn(r"$\mathcal L_{k,t}\subseteq\mathcal L_t$", pool_definition)
        self.assertIn("exact token contracts", pool_definition)
        self.assertIn("persisted V3 swap archive", pool_definition)
        self.assertIn("one half to each", liquidity_definition)

        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        formula = by_column["vehicle_linked_liquidity_usd"].formula
        self.assertEqual(
            formula,
            r"$\displaystyle\sum_{p\in\mathcal L_{k,t}}\frac{\mathrm{TVL}_{p,t}}{m_p}$",
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
        self.assertIn('direct_quality"].lt(0.90)', decomposition)
        self.assertIn('direct_quality"].ge(0.90)', decomposition)
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
            r"L_{k,t}": r"L_{k,t}",
            r"\mathcal L_{k,t}": r"\mathcal L_{k,t}",
            r"\mathrm{TVL}_{p,t}": r"\mathrm{TVL}_{p,t}",
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
            r"\mathcal R^{\mathrm{transfer}}_{k,w}": r"\mathcal{R}^{\mathrm{transfer}}_{k,w}",
            r"\mathcal R_{k,w}": r"\mathcal{R}_{k,w}",
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
            r"R_{k,t}": r"$R_{k,t}$",
            r"\sigma^{(30)}_{k,t-1}": r"$\sigma^{(30)}_{k,t-1}$",
            r"k^\star": r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
            r"h^\star": r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
            r"\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}": (
                r"$t^{\mathrm{V3}}_0,\ \mathcal T^{\mathrm{V3}}_{\mathrm{pre}},\ "
                r"\mathcal P^{\mathrm{V3}}_q$"
            ),
            r"\mathcal L_t": r"$\mathcal L_t,\ \mathcal L_{k,t},\ m_p$",
            r"\mathcal R^4_g": r"$\mathcal R^3_g,\ \mathcal R^4_g$",
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
            "settlement_transfer_incidence",
        ]:
            self.assertIn(r"\frac", by_column[column].formula)

    def test_regression_notation_is_separate_from_construction_formula(self) -> None:
        for spec in VARIABLE_SPECS:
            self.assertTrue(spec.notation.startswith("$"), spec.column)
            if spec.formula:
                self.assertTrue(spec.formula.startswith("$"), spec.column)
                self.assertNotEqual(spec.notation, spec.formula, spec.column)

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
            root / "scripts" / "tabulate" / "render_data_coverage.py",
            root / "scripts" / "tabulate" / "render_sample_coverage.py",
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn('if __name__ == "__main__"', text)

    def test_tabulate_scripts_write_tabular_fragments_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "scripts" / "tabulate" / "render_data_coverage.py",
            root / "scripts" / "tabulate" / "render_sample_coverage.py",
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(r"\begin{table}", text)
            self.assertNotIn(r"\caption{", text)
            self.assertNotIn(r"\label{", text)
            self.assertNotIn("Notes:", text)

        for stem in [
            "data_coverage",
            "sample_coverage",
            "summary_statistics",
            "variable_notation",
        ]:
            rendered = (root / "output" / "tables" / f"{stem}.tex").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("Notes:", rendered, stem)

    def test_tabulate_outputs_are_tex_pdf_only_and_unnumbered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "scripts" / "tabulate" / "render_data_coverage.py",
            root / "scripts" / "tabulate" / "render_sample_coverage.py",
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(".to_csv(", text)
            self.assertNotIn(".read_csv(", text)
            self.assertNotIn("table_00_", text)
            self.assertNotIn("table_01_", text)

    def test_table_artifact_logging_is_centralized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tabulate = root / "scripts" / "tabulate"
        helper = (tabulate / "utils.py").read_text(encoding="utf-8")
        self.assertEqual(helper.count('LOGGER.info("wrote %s"'), 2)
        for script in tabulate.glob("render_*.py"):
            self.assertNotIn('print(f"wrote', script.read_text(encoding="utf-8"), script.name)

    def test_paper_table_writer_escapes_comparison_symbols(self) -> None:
        self.assertEqual(_latex_escape("p <0.001"), r"p \ensuremath{<}0.001")
        self.assertEqual(_latex_escape(">0.025"), r"\ensuremath{>}0.025")

    def test_source_does_not_generate_csv_artifacts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for base in [root / "scripts", root / "src"]:
            for path in base.rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                msg = str(path.relative_to(root))
                self.assertNotIn(".to_csv(", text, msg)
                self.assertNotIn(".read_csv(", text, msg)
                self.assertNotIn(".csv", text, msg)

    def test_paper_table_writer_does_not_emit_data_sidecars(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "build_paper_exhibits.py").read_text(encoding="utf-8")
        writer = text.split("def _write_table(", 1)[1].split("\ndef _copy_if_exists", 1)[0]
        self.assertNotIn(".to_pickle(", writer)
        self.assertNotIn(".to_parquet(", writer)

    def test_variable_construction_uses_flexible_columns(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "run_core_rq_experiments.py").read_text(
            encoding="utf-8"
        )
        block = text.split("def variable_construction_table()", 1)[1].split(
            "\ndef route_cost_daily", 1
        )[0]
        self.assertIn(r">{\raggedright\arraybackslash}X", block)
        self.assertNotIn(r"\linewidth}", block)
        self.assertNotIn("p{0.", block)

    def test_p2_registries_read_current_results(self) -> None:
        root = Path(__file__).resolve().parents[1]
        remaining = (
            root / "scripts" / "run_jfe_remaining_blocker_fixes.py"
        ).read_text(encoding="utf-8")
        main_tables = (root / "scripts" / "build_jfe_main_tables.py").read_text(
            encoding="utf-8"
        )
        pipeline = (
            root / "scripts" / "build_results_evidence_outputs.py"
        ).read_text(encoding="utf-8")

        self.assertIn("p2_liquidity_route_feedback.pkl", remaining)
        self.assertIn("p2_dynamic_predictability.pkl", main_tables)
        self.assertNotIn("0.2817", remaining + main_tables)
        self.assertLess(
            pipeline.index('"run_feedback_proposition_tests.py"'),
            pipeline.index('"run_jfe_remaining_blocker_fixes.py"'),
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
