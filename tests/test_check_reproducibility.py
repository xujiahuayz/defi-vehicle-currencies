from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_reproducibility


class ReproducibilityInventoryTests(unittest.TestCase):
    def test_collect_excludes_generation_keyed_cache_shards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            keep = root / "data" / "processed" / "panel.parquet"
            frontier_cache = (
                root
                / "data"
                / "empirical"
                / "_transaction_state_frontier_day_cache"
                / "engine_abc"
                / "20200101.parquet"
            )
            replay_checkpoint = (
                root
                / "data"
                / "empirical"
                / "_tick_replay_checkpoints"
                / "engine_abc"
                / "pre_20200101.pkl"
            )
            for path in (keep, frontier_cache, replay_checkpoint):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            with patch.object(check_reproducibility, "ROOT", root):
                self.assertEqual(check_reproducibility.collect(), [keep])

    def test_canonical_unified_shards_are_not_scanned_as_final_artefacts(self) -> None:
        self.assertNotIn("data/unified", check_reproducibility.ARTEFACT_DIRS)


if __name__ == "__main__":
    unittest.main()
