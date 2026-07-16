"""Candidate-linked Uniswap V3 liquidity and concentration.

For each day, allocate valid pool-level USD TVL across the candidate tokens that
are sides of the pool. A pool with one candidate side contributes all TVL to that
candidate; a pool with two candidate sides contributes half to each. This keeps
the allocation exhaustive without using an outcome-related winner rule.

Outputs:
  data/exhibits/lp_concentration.parquet
    columns: date, token_address, token_symbol, is_vehicle_candidate,
             total_lp_liquidity_usd, lp_concentration_share

  output/exhibits/lp_concentration_top5.pdf
    daily LP concentration share for the five candidate tokens
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR

# ---------------------------------------------------------------------------
# Paper candidate set (lowercase Ethereum addresses)
# ---------------------------------------------------------------------------

VEHICLE_CANDIDATES: dict[str, str] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
}

# The Graph occasionally reports absurd pool-level tvlUSD for spam/meme pools
# because token decimals or token prices are stale/bad. Uniswap V3 total TVL is
# far below this threshold over the sample, so a single pool above it is a data
# error rather than economically meaningful liquidity.
MAX_POOL_TVL_USD = 10_000_000_000

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

LP_CONCENTRATION_PATH = DATA_DIR / "exhibits" / "lp_concentration.parquet"
LP_CHART_PATH = OUTPUT_DIR / "exhibits" / "lp_concentration_top5.pdf"


def _raw_v3_path(stream: str, stamp: str) -> Path:
    return DATA_DIR / "raw" / "thegraph" / "uniswap_v3" / f"uniswap_v3_{stream}_{stamp}.jsonl.gz"


# ---------------------------------------------------------------------------
# Daily pool snapshots and candidate allocation
# ---------------------------------------------------------------------------

PoolIdentity = tuple[str, str, str, str]
PoolSnapshot = tuple[str, str, str, str, float]


def _available_stamps(stream: str) -> list[str]:
    """Return YYYYMMDD stamps for an available V3 raw-data stream."""

    directory = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
    stamps: set[str] = set()
    if directory.is_dir():
        for path in directory.glob(f"uniswap_v3_{stream}_*.jsonl.gz"):
            stamp = path.name.removesuffix(".jsonl.gz").rsplit("_", 1)[-1]
            if len(stamp) == 8 and stamp.isdigit():
                stamps.add(stamp)
    return sorted(stamps)


def _build_pool_registry(stamps: list[str]) -> dict[str, PoolIdentity]:
    """Map pool contracts to exact token contracts using persisted swap records."""

    registry: dict[str, PoolIdentity] = {}
    for index, stamp in enumerate(stamps, 1):
        path = _raw_v3_path("swaps", stamp)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    pool = rec.get("pool") or {}
                    token0 = pool.get("token0") or {}
                    token1 = pool.get("token1") or {}
                    pool_id = str(pool.get("id") or "").lower()
                    token0_id = str(token0.get("id") or "").lower()
                    token1_id = str(token1.get("id") or "").lower()
                except (AttributeError, json.JSONDecodeError, TypeError):
                    continue
                if pool_id and token0_id and token1_id:
                    registry[pool_id] = (
                        token0_id,
                        str(token0.get("symbol") or ""),
                        token1_id,
                        str(token1.get("symbol") or ""),
                    )
        if index % 250 == 0 or index == len(stamps):
            print(
                f"  pool registry: {index}/{len(stamps)} days, "
                f"{len(registry):,} pools",
                flush=True,
            )
    return registry


def _pool_snapshot_from_record(
    rec: dict,
    pool_registry: dict[str, PoolIdentity],
) -> tuple[str, PoolSnapshot] | None:
    """Resolve one daily snapshot using embedded or registry token contracts."""

    try:
        pool = rec.get("pool") or {}
        token0 = pool.get("token0") or {}
        token1 = pool.get("token1") or {}
        pool_id = str(pool.get("id") or "").lower()
        token0_id = str(token0.get("id") or "").lower()
        token1_id = str(token1.get("id") or "").lower()
        token0_symbol = str(token0.get("symbol") or "")
        token1_symbol = str(token1.get("symbol") or "")
        tvl_usd = float(rec.get("tvlUSD", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    if not pool_id or not 0 < tvl_usd <= MAX_POOL_TVL_USD:
        return None

    if not token0_id or not token1_id:
        identity = pool_registry.get(pool_id)
        if identity is None:
            return None
        token0_id, registry_symbol0, token1_id, registry_symbol1 = identity
        token0_symbol = token0_symbol or registry_symbol0
        token1_symbol = token1_symbol or registry_symbol1

    return pool_id, (
        token0_id,
        token0_symbol,
        token1_id,
        token1_symbol,
        tvl_usd,
    )


def _build_pool_snapshot(
    stamp: str,
    pool_registry: dict[str, PoolIdentity] | None = None,
) -> dict[str, PoolSnapshot]:
    """Return valid pool token identities and USD TVL from poolDayDatas."""

    snapshot: dict[str, PoolSnapshot] = {}
    path = _raw_v3_path("daily", stamp)
    if not path.exists():
        return snapshot
    if pool_registry is None:
        pool_registry = _build_pool_registry([stamp])
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            resolved = _pool_snapshot_from_record(rec, pool_registry)
            if resolved is not None:
                pool_id, pool_snapshot = resolved
                snapshot[pool_id] = pool_snapshot
    return snapshot


def _candidate_allocations(pool: PoolSnapshot) -> tuple[tuple[str, str, float], ...]:
    """Allocate pool TVL equally across the candidate tokens on its two sides."""

    token0_id, token0_symbol, token1_id, token1_symbol, _ = pool
    candidates = [
        (address, symbol)
        for address, symbol in (
            (token0_id, token0_symbol),
            (token1_id, token1_symbol),
        )
        if address in VEHICLE_CANDIDATES
    ]
    if not candidates:
        return ()
    weight = 1.0 / len(candidates)
    return tuple(
        (address, VEHICLE_CANDIDATES[address], weight)
        for address, _ in candidates
    )


def compute_lp_day(
    stamp: str,
    pool_registry: dict[str, PoolIdentity] | None = None,
) -> pd.DataFrame:
    """Allocate day-level V3 pool TVL and compute each candidate's share."""

    date_iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    snapshot = _build_pool_snapshot(stamp, pool_registry)
    candidate_usd: dict[str, float] = defaultdict(float)
    candidate_symbol: dict[str, str] = {}

    for pool in snapshot.values():
        tvl_usd = pool[-1]
        for address, symbol, weight in _candidate_allocations(pool):
            candidate_usd[address] += weight * tvl_usd
            candidate_symbol[address] = symbol

    if not candidate_usd:
        return pd.DataFrame(columns=[
            "date", "token_address", "token_symbol", "is_vehicle_candidate",
            "total_lp_liquidity_usd", "lp_concentration_share",
        ])

    total = sum(candidate_usd.values())
    rows = [
        {
            "date": date_iso,
            "token_address": address,
            "token_symbol": candidate_symbol.get(address, VEHICLE_CANDIDATES[address]),
            "is_vehicle_candidate": True,
            "total_lp_liquidity_usd": usd,
            "lp_concentration_share": usd / total,
        }
        for address, usd in candidate_usd.items()
    ]
    return (
        pd.DataFrame(rows)
        .sort_values("total_lp_liquidity_usd", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Multi-day run
# ---------------------------------------------------------------------------


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def run(
    start: str | None = None,
    end: str | None = None,
    chart: bool = True,
) -> pd.DataFrame:
    """Compute LP concentration for a date range and write the exhibit Parquet.

    start / end are YYYY-MM-DD inclusive bounds. Returns the combined DataFrame.
    """
    stamps = _available_stamps("daily")
    if start:
        s = start.replace("-", "")
        stamps = [d for d in stamps if d >= s]
    if end:
        e = end.replace("-", "")
        stamps = [d for d in stamps if d <= e]

    if not stamps:
        print("no V3 daily pool snapshots found for the requested range", flush=True)
        return pd.DataFrame()

    print(
        f"LP concentration: {len(stamps)} days [{stamps[0]} .. {stamps[-1]}]",
        flush=True,
    )

    registry_stamps = _available_stamps("swaps")
    pool_registry = _build_pool_registry(registry_stamps)

    frames = []
    for index, stamp in enumerate(stamps, 1):
        day_df = compute_lp_day(stamp, pool_registry)
        if not day_df.empty:
            frames.append(day_df)
        if index % 100 == 0 or index == len(stamps):
            print(
                f"  pool snapshots: {index}/{len(stamps)} days, "
                f"{sum(len(frame) for frame in frames):,} token-days",
                flush=True,
            )

    if not frames:
        print("no LP data produced", flush=True)
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    _write_parquet(combined, LP_CONCENTRATION_PATH)
    print(
        f"LP concentration written: {len(combined):,} rows -> {LP_CONCENTRATION_PATH}",
        flush=True,
    )

    if chart:
        _plot_top5(combined)

    return combined


def _plot_top5(df: pd.DataFrame) -> None:
    """Daily LP concentration share for the five candidate tokens."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if df.empty:
        return

    # Identify top-5 tokens by mean LP concentration share across all days
    mean_share = (
        df.groupby("token_address")["lp_concentration_share"]
        .mean()
        .sort_values(ascending=False)
    )
    top5_addrs = mean_share.head(5).index.tolist()

    # Get symbol lookup
    sym_map = df.drop_duplicates("token_address").set_index("token_address")["token_symbol"].to_dict()
    top5_labels = [sym_map.get(a, a[:8]) for a in top5_addrs]

    # Pivot: date x token
    pivot = df[df["token_address"].isin(top5_addrs)].pivot_table(
        index="date", columns="token_address", values="lp_concentration_share", aggfunc="sum"
    ).fillna(0.0)
    pivot.index = pd.to_datetime(pivot.index)
    pivot = pivot.sort_index()

    fig, ax = plt.subplots(figsize=(10, 5))
    for addr, label in zip(top5_addrs, top5_labels):
        if addr in pivot.columns:
            ax.plot(pivot.index, pivot[addr], label=label, linewidth=1.5)

    ax.set_xlabel("Date")
    ax.set_ylabel("LP Concentration Share")
    ax.set_title("Daily candidate-linked liquidity concentration (Uniswap V3)")
    ax.legend(loc="best", fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    fig.tight_layout()

    LP_CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(LP_CHART_PATH, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"chart saved -> {LP_CHART_PATH}", flush=True)
