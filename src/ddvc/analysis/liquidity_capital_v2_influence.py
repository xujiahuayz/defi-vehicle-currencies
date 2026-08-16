"""Concentration and leave-one-unit influence evidence for the V2 capital family.

The `liquidity_capital_v2_predictability` claim pools five candidate tokens and
every admitted Uniswap V2 and SushiSwap V2 pool into one bidirectional
predictability estimate. Two published rivals apply directly. Griffin and Shams
motivate the concentration diagnostic: a pooled coefficient estimated over a
support whose mass sits in a handful of units is a statement about those units,
not about the market. Comerton-Forde and colleagues motivate the owner
diagnostic: when one inventory holder supplies most of the capital, its own
behaviour is the estimate. With exactly five candidates a leave-one-candidate
refit is load-bearing rather than optional.

This module owns the parts of that attack that are pure functions of released
objects: the pool- and candidate-level contribution ledgers, the exact
recomputation of the candidate-day capital block from the released
pool-candidate allocation rows, and the leave-one-unit panels the estimator
refits. It deliberately does not fit anything. The fitted half lives with the
claim's single estimator owner, `scripts/run_liquidity_capital_v2_predictability.py`,
so that one covariance contract serves the headline and its diagnostics.

Two rules are enforced here rather than trusted. First, the recomputation is
reconciled against the released panel before any exclusion is taken, so a
leave-one-pool refit can never be read as evidence when the arithmetic that
produced it does not reproduce the released capital column. Second, the
five-candidate share denominator is *not* redefined when a candidate is dropped
from a regression: dropping a candidate is an influence diagnostic on a fixed
estimand, and silently re-normalising to four candidates would answer a
different question.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ATTACK_ID = "influence_concentration"
POOL_KEY_SEPARATOR = ":"
CAPITAL_BLOCK_COLUMNS = (
    "v2_capital_day_supported",
    "v2_candidate_pool_observed",
    "v2_deposited_capital_usd",
    "v2_log1p_deposited_capital_usd",
    "v2_five_candidate_capital_share",
    "v2_candidate_pool_count",
    "v2_candidate_venue_count",
    "v2_candidate_allocation_row_count",
    "v2_capital_validation_status",
    "v2_capital_state_generation",
    "v2_capital_support_status",
)
# The released panel's capital sums are DuckDB float reductions, so a faithful
# recomputation agrees to floating-point tolerance rather than to the bit. The
# builder measured 3.3e-15 relative on the levels; anything at or below this
# bound cannot reach a coefficient, and anything above it is a real difference.
RECONCILIATION_RELATIVE_TOLERANCE = 1e-9


def _pool_key_expression() -> str:
    return f"venue || '{POOL_KEY_SEPARATOR}' || pool"


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def open_candidate_capital(path: str | Path) -> duckdb.DuckDBPyConnection:
    """Load the allocation columns this attack needs into a deterministic table.

    Single-threaded on purpose: the released panel's own note records that a
    parallel float reduction moves the installed bytes without moving any value.
    A diagnostic that must reproduce byte-identically cannot inherit that.
    """

    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=true")
    connection.execute(
        f"""
        CREATE TABLE allocation AS
        SELECT cast(strptime(day, '%Y%m%d') AS DATE) AS origin_date,
            candidate_address,
            venue,
            pool,
            {_pool_key_expression()} AS pool_key,
            candidate_capital_usd,
            capital_validation_status,
            state_generation
        FROM read_parquet('{str(Path(path)).replace("'", "''")}')
        """
    )
    return connection


def pool_contribution_ledger(
    connection: duckdb.DuckDBPyConnection, *, top_n: int = 10
) -> pd.DataFrame:
    """Rank pools by the candidate-attributed capital they carry, with shares."""

    if top_n < 1:
        raise ValueError("pool contribution ledger needs a positive top_n")
    pools = connection.execute(
        """
        SELECT pool_key, any_value(venue) AS venue,
            sum(candidate_capital_usd) AS capital_usd_days,
            count(*) AS allocation_rows,
            count(DISTINCT origin_date) AS observed_dates,
            count(DISTINCT candidate_address) AS candidates,
            min(origin_date) AS first_date, max(origin_date) AS last_date
        FROM allocation GROUP BY pool_key ORDER BY capital_usd_days DESC, pool_key
        """
    ).df()
    if pools.empty:
        raise ValueError("candidate capital allocation carries no pool")
    total = float(pools["capital_usd_days"].sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("candidate capital allocation has no positive total")
    pools["capital_share"] = pools["capital_usd_days"] / total
    pools["rank"] = np.arange(1, len(pools) + 1)
    leader = connection.execute(
        """
        SELECT pool_key, candidate_address, sum(candidate_capital_usd) AS candidate_capital
        FROM allocation GROUP BY pool_key, candidate_address
        """
    ).df()
    leader = (
        leader.sort_values(
            ["pool_key", "candidate_capital", "candidate_address"],
            ascending=[True, False, True],
        )
        .drop_duplicates("pool_key")
        .rename(columns={"candidate_address": "leading_candidate_address"})
    )
    pools = pools.merge(
        leader[["pool_key", "leading_candidate_address"]], on="pool_key", how="left"
    )
    ranked = pools.head(top_n).copy()
    ranked.insert(0, "record", "pool_contribution")
    summary = pd.DataFrame(
        [
            {
                "record": "pool_concentration_summary",
                "pools": int(len(pools)),
                "capital_usd_days": total,
                "top_1_share": float(pools["capital_share"].iloc[0]),
                "top_5_share": float(pools["capital_share"].head(5).sum()),
                "top_10_share": float(pools["capital_share"].head(10).sum()),
                "herfindahl_index": float((pools["capital_share"] ** 2).sum()),
                "pools_covering_half": int(
                    (pools["capital_share"].cumsum() < 0.5).sum() + 1
                ),
            }
        ]
    )
    return pd.concat([summary, ranked], ignore_index=True, sort=False)


def top_pool_keys(ledger: pd.DataFrame, *, count: int) -> list[str]:
    """Return the exclusion perimeter: the highest-contribution pools, in order."""

    if count < 1:
        raise ValueError("leave-one-pool perimeter needs a positive count")
    contributions = ledger[ledger["record"].eq("pool_contribution")]
    if len(contributions) < count:
        raise ValueError("pool contribution ledger is shorter than the exclusion perimeter")
    return contributions.sort_values("rank")["pool_key"].head(count).tolist()


def candidate_capital_block(
    connection: duckdb.DuckDBPyConnection,
    grid: pd.DataFrame,
    *,
    excluded_pool_keys: Sequence[str] = (),
) -> pd.DataFrame:
    """Recompute the candidate-day capital block, optionally dropping pools.

    This mirrors `_v2_candidate_day_query` exactly, including its date-global
    support flag, its supported-zero semantics and its distinct status
    aggregation, so that the no-exclusion case is a reconciliation of the
    released panel rather than a second, differently-shaped construction.
    """

    required = {"origin_date", "candidate_address"}
    if not required <= set(grid.columns):
        raise ValueError("capital block grid needs origin_date and candidate_address")
    excluded = tuple(dict.fromkeys(excluded_pool_keys))
    predicate = ""
    if excluded:
        predicate = " WHERE pool_key NOT IN (" + ",".join(_quote(key) for key in excluded) + ")"
    days = connection.execute(
        f"""
        SELECT origin_date,
            string_agg(DISTINCT capital_validation_status, '|'
                ORDER BY capital_validation_status) AS v2_capital_validation_status,
            string_agg(DISTINCT state_generation, '|'
                ORDER BY state_generation) AS v2_capital_state_generation
        FROM allocation{predicate} GROUP BY origin_date
        """
    ).df()
    candidates = connection.execute(
        f"""
        SELECT origin_date, candidate_address,
            sum(candidate_capital_usd) AS deposited_capital_usd,
            count(DISTINCT pool_key) AS pool_count,
            count(DISTINCT venue) AS venue_count,
            count(*) AS allocation_row_count
        FROM allocation{predicate} GROUP BY origin_date, candidate_address
        """
    ).df()
    block = grid.loc[:, ["origin_date", "candidate_address"]].copy()
    block["origin_date"] = pd.to_datetime(block["origin_date"])
    for frame in (days, candidates):
        frame["origin_date"] = pd.to_datetime(frame["origin_date"])
    block = block.merge(days, on="origin_date", how="left", validate="many_to_one")
    block = block.merge(
        candidates, on=["origin_date", "candidate_address"], how="left", validate="one_to_one"
    )
    supported = block["v2_capital_validation_status"].notna()
    observed = supported & block["allocation_row_count"].notna()
    capital = block["deposited_capital_usd"].where(observed, 0.0).where(supported)
    total = capital.groupby(block["origin_date"]).transform("sum")
    block["v2_capital_day_supported"] = supported.to_numpy(dtype=bool)
    block["v2_candidate_pool_observed"] = observed.to_numpy(dtype=bool)
    block["v2_deposited_capital_usd"] = capital
    block["v2_log1p_deposited_capital_usd"] = np.log1p(capital).where(supported)
    block["v2_five_candidate_capital_share"] = (capital / total).where(
        supported & total.gt(0)
    )
    for source, target in (
        ("pool_count", "v2_candidate_pool_count"),
        ("venue_count", "v2_candidate_venue_count"),
        ("allocation_row_count", "v2_candidate_allocation_row_count"),
    ):
        block[target] = block[source].where(observed, 0.0).where(supported).astype(float)
    block["v2_capital_support_status"] = np.where(
        ~supported, "unavailable",
        np.where(observed, "observed_candidate_pools", "supported_zero_capital"),
    )
    return block.loc[:, ["origin_date", "candidate_address", *CAPITAL_BLOCK_COLUMNS]]


def rebuild_candidate_day(released: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
    """Return the released panel with its capital block replaced, columns intact."""

    keys = ["origin_date", "candidate_address"]
    panel = released.copy()
    panel["origin_date"] = pd.to_datetime(panel["origin_date"])
    replaced = panel.drop(columns=list(CAPITAL_BLOCK_COLUMNS)).merge(
        block, on=keys, how="left", validate="one_to_one"
    )
    if len(replaced) != len(panel) or replaced[list(CAPITAL_BLOCK_COLUMNS)].isna().all(axis=1).any():
        raise ValueError("capital block does not cover the released candidate-day grid")
    return replaced.loc[:, list(panel.columns)].sort_values(keys).reset_index(drop=True)


def capital_reconciliation(released: pd.DataFrame, rebuilt: pd.DataFrame) -> pd.DataFrame:
    """Compare the no-exclusion recomputation with the released capital column.

    A leave-one-pool result is only evidence if the same arithmetic reproduces
    the released panel when nothing is left out. This returns that comparison as
    a support record and raises when the difference exceeds floating tolerance,
    which is the difference between a rebuilt panel and a revised one.
    """

    keys = ["origin_date", "candidate_address"]
    merged = (
        released.loc[:, [*keys, "v2_deposited_capital_usd", "v2_five_candidate_capital_share",
                         "v2_candidate_allocation_row_count", "v2_capital_day_supported"]]
        .merge(
            rebuilt.loc[:, [*keys, "v2_deposited_capital_usd", "v2_five_candidate_capital_share",
                            "v2_candidate_allocation_row_count", "v2_capital_day_supported"]],
            on=keys, how="outer", suffixes=("_released", "_rebuilt"), validate="one_to_one",
        )
    )
    if len(merged) != len(released):
        raise ValueError("capital reconciliation does not align the released grid")
    support_mismatch = int(
        merged["v2_capital_day_supported_released"].astype("boolean").fillna(False).ne(
            merged["v2_capital_day_supported_rebuilt"].astype("boolean").fillna(False)
        ).sum()
    )
    row_mismatch = int(
        merged["v2_candidate_allocation_row_count_released"].fillna(-1).ne(
            merged["v2_candidate_allocation_row_count_rebuilt"].fillna(-1)
        ).sum()
    )
    records = []
    worst = 0.0
    for column in ("v2_deposited_capital_usd", "v2_five_candidate_capital_share"):
        left = merged[f"{column}_released"].astype(float)
        right = merged[f"{column}_rebuilt"].astype(float)
        both = left.notna() & right.notna()
        missing_mismatch = int(left.notna().ne(right.notna()).sum())
        absolute = (left[both] - right[both]).abs()
        scale = pd.concat([left[both].abs(), right[both].abs()], axis=1).max(axis=1).clip(lower=1.0)
        relative = float((absolute / scale).max()) if both.any() else 0.0
        worst = max(worst, relative)
        records.append({
            "record": "released_recomputation_reconciliation",
            "column": column,
            "compared_rows": int(both.sum()),
            "missing_disagreements": missing_mismatch,
            "maximum_absolute_difference": float(absolute.max()) if both.any() else 0.0,
            "maximum_relative_difference": relative,
            "support_flag_disagreements": support_mismatch,
            "allocation_row_disagreements": row_mismatch,
            "relative_tolerance": RECONCILIATION_RELATIVE_TOLERANCE,
        })
    frame = pd.DataFrame(records)
    if (
        worst > RECONCILIATION_RELATIVE_TOLERANCE
        or support_mismatch
        or row_mismatch
        or frame["missing_disagreements"].gt(0).any()
    ):
        raise ValueError(
            "recomputed V2 capital does not reproduce the released panel: "
            f"relative={worst:.3e}; support={support_mismatch}; rows={row_mismatch}"
        )
    return frame


def candidate_contribution_ledger(candidate_day: pd.DataFrame) -> pd.DataFrame:
    """Report what each candidate contributes to capital and to route use."""

    data = candidate_day.copy()
    data["origin_date"] = pd.to_datetime(data["origin_date"])
    capital_supported = data["v2_capital_day_supported"].astype(bool)
    route_supported = data["route_day_supported"].astype(bool)
    total_capital = float(data.loc[capital_supported, "v2_deposited_capital_usd"].sum())
    if total_capital <= 0:
        raise ValueError("candidate contribution ledger has no positive capital")
    rows = []
    for (address, symbol), group in data.groupby(
        ["candidate_address", "candidate_symbol"], sort=True
    ):
        capital_rows = group[group["v2_capital_day_supported"].astype(bool)]
        route_rows = group[group["route_day_supported"].astype(bool)]
        rows.append({
            "record": "candidate_contribution",
            "candidate_address": address,
            "candidate_symbol": symbol,
            "capital_supported_days": int(len(capital_rows)),
            "capital_usd_days": float(capital_rows["v2_deposited_capital_usd"].sum()),
            "capital_share_of_total": float(
                capital_rows["v2_deposited_capital_usd"].sum() / total_capital
            ),
            "mean_daily_capital_share": float(
                capital_rows["v2_five_candidate_capital_share"].mean()
            ),
            "maximum_daily_capital_share": float(
                capital_rows["v2_five_candidate_capital_share"].max()
            ),
            "mean_intermediary_episode_share": float(
                route_rows["intermediary_episode_share"].mean()
            ),
            "endpoint_supported_days": int(
                route_rows["route_endpoint_supported"].astype(bool).sum()
            ),
            "maximum_candidate_pool_count": float(
                capital_rows["v2_candidate_pool_count"].max()
            ),
        })
    ledger = pd.DataFrame(rows)
    summary = pd.DataFrame([{
        "record": "candidate_concentration_summary",
        "capital_supported_days": int(capital_supported.sum()),
        "route_supported_days": int(route_supported.sum()),
        "capital_usd_days": total_capital,
        "top_1_share": float(ledger["capital_share_of_total"].max()),
        "herfindahl_index": float((ledger["capital_share_of_total"] ** 2).sum()),
    }])
    return pd.concat([summary, ledger], ignore_index=True, sort=False)


def within_transform_weight(
    sample: pd.DataFrame, residual_predictor: pd.Series
) -> pd.DataFrame:
    """Report each candidate's share of the within-transformed predictor variance.

    In a two-way absorbed regression the pooled slope is a variance-weighted
    average of unit-level relationships, so this is the exact weight each
    candidate carries in the coefficient a leave-one-candidate refit perturbs.
    """

    weights = pd.DataFrame({
        "candidate_address": sample["candidate_address"].to_numpy(),
        "squared_residual_predictor": np.square(residual_predictor.to_numpy(float)),
    })
    total = float(weights["squared_residual_predictor"].sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("within-transformed predictor carries no variance")
    grouped = weights.groupby("candidate_address", sort=True)[
        "squared_residual_predictor"
    ].agg(["sum", "count"])
    grouped["predictor_variance_share"] = grouped["sum"] / total
    return grouped.reset_index().rename(columns={"sum": "predictor_variance", "count": "observations"})


def leave_out_units(
    candidate_day: pd.DataFrame, pool_keys: Iterable[str]
) -> list[Mapping[str, str]]:
    """Return the ordered leave-out perimeter: the recomputed base, then units."""

    candidates = (
        candidate_day.loc[:, ["candidate_address", "candidate_symbol"]]
        .drop_duplicates()
        .sort_values("candidate_address")
    )
    units: list[Mapping[str, str]] = [
        {"leave_out_kind": "none", "leave_out_unit": "recomputed_full_sample", "leave_out_label": "none"}
    ]
    units.extend(
        {
            "leave_out_kind": "candidate",
            "leave_out_unit": row.candidate_address,
            "leave_out_label": row.candidate_symbol,
        }
        for row in candidates.itertuples(index=False)
    )
    units.extend(
        {"leave_out_kind": "pool", "leave_out_unit": key, "leave_out_label": key}
        for key in pool_keys
    )
    return units
