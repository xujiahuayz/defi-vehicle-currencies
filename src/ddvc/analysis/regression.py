"""Small regression primitives shared by empirical runners."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class ClusteredOLSResult:
    """OLS estimates and one-way cluster-robust inference."""

    beta: np.ndarray
    covariance: np.ndarray
    n_observations: int
    n_clusters: int

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


def ols_clustered(
    y: pd.Series | np.ndarray,
    x: pd.DataFrame | np.ndarray,
    cluster: pd.Series | np.ndarray,
    *,
    add_constant: bool = True,
    k_absorbed: int = 0,
    min_observations: int = 1,
    min_clusters: int = 2,
) -> ClusteredOLSResult:
    """Fit OLS with a one-way CR1 cluster-robust covariance matrix."""
    y_array = np.asarray(y, dtype=float).reshape(-1)
    x_array = np.asarray(x, dtype=float)
    cluster_array = np.asarray(cluster).reshape(-1)
    if x_array.ndim == 1:
        x_array = x_array[:, None]
    if len(y_array) != len(x_array) or len(y_array) != len(cluster_array):
        raise ValueError("clustered OLS inputs must have the same row count")
    finite = np.isfinite(y_array) & np.isfinite(x_array).all(axis=1) & pd.notna(cluster_array)
    y_array = y_array[finite]
    x_array = x_array[finite]
    cluster_array = cluster_array[finite]
    if add_constant:
        x_array = np.column_stack([np.ones(len(x_array)), x_array])
    n, k = x_array.shape
    cluster_codes, unique_clusters = pd.factorize(cluster_array, sort=False)
    n_clusters = len(unique_clusters)
    empty = ClusteredOLSResult(
        beta=np.full(k, np.nan),
        covariance=np.full((k, k), np.nan),
        n_observations=n,
        n_clusters=n_clusters,
    )
    if n < min_observations or n_clusters < min_clusters or n <= k + k_absorbed:
        return empty
    if np.linalg.matrix_rank(x_array) < k:
        return empty
    xtx_inverse = np.linalg.pinv(x_array.T @ x_array)
    beta = xtx_inverse @ (x_array.T @ y_array)
    residual = y_array - x_array @ beta
    meat = np.zeros((k, k))
    for code in range(n_clusters):
        selected = cluster_codes == code
        score = x_array[selected].T @ residual[selected]
        meat += np.outer(score, score)
    scale = (n_clusters / (n_clusters - 1)) * (
        (n - 1) / (n - k - k_absorbed)
    )
    covariance = scale * xtx_inverse @ meat @ xtx_inverse
    return ClusteredOLSResult(
        beta=beta,
        covariance=covariance,
        n_observations=n,
        n_clusters=n_clusters,
    )


def ols_clustered_named(
    y: pd.Series | np.ndarray,
    x: pd.DataFrame,
    cluster: pd.Series | np.ndarray,
    *,
    add_constant: bool = True,
    k_absorbed: int = 0,
    min_observations: int = 1,
    min_clusters: int = 2,
) -> tuple[int, int, dict[str, float]]:
    """Fit clustered OLS and expose named statistics for a DataFrame design."""
    result = ols_clustered(
        y,
        x,
        cluster,
        add_constant=add_constant,
        k_absorbed=k_absorbed,
        min_observations=min_observations,
        min_clusters=min_clusters,
    )
    return (
        result.n_observations,
        result.n_clusters,
        result.named_statistics(list(x.columns), offset=int(add_constant)),
    )


def ols_hac(y: np.ndarray, x: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients with a Newey-West Bartlett covariance matrix."""
    if y.ndim != 1 or x.ndim != 2 or len(y) != len(x):
        raise ValueError("HAC inputs require one outcome per design-matrix row")
    if lag < 0:
        raise ValueError("HAC lag must be nonnegative")
    n, k = x.shape
    if n == 0 or k == 0:
        raise ValueError("HAC inputs cannot be empty")
    xtx_inverse = np.linalg.pinv(x.T @ x)
    beta = xtx_inverse @ (x.T @ y)
    residual = y - x @ beta
    scores = x * residual[:, None]
    meat = scores.T @ scores
    for offset in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - offset / (lag + 1.0)
        autocovariance = scores[offset:].T @ scores[:-offset]
        meat += weight * (autocovariance + autocovariance.T)
    finite_sample_scale = n / max(n - k, 1)
    covariance = xtx_inverse @ meat @ xtx_inverse * finite_sample_scale
    return beta, covariance
