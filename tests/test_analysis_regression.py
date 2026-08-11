from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    ClusteredOLSResult,
    absorb_fixed_effects,
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    joint_wald_f,
    linear_contrast,
    mean_clustered,
    ols_clustered,
    ols_clustered_named,
    ols_hac,
    year_endpoint_change,
)


class RegressionPrimitiveTests(unittest.TestCase):
    def test_negative_covariance_variance_is_missing_not_zero(self) -> None:
        result = ClusteredOLSResult(
            beta=np.array([1.0]),
            covariance=np.array([[-1.0]]),
            n_observations=10,
            n_clusters=5,
            absorbed_degrees_of_freedom=0,
        )
        self.assertTrue(np.isnan(result.standard_errors[0]))
        self.assertTrue(np.isnan(result.t_statistics[0]))
        self.assertTrue(np.isnan(result.p_values[0]))

    def test_clustered_mean_uses_cluster_scores_not_bernoulli_iid_variance(self) -> None:
        result = mean_clustered(
            np.array([1.0, 1.0, 0.0, 0.0]),
            np.array(["a", "a", "b", "b"]),
        )
        self.assertAlmostEqual(result.estimate, 0.5)
        self.assertEqual(result.n_observations, 4)
        self.assertEqual(result.n_clusters, 2)
        self.assertGreater(result.standard_error, 0.0)

    def test_holm_adjustment_is_monotone_in_sorted_pvalues(self) -> None:
        adjusted = holm_adjusted_pvalues(np.array([0.01, 0.04, 0.03, np.nan]))
        np.testing.assert_allclose(adjusted[:3], [0.03, 0.06, 0.06])
        self.assertTrue(np.isnan(adjusted[3]))

    def test_joint_wald_f_uses_named_clustered_covariance_block(self) -> None:
        result = ClusteredOLSResult(
            beta=np.array([1.0, 2.0]),
            covariance=np.diag([1.0, 4.0]),
            n_observations=100,
            n_clusters=10,
            absorbed_degrees_of_freedom=0,
        )
        statistic, numerator_df, denominator_df, p_value = joint_wald_f(
            result, ("first", "second"), ("first", "second")
        )
        self.assertAlmostEqual(statistic, 1.0)
        self.assertEqual(numerator_df, 2)
        self.assertEqual(denominator_df, 9)
        self.assertAlmostEqual(p_value, stats.f.sf(1.0, 2, 9))
        with self.assertRaisesRegex(ValueError, "must be unique"):
            joint_wald_f(result, ("first", "first"), ("first",))
        with self.assertRaisesRegex(ValueError, "must be unique"):
            joint_wald_f(result, ("first", "second"), ("first", "first"))

    def test_linear_contrast_uses_full_clustered_covariance(self) -> None:
        result = ClusteredOLSResult(
            beta=np.array([3.0, 2.0]),
            covariance=np.array([[4.0, 1.0], [1.0, 9.0]]),
            n_observations=100,
            n_clusters=11,
            absorbed_degrees_of_freedom=0,
        )
        contrast = linear_contrast(result, (1.0, -2.0))
        self.assertAlmostEqual(contrast.estimate, -1.0)
        self.assertAlmostEqual(contrast.standard_error, 6.0)
        self.assertEqual(contrast.degrees_freedom, 10)
        self.assertLess(contrast.confidence_interval_lower, contrast.estimate)
        self.assertGreater(contrast.confidence_interval_upper, contrast.estimate)
        invalid = replace(result, covariance=np.array([[-1.0, 0.0], [0.0, 1.0]]))
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            linear_contrast(invalid, (1.0, 0.0))

    def test_common_calendar_mask_balances_a_partial_endpoint_year(self) -> None:
        dates = pd.to_datetime(
            ["2022-01-01", "2022-07-01", "2024-01-01", "2024-07-01", "2026-01-01"]
        )
        years = dates.year.to_numpy()
        mask = common_calendar_day_mask(
            dates,
            years,
            baseline_year=2022,
            comparison_year=2026,
        )
        self.assertEqual(mask.tolist(), [True, False, True, False, True])

    def test_year_endpoint_change_owns_year_dummy_hac_contrast(self) -> None:
        estimate = year_endpoint_change(
            np.array([0.0, 0.2, 0.4, 0.8, 1.0, 1.2]),
            np.array([2022, 2022, 2024, 2024, 2026, 2026]),
            baseline_year=2022,
            comparison_year=2026,
            hac_lag=0,
        )
        self.assertAlmostEqual(estimate.baseline_mean, 0.1)
        self.assertAlmostEqual(estimate.comparison_mean, 1.1)
        self.assertAlmostEqual(estimate.change, 1.0)
        self.assertEqual(estimate.n_observations, 6)
        with self.assertRaisesRegex(ValueError, "both endpoint years"):
            year_endpoint_change(
                np.array([0.0, 0.2]),
                np.array([2022, 2022]),
                baseline_year=2022,
                comparison_year=2026,
                hac_lag=0,
            )

    def test_hac_preserves_the_ols_point_estimate(self) -> None:
        x_value = np.arange(12, dtype=float)
        design = np.column_stack([np.ones(len(x_value)), x_value])
        outcome = 2.0 + 3.0 * x_value + np.array([0.0, 1.0, -1.0] * 4)
        beta, covariance = ols_hac(outcome, design, lag=3)
        expected = np.linalg.lstsq(design, outcome, rcond=None)[0]
        np.testing.assert_allclose(beta, expected)
        np.testing.assert_allclose(covariance, covariance.T)
        self.assertTrue(np.isfinite(covariance).all())

    def test_hac_calendar_index_does_not_join_unsupported_gaps(self) -> None:
        outcome = np.array([0.0, 1.0, 0.0, 1.0])
        design = np.ones((4, 1))
        adjacent_dates = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
        )
        gapped_dates = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2025-01-01", "2025-01-02"]
        )
        _beta, adjacent = ols_hac(
            outcome, design, lag=1, time_index=adjacent_dates
        )
        _beta, gapped = ols_hac(
            outcome, design, lag=1, time_index=gapped_dates
        )
        self.assertNotAlmostEqual(float(adjacent[0, 0]), float(gapped[0, 0]))

    def test_year_endpoint_change_uses_calendar_dates_when_supplied(self) -> None:
        dates = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2025-01-01", "2026-01-01", "2026-01-02"]
        )
        estimate = year_endpoint_change(
            np.array([0.0, 0.2, 0.4, 0.8, 1.0]),
            dates.year.to_numpy(),
            baseline_year=2024,
            comparison_year=2026,
            hac_lag=1,
            dates=dates,
        )
        self.assertAlmostEqual(estimate.change, 0.8)
        self.assertEqual(estimate.n_observations, 5)

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

    def test_weighted_absorption_zeroes_weighted_group_means(self) -> None:
        frame = pd.DataFrame(
            {
                "group": ["a", "a", "b", "b"],
                "value": [1.0, 4.0, 2.0, 8.0],
                "weight": [1.0, 3.0, 2.0, 1.0],
            }
        )
        absorbed = absorb_fixed_effects(
            frame["value"],
            frame["group"],
            weights=frame["weight"],
        )
        weighted_sums = (absorbed * frame["weight"]).groupby(frame["group"]).sum()
        np.testing.assert_allclose(weighted_sums, 0.0, atol=1e-12)

    def test_weighted_absorption_rejects_nonpositive_weights(self) -> None:
        values = pd.Series([1.0, 2.0])
        groups = pd.Series(["a", "a"])
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            absorb_fixed_effects(values, groups, weights=np.array([1.0, 0.0]))

    def test_weighted_multiway_absorption_matches_dummy_wls(self) -> None:
        frame = pd.DataFrame(
            {
                "a": ["a", "a", "a", "b", "b", "c", "c"],
                "b": [1, 2, 3, 1, 3, 2, 3],
                "value": [3.0, 5.0, 8.0, 2.0, 7.0, 4.0, 9.0],
                "weight": [1.0, 2.0, 1.0, 3.0, 2.0, 4.0, 1.0],
            }
        )
        absorbed = absorb_fixed_effects(
            frame["value"],
            frame["a"],
            frame["b"],
            weights=frame["weight"],
        )
        dummies = pd.get_dummies(frame[["a", "b"]].astype(str), drop_first=True, dtype=float)
        design = np.column_stack([np.ones(len(frame)), dummies.to_numpy()])
        square_root_weights = np.sqrt(frame["weight"].to_numpy())
        weighted_design = design * square_root_weights[:, None]
        weighted_outcome = frame["value"].to_numpy() * square_root_weights
        coefficient = np.linalg.lstsq(weighted_design, weighted_outcome, rcond=None)[0]
        expected = frame["value"].to_numpy() - design @ coefficient
        np.testing.assert_allclose(absorbed, expected, atol=1e-9)

    def test_absorb_fixed_effects_reuses_high_cardinality_group_codes(self) -> None:
        rows = 100_000
        values = pd.Series(np.sin(np.arange(rows) / 19.0))
        first = pd.Series(np.arange(rows) // 2)
        second = pd.Series(np.arange(rows) % 2)
        absorbed = absorb_fixed_effects(values, first, second)
        self.assertEqual(len(absorbed), rows)
        np.testing.assert_allclose(absorbed.groupby(first).mean(), 0.0, atol=1e-10)
        np.testing.assert_allclose(absorbed.groupby(second).mean(), 0.0, atol=1e-10)

    def test_absorb_fixed_effects_rejects_missing_group_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot contain missing"):
            absorb_fixed_effects(
                pd.Series([1.0, 2.0, 3.0]),
                pd.Series(["a", None, "b"]),
            )

    def test_absorb_fixed_effects_preserves_partial_missing_values_by_column(self) -> None:
        frame = pd.DataFrame(
            {
                "group": ["a", "a", "a", "b", "b"],
                "first": [1.0, np.nan, 5.0, 2.0, 8.0],
                "second": [np.nan, 4.0, 10.0, 3.0, 9.0],
            }
        )

        absorbed = absorb_fixed_effects(frame[["first", "second"]], frame["group"])

        self.assertTrue(absorbed.isna().equals(frame[["first", "second"]].isna()))
        for column in ["first", "second"]:
            np.testing.assert_allclose(
                absorbed[column].groupby(frame["group"]).mean(),
                0.0,
                atol=1e-12,
            )

    def test_weighted_absorption_excludes_missing_values_from_group_weight(self) -> None:
        frame = pd.DataFrame(
            {
                "group": ["a", "a", "a", "b", "b"],
                "value": [1.0, np.nan, 5.0, 2.0, 8.0],
                "weight": [1.0, 100.0, 3.0, 2.0, 1.0],
            }
        )

        absorbed = absorb_fixed_effects(
            frame["value"],
            frame["group"],
            weights=frame["weight"],
        )

        self.assertTrue(np.isnan(absorbed.iloc[1]))
        weighted_sums = (absorbed * frame["weight"]).groupby(frame["group"]).sum()
        np.testing.assert_allclose(weighted_sums, 0.0, atol=1e-12)

    def test_absorb_fixed_effects_rejects_infinite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot contain infinite"):
            absorb_fixed_effects(
                pd.Series([1.0, np.inf, 3.0]),
                pd.Series(["a", "a", "b"]),
            )

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

    def test_weighted_clustered_ols_matches_direct_wls_point_estimate(self) -> None:
        x_value = np.arange(8, dtype=float)
        design = np.column_stack([np.ones(len(x_value)), x_value])
        outcome = 1.0 + 0.75 * x_value + np.array([0.0, 1.0, -0.5, 0.25] * 2)
        weights = np.array([1.0, 2.0, 1.0, 4.0, 1.0, 3.0, 2.0, 1.0])
        result = ols_clustered(
            outcome,
            x_value,
            np.repeat(["a", "b", "c", "d"], 2),
            weights=weights,
        )
        expected = np.linalg.solve(
            design.T @ (weights[:, None] * design),
            design.T @ (weights * outcome),
        )
        np.testing.assert_allclose(result.beta, expected)

    def test_weighted_clustered_ols_rejects_nonpositive_weights(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            ols_clustered(
                np.arange(4.0),
                np.arange(4.0),
                np.array(["a", "a", "b", "b"]),
                weights=np.array([1.0, 1.0, 0.0, 1.0]),
            )

    def test_frequency_weighted_two_way_covariance_matches_row_expansion(self) -> None:
        outcome = np.array([0.0, 1.0, 0.5, 1.5, -0.5, 2.0, 1.0, 2.5])
        design = np.arange(8, dtype=float)
        first = np.repeat(["a", "b", "c", "d"], 2)
        second = np.tile(["t1", "t2"], 4)
        counts = np.array([1, 3, 2, 4, 3, 1, 2, 5])
        grouped = ols_clustered(
            outcome,
            design,
            first,
            additional_clusters=(second,),
            weights=counts,
            frequency_weights=True,
        )
        expanded = ols_clustered(
            np.repeat(outcome, counts),
            np.repeat(design, counts),
            np.repeat(first, counts),
            additional_clusters=(np.repeat(second, counts),),
        )
        np.testing.assert_allclose(grouped.beta, expanded.beta)
        np.testing.assert_allclose(grouped.covariance, expanded.covariance)
        self.assertEqual(grouped.n_observations, len(outcome))
        self.assertEqual(grouped.finite_sample_observations, int(counts.sum()))

    def test_frequency_weights_reject_noninteger_analytic_weights(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integers"):
            ols_clustered(
                np.arange(4.0),
                np.arange(4.0),
                np.array(["a", "a", "b", "b"]),
                weights=np.array([1.0, 1.5, 2.0, 1.0]),
                frequency_weights=True,
            )

    def test_two_way_clustered_ols_matches_cr1_inclusion_exclusion(self) -> None:
        x_value = np.arange(12, dtype=float)
        design = np.column_stack([np.ones(len(x_value)), x_value])
        outcome = 2.0 + 0.5 * x_value + np.array(
            [0.0, 1.0, -0.5, 0.5, -1.0, 0.25] * 2
        )
        pool = np.repeat(["a", "b", "c", "d"], 3)
        month = np.tile(["m1", "m2", "m3"], 4)
        result = ols_clustered(
            outcome,
            x_value,
            pool,
            additional_clusters=(month,),
        )
        beta = np.linalg.lstsq(design, outcome, rcond=None)[0]
        residual = outcome - design @ beta
        bread = np.linalg.inv(design.T @ design)

        def covariance(labels: object) -> np.ndarray:
            codes, unique = pd.factorize(labels)
            meat = np.zeros((2, 2))
            for code in range(len(unique)):
                score = design[codes == code].T @ residual[codes == code]
                meat += np.outer(score, score)
            scale = (len(unique) / (len(unique) - 1)) * (11 / 10)
            return scale * bread @ meat @ bread

        expected = (
            covariance(pool)
            + covariance(month)
            - covariance(pd.MultiIndex.from_arrays([pool, month]))
        )
        np.testing.assert_allclose(result.beta, beta)
        np.testing.assert_allclose(result.covariance, expected)
        self.assertEqual(result.cluster_counts, (4, 3))
        self.assertEqual(result.n_clusters, 3)
        expected_p = 2 * stats.t.sf(abs(result.t_statistics), 2)
        np.testing.assert_allclose(result.p_values, expected_p)

    def test_many_cluster_groups_use_bounded_grouped_score_accumulation(self) -> None:
        rows = 40_000
        x_value = np.linspace(-2.0, 2.0, rows)
        outcome = 1.5 + 0.4 * x_value + np.sin(np.arange(rows) / 13.0)
        first = np.arange(rows) // 2
        second = np.arange(rows) % 101
        result = ols_clustered(
            outcome,
            x_value,
            first,
            additional_clusters=(second,),
        )
        self.assertEqual(result.n_observations, rows)
        self.assertEqual(result.cluster_counts, (20_000, 101))
        np.testing.assert_allclose(result.beta, [1.5, 0.4], atol=1e-3)
        self.assertTrue(np.isfinite(result.covariance).all())

    def test_multiway_cluster_rejects_hac_and_a_third_dimension(self) -> None:
        values = np.arange(8, dtype=float)
        first = np.repeat(["a", "b"], 4)
        second = np.tile(["x", "y"], 4)
        with self.assertRaisesRegex(ValueError, "HAC cannot be combined"):
            ols_clustered(
                values,
                values,
                first,
                additional_clusters=(second,),
                cluster_hac_lag=1,
            )
        with self.assertRaisesRegex(ValueError, "at most two"):
            ols_clustered(
                values,
                values,
                first,
                additional_clusters=(second, first),
            )

    def test_clustered_ols_returns_nan_when_rank_deficient(self) -> None:
        result = ols_clustered(
            np.arange(6, dtype=float),
            np.ones((6, 1)),
            np.repeat(["a", "b"], 3),
        )
        self.assertTrue(np.isnan(result.beta).all())

    def test_cluster_hac_lag_zero_matches_clustered_inference(self) -> None:
        time = np.repeat(np.arange(6), 2)
        x_value = np.tile([0.0, 1.0], 6) + time
        outcome = 1.0 + 0.5 * x_value + np.repeat([0.0, 1.0, -0.5], 4)
        clustered = ols_clustered(outcome, x_value, time)
        hac_zero = ols_clustered(
            outcome[::-1],
            x_value[::-1],
            time[::-1],
            cluster_hac_lag=0,
        )
        np.testing.assert_allclose(hac_zero.beta, clustered.beta)
        np.testing.assert_allclose(hac_zero.covariance, clustered.covariance)
        hac_forward = ols_clustered(outcome, x_value, time, cluster_hac_lag=2)
        hac_reverse = ols_clustered(
            outcome[::-1], x_value[::-1], time[::-1], cluster_hac_lag=2
        )
        np.testing.assert_allclose(hac_reverse.beta, hac_forward.beta)
        np.testing.assert_allclose(hac_reverse.covariance, hac_forward.covariance)

    def test_cluster_hac_rejects_negative_lag(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            ols_clustered(np.arange(4.0), np.arange(4.0), [0, 0, 1, 1], cluster_hac_lag=-1)

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
