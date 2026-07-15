from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "tabulate"))

from ddvc.variable_registry import OBSERVATIONS_TABLE_COLUMNS, SUMMARY_SPECS, VARIABLE_SPECS
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
                "lp_concentration",
                "direct_available_share",
                "no_direct_vehicle_available_share",
                "route_cost_advantage_median_bps",
                "settlement_transfer_incidence",
            },
            columns,
        )

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
