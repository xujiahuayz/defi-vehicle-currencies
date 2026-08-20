from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.figure_outputs import (
    bridge_adoption_capital_path,
    render_bridge_adoption_capital_path,
    render_vehicle_excess_use_transition,
    vehicle_excess_use_transition,
)


def bridge_path_fixture() -> pd.DataFrame:
    rows = []
    for vehicle_class, slope in (("stablecoin", 0.10), ("WETH", 0.02)):
        for event_time in range(-7, 8):
            rows.append(
                {
                    "record_type": "bridge_adoption_capital_path",
                    "vehicle_class": vehicle_class,
                    "event_time_days": event_time,
                    "coefficient": slope * (event_time + 7),
                    "standard_error": 0.02,
                    "events": 267,
                }
            )
    return pd.DataFrame(rows)


def transition_fixture() -> pd.DataFrame:
    rows = []
    for symbol, count_start, count_end, value_start, value_end in (
        ("USDC", 1.4, 1.5, 1.1, 1.15),
        ("USDT", 1.05, 1.23, 0.59, 1.42),
    ):
        for year, count, value in (
            (2024, count_start, value_start),
            (2026, count_end, value_end),
        ):
            rows.append(
                {
                    "level": "token",
                    "year": year,
                    "symbol": symbol,
                    "vehicle_excess_use_count_ratio": count,
                    "vehicle_excess_use_ratio_within_20pct": value,
                }
            )
    return pd.DataFrame(rows)


class FigureOutputTests(unittest.TestCase):
    def test_bridge_path_requires_both_vehicle_classes_and_all_days(self) -> None:
        result = bridge_adoption_capital_path(bridge_path_fixture())
        self.assertEqual(len(result), 30)
        with self.assertRaisesRegex(ValueError, "one unique row"):
            bridge_adoption_capital_path(bridge_path_fixture().iloc[:-1])

    def test_bridge_path_renderer_writes_vector_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bridge-path.pdf"
            render_bridge_adoption_capital_path(bridge_path_fixture(), output)
            payload = output.read_bytes()
            self.assertGreater(len(payload), 1_000)
            self.assertEqual(payload[:4], b"%PDF")
            self.assertNotIn(b"/Subtype /Image", payload)

    def test_transition_requires_both_candidates_and_years(self) -> None:
        result = vehicle_excess_use_transition(transition_fixture())
        self.assertEqual(
            result[["symbol", "year"]].values.tolist(),
            [["USDC", 2024], ["USDC", 2026], ["USDT", 2024], ["USDT", 2026]],
        )
        with self.assertRaisesRegex(ValueError, "one unique cell"):
            vehicle_excess_use_transition(transition_fixture().iloc[:-1])

    def test_renderer_writes_vector_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "transition.pdf"
            render_vehicle_excess_use_transition(transition_fixture(), output)
            payload = output.read_bytes()
            self.assertGreater(len(payload), 1_000)
            self.assertEqual(payload[:4], b"%PDF")
            self.assertNotIn(b"/Subtype /Image", payload)


if __name__ == "__main__":
    unittest.main()
