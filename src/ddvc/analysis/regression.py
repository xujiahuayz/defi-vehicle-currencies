"""Small regression primitives shared by empirical runners."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


def holm_adjusted_pvalues(values: pd.Series | np.ndarray) -> np.ndarray:
    """Holm family-wise adjusted p-values, preserving missing positions."""
    pvalues = np.asarray(values, dtype=float).reshape(-1)
    adjusted = np.full(len(pvalues), np.nan, dtype=float)
    finite_positions = np.flatnonzero(np.isfinite(pvalues))
    if not len(finite_positions):
        return adjusted
    ordered_positions = finite_positions[
        np.argsort(pvalues[finite_positions], kind="stable")
    ]
    scaled = np.array(
        [
            min((len(ordered_positions) - rank) * pvalues[position], 1.0)
            for rank, position in enumerate(ordered_positions)
        ]
    )
    monotone = np.maximum.accumulate(scaled)
    adjusted[ordered_positions] = monotone
    return adjusted


@dataclass(frozen=True)
class ClusteredOLSResult:
    """OLS estimates and one-way cluster-robust inference."""

    beta: np.ndarray
    covariance: np.ndarray
    n_observations: int
    n_clusters: int
    absorbed_degrees_of_freedom: int

    @property
    def standard_errors(self) -> np.ndarray:
        return np.sqrt(np.maximum(np.diag(self.covariance), 0.0))

    @property
    def t_statistics(self) -> np.ndarray:
        return np.divide(
            self.beta,
            self.standard_errors,
            out=np.full_like(self.beta, np.nan, dtype=float),
            where=self.standard_errors > 0,
        )

    @property
    def p_values(self) -> np.ndarray:
        if self.n_clusters < 2:
            return np.full_like(self.beta, np.nan, dtype=float)
        return 2 * stats.t.sf(np.abs(self.t_statistics), self.n_clusters - 1)

    def named_statistics(
        self, names: list[str], *, offset: int = 0
    ) -> dict[str, float]:
        """Return coefficient, standard-error, t, and p fields by regressor."""
        if len(names) + offset != len(self.beta):
            raise ValueError("coefficient names do not match the fitted design")
        statistics: dict[str, float] = {}
        for index, name in enumerate(names, start=offset):
            statistics[f"{name}_beta"] = float(self.beta[index])
            statistics[f"{name}_se"] = float(self.standard_errors[index])
            statistics[f"{name}_t"] = float(self.t_statistics[index])
            statistics[f"{name}_p"] = float(self.p_values[index])
        return statistics


@dataclass(frozen=True)
class ClusteredMeanResult:
    """Mean and confidence interval with one-way cluster dependence."""

    estimate: float
    standard_error: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    n_observations: int
    n_clusters: int


def mean_clustered(
    values: pd.Series | np.ndarray,
    clusters: pd.Series | np.ndarray,
    *,
    confidence_level: float = 0.95,
) -> ClusteredMeanResult:
    """Estimate a mean with a finite-cluster CR1 confidence interval."""
    value_array = np.asarray(values, dtype=float).reshape(-1)
    cluster_array = np.asarray(clusters).reshape(-1)
    if len(value_array) != len(cluster_array):
        raise ValueError("clustered mean requires one cluster per observation")
    if not 0 < confidence_level < 1:
        raise ValueError("clustered mean confidence level must lie inside zero and one")
    finite = np.isfinite(value_array) & pd.notna(cluster_array)
    value_array = value_array[finite]
    cluster_array = cluster_array[finite]
    if not len(value_array):
        raise ValueError("clustered mean inputs cannot be empty")
    estimate = float(value_array.mean())
    scores = pd.Series(value_array - estimate).groupby(cluster_array).sum()
    n_clusters = len(scores)
    if n_clusters < 2:
        standard_error = float("nan")
        lower = float("nan")
        upper = float("nan")
    else:
        variance = (
            n_clusters
            / (n_clusters - 1)
            * float(scores.pow(2).sum())
            / len(value_array) ** 2
        )
        standard_error = float(np.sqrt(max(variance, 0.0)))
        critical = float(
            stats.t.ppf(0.5 + confidence_level / 2, n_clusters - 1)
        )
        lower = estimate - critical * standard_error
        upper = estimate + critical * standard_error
    return ClusteredMeanResult(
        estimate=estimate,
        standard_error=standard_error,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        n_observations=len(value_array),
        n_clusters=n_clusters,
    )


@dataclass(frozen=True)
class YearEndpointChange:
    """HAC contrast between two endpoint-year means in an ordered series."""

    baseline_mean: float
    comparison_mean: float
    change: float
    standard_error: float
    t_statistic: float
    p_value: float
    n_observations: int
    degrees_freedom: int


def common_calendar_day_mask(
    dates: pd.Series | np.ndarray,
    years: pd.Series | np.ndarray,
    *,
    baseline_year: int,
    comparison_year: int,
) -> np.ndarray:
    """Keep daily observations at month-and-day positions seen in both endpoint years."""
    date_array = pd.to_datetime(pd.Series(np.asarray(dates).reshape(-1)), errors="coerce")
    year_array = np.asarray(years).reshape(-1)
    if len(date_array) != len(year_array):
        raise ValueError("calendar-balance dates and years must have the same row count")
    valid = date_array.notna().to_numpy() & pd.notna(year_array)
    stamps = date_array.dt.strftime("%m-%d").to_numpy()
    baseline_days = set(stamps[valid & (year_array == baseline_year)])
    comparison_days = set(stamps[valid & (year_array == comparison_year)])
    common_days = baseline_days & comparison_days
    if not common_days:
        raise ValueError("calendar balance requires common endpoint-year days")
    return valid & np.isin(stamps, list(common_days))


def absorb_fixed_effects(
    values: pd.Series | pd.DataFrame,
    *groups: pd.Series,
    tolerance: float = 1e-10,
    max_iterations: int = 10_000,
) -> pd.Series | pd.DataFrame:
    """Residualize values against one or more categorical fixed effects.

    Alternating projections are required for unbalanced multi-way panels. The
    common one-pass expression ``x - mean_a - mean_b + mean(x)`` is exact only
    when the two fixed-effect partitions are orthogonal.
    """
    if not groups:
        raise ValueError("at least one fixed-effect group is required")
    if tolerance <= 0 or max_iterations < 1:
        raise ValueError("fixed-effect absorption requires positive convergence controls")
    result = values.astype(float).copy()
    for group in groups:
        if len(group) != len(result) or not group.index.equals(result.index):
            raise ValueError("fixed-effect groups must align with the values")
    for _ in range(max_iterations):
        previous = result.copy()
        for group in groups:
            result -= result.groupby(group, observed=True).transform("mean")
        delta = (result - previous).abs().to_numpy(dtype=float)
        if delta.size == 0 or np.nanmax(delta) <= tolerance:
            return result
    raise RuntimeError("fixed-effect absorption did not converge")


def _absorbed_fixed_effect_rank(groups: list[np.ndarray]) -> int:
    """Exact dummy-matrix rank for one or two fixed effects."""
    if not groups:
        return 0
    codes = [pd.factorize(group, sort=False)[0] for group in groups]
    levels = [int(code.max()) + 1 if len(code) else 0 for code in codes]
    if len(groups) == 1:
        return levels[0]

    first_levels, second_levels = levels
    parents = list(range(first_levels + second_levels))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for first, second in zip(codes[0], codes[1], strict=True):
        left = root(int(first))
        right = root(first_levels + int(second))
        if left != right:
            parents[right] = left
    components = len({root(index) for index in range(len(parents))})
    return max(first_levels + second_levels - components, 0)


def ols_clustered(
    y: pd.Series | np.ndarray,
    x: pd.DataFrame | np.ndarray,
    cluster: pd.Series | np.ndarray,
    *,
    add_constant: bool = True,
    k_absorbed: int = 0,
    absorbed_groups: tuple[pd.Series | np.ndarray, ...] = (),
    min_observations: int = 1,
    min_clusters: int = 2,
    cluster_hac_lag: int | None = None,
) -> ClusteredOLSResult:
    """Fit OLS with CR1 inference, optionally HAC across ordered clusters."""
    if cluster_hac_lag is not None and cluster_hac_lag < 0:
        raise ValueError("cluster HAC lag must be nonnegative")
    y_array = np.asarray(y, dtype=float).reshape(-1)
    x_array = np.asarray(x, dtype=float)
    cluster_array = np.asarray(cluster).reshape(-1)
    if x_array.ndim == 1:
        x_array = x_array[:, None]
    if len(y_array) != len(x_array) or len(y_array) != len(cluster_array):
        raise ValueError("clustered OLS inputs must have the same row count")
    group_arrays = [np.asarray(group).reshape(-1) for group in absorbed_groups]
    if any(len(group) != len(y_array) for group in group_arrays):
        raise ValueError("absorbed fixed-effect groups must align with the regression inputs")
    if len(group_arrays) > 2:
        raise ValueError("absorbed degree-of-freedom correction supports at most two fixed effects")
    finite = np.isfinite(y_array) & np.isfinite(x_array).all(axis=1) & pd.notna(cluster_array)
    for group in group_arrays:
        finite &= pd.notna(group)
    y_array = y_array[finite]
    x_array = x_array[finite]
    cluster_array = cluster_array[finite]
    group_arrays = [group[finite] for group in group_arrays]
    if add_constant:
        x_array = np.column_stack([np.ones(len(x_array)), x_array])
    n, k = x_array.shape
    cluster_codes, unique_clusters = pd.factorize(
        cluster_array, sort=cluster_hac_lag is not None
    )
    n_clusters = len(unique_clusters)
    absorbed_rank = _absorbed_fixed_effect_rank(group_arrays)
    absorbed_degrees_of_freedom = k_absorbed + max(
        absorbed_rank - int(add_constant and absorbed_rank > 0),
        0,
    )
    empty = ClusteredOLSResult(
        beta=np.full(k, np.nan),
        covariance=np.full((k, k), np.nan),
        n_observations=n,
        n_clusters=n_clusters,
        absorbed_degrees_of_freedom=absorbed_degrees_of_freedom,
    )
    if (
        n < min_observations
        or n_clusters < min_clusters
        or n <= k + absorbed_degrees_of_freedom
    ):
        return empty
    if np.linalg.matrix_rank(x_array) < k:
        return empty
    xtx_inverse = np.linalg.pinv(x_array.T @ x_array)
    beta = xtx_inverse @ (x_array.T @ y_array)
    residual = y_array - x_array @ beta
    scores = np.zeros((n_clusters, k))
    for code in range(n_clusters):
        selected = cluster_codes == code
        scores[code] = x_array[selected].T @ residual[selected]
    meat = scores.T @ scores
    if cluster_hac_lag is not None:
        for offset in range(1, min(cluster_hac_lag, n_clusters - 1) + 1):
            weight = 1.0 - offset / (cluster_hac_lag + 1.0)
            autocovariance = scores[offset:].T @ scores[:-offset]
            meat += weight * (autocovariance + autocovariance.T)
    scale = (n_clusters / (n_clusters - 1)) * (
        (n - 1) / (n - k - absorbed_degrees_of_freedom)
    )
    covariance = scale * xtx_inverse @ meat @ xtx_inverse
    return ClusteredOLSResult(
        beta=beta,
        covariance=covariance,
        n_observations=n,
        n_clusters=n_clusters,
        absorbed_degrees_of_freedom=absorbed_degrees_of_freedom,
    )


def ols_clustered_named(
    y: pd.Series | np.ndarray,
    x: pd.DataFrame,
    cluster: pd.Series | np.ndarray,
    *,
    add_constant: bool = True,
    k_absorbed: int = 0,
    absorbed_groups: tuple[pd.Series | np.ndarray, ...] = (),
    min_observations: int = 1,
    min_clusters: int = 2,
    cluster_hac_lag: int | None = None,
) -> tuple[int, int, dict[str, float]]:
    """Fit clustered OLS and expose named statistics for a DataFrame design."""
    result = ols_clustered(
        y,
        x,
        cluster,
        add_constant=add_constant,
        k_absorbed=k_absorbed,
        absorbed_groups=absorbed_groups,
        min_observations=min_observations,
        min_clusters=min_clusters,
        cluster_hac_lag=cluster_hac_lag,
    )
    return (
        result.n_observations,
        result.n_clusters,
        result.named_statistics(list(x.columns), offset=int(add_constant)),
    )


def ols_hac(
    y: np.ndarray,
    x: np.ndarray,
    lag: int,
    *,
    time_index: pd.Series | np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients with a Newey-West Bartlett covariance matrix.

    When ``time_index`` is present, lags are calendar-day distances and gaps do not
    become adjacent merely because unsupported dates were removed from the sample.
    """
    if y.ndim != 1 or x.ndim != 2 or len(y) != len(x):
        raise ValueError("HAC inputs require one outcome per design-matrix row")
    if lag < 0:
        raise ValueError("HAC lag must be nonnegative")
    n, k = x.shape
    if n == 0 or k == 0:
        raise ValueError("HAC inputs cannot be empty")
    time_codes: np.ndarray | None = None
    if time_index is not None:
        timestamps = pd.to_datetime(
            pd.Series(np.asarray(time_index).reshape(-1)), errors="coerce"
        )
        if len(timestamps) != n or timestamps.isna().any():
            raise ValueError("HAC time index requires one valid date per observation")
        time_codes = timestamps.to_numpy(dtype="datetime64[D]").astype(np.int64)
        if len(np.unique(time_codes)) != n or np.any(np.diff(time_codes) <= 0):
            raise ValueError("HAC time index must be unique and strictly increasing")
    xtx_inverse = np.linalg.pinv(x.T @ x)
    beta = xtx_inverse @ (x.T @ y)
    residual = y - x @ beta
    scores = x * residual[:, None]
    meat = scores.T @ scores
    positions = (
        {int(value): index for index, value in enumerate(time_codes)}
        if time_codes is not None
        else None
    )
    max_offset = lag if time_codes is not None else min(lag, n - 1)
    for offset in range(1, max_offset + 1):
        weight = 1.0 - offset / (lag + 1.0)
        if time_codes is None or positions is None:
            current = np.arange(offset, n)
            previous = np.arange(0, n - offset)
        else:
            pairs = [
                (index, positions[int(value) - offset])
                for index, value in enumerate(time_codes)
                if int(value) - offset in positions
            ]
            if not pairs:
                continue
            current = np.fromiter((pair[0] for pair in pairs), dtype=int)
            previous = np.fromiter((pair[1] for pair in pairs), dtype=int)
        autocovariance = scores[current].T @ scores[previous]
        meat += weight * (autocovariance + autocovariance.T)
    finite_sample_scale = n / max(n - k, 1)
    covariance = xtx_inverse @ meat @ xtx_inverse * finite_sample_scale
    return beta, covariance


