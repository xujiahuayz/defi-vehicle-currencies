from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from scripts.plot.render_vehicle_dominance_timelapse import (
    SYMBOLS,
    interpolated_timeline,
    monthly_vehicle_shares,
    render_outputs,
    select_endpoint_decomposition,
    spread_label_positions,
)


def choice_fixture() -> pd.DataFrame:
    rows = []
    for date, scale in (("2024-01-15", 1), ("2026-06-15", 2)):
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
                    "candidate_symbol": symbol,
                    "candidate_type": candidate_type,
                    "route_count": count * scale,
                }
            )
    # Fill the months between the endpoints so the production completeness
    # guard remains active in this compact fixture.
    frame = pd.DataFrame(rows)
    monthly = []
    for month in pd.date_range("2024-01-01", "2026-06-01", freq="MS"):
        clone = frame.iloc[:5].copy()
        clone["date"] = month + pd.Timedelta(days=14)
        monthly.append(clone)
    return pd.concat(monthly, ignore_index=True)


def decomposition_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "count_share",
                "source_column": "route_count",
                "reporting_scope": "pooled",
                "baseline_year": 2024,
                "comparison_year": 2026,
                "baseline_stable_share": 0.17,
                "comparison_stable_share": 0.43,
                "total_change": 0.26,
                "within_common": -0.01,
                "common_pair_reweighting": 0.09,
                "common_support_mass": 0.0,
                "exclusive_pair_contribution": 0.18,
                "common_month_days": 181,
            }
        ]
    )


class VehicleDominanceTimelapseTests(unittest.TestCase):
    def test_monthly_shares_keep_smaller_stables_in_the_denominator(self) -> None:
        shares = monthly_vehicle_shares(choice_fixture())
        self.assertEqual(tuple(shares.columns[:4]), SYMBOLS)
        self.assertEqual(len(shares), 30)
        self.assertAlmostEqual(float(shares.iloc[0]["WETH"]), 0.60)
        self.assertAlmostEqual(float(shares.iloc[0]["DAI"]), 0.05)
        self.assertAlmostEqual(float(shares.iloc[0]["stable_share"]), 0.40)
        self.assertAlmostEqual(float(shares.iloc[0][list(SYMBOLS)].sum()), 0.95)

    def test_decomposition_is_an_exact_accounting_identity(self) -> None:
        row = select_endpoint_decomposition(decomposition_fixture())
        self.assertAlmostEqual(float(row["total_change"]), 0.26)
        broken = decomposition_fixture()
        broken.loc[0, "exclusive_pair_contribution"] = 0.17
        with self.assertRaisesRegex(ValueError, "do not sum"):
            select_endpoint_decomposition(broken)

    def test_interpolation_retains_monthly_endpoints(self) -> None:
        shares = monthly_vehicle_shares(choice_fixture())
        timeline = interpolated_timeline(shares, frames=17)
        self.assertEqual(len(timeline), 17)
        for symbol in (*SYMBOLS, "stable_share"):
            self.assertAlmostEqual(float(timeline.iloc[0][symbol]), float(shares.iloc[0][symbol]))
            self.assertAlmostEqual(float(timeline.iloc[-1][symbol]), float(shares.iloc[-1][symbol]))

    def test_labels_are_spread_without_reordering(self) -> None:
        values = {"WETH": 0.60, "USDC": 0.20, "USDT": 0.18, "DAI": 0.01}
        positions = spread_label_positions(values)
        ordered = sorted(values, key=values.get)
        gaps = [positions[b] - positions[a] for a, b in zip(ordered, ordered[1:])]
        self.assertTrue(all(gap >= 0.055 - 1e-12 for gap in gaps))

    def test_poster_renderer_writes_16_by_9_png_and_pdf(self) -> None:
        shares = monthly_vehicle_shares(choice_fixture())
        decomposition = select_endpoint_decomposition(decomposition_fixture())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "poster.pdf"
            png = root / "poster.png"
            render_outputs(
                shares,
                decomposition,
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
