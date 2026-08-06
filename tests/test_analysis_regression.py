from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    ols_clustered,
    ols_clustered_named,
    ols_hac,
)


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

    def test_multiway_absorption_matches_dummy_regression_on_unbalanced_panel(self) -> None:
        frame = pd.DataFrame(
            {
                "a": ["a", "a", "a", "b", "b", "c", "c"],
                "b": [1, 2, 3, 1, 3, 2, 3],
                "value": [3.0, 5.0, 8.0, 2.0, 7.0, 4.0, 9.0],
            }
        )
        absorbed = absorb_fixed_effects(frame["value"], frame["a"], frame["b"])
        dummies = pd.get_dummies(frame[["a", "b"]].astype(str), drop_first=True, dtype=float)
        design = np.column_stack([np.ones(len(frame)), dummies.to_numpy()])
        expected = frame["value"].to_numpy() - design @ np.linalg.lstsq(
            design, frame["value"].to_numpy(), rcond=None
        )[0]
        np.testing.assert_allclose(absorbed, expected, atol=1e-9)
        for group in [frame["a"], frame["b"]]:
            np.testing.assert_allclose(absorbed.groupby(group).mean(), 0.0, atol=1e-9)

    def test_clustered_ols_matches_manual_cr1_covariance(self) -> None:
        x_value = np.arange(12, dtype=float)
        design = x_value[:, None]
        outcome = 2.0 + 0.5 * x_value + np.array([0.0, 1.0, -1.0] * 4)
        cluster = np.repeat(np.arange(4), 3)
        result = ols_clustered(outcome, design, cluster)
        x_with_constant = np.column_stack([np.ones(len(x_value)), x_value])
        beta = np.linalg.lstsq(x_with_constant, outcome, rcond=None)[0]
        residual = outcome - x_with_constant @ beta
        bread = np.linalg.inv(x_with_constant.T @ x_with_constant)
        meat = np.zeros((2, 2))
        for group in np.unique(cluster):
            score = x_with_constant[cluster == group].T @ residual[cluster == group]
            meat += np.outer(score, score)
        scale = (4 / 3) * (11 / 10)
        expected_covariance = scale * bread @ meat @ bread
        np.testing.assert_allclose(result.beta, beta)
        np.testing.assert_allclose(result.covariance, expected_covariance)
        self.assertEqual(result.n_clusters, 4)
        self.assertEqual(
            set(result.named_statistics(["constant", "slope"])),
            {
                "constant_beta",
                "constant_se",
                "constant_t",
                "constant_p",
                "slope_beta",
                "slope_se",
                "slope_t",
                "slope_p",
            },
        )
        n, clusters, named = ols_clustered_named(
            pd.Series(outcome),
            pd.DataFrame({"slope": x_value}),
            pd.Series(cluster),
        )
        self.assertEqual((n, clusters), (12, 4))
        self.assertAlmostEqual(named["slope_beta"], beta[1])

    def test_clustered_ols_returns_nan_when_rank_deficient(self) -> None:
        result = ols_clustered(
            np.arange(6, dtype=float),
            np.ones((6, 1)),
            np.repeat(["a", "b"], 3),
        )
        self.assertTrue(np.isnan(result.beta).all())

    def test_clustered_ols_counts_absorbed_fixed_effect_degrees_of_freedom(self) -> None:
        x_value = np.arange(12, dtype=float)
        outcome = 1.0 + 0.25 * x_value + np.array([0.0, 1.0, -1.0] * 4)
        cluster = np.repeat(np.arange(4), 3)
        one_way = np.repeat(["a", "b", "c"], 4)
        uncorrected = ols_clustered(outcome, x_value, cluster)
        corrected = ols_clustered(
            outcome,
            x_value,
            cluster,
            absorbed_groups=(one_way,),
        )
        self.assertEqual(corrected.absorbed_degrees_of_freedom, 2)
        np.testing.assert_allclose(corrected.beta, uncorrected.beta)
        np.testing.assert_allclose(
            corrected.covariance,
            uncorrected.covariance * ((12 - 2) / (12 - 2 - 2)),
        )

        first = np.array(["a", "a", "b", "b", "c", "c"])
        second = np.array([1, 2, 2, 3, 3, 1])
        connected = ols_clustered(
            np.arange(6, dtype=float),
            np.arange(6, dtype=float),
            np.repeat(["x", "y", "z"], 2),
            absorbed_groups=(first, second),
        )
        self.assertEqual(connected.absorbed_degrees_of_freedom, 4)


if __name__ == "__main__":
    unittest.main()
