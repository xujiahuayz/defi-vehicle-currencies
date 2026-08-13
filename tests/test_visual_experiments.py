from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.figure_outputs import ASSET_TYPES
from ddvc.visual_experiments import (
    annual_integration_flows,
    annual_vehicle_composition,
    daily_vehicle_shares,
    integration_change_cells,
    latest_token_excess_use,
    render_excess_use_heatmap,
    render_stable_share_ridgeline,
    render_vehicle_composition_bands,
)


def daily_fixture() -> pd.DataFrame:
    rows = []
    for day, scale in zip(pd.date_range("2025-12-29", periods=6), range(1, 7), strict=True):
        row: dict[str, object] = {"date": day}
        for index, asset_type in enumerate(ASSET_TYPES, 1):
            row[f"cnt_{asset_type}"] = scale * index
            row[f"usd_within_20pct_{asset_type}"] = scale * index * 100
            row[f"cnt_single_venue_{asset_type}"] = scale * index * 0.6
            row[f"cnt_cross_venue_{asset_type}"] = scale * index * 0.4
            row[f"usd_within_20pct_single_venue_{asset_type}"] = scale * index * 60
            row[f"usd_within_20pct_cross_venue_{asset_type}"] = scale * index * 40
        rows.append(row)
    return pd.DataFrame(rows)


def token_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"level": "token", "year": 2026, "symbol": symbol, "intermediate_routes": routes, "vehicle_excess_use_count_ratio": count, "vehicle_excess_use_ratio_within_20pct": value}
            for symbol, routes, count, value in (
                ("USDC", 100, 1.5, 1.1),
                ("USDT", 80, 1.2, 1.4),
                ("WETH", 120, 0.8, 0.7),
            )
        ]
    )


def annual_fixture() -> pd.DataFrame:
    rows = []
    for year in (2024, 2026):
        for scope, multiplier in (("all", 10), ("single_venue", 6), ("cross_venue", 4)):
            total = sum(range(1, len(ASSET_TYPES) + 1)) * multiplier
            for index, asset_type in enumerate(ASSET_TYPES, 1):
                mass = index * multiplier
                rows.append({"year": year, "integration_scope": scope, "asset_type": asset_type, "episodes": mass, "episode_share": mass / total, "usd_within_20pct": mass * 100, "usd_share_within_20pct": mass / total})
    return pd.DataFrame(rows)


def rival_fixture() -> pd.DataFrame:
    rows = []
    for weighting, support in (("episode", "all_routes"), ("value", "within_20pct")):
        for index, scope in enumerate(("all", "single_venue", "cross_venue"), 1):
            rows.append({"baseline_year": 2024, "comparison_year": 2026, "integration_scope": scope, "weighting": weighting, "value_support": support, "transformation": "share_level", "change": index / 10, "hac_standard_error": index / 100})
    return pd.DataFrame(rows)


class VisualExperimentTests(unittest.TestCase):
    def test_annual_composition_and_flows_are_exhaustive(self) -> None:
        result = annual_vehicle_composition(annual_fixture())
        self.assertEqual(len(result), 30)
        flows = annual_integration_flows(annual_fixture())
        self.assertTrue(flows.groupby("weighting")["share"].sum().round(12).eq(1).all())

    def test_integration_change_cells_require_all_scopes_and_weightings(self) -> None:
        self.assertEqual(len(integration_change_cells(rival_fixture())), 6)
        with self.assertRaisesRegex(ValueError, "six unique"):
            integration_change_cells(rival_fixture().iloc[:-1])

    def test_daily_shares_are_exhaustive(self) -> None:
        result = daily_vehicle_shares(daily_fixture())
        for prefix in ("count", "value"):
            columns = [f"{prefix}_share_{asset_type}" for asset_type in ASSET_TYPES]
            self.assertTrue(result[columns].sum(axis=1).round(12).eq(1).all())

    def test_token_selection_uses_latest_year_and_route_mass(self) -> None:
        older = token_fixture().assign(year=2025, intermediate_routes=1000)
        result = latest_token_excess_use(pd.concat([older, token_fixture()]), limit=2)
        self.assertEqual(set(result["symbol"]), {"WETH", "USDC"})
        self.assertEqual(result["year"].unique().tolist(), [2026])

    def test_renderers_write_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = [root / f"figure-{index}.pdf" for index in range(3)]
            render_stable_share_ridgeline(daily_fixture(), outputs[0])
            render_vehicle_composition_bands(daily_fixture(), outputs[1])
            render_excess_use_heatmap(token_fixture(), outputs[2])
            self.assertTrue(all(path.exists() and path.stat().st_size > 1_000 for path in outputs))


if __name__ == "__main__":
    unittest.main()
