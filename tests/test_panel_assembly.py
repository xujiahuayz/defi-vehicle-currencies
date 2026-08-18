from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.panel_assembly import assemble_parquet_shards


class PanelAssemblyTests(unittest.TestCase):
    def test_skips_zero_column_empty_shard_before_nonempty_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = root / "20200101.parquet"
            populated = root / "20200102.parquet"
            output = root / "panel.parquet"
            pq.write_table(pa.table({}), empty)
            pq.write_table(pa.table({"day": [2], "vehicle": ["USDC"]}), populated)

            result = assemble_parquet_shards([empty, populated], output)

            self.assertEqual(result.rows, 1)
            self.assertEqual(result.shards, 1)
            self.assertEqual(pq.read_table(output).to_pydict(), {"day": [2], "vehicle": ["USDC"]})

    def test_unifies_all_shards_when_the_first_column_is_null_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "20200101.parquet"
            second = root / "20200102.parquet"
            output = root / "panel.parquet"
            pq.write_table(pa.table({"day": [1], "label": pa.nulls(1)}), first)
            pq.write_table(pa.table({"day": [2], "label": ["stable"]}), second)

            result = assemble_parquet_shards([first, second], output)

            table = pq.read_table(output)
            self.assertEqual(result.rows, 2)
            self.assertEqual(table.column("label").to_pylist(), [None, "stable"])

    def test_adds_a_column_that_only_appears_in_a_later_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "20200101.parquet"
            second = root / "20200102.parquet"
            output = root / "panel.parquet"
            pq.write_table(pa.table({"day": [1]}), first)
            pq.write_table(pa.table({"day": [2], "vehicle": ["USDC"]}), second)

            assemble_parquet_shards([first, second], output)

            table = pq.read_table(output)
            self.assertEqual(table.column("vehicle").to_pylist(), [None, "USDC"])

    def test_failed_assembly_preserves_the_previous_output_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "20200101.parquet"
            bad = root / "20200102.parquet"
            output = root / "panel.parquet"
            pq.write_table(pa.table({"day": [0]}), output)
            before = output.read_bytes()
            pq.write_table(pa.table({"day": [1]}), good)
            bad.write_text("not parquet")

            with self.assertRaises(Exception):
                assemble_parquet_shards([good, bad], output)

            self.assertEqual(output.read_bytes(), before)
            self.assertFalse((root / "panel.parquet.tmp").exists())
            self.assertEqual(list(root.glob(".panel.parquet.*.tmp")), [])

    def test_duplicate_key_contract_preserves_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard = root / "20200101.parquet"
            output = root / "panel.parquet"
            pq.write_table(pa.table({"day": [0], "pair": ["old"]}), output)
            before = output.read_bytes()
            pq.write_table(
                pa.table({"day": [1, 1], "pair": ["a", "a"]}),
                shard,
            )

            with self.assertRaisesRegex(ValueError, "duplicate keys"):
                assemble_parquet_shards(
                    [shard],
                    output,
                    unique_keys=("day", "pair"),
                )

            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(list(root.glob(".panel.parquet.*.tmp")), [])

if __name__ == "__main__":
    unittest.main()
