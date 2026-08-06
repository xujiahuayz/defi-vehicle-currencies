"""Small regression primitives shared by empirical runners."""

from __future__ import annotations

import numpy as np


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
