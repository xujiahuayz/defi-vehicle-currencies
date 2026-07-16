from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ddvc.analysis import raw_data_inventory
from ddvc.analysis.raw_data_inventory import (
    build_raw_data_inventory,
    count_jsonl_gz_rows,
    metadata_row_count,
    summarize_raw_data_inventory,
)
from ddvc.fetch.sources import DEX_SOURCES


class RawDataInventoryTests(unittest.TestCase):
    def test_metadata_count_supports_current_and_legacy_sidecars(self) -> None:
        current = {"streams": {"swaps": {"rows": 12}}}
        legacy = {"swaps": 8, "pool_days": 3}
        self.assertEqual(metadata_row_count(current, "swaps"), 12)
        self.assertEqual(metadata_row_count(legacy, "swaps"), 8)
        self.assertEqual(metadata_row_count(legacy, "daily"), 3)
        self.assertIsNone(metadata_row_count(legacy, "mints"))

    def test_exact_jsonl_count_handles_missing_terminal_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(b'{"id":1}\n{"id":2}')
            self.assertEqual(count_jsonl_gz_rows(path), 2)

    def test_inventory_uses_exact_count_then_native_cache(self) -> None:
        source = "uniswap_v2"
        source_spec = DEX_SOURCES[source]
        with tempfile.TemporaryDirectory() as tmp:
            raw_root = Path(tmp)
            source_dir = raw_root / source_spec.backend / source
            source_dir.mkdir(parents=True)
            path = source_dir / f"{source}_swaps_20200101.jsonl.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(b'{"id":1}\n{"id":2}\n')

            with patch.object(raw_data_inventory, "DEX_SOURCES", {source: source_spec}):
                first = build_raw_data_inventory(raw_root, workers=1)
                second = build_raw_data_inventory(raw_root, previous=first, workers=1)
                summary = summarize_raw_data_inventory(second)

            self.assertEqual(int(first.loc[0, "records"]), 2)
            self.assertEqual(first.loc[0, "count_method"], "exact scan")
            self.assertEqual(second.loc[0, "count_method"], "cached exact scan")
            self.assertEqual(int(summary.loc[0, "swap_records"]), 2)
            self.assertEqual(int(summary.loc[0, "raw_files"]), 1)
            self.assertGreater(int(summary.loc[0, "compressed_bytes"]), 0)
            self.assertEqual(int(summary.loc[0, "total_records"]), 2)

    def test_summary_rejects_unregistered_streams(self) -> None:
        inventory = pd.DataFrame(
            {
                "source": ["uniswap_v2"],
                "backend": ["thegraph"],
                "stream": ["mystery"],
                "date": [pd.Timestamp("2020-01-01")],
                "records": [1],
                "compressed_bytes": [10],
            }
        )
        with self.assertRaisesRegex(ValueError, "unknown streams"):
            summarize_raw_data_inventory(inventory)


if __name__ == "__main__":
    unittest.main()
