from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.panel_assembly import assemble_parquet_shards
from scripts import assemble_route_cost_panel as route_assembly


class PanelAssemblyTests(unittest.TestCase):
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

    def test_automatic_cache_selection_refuses_a_fullest_tie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for engine in ("engine_a", "engine_b"):
                spec = root / engine / "hall"
                spec.mkdir(parents=True)
                (spec / "20200101.parquet").touch()
            original = route_assembly.CACHE
            route_assembly.CACHE = root
            try:
                with self.assertRaisesRegex(RuntimeError, "ambiguous fullest caches"):
                    route_assembly.fullest_spec()
            finally:
                route_assembly.CACHE = original


if __name__ == "__main__":
    unittest.main()