def year_endpoint_change(
    values: pd.Series | np.ndarray,
    years: pd.Series | np.ndarray,
    *,
    baseline_year: int,
    comparison_year: int,
    hac_lag: int,
    dates: pd.Series | np.ndarray | None = None,
) -> YearEndpointChange:
    """Estimate an endpoint-year mean change with intervening year indicators."""
    value_array = np.asarray(values, dtype=float).reshape(-1)
    year_array = np.asarray(years).reshape(-1)
    if len(value_array) != len(year_array):
        raise ValueError("year-change values and years must have the same row count")
    finite = np.isfinite(value_array) & pd.notna(year_array)
    date_array: np.ndarray | None = None
    if dates is not None:
        parsed_dates = pd.to_datetime(
            pd.Series(np.asarray(dates).reshape(-1)), errors="coerce"
        )
        if len(parsed_dates) != len(value_array):
            raise ValueError("year-change dates must align with values")
        finite &= parsed_dates.notna().to_numpy()
        date_array = parsed_dates.to_numpy()[finite]
    value_array = value_array[finite]
    year_array = year_array[finite].astype(int)
    observed_years = sorted(set(year_array))
    if baseline_year not in observed_years or comparison_year not in observed_years:
        raise ValueError("year-change contrast requires both endpoint years")
    comparison_years = [year for year in observed_years if year != baseline_year]
    design = np.column_stack(
        [
            np.ones(len(value_array)),
            *[year_array == year for year in comparison_years],
        ]
    ).astype(float)
    beta, covariance = ols_hac(
        value_array,
        design,
        hac_lag,
        time_index=date_array,
    )
    comparison_column = 1 + comparison_years.index(comparison_year)
    standard_error = float(
        np.sqrt(max(covariance[comparison_column, comparison_column], 0.0))
    )
    change = float(beta[comparison_column])
    t_statistic = change / standard_error if standard_error > 0 else np.nan
    degrees_freedom = max(len(value_array) - design.shape[1], 1)
    p_value = (
        float(2 * stats.t.sf(abs(t_statistic), degrees_freedom))
        if np.isfinite(t_statistic)
        else np.nan
    )
    return YearEndpointChange(
        baseline_mean=float(value_array[year_array == baseline_year].mean()),
        comparison_mean=float(value_array[year_array == comparison_year].mean()),
        change=change,
        standard_error=standard_error,
        t_statistic=float(t_statistic),
        p_value=p_value,
        n_observations=len(value_array),
        degrees_freedom=degrees_freedom,
    )
