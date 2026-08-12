from __future__ import annotations

import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ddvc.prices import day_price_frame, day_prices, load_canonical_token_prices
from ddvc.provenance import sidecar_path


class DayPriceTests(unittest.TestCase):
    def test_canonical_price_loader_requires_provenance_and_full_value_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token-price.parquet"
            frame = pd.DataFrame(
                [
                    {
                        "day": "20250101",
                        "token": "0xabc",
                        "symbol": "ABC",
                        "price_usd": 2.0,
                        "n_observations": 4,
                        "n_consensus": 3,
                        "consensus_share": 0.75,
                        "gross_weight_usd": 10.0,
                        "consensus_weight_usd": 8.0,
                        "price_source": "canonical_repriced_route_legs",
                        "validation_status": "minimum_observations_and_price_consensus_passed",
                    }
                ]
            )
            frame.to_parquet(path, index=False)
            sidecar_path(path).parent.mkdir(parents=True, exist_ok=True)
            sidecar_path(path).write_text("{}", encoding="utf-8")
            with patch("ddvc.prices.current_artifacts", return_value=nullcontext((path,))) as current:
                loaded = load_canonical_token_prices(path, columns=("day", "token", "price_usd"))
            self.assertEqual(current.call_count, 1)
            current.assert_called_with([path], consumer="canonical address-day token prices")
            self.assertEqual(loaded.to_dict("records"), [{"day": "20250101", "token": "0xabc", "price_usd": 2.0}])
            frame.loc[0, "n_consensus"] = 2
            frame.to_parquet(path, index=False)
            with (
                patch("ddvc.prices.current_artifacts", return_value=nullcontext((path,))),
                self.assertRaisesRegex(ValueError, "support"),
            ):
                load_canonical_token_prices(path)

            frame.loc[0, "n_consensus"] = 3
            frame.to_parquet(path, index=False)
            with (
                patch("ddvc.prices.current_artifacts", return_value=nullcontext((path,))),
                self.assertRaisesRegex(ValueError, "nonempty"),
            ):
                load_canonical_token_prices(path, columns=[])

    def test_consensus_screened_volume_weighted_median(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A", "A", "A"],
                "token_out": ["B", "B", "B"],
                "token_in_sym": ["AAA", "AAA", "AAA"],
                "token_out_sym": ["BBB", "BBB", "BBB"],
                "amount_in": [10.0, 50.0, 2.0],
                "amount_out": [10.0, 50.0, 1.0],
                "amount_usd": [10.0, 100.0, 1.0],
            }
        )
        prices = day_prices(legs)
        self.assertEqual(prices["a"], ("AAA", 2.0))
        self.assertEqual(prices["b"], ("BBB", 2.0))

    def test_high_weight_price_outlier_cannot_capture_the_estimate(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A"] * 4,
                "token_out": ["B"] * 4,
                "token_in_sym": ["AAA"] * 4,
                "token_out_sym": ["BBB"] * 4,
                "amount_in": [10.0, 20.0, 30.0, 10.0],
                "amount_out": [10.0, 20.0, 30.0, 10.0],
                "amount_usd": [10.0, 20.0, 30.0, 1_000_000.0],
            }
        )
        prices = day_prices(legs)
        self.assertEqual(prices["a"], ("AAA", 1.0))
        self.assertEqual(prices["b"], ("BBB", 1.0))

    def test_incoherent_price_observations_are_rejected(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A", "A", "A"],
                "token_out": ["B", "B", "B"],
                "token_in_sym": ["AAA", "AAA", "AAA"],
                "token_out_sym": ["BBB", "BBB", "BBB"],
                "amount_in": [1.0, 1.0, 1.0],
                "amount_out": [1.0, 1.0, 1.0],
                "amount_usd": [1.0, 100.0, 10_000.0],
            }
        )
        self.assertEqual(day_prices(legs), {})

    def test_missing_input_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount_out"):
            day_prices(pd.DataFrame({"amount_usd": [1.0]}))

    def test_price_frame_preserves_validation_evidence(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A"] * 4,
                "token_out": ["B"] * 4,
                "token_in_sym": ["AAA"] * 4,
                "token_out_sym": ["BBB"] * 4,
                "amount_in": [10.0, 20.0, 30.0, 10.0],
                "amount_out": [10.0, 20.0, 30.0, 10.0],
                "amount_usd": [10.0, 20.0, 30.0, 1_000_000.0],
            }
        )

        frame = day_price_frame(legs).set_index("token")

        self.assertEqual(frame.loc["a", "price_usd"], 1.0)
        self.assertEqual(frame.loc["a", "n_observations"], 4)
        self.assertEqual(frame.loc["a", "n_consensus"], 3)
        self.assertEqual(frame.loc["a", "consensus_share"], 0.75)
        self.assertEqual(frame.loc["a", "price_source"], "canonical_repriced_route_legs")


if __name__ == "__main__":
    unittest.main()
