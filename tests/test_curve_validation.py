from __future__ import annotations

import unittest

from scripts.validate_curve_quoter import summarise_errors


class CurveValidationTest(unittest.TestCase):
    def test_error_summary_preserves_tail_and_overquote_direction(self) -> None:
        summary = summarise_errors([-2.0, -0.2, 0.0, 0.2, 0.8])

        self.assertAlmostEqual(summary["median_abs_err_pct"], 0.2)
        self.assertAlmostEqual(summary["p90_abs_err_pct"], 1.52)
        self.assertAlmostEqual(summary["max_abs_err_pct"], 2.0)
        self.assertAlmostEqual(summary["within_1pct"], 80.0)
        self.assertAlmostEqual(summary["overquote_gt_10bps_pct"], 40.0)
        self.assertAlmostEqual(summary["overquote_gt_25bps_pct"], 20.0)


if __name__ == "__main__":
    unittest.main()
