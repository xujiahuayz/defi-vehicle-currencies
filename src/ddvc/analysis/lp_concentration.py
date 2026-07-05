"""Foundational exhibit #1 — LP concentration on vehicle currencies as base asset.

For each day, computes per-pool net LP liquidity delta (Uniswap V3 mints minus
burns), identifies the "base asset" of each pool as the token with higher VShare
(or a hardcoded known-vehicle list as fallback), and aggregates the fraction of
all V3 LP liquidity provided against each token as base.

Outputs:
  data/exhibits/lp_concentration.parquet
    columns: date, token_address, token_symbol, is_vehicle_candidate,
             total_lp_liquidity_usd, lp_concentration_share

  output/exhibits/lp_concentration_top5.pdf
    daily LP concentration share for the top-5 tokens over the sample period

The liquidity unit for mints/burns is the raw ``amount`` field (the Uniswap V3
concentrated-liquidity measure in L units). Since L is not directly comparable
across pools in USD terms we instead use pool-USD TVL from the V3 daily snapshot
as a per-pool USD scale factor. On days when a daily snapshot is missing for a
pool, we fall back to L-unit liquidity (relative comparison only, not absolute
USD).
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR

# ---------------------------------------------------------------------------
# Known vehicle / base asset candidates (lowercase Ethereum addresses)
# ---------------------------------------------------------------------------

VEHICLE_CANDIDATES: dict[str, str] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0x853d955acef822db058eb8505911ed77f175b99e": "FRAX",
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
# Pool registry — map pool_id -> (token0_addr, token0_sym, token1_addr, token1_sym)
# ---------------------------------------------------------------------------

def _build_pool_registry(stamp: str) -> dict[str, tuple[str, str, str, str]]:
    """Build pool_id -> (t0_addr, t0_sym, t1_addr, t1_sym) from the swaps stream."""
    pools: dict[str, tuple[str, str, str, str]] = {}
    path = _raw_v3_path("swaps", stamp)
    if not path.exists():
        return pools
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pool = rec.get("pool") or {}
            pid = pool.get("id")
            t0 = pool.get("token0") or {}
            t1 = pool.get("token1") or {}
            t0_id = t0.get("id")
            t1_id = t1.get("id")
            if pid and t0_id and t1_id:
                pools[pid.lower()] = (
                    t0_id.lower(), t0.get("symbol", ""),
                    t1_id.lower(), t1.get("symbol", ""),
                )
    return pools


def _build_tvl_map(stamp: str) -> dict[str, float]:
    """Build pool_id -> tvlUSD from the V3 daily snapshot."""
    tvl: dict[str, float] = {}
    path = _raw_v3_path("daily", stamp)
    if not path.exists():
        return tvl
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pool = rec.get("pool") or {}
            pid = pool.get("id")
            if pid:
                try:
                    value = float(rec.get("tvlUSD", 0) or 0)
                    if 0 < value <= MAX_POOL_TVL_USD:
                        tvl[pid.lower()] = value
                except (TypeError, ValueError):
                    pass
    return tvl


# ---------------------------------------------------------------------------
# Per-day LP delta calculation
# ---------------------------------------------------------------------------

def _load_liquidity_events(stream: str, stamp: str) -> list[dict]:
    """Load mints or burns for one day; return list of {pool_id, amount, amount0, amount1}."""
    path = _raw_v3_path(stream, stamp)
    if not path.exists():
        return []
    events = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pool = rec.get("pool") or {}
            pid = pool.get("id")
            if not pid:
                continue
            try:
                amount = float(rec.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0
            try:
                amount0 = abs(float(rec.get("amount0", 0) or 0))
            except (TypeError, ValueError):
                amount0 = 0.0
            try:
                amount1 = abs(float(rec.get("amount1", 0) or 0))
            except (TypeError, ValueError):
                amount1 = 0.0
            events.append({
                "pool_id": pid.lower(),
                "amount": amount,
                "amount0": amount0,
                "amount1": amount1,
            })
    return events


def compute_lp_day(
    stamp: str,
    vshare_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """LP concentration metrics for one day.

    stamp: YYYYMMDD
    vshare_df: optional DataFrame from the metrics layer with columns
               ['token_address', 'VShare', 'date'] for the same day. Used to
               identify base asset dynamically; falls back to VEHICLE_CANDIDATES
               hardcoded list if not provided.

    Returns a DataFrame with columns:
        date, token_address, token_symbol, is_vehicle_candidate,
        total_lp_liquidity_usd, lp_concentration_share
    """
    date_iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"

    pools = _build_pool_registry(stamp)
    tvl = _build_tvl_map(stamp)

    mints = _load_liquidity_events("mints", stamp)
    burns = _load_liquidity_events("burns", stamp)

    if not mints and not burns:
        return pd.DataFrame(columns=[
            "date", "token_address", "token_symbol", "is_vehicle_candidate",
            "total_lp_liquidity_usd", "lp_concentration_share",
        ])

    # Build net liquidity (L units) per pool
    net_liq: dict[str, float] = defaultdict(float)
    for ev in mints:
        net_liq[ev["pool_id"]] += ev["amount"]
    for ev in burns:
        net_liq[ev["pool_id"]] -= ev["amount"]

    # Use abs(net_liq) as a proxy for LP activity magnitude; treat net 0 as 0.
    # For absolute USD, scale by TVL / total_L_for_pool (approximation only).
    # A better approach: use TVL directly as the "weight" for each pool —
    # this measures how much USD is locked in pools whose base is this token.

    # Build per-pool USD weight: TVL from daily snapshot, or fall back to |net_liq| L
    pool_usd: dict[str, float] = {}
    for pid in set(list(net_liq.keys()) + list(tvl.keys())):
        usd = tvl.get(pid, 0.0)
        if usd > 0:
            pool_usd[pid] = usd

    # Identify the VShare map for this day if provided
    vshare_map: dict[str, float] = {}
    if vshare_df is not None and not vshare_df.empty:
        day_vs = vshare_df[vshare_df["date"] == date_iso]
        for _, row in day_vs.iterrows():
            vshare_map[row["token_address"]] = float(row["VShare"])

    def _base_asset(pid: str) -> tuple[str, str] | None:
        """Return (address, symbol) of the vehicle-side base asset in this pool.

        The paper object is liquidity supplied against candidate vehicle assets.
        Earlier versions let any high-VShare token become the pool "base", which
        is useful descriptively but too noisy for the vehicle-currency test.
        Here a pool contributes only if at least one side is a known vehicle
        candidate. If both sides are candidates, choose the side with higher
        same-day vehicle volume share, falling back to the priority list.
        """
        info = pools.get(pid)
        if not info:
            return None
        t0_id, t0_sym, t1_id, t1_sym = info
        t0_is_vehicle = t0_id in VEHICLE_CANDIDATES
        t1_is_vehicle = t1_id in VEHICLE_CANDIDATES

        if not t0_is_vehicle and not t1_is_vehicle:
            return None
        if t0_is_vehicle and not t1_is_vehicle:
            return t0_id, t0_sym
        if t1_is_vehicle and not t0_is_vehicle:
            return t1_id, t1_sym

        # If both are vehicle candidates and VShare data are available, pick the
        # candidate with higher same-day vehicle share. In the metrics table the
        # index column currently stores symbols, so the lookup is by symbol.
        if vshare_map:
            vs0 = vshare_map.get(t0_sym, 0.0)
            vs1 = vshare_map.get(t1_sym, 0.0)
            if vs0 > vs1:
                return t0_id, t0_sym
            elif vs1 > vs0:
                return t1_id, t1_sym
            # Fall through to hardcoded list if tied

        # Fall back: prefer known vehicle candidates, ordered by priority
        prio = {addr: i for i, addr in enumerate(VEHICLE_CANDIDATES.keys())}
        p0 = prio.get(t0_id, 999)
        p1 = prio.get(t1_id, 999)
        if p0 < p1:
            return t0_id, t0_sym
        elif p1 < p0:
            return t1_id, t1_sym
        else:
            # Both unknown or same priority: return None (unclassified)
            return None

    # Aggregate LP USD by base asset
    base_usd: dict[str, float] = defaultdict(float)
    base_sym: dict[str, str] = {}

    for pid, usd in pool_usd.items():
        ba = _base_asset(pid)
        if ba is None:
            continue
        addr, sym = ba
        base_usd[addr] += usd
        base_sym[addr] = sym

    if not base_usd:
        return pd.DataFrame(columns=[
            "date", "token_address", "token_symbol", "is_vehicle_candidate",
            "total_lp_liquidity_usd", "lp_concentration_share",
        ])

    total = sum(base_usd.values())
    rows = []
    for addr, usd in base_usd.items():
        sym = base_sym.get(addr, "")
        rows.append({
            "date": date_iso,
            "token_address": addr,
            "token_symbol": sym,
            "is_vehicle_candidate": addr in VEHICLE_CANDIDATES,
            "total_lp_liquidity_usd": usd,
            "lp_concentration_share": usd / total if total > 0 else 0.0,
        })
    df = pd.DataFrame(rows).sort_values("total_lp_liquidity_usd", ascending=False)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Multi-day run
# ---------------------------------------------------------------------------

def _available_stamps() -> list[str]:
    """YYYYMMDD stamps for which V3 mints or burns data exists."""
    d = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
    stamps: set[str] = set()
    if d.is_dir():
        for f in d.glob("uniswap_v3_mints_*.jsonl.gz"):
            # f.name = "uniswap_v3_mints_20230101.jsonl.gz"
            # f.stem = "uniswap_v3_mints_20230101.jsonl" (only strips one suffix)
            name_no_gz = f.name[:-3]  # strip .gz
            stamp = name_no_gz.replace(".jsonl", "").split("_")[-1]
            if len(stamp) == 8 and stamp.isdigit():
                stamps.add(stamp)
    return sorted(stamps)


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def run(
    start: str | None = None,
    end: str | None = None,
    skip_existing: bool = True,
    chart: bool = True,
) -> pd.DataFrame:
    """Compute LP concentration for a date range and write the exhibit Parquet.

    start / end are YYYY-MM-DD inclusive bounds. Returns the combined DataFrame.
    """
    stamps = _available_stamps()
    if start:
        s = start.replace("-", "")
        stamps = [d for d in stamps if d >= s]
    if end:
        e = end.replace("-", "")
        stamps = [d for d in stamps if d <= e]

    if not stamps:
        print("no V3 mints/burns data found for the requested range", flush=True)
        return pd.DataFrame()

    print(
        f"LP concentration: {len(stamps)} days [{stamps[0]} .. {stamps[-1]}]",
        flush=True,
    )

    # Try to load metrics for VShare cross-reference
    metrics_path = DATA_DIR / "metrics" / "daily_token_metrics.parquet"
    vshare_df: pd.DataFrame | None = None
    if metrics_path.exists():
        try:
            vshare_df = pd.read_parquet(metrics_path)
        except Exception:
            vshare_df = None

    frames = []
    for stamp in stamps:
        day_df = compute_lp_day(stamp, vshare_df=vshare_df)
        if not day_df.empty:
            frames.append(day_df)
            print(
                f"  {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}: "
                f"{len(day_df)} tokens, "
                f"total_usd={day_df['total_lp_liquidity_usd'].sum():,.0f}",
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
    """Daily LP concentration share for the top-5 tokens (by mean share). PDF output."""
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
    ax.set_title("Daily LP Concentration Share — Top 5 Base Assets (Uniswap V3)")
    ax.legend(loc="best", fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    fig.tight_layout()

    LP_CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(LP_CHART_PATH, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"chart saved -> {LP_CHART_PATH}", flush=True)
