from __future__ import annotations

import unittest

import numpy as np

from ddvc.analysis.regression import ols_hac


class RegressionPrimitiveTests(unittest.TestCase):
    def test_hac_preserves_the_ols_point_estimate(self) -> None:
        x_value = np.arange(12, dtype=float)
        design = np.column_stack([np.ones(len(x_value)), x_value])
        outcome = 2.0 + 3.0 * x_value + np.array([0.0, 1.0, -1.0] * 4)
        beta, covariance = ols_hac(outcome, design, lag=3)
        expected = np.linalg.lstsq(design, outcome, rcond=None)[0]
        np.testing.assert_allclose(beta, expected)
        np.testing.assert_allclose(covariance, covariance.T)
        self.assertTrue(np.isfinite(covariance).all())

    def test_hac_rejects_misaligned_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "one outcome"):
            ols_hac(np.ones(2), np.ones((3, 1)), lag=1)


if __name__ == "__main__":
    unittest.main()
