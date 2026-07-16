from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "tabulate"))

from ddvc.variable_registry import (
    NOTATION_DEFINITIONS,
    OBSERVATIONS_TABLE_COLUMNS,
    SUMMARY_SPECS,
    VARIABLE_SPECS,
)
from utils import validate_output_stem


class VariableRegistryTests(unittest.TestCase):
    def test_registered_columns_are_unique(self) -> None:
        columns = [spec.column for spec in VARIABLE_SPECS]
        self.assertEqual(len(columns), len(set(columns)))

    def test_summary_specs_are_observation_columns(self) -> None:
        observation_columns = set(OBSERVATIONS_TABLE_COLUMNS)
        for spec in SUMMARY_SPECS:
            self.assertIn(spec.column, observation_columns)

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
                "route_cost_advantage_median_bps",
                "settlement_transfer_incidence",
            },
            columns,
        )

    def test_notation_key_defines_route_indices_and_superscripts(self) -> None:
        notation = " ".join(item.notation for item in NOTATION_DEFINITIONS)
        definitions = " ".join(item.definition for item in NOTATION_DEFINITIONS)
        for symbol in ["$i,\\ j$", "$k$", "$\\ell,\\ p$", "$t,\\ w$", "$q$", "$r$"]:
            self.assertIn(symbol, notation)
        self.assertIn(r"superscripts $D$ and $V$", definitions)
        self.assertIn(r"superscript $B$ denotes bridged", definitions)

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
            "daily_all_route_volume_usd": r"$A_t$",
            "daily_indirect_route_volume_usd": r"$\mathrm{IVol}_t$",
            "vehicle_linked_liquidity_usd": r"$L_{k,t}$",
            "future_bridge_share_t7": r"$\mathrm{VehicleShare}_{k,t+7}$",
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

    def test_formula_cells_are_blank_or_actual_calculations(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        registered_notations = {spec.notation for spec in VARIABLE_SPECS}
        for column in [
            "bridge_volume_usd",
            "daily_indirect_route_volume_usd",
            "future_bridge_share_t7",
        ]:
            self.assertEqual(by_column[column].formula, "")

        for spec in VARIABLE_SPECS:
            if not spec.formula:
                continue
            self.assertTrue(spec.formula.startswith("$"), spec.column)
            self.assertNotEqual(spec.notation, spec.formula, spec.column)
            self.assertNotIn(spec.formula, registered_notations, spec.column)
            self.assertNotIn(r"\equiv", spec.formula, spec.column)

    def test_network_formulas_reuse_existing_route_symbols(self) -> None:
        by_column = {spec.column: spec for spec in VARIABLE_SPECS}
        count_formula = by_column["betweenness_centrality"].formula
        volume_formula = by_column["volume_weighted_betweenness"].formula
        self.assertIn(r"N^{B}_{k,t}", count_formula)
        self.assertIn(r"\mathrm{IVol}_{k,t}", volume_formula)
        self.assertIn(r"A_t", volume_formula)

        symbol_key = " ".join(item.notation for item in NOTATION_DEFINITIONS)
        for duplicate_symbol in [
            r"N^{\mathrm{mid}}_{k,t}",
            r"\mathrm{Vol}^{\mathrm{mid}}_{k,t}",
            r"\mathrm{Vol}^{\mathrm{route}}_t",
            r"\mathrm{Betweenness}^{\mathrm{vol}}",
        ]:
            self.assertNotIn(duplicate_symbol, symbol_key)

    def test_every_auxiliary_formula_symbol_is_defined(self) -> None:
        formulas = " ".join(spec.formula for spec in VARIABLE_SPECS)
        symbol_key = " ".join(
            item.notation + " " + item.definition for item in NOTATION_DEFINITIONS
        )
        required_symbols = {
            r"A_t": r"A_t",
            r"\mathrm{IVol}_{k,t}": r"\mathrm{IVol}_{k,t}",
            r"\mathrm{IVol}_t": r"\mathrm{IVol}_t",
            r"N^{B}_{k,t}": r"N^B_{k,t}",
            r"N^{B}_{t}": r"N^B_t",
            r"\mathcal A^{k}_{t}": r"\mathcal A^k_t",
            r"\mathcal A_t": r"\mathcal A_t",
            r"\mathcal M^{k}_{t}": r"\mathcal M^k_t",
            r"\mathrm{Vol}^{\mathrm{in}}": r"\mathrm{Vol}^{\mathrm{in}}",
            r"\mathrm{Vol}^{\mathrm{out}}": r"\mathrm{Vol}^{\mathrm{out}}",
            r"N^{\mathrm{route}}": r"N^{\mathrm{route}}",
            r"N^{\mathrm{src}}": r"N^{\mathrm{src}}",
            r"N^{\mathrm{sink}}": r"N^{\mathrm{sink}}",
            r"\mathrm{Vol}^{\mathrm{src}}": r"\mathrm{Vol}^{\mathrm{src}}",
            r"\mathrm{Vol}^{\mathrm{sink}}": r"\mathrm{Vol}^{\mathrm{sink}}",
            r"\mathrm{DVol}_t": r"\mathrm{DVol}_t",
            r"\ell": r"$\ell,\ p$",
            r"p\in": r"$\ell,\ p$",
            r"L_{k,t}": r"L_{k,t}",
            r"\mathcal L_{k,t}": r"\mathcal L_{k,t}",
            r"\mathrm{TVL}_{p,t}": r"\mathrm{TVL}_{p,t}",
            r"\mathcal K": r"\mathcal K",
            r"\mathcal P_{k,t,q}": r"\mathcal{P}_{k,t,q}",
            r"\mathcal D_{k,t,q}": r"\mathcal{D}_{k,t,q}",
            r"\mathcal V_{k,t,q}": r"\mathcal{V}_{k,t,q}",
            r"\mathcal C_{k,t,q}": r"\mathcal{C}_{k,t,q}",
            r"\mathcal T_{k,t,q}": r"\mathcal{T}_{k,t,q}",
            r"\mathcal W_{k,t,q}": r"\mathcal{W}_{k,t,q}",
            r"/q": r"$q$",
            r"O^D_{i,j,q,t}": r"O^{D}_{i,j,q,t}",
            r"\Delta C_{i,j,k,q,t}": r"\Delta C_{i,j,k,q,t}",
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

    def test_variable_units_are_measurement_units_not_observation_levels(self) -> None:
        for spec in VARIABLE_SPECS:
            unit = spec.unit.lower()
            self.assertNotIn("candidate vehicle", unit, spec.column)
            self.assertNotIn("token x", unit, spec.column)
            self.assertNotIn("token-day", unit, spec.column)

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
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn('if __name__ == "__main__"', text)

    def test_tabulate_scripts_write_tabular_fragments_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(r"\begin{table}", text)
            self.assertNotIn(r"\caption{", text)
            self.assertNotIn(r"\label{", text)

    def test_tabulate_outputs_are_tex_pdf_only_and_unnumbered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scripts = [
            root / "scripts" / "tabulate" / "render_variable_notation.py",
            root / "scripts" / "tabulate" / "render_summary_statistics.py",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn(".to_csv(", text)
            self.assertNotIn(".read_csv(", text)
            self.assertNotIn("table_00_", text)
            self.assertNotIn("table_01_", text)

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


if __name__ == "__main__":
    unittest.main()
