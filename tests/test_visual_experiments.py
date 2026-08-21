from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from ddvc.figure_outputs import ASSET_TYPES
from ddvc.visual_experiments import (
    WEIGHTINGS,
    annual_integration_flows,
    annual_vehicle_composition,
    integration_change_cells,
    render_annual_composition_bands,
    render_annual_integration_alluvial,
    render_deck_annual_composition_bands,
    render_integration_change_forest,
)


def annual_fixture() -> pd.DataFrame:
    rows = []
    for year in (2024, 2026):
        for scope, multiplier in (("all", 10), ("single_venue", 6), ("cross_venue", 4)):
            total = sum(range(1, len(ASSET_TYPES) + 1)) * multiplier
            for index, asset_type in enumerate(ASSET_TYPES, 1):
                mass = index * multiplier
                rows.append(
                    {
                        "year": year,
                        "integration_scope": scope,
                        "asset_type": asset_type,
                        "episodes": mass,
                        "episode_share": mass / total,
                        "usd_within_20pct": mass * 100,
                        "usd_share_within_20pct": mass / total,
                    }
                )
    return pd.DataFrame(rows)


def halfyear_fixture() -> pd.DataFrame:
    rows = []
    periods = (
        (0, "2018 H2"),
        (1, "2019 H1"),
        (2, "2019 H2"),
        (3, "2020 H1"),
    )
    for period_order, period in periods:
        for scope, multiplier in (
            ("all", 10),
            ("single_venue", 6),
            ("cross_venue", 4),
        ):
            total = sum(range(1, len(ASSET_TYPES) + 1)) * multiplier
            for index, asset_type in enumerate(ASSET_TYPES, 1):
                mass = index * multiplier
                rows.append(
                    {
                        "period": period,
                        "period_order": period_order,
                        "integration_scope": scope,
                        "asset_type": asset_type,
                        "episodes": mass,
                        "episode_share": mass / total,
                        "usd_within_20pct": mass * 100,
                        "usd_share_within_20pct": mass / total,
                    }
                )
    return pd.DataFrame(rows)


def rival_fixture() -> pd.DataFrame:
    rows = []
    for weighting, support in (("episode", "all_routes"), ("value", "within_20pct")):
        for index, scope in enumerate(("all", "single_venue", "cross_venue"), 1):
            rows.append(
                {
                    "baseline_year": 2024,
                    "comparison_year": 2026,
                    "integration_scope": scope,
                    "weighting": weighting,
                    "value_support": support,
                    "transformation": "share_level",
                    "change": index / 10,
                    "hac_standard_error": index / 100,
                }
            )
    return pd.DataFrame(rows)


class VisualExperimentTests(unittest.TestCase):
    def test_episode_weighting_is_labelled_as_intermediary_episodes(self) -> None:
        self.assertEqual(WEIGHTINGS[0], ("count", "Intermediary episodes"))

    def test_annual_composition_and_flows_are_exhaustive(self) -> None:
        result = annual_vehicle_composition(annual_fixture())
        self.assertEqual(len(result), 30)
        flows = annual_integration_flows(annual_fixture())
        self.assertTrue(flows.groupby("weighting")["share"].sum().round(12).eq(1).all())

    def test_integration_change_cells_require_all_scopes_and_weightings(self) -> None:
        self.assertEqual(len(integration_change_cells(rival_fixture())), 6)
        with self.assertRaisesRegex(ValueError, "six unique"):
            integration_change_cells(rival_fixture().iloc[:-1])

    def test_current_renderers_write_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = [root / f"figure-{index}.pdf" for index in range(3)]
            render_annual_composition_bands(annual_fixture(), outputs[0])
            render_annual_integration_alluvial(annual_fixture(), outputs[1])
            render_integration_change_forest(rival_fixture(), outputs[2])
            self.assertTrue(all(path.exists() and path.stat().st_size > 1_000 for path in outputs))

    def test_halfyear_composition_uses_full_percent_axes_and_annual_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = [root / "paper.pdf", root / "deck.pdf"]
            render_annual_composition_bands(halfyear_fixture(), outputs[0])
            render_deck_annual_composition_bands(halfyear_fixture(), outputs[1])

            for output in outputs:
                text = "\n".join(
                    page.extract_text() or "" for page in PdfReader(output).pages
                )
                self.assertEqual(text.count("100%"), 2)
                self.assertNotIn("90%", text)
                self.assertEqual(text.count("2019\nH1"), 2)
                self.assertEqual(text.count("2020\nH1"), 2)
                self.assertNotIn("2018", text)
                self.assertNotIn("H2", text)


if __name__ == "__main__":
    unittest.main()
