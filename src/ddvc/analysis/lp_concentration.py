"""Candidate-linked deposited capital and its cross-candidate share.

The canonical pool-capital materializer allocates each valid pool's accounting
capital once across candidate token sides. This module aggregates that processed
panel across every protocol whose capital contract is currently admitted. It
does not parse provider data and does not interpret TVL as marginal or executable
depth.

Outputs:
  data/exhibits/lp_capital_concentration.parquet
    columns: date, token_address, token_symbol, is_vehicle_candidate,
             total_lp_capital_usd, lp_capital_share, venue_count,
             pool_family_count, state_generation_count, quantity_kind

  output/exhibits/lp_capital_share_top5.pdf
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.paths import (
    LP_CAPITAL_CONCENTRATION_PANEL,
    OUTPUT_DIR,
    POOL_CANDIDATE_CAPITAL_PANEL,
)
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.runtime import atomic_output


LP_CAPITAL_CHART_PATH = OUTPUT_DIR / "exhibits" / "lp_capital_share_top5.pdf"


def compute_lp_capital_day(candidate_rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one day's validated pool-candidate capital without double counting."""

    columns = [
        "date",
        "token_address",
        "token_symbol",
        "is_vehicle_candidate",
        "total_lp_capital_usd",
        "lp_capital_share",
        "venue_count",
        "pool_family_count",
        "state_generation_count",
        "quantity_kind",
    ]
    if candidate_rows.empty:
        return pd.DataFrame(columns=columns)
    required = {
        "day",
        "venue",
        "pool",
        "candidate",
        "candidate_address",
        "candidate_capital_usd",
        "quantity_kind",
        "capital_validation_status",
        "pool_family",
        "state_generation",
    }
    missing = required - set(candidate_rows.columns)
    if missing:
        raise ValueError(f"candidate-capital rows lack required columns: {sorted(missing)}")
    if candidate_rows["day"].astype(str).nunique() != 1:
        raise ValueError("compute_lp_capital_day requires exactly one calendar day")
    if candidate_rows.duplicated(["venue", "pool", "candidate"]).any():
        raise ValueError("duplicate pool-candidate rows would double count deposited capital")
    valid = candidate_rows[
        candidate_rows["quantity_kind"].eq("deposited_capital")
        & candidate_rows["capital_validation_status"].eq("reported_plausible")
        & candidate_rows["candidate_address"].isin(VEHICLE_CANDIDATES)
    ].copy()
    valid["candidate_capital_usd"] = pd.to_numeric(
        valid["candidate_capital_usd"], errors="coerce"
    )
    valid = valid[
        np.isfinite(valid["candidate_capital_usd"])
        & valid["candidate_capital_usd"].gt(0)
    ]
    if valid.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        valid.groupby(["candidate_address", "candidate"], as_index=False)
        .agg(
            total_lp_capital_usd=("candidate_capital_usd", "sum"),
            venue_count=("venue", "nunique"),
            pool_family_count=("pool_family", "nunique"),
            state_generation_count=("state_generation", "nunique"),
        )
        .rename(
            columns={
                "candidate_address": "token_address",
                "candidate": "token_symbol",
            }
        )
    )
    total = float(grouped["total_lp_capital_usd"].sum())
    grouped["date"] = pd.to_datetime(str(valid["day"].iloc[0]), format="%Y%m%d")
    grouped["is_vehicle_candidate"] = True
    grouped["lp_capital_share"] = grouped["total_lp_capital_usd"] / total
    grouped["quantity_kind"] = "deposited_capital"
    return (
        grouped[columns]
        .sort_values("total_lp_capital_usd", ascending=False)
        .reset_index(drop=True)
    )


def candidate_capital_changes(candidate_rows: pd.DataFrame) -> pd.DataFrame:
    """Attach log capital changes only where the persisted exact-day lag is valid."""

    required = {
        "candidate_capital_usd",
        "candidate_capital_usd_lagged",
        "exact_lag_valid",
    }
    missing = required - set(candidate_rows)
    if missing:
        raise ValueError(f"candidate-capital change input lacks columns: {sorted(missing)}")
    out = candidate_rows.copy()
    current = pd.to_numeric(out["candidate_capital_usd"], errors="coerce")
    lagged = pd.to_numeric(out["candidate_capital_usd_lagged"], errors="coerce")
    exact = out["exact_lag_valid"].fillna(False).astype(bool)
    if not (np.isfinite(current) & current.gt(0)).all():
        raise ValueError("candidate capital must be finite positive")
    if (exact & ~(np.isfinite(lagged) & lagged.gt(0))).any():
        raise ValueError("an exact-lag candidate-capital row lacks finite positive lagged capital")
    out["log_capital"] = np.log(current.clip(lower=1.0))
    out["dlog_capital"] = np.where(
        exact,
        out["log_capital"] - np.log(lagged.clip(lower=1.0)),
        np.nan,
    )
    return out


