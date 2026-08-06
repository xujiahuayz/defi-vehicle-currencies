from __future__ import annotations

import unittest

from ddvc.analysis.block_timing import PoolView


class PoolViewTests(unittest.TestCase):
    def test_pre_event_lookup_is_strict_in_block_log_order(self) -> None:
        view = PoolView(
            [
                (100, 3, 1_000, 0, 1.0),
                (100, 9, 1_001, 0, 2.0),
                (101, 1, 1_002, 0, 3.0),
            ]
        )
        self.assertIsNone(view.before(100, 3))
        self.assertEqual(view.before(100, 9), 1.0)
        self.assertEqual(view.before(100, 10), 2.0)
        self.assertEqual(view.before(101, 1), 2.0)
        self.assertEqual(view.before(102, 0), 3.0)

    def test_hour_state_uses_last_observed_post_swap_state(self) -> None:
        view = PoolView(
            [
                (100, 3, 1_000, 0, 1.0),
                (100, 9, 1_001, 0, 2.0),
                (101, 1, 3_601, 1, 3.0),
            ]
        )
        self.assertEqual(view.at_hour(0), 2.0)
        self.assertEqual(view.at_hour(1), 3.0)


if __name__ == "__main__":
    unittest.main()
