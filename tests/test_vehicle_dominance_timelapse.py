from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from scripts.plot.render_vehicle_dominance_timelapse import (
    SYMBOLS,
    bubble_area,
    interpolated_timeline,
    monthly_vehicle_state,
    render_outputs,
    spread_label_positions,
)


def choice_fixture() -> pd.DataFrame:
    rows = []
    for date, scale in (("2020-06-15", 1), ("2026-06-15", 2)):
        for symbol, candidate_type, count in (
            ("WETH", "native", 60),
            ("USDC", "stable", 20),
            ("USDT", "stable", 10),
            ("DAI", "stable", 5),
            ("FRAX", "stable", 5),
        ):
            rows.append(
                {
                    "date": date,
                    "src": f"source-{symbol}",
                    "tgt": f"target-{symbol}",
                    "candidate_symbol": symbol,
                    "candidate_type": candidate_type,
                    "route_count": count * scale,
                    "within_20pct_value_usd": count * scale * 10,
                }
            )
    # Fill the months between the endpoints so the production completeness
    # guard remains active in this compact fixture.
    frame = pd.DataFrame(rows)
    monthly = []
    for month in pd.date_range("2020-06-01", "2026-06-01", freq="MS"):
        clone = frame.iloc[:5].copy()
        clone["date"] = month + pd.Timedelta(days=14)
        monthly.append(clone)
    return pd.concat(monthly, ignore_index=True)


class VehicleDominanceTimelapseTests(unittest.TestCase):
    def test_monthly_state_keeps_smaller_stables_in_the_denominator(self) -> None:
        state = monthly_vehicle_state(choice_fixture())
        self.assertEqual(len(state), 73)
        self.assertAlmostEqual(float(state.iloc[0]["WETH_count_share"]), 0.60)
        self.assertAlmostEqual(float(state.iloc[0]["DAI_value_share"]), 0.05)
        self.assertAlmostEqual(float(state.iloc[0]["stable_count_share"]), 0.40)
        named = sum(float(state.iloc[0][f"{symbol}_count_share"]) for symbol in SYMBOLS)
        self.assertAlmostEqual(named, 0.95)
        self.assertEqual(float(state.iloc[0]["WETH_active_pairs"]), 1.0)

    def test_interpolation_retains_monthly_endpoints(self) -> None:
        state = monthly_vehicle_state(choice_fixture())
        timeline = interpolated_timeline(state, frames=17)
        self.assertEqual(len(timeline), 17)
        for column in state.columns:
            self.assertAlmostEqual(float(timeline.iloc[0][column]), float(state.iloc[0][column]))
            self.assertAlmostEqual(float(timeline.iloc[-1][column]), float(state.iloc[-1][column]))

    def test_labels_are_spread_without_reordering(self) -> None:
        values = {"WETH": 0.60, "USDC": 0.20, "USDT": 0.18, "DAI": 0.01}
        positions = spread_label_positions(values)
        ordered = sorted(values, key=values.get)
        gaps = [positions[b] - positions[a] for a, b in zip(ordered, ordered[1:])]
        self.assertTrue(all(gap >= 0.055 - 1e-12 for gap in gaps))

    def test_bubble_area_is_positive_and_increases_with_pair_breadth(self) -> None:
        self.assertGreater(bubble_area(0, maximum=1000), 0)
        self.assertGreater(
            bubble_area(1000, maximum=1000),
            bubble_area(100, maximum=1000),
        )

    def test_poster_renderer_writes_16_by_9_png_and_pdf(self) -> None:
        state = monthly_vehicle_state(choice_fixture())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "poster.pdf"
            png = root / "poster.png"
            render_outputs(
                state,
                video_output=root / "unused.mp4",
                poster_pdf_output=pdf,
                poster_png_output=png,
                seconds=1,
                fps=2,
                poster_only=True,
            )
            image = plt.imread(png)
            self.assertEqual(image.shape[:2], (1080, 1920))
            self.assertGreater(pdf.stat().st_size, 5_000)


if __name__ == "__main__":
    unittest.main()
