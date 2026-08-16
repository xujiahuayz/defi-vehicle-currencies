"""The canonical estimator must still reproduce the committed dominance exhibit.

`output/exhibits/dominance_regressions.jsonl` was written before `2076e5e`
replaced the producer's hand-rolled `demean` with `absorb_fixed_effects` and
before `a63e53b` moved its inference onto `ols_clustered`. Its panel input,
`data/processed/counterfactual_dominance_clean.parquet`, is not held in a
presentation checkout, so the exhibit cannot be re-derived here to check that
the refactor left the numbers alone.

The deck frame that displays those coefficients is therefore only honest while
the two implementations are the same estimator. This test pins that: it runs the
superseded implementation and the canonical one over the same design and demands
they agree to machine precision. If `ols_clustered`'s CR1 scaling or
`absorb_fixed_effects`'s projection ever changes, this fails, and the displayed
ladder must be regenerated on the data host before it is presented again.

Delete this test once the exhibit is regenerated from the panel under the
current producer; at that point its certificate carries the same guarantee.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered


def superseded_demean(
    frame: pd.DataFrame, columns: list[str], group: pd.Series
) -> pd.DataFrame:
    """The producer's absorption as it stood when the exhibit was written."""

    return frame[columns] - frame[columns].groupby(group).transform("mean")


def superseded_ols_cluster(
    y: np.ndarray, x: np.ndarray, cluster: np.ndarray, k_absorbed: int = 0
) -> tuple[np.ndarray, np.ndarray, int]:
    """The producer's CR1 inference as it stood when the exhibit was written."""

    xtx_inverse = np.linalg.pinv(x.T @ x)
    beta = xtx_inverse @ (x.T @ y)
    residual = y - x @ beta
    meat = np.zeros((x.shape[1], x.shape[1]))
    groups = np.unique(cluster)
    for group in groups:
        rows = cluster == group
        score = x[rows].T @ residual[rows]
        meat += np.outer(score, score)
    n, k = x.shape
    g = len(groups)
    dof = max(1, n - k - k_absorbed)
    scale = (g / max(1, g - 1)) * ((n - 1) / dof)
    covariance = xtx_inverse @ meat @ xtx_inverse * scale
    return beta, np.sqrt(np.maximum(np.diag(covariance), 0)), g


def switching_panel(seed: int, rows: int) -> pd.DataFrame:
    """A pair-by-day panel restricted to cells that switch intermediary type."""

    generator = np.random.default_rng(seed)
    pair = generator.integers(0, 60, rows)
    day = generator.integers(0, 40, rows)
    native = generator.integers(0, 2, rows).astype(float)
    log_usd = generator.normal(8.0, 2.0, rows)
    latent = -0.05 * native + 0.03 * log_usd + generator.normal(0, 1, rows)
    frame = pd.DataFrame(
        {
            "pair": pair.astype(str),
            "cell": np.char.add(pair.astype(str), np.char.add("_", day.astype(str))),
            "native": native,
            "log_usd": log_usd,
            "dominated": (latent > 0).astype(float),
            "gap_bps": latent * 40.0,
        }
    )
    mix = frame.groupby("cell").native.agg(["mean", "size"])
    switching = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
    return frame[frame.cell.isin(switching)].copy()


@pytest.mark.parametrize(("seed", "rows"), ((0, 4_000), (1, 12_000), (2, 40_000)))
@pytest.mark.parametrize("outcome", ("dominated", "gap_bps"))
def test_canonical_estimator_reproduces_the_committed_dominance_ladder(
    seed: int, rows: int, outcome: str
) -> None:
    frame = switching_panel(seed, rows)
    columns = [outcome, "native", "log_usd"]

    superseded = superseded_demean(frame, columns, frame.cell)
    canonical = absorb_fixed_effects(frame[columns], frame.cell)
    assert np.allclose(
        superseded.to_numpy(), canonical.to_numpy(), rtol=0, atol=1e-12
    )

    design = np.column_stack([canonical.native, canonical.log_usd])
    absorbed = frame.cell.nunique()
    expected_beta, expected_se, expected_clusters = superseded_ols_cluster(
        canonical[outcome].to_numpy(), design, frame.pair.to_numpy(), absorbed
    )
    fit = ols_clustered(
        canonical[outcome].to_numpy(),
        design,
        frame.pair.to_numpy(),
        add_constant=False,
        k_absorbed=absorbed,
    )
    assert fit.n_clusters == expected_clusters
    assert np.allclose(fit.beta, expected_beta, rtol=0, atol=1e-12)
    assert np.allclose(fit.standard_errors, expected_se, rtol=0, atol=1e-12)


def test_pooled_specifications_survive_the_inference_refactor() -> None:
    """The unabsorbed rungs of the ladder use the same code path as the FE rung."""

    frame = switching_panel(3, 20_000)
    design = np.column_stack(
        [np.ones(len(frame)), frame.native.to_numpy(), frame.log_usd.to_numpy()]
    )
    outcome = frame.dominated.to_numpy()
    cluster = frame.pair.to_numpy()
    expected_beta, expected_se, _ = superseded_ols_cluster(outcome, design, cluster)
    fit = ols_clustered(outcome, design, cluster, add_constant=False)
    assert np.allclose(fit.beta, expected_beta, rtol=0, atol=1e-12)
    assert np.allclose(fit.standard_errors, expected_se, rtol=0, atol=1e-12)