def run(
    start: str | None = None,
    end: str | None = None,
    chart: bool = True,
) -> pd.DataFrame:
    """Aggregate canonical candidate capital over an optional inclusive date range."""

    if not POOL_CANDIDATE_CAPITAL_PANEL.exists():
        raise FileNotFoundError(
            "canonical candidate-capital panel is missing; run the pool-capital materializer"
        )
    require_current_artifacts(
        [POOL_CANDIDATE_CAPITAL_PANEL],
        consumer="candidate-linked LP-capital aggregation",
    )
    clauses = []
    if start:
        clauses.append(f"day >= '{start.replace('-', '')}'")
    if end:
        clauses.append(f"day <= '{end.replace('-', '')}'")
    perimeter = " AND ".join(clauses) if clauses else "true"
    addresses = ",".join(f"'{address}'" for address in VEHICLE_CANDIDATES)
    source = POOL_CANDIDATE_CAPITAL_PANEL.as_posix()
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    con.execute(
        f"SET temp_directory='{(POOL_CANDIDATE_CAPITAL_PANEL.parent / '_duckdb_tmp').as_posix()}'"
    )
    violations = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE quantity_kind!='deposited_capital'),
            count(*) FILTER (WHERE capital_validation_status!='reported_plausible'),
            count(*) FILTER (WHERE candidate_address NOT IN ({addresses})),
            count(*) FILTER (
                WHERE NOT isfinite(candidate_capital_usd) OR candidate_capital_usd<=0
            ),
            count(*) FILTER (
                WHERE pool_family IS NULL OR state_generation IS NULL
            )
        FROM read_parquet('{source}')
        WHERE {perimeter}
        """
    ).fetchone()
    if any(violations):
        con.close()
        raise ValueError(
            "candidate-capital input violates quantity/status/address/value/contract fields: "
            f"{violations}"
        )
    with atomic_output(LP_CAPITAL_CONCENTRATION_PANEL) as temporary:
        con.execute(
            f"""
            COPY (
                WITH grouped AS (
                    SELECT
                        day,
                        candidate_address AS token_address,
                        candidate AS token_symbol,
                        sum(candidate_capital_usd) AS total_lp_capital_usd,
                        count(DISTINCT venue) AS venue_count,
                        count(DISTINCT pool_family) AS pool_family_count,
                        count(DISTINCT state_generation) AS state_generation_count
                    FROM read_parquet('{source}')
                    WHERE {perimeter}
                    GROUP BY day, candidate_address, candidate
                )
                SELECT
                    cast(strptime(day, '%Y%m%d') AS DATE) AS date,
                    token_address,
                    token_symbol,
                    true AS is_vehicle_candidate,
                    total_lp_capital_usd,
                    total_lp_capital_usd /
                        sum(total_lp_capital_usd) OVER (PARTITION BY day) AS lp_capital_share,
                    venue_count,
                    pool_family_count,
                    state_generation_count,
                    'deposited_capital' AS quantity_kind
                FROM grouped
                ORDER BY day, total_lp_capital_usd DESC
            ) TO '{temporary.as_posix()}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )
    con.close()
    combined = pd.read_parquet(LP_CAPITAL_CONCENTRATION_PANEL)
    if combined.empty:
        return combined
    stamp(
        LP_CAPITAL_CONCENTRATION_PANEL,
        code_sources=[
            "src/ddvc/analysis/lp_concentration.py",
            "src/ddvc/asset_types.py",
            "src/ddvc/paths.py",
            "src/ddvc/runtime.py",
        ],
        inputs=[POOL_CANDIDATE_CAPITAL_PANEL],
        rows=len(combined),
        notes="quantity=deposited_capital; cross-protocol admitted-capital perimeter",
    )
    if chart:
        _plot_top5(combined)
    return combined


def _plot_top5(df: pd.DataFrame) -> None:
    """Plot each candidate's share of admitted candidate-linked pool capital."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if df.empty:
        return
    mean_share = (
        df.groupby("token_address")["lp_capital_share"]
        .mean()
        .sort_values(ascending=False)
    )
    top5_addrs = mean_share.head(5).index.tolist()
    symbol = (
        df.drop_duplicates("token_address")
        .set_index("token_address")["token_symbol"]
        .to_dict()
    )
    pivot = (
        df[df["token_address"].isin(top5_addrs)]
        .pivot_table(
            index="date",
            columns="token_address",
            values="lp_capital_share",
            aggfunc="sum",
        )
        .fillna(0.0)
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(10, 5))
    for address in top5_addrs:
        if address in pivot.columns:
            ax.plot(
                pivot.index,
                pivot[address],
                label=symbol.get(address, address[:8]),
                linewidth=1.5,
            )
    ax.set_xlabel("Date")
    ax.set_ylabel("Share of candidate-linked deposited capital")
    ax.set_title("Candidate-linked deposited pool capital")
    ax.legend(loc="best", fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    fig.tight_layout()
    LP_CAPITAL_CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(LP_CAPITAL_CHART_PATH, format="pdf", bbox_inches="tight")
    plt.close(fig)
