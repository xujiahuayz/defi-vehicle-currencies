from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH
from scripts.build_transaction_state_frontier import (
    candidate_vehicles,
    checkpoint_day,
    latest_replay_checkpoint,
    load_replay_checkpoint,
    save_replay_checkpoint,
    select_days,
    summarise,
    validation_error_diagnostics,
)
from ddvc.pricing.tick_replay import TickReplayState


class TransactionStateFrontierScriptTests(unittest.TestCase):
    def test_candidate_set_canonicalises_native_forms_once(self) -> None:
        vehicles = candidate_vehicles()
        self.assertIn(WETH, vehicles)
        self.assertNotIn(NATIVE_ETH, vehicles)
        self.assertEqual(len(vehicles), len(set(vehicles)))

    def test_explicit_day_selection_is_exact_and_normalised(self) -> None:
        selected = select_days(
            ["20220615", "20240615"],
            explicit=["2022-06-15"],
            monthly=False,
        )
        self.assertEqual(selected, ["20220615"])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            select_days(["20220615"], explicit=["20230615"], monthly=False)

    def test_summary_keeps_all_and_valuation_coherent_samples_separate(self) -> None:
        panel = pd.DataFrame(
            {
                "day": ["20220615", "20220615", "20240615"],
                "within_20pct": [True, False, True],
                "input_usd": [100.0, 200.0, 300.0],
                "chosen_validation_error_bps": [1.0, -2.0, 3.0],
                "within_reach_search_regret_bps": [0.0, 5.0, 10.0],
                "public_reach_same_vehicle_regret_bps": [1.0, 6.0, 11.0],
                "public_path_regret_bps": [2.0, 20.0, 12.0],
                "reach_increment_bps": [1.0, 1.0, 1.0],
                "path_choice_increment_bps": [1.0, 14.0, 1.0],
                "direct_omission_bps": [None, 4.0, 0.0],
                "public_gain_usd": [0.02, 0.40, 0.36],
            }
        )
        summary = summarise(panel)
        pooled = summary[summary["day"].eq("pooled")].set_index("sample")
        self.assertEqual(int(pooled.loc["all", "routes"]), 3)
        self.assertEqual(int(pooled.loc["within_20pct", "routes"]), 2)
        self.assertAlmostEqual(
            float(pooled.loc["all", "public_path_regret_positive_share"]),
            1.0,
        )

    def test_replay_checkpoint_round_trips_exact_state(self) -> None:
        replay = TickReplayState()
        replay.ticks_by_venue = {"uniswap_v3": {"pool": {-10: 5, 10: -5}}}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.pkl"
            save_replay_checkpoint(path, replay)
            restored = load_replay_checkpoint(path)
        self.assertEqual(restored.ticks_by_venue, replay.ticks_by_venue)

    def test_validation_diagnostics_keep_rejected_tail_visible(self) -> None:
        diagnostics = validation_error_diagnostics([0.0, -10.0, 200.0, -500.0])
        self.assertEqual(diagnostics["quote_available"], 4)
        self.assertEqual(diagnostics["output_mismatch"], 2)
        self.assertEqual(diagnostics["validation_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["mismatch_abs_min_bps"], 200.0)
        self.assertEqual(diagnostics["mismatch_abs_max_bps"], 500.0)
        self.assertEqual(diagnostics["validation_within_tolerance_share"], 0.5)

    def test_latest_checkpoint_never_jumps_past_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for day in ("20220101", "20230101", "20240101"):
                (root / f"pre_{day}.pkl").touch()
            selected = latest_replay_checkpoint(root, "20230615")
        assert selected is not None
        self.assertEqual(checkpoint_day(selected), "20230101")


if __name__ == "__main__":
    unittest.main()
