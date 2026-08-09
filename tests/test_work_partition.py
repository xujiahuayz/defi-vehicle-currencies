from __future__ import annotations

import unittest

from ddvc.work_partition import weighted_contiguous_chunks


class WeightedContiguousChunksTests(unittest.TestCase):
    def test_preserves_order_and_uses_requested_nonempty_parts(self) -> None:
        items = list("abcdefg")
        chunks = weighted_contiguous_chunks(items, [1] * len(items), 3)
        self.assertEqual([item for chunk in chunks for item in chunk], items)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(chunks))

    def test_balances_late_heavy_inputs_instead_of_day_counts(self) -> None:
        items = list(range(12))
        weights = [1] * 6 + [10] * 6
        chunks = weighted_contiguous_chunks(items, weights, 3)
        loads = [sum(weights[item] for item in chunk) for chunk in chunks]
        self.assertEqual([item for chunk in chunks for item in chunk], items)
        self.assertLessEqual(max(loads), 30)
        self.assertGreater(len(chunks[0]), len(chunks[-1]))

    def test_single_large_day_sets_the_minimax_capacity(self) -> None:
        chunks = weighted_contiguous_chunks(list(range(5)), [1, 1, 100, 1, 1], 3)
        self.assertEqual(chunks, [[0, 1], [2], [3, 4]])

    def test_rejects_mismatched_inputs_and_invalid_part_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "same length"):
            weighted_contiguous_chunks([1], [], 1)
        with self.assertRaisesRegex(ValueError, "positive"):
            weighted_contiguous_chunks([1], [1], 0)


if __name__ == "__main__":
    unittest.main()
