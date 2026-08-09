#!/usr/bin/env python3
"""Validated constant-product pool-day panel for LP rent incidence.

UNISWAP V2. `pairHourData` gives end-of-hour reserves and hourly USD volume for
every pair, which is everything the constant-product accounting needs. Fees are
30 basis points of volume. The pool's marginal price is `reserve1 / reserve0`,
so realised variance comes from the pool itself rather than an external feed.
Loss-versus-rebalancing for a constant-product pool is the closed form of
Milionis, Moallemi, Roughgarden and Zhang: the instantaneous rate is one eighth
of the variance rate times pool value, and integrating over a day gives realised
variance over eight times pool value. Realised variance is invariant to which
leg is the numeraire, because inverting a price only flips the sign of every log
return, so the dollar figure does not depend on that choice; what the choice
fixes is the interpretation, which is stated in the finding.

UNISWAP V3 is withheld. Provider TVL failed the historical-balance audit, and
local virtual depth is neither deposited capital nor a valid LVR scale. The
dormant V3 materializer remains available for future redevelopment but is not
reachable from this release CLI until event-replayed inventories and
path-integrated LVR both pass.

GAS. Every mint and every burn is a transaction someone paid for, so the counts
observed in the canonical event layer times a per-operation gas figure times the day's
median gas price times the ETH price is the pool's realised repositioning bill.
It is netted at pool level against pool-level fee revenue, which is the correct
incidence: the pool's providers as a group paid it.

Screens are applied in the analysis script, not here, so that the panel keeps
the rows a screen removes and the screen can be reported and varied.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.data_release import require_node_d_release
from ddvc.liquidity import CAPITAL_COLUMN
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import (
    DATA_DIR,
    MARKET_STATE_LOCK,
    POOL_CAPITAL_PANEL,
    RAW_MARKET_DATA_LOCK,
)
from ddvc.pricing.v3pools import derive_fee_tier
from ddvc.provenance import cache_key, require_current_artifacts, sidecar_path, stamp
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import (
    STATE_ROOT,
    available_state_days,
    read_cp_partition,
    read_tick_partition,
    state_partition_path,
)
from ddvc.work_partition import weighted_contiguous_chunks

PROC = DATA_DIR / "processed"
LOCK = PROC / ".rent_incidence_panels.lock"
DAY_CACHE_ROOT = PROC / "_rent_incidence_day_cache"

DEFAULT_RENT_WORKERS = 2
MAX_RENT_WORKERS = 4
UNIQUE_KEYS = ("venue", "day", "pool")

COMMON_SHARD_CODE_SOURCES = [
    "scripts/build_rent_incidence_panel.py",
    "src/ddvc/liquidity.py",
    "src/ddvc/paths.py",
    "src/ddvc/state_data.py",
    "src/ddvc/work_partition.py",
]
COMMON_OUTPUT_CODE_SOURCES = [
    *COMMON_SHARD_CODE_SOURCES,
    "src/ddvc/panel_assembly.py",
    "src/ddvc/provenance.py",
    "src/ddvc/runtime.py",
]
V2_SHARD_CODE_SOURCES = COMMON_SHARD_CODE_SOURCES
V3_SHARD_CODE_SOURCES = [*COMMON_SHARD_CODE_SOURCES, "src/ddvc/pricing/v3pools.py"]
V2_OUTPUT_CODE_SOURCES = COMMON_OUTPUT_CODE_SOURCES
V3_OUTPUT_CODE_SOURCES = [*COMMON_OUTPUT_CODE_SOURCES, "src/ddvc/pricing/v3pools.py"]

CAPITAL_COLUMNS = (
    "reported_capital_usd",
    CAPITAL_COLUMN,
    "capital_source",
    "quantity_kind",
    "pool_family",
    "invariant_family",
    "state_generation",
    "capital_validation_status",
    "exact_lag_valid",
)
V2_BASE_COLUMNS = (
    "day", "venue", "pool", "token0", "token1", "sym0", "sym1",
    "n_hours", "n_ret", "volume_usd", "reserve0", "reserve1", "rv",
    "rv_4h", "rv_oc", "max_abs_ret", "n_mint", "n_burn", "fee_rate",
    "liquidity",
)
V3_BASE_COLUMNS = (
    "day", "venue", "pool", "token0", "token1", "sym0", "sym1",
    "n_hours", "n_ret", "volume_usd", "n_swap", "reserve0", "reserve1",
    "rv", "rv_4h", "rv_oc", "max_abs_ret", "n_mint", "n_burn",
    "fee_rate", "tick", "liquidity", "sqrt_price_x96",
)
V2_COLUMNS = (*V2_BASE_COLUMNS, *CAPITAL_COLUMNS)
V3_COLUMNS = (*V3_BASE_COLUMNS, *CAPITAL_COLUMNS)


def _panel_schema(columns: tuple[str, ...]) -> pa.Schema:
    string_columns = {
        "day", "venue", "pool", "token0", "token1", "sym0", "sym1",
        "capital_source", "quantity_kind", "pool_family", "invariant_family",
        "state_generation", "capital_validation_status",
    }
    integer_columns = {"n_hours", "n_ret", "n_mint", "n_burn", "n_swap", "tick"}
    required_columns = {
        *UNIQUE_KEYS,
        "capital_source",
        "quantity_kind",
        "pool_family",
        "invariant_family",
        "state_generation",
        "capital_validation_status",
        "exact_lag_valid",
    }
    return pa.schema(
        [
            pa.field(
                column,
                pa.string()
                if column in string_columns
                else pa.int64()
                if column in integer_columns
                else pa.bool_()
                if column == "exact_lag_valid"
                else pa.float64(),
                nullable=column not in required_columns,
            )
            for column in columns
        ]
    )


V2_SCHEMA = _panel_schema(V2_COLUMNS)
V3_SCHEMA = _panel_schema(V3_COLUMNS)


def _expected_schema(columns: tuple[str, ...]) -> pa.Schema:
    if columns == V2_COLUMNS:
        return V2_SCHEMA
    if columns == V3_COLUMNS:
        return V3_SCHEMA
    raise ValueError("unknown rent-panel schema contract")

V2_FEE = 0.003

# Per-operation gas for a liquidity event. The repository's only receipt-measured
# figure is for swaps (`ddvc.cpquote.GAS_BY_LEGS`: 154,604 units for one leg,
# measured on 2024-01-15 receipts). A liquidity event moves two token balances
# plus position state instead of one balance pair, so these are set as multiples
# of that measured baseline rather than invented: a v2 mint or burn at roughly
# the cost of a one-leg swap, a v3 mint at roughly 1.6x it because the position
# manager writes an NFT and tick state, a v3 burn plus collect at roughly 1.3x.
# The analysis script re-runs every net-return conclusion across a wide band
# around these, because the level is an assumption and the sign of a net return
# must not rest on one.
GAS_UNITS = {"v2_mint": 155_000, "v2_burn": 155_000,
             "v3_mint": 250_000, "v3_burn": 200_000}


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _rv_multiscale(hours: np.ndarray, prices: np.ndarray,
                   scale: float = 1.0) -> tuple[float, float, float, float]:
    """Realised variance at three sampling scales, plus the largest single move.

    A constant-product pool's marginal price only moves when someone trades it,
    and a round trip through the fee band moves it and moves it back, so hourly
    realised variance on the pool's own price carries a microstructure component
    that is largest exactly where the pool is thinnest. Sampling more coarsely
    shrinks that component while leaving the fundamental part alone, which is
    what makes the coarse estimates a bound on the bias rather than a taste
    difference. `scale` is 2 when the input is a square-root price.
    """
    if prices.size < 2:
        return 0.0, 0.0, 0.0, 0.0
    lp = np.log(prices) * scale
    lr = np.diff(lp)
    rv1 = float(np.sum(lr ** 2))
    bucket = hours // 4
    last = {}
    for b, v in zip(bucket, lp):
        last[b] = v
    keys = sorted(last)
    lp4 = np.array([last[k] for k in keys], dtype=float)
    rv4 = float(np.sum(np.diff(lp4) ** 2)) if lp4.size > 1 else 0.0
    rv_oc = float((lp[-1] - lp[0]) ** 2)
    return rv1, rv4, rv_oc, float(np.max(np.abs(lr)))


def _days(family: str, venue: str) -> list[str]:
    return available_state_days(family, venue)


def _capital_day(venue: str, day: str) -> pd.DataFrame:
    """Read only the accounting-capital partition needed by one output shard."""
    capital = pd.read_parquet(
        POOL_CAPITAL_PANEL,
        columns=["venue", "day", "pool", *CAPITAL_COLUMNS],
        filters=[("venue", "==", venue), ("day", "==", day)],
    )
    if capital.empty:
        return capital.drop(columns="venue")
    capital = capital.copy()
    capital["pool"] = capital["pool"].str.lower()
    duplicate = capital.duplicated(["day", "pool"], keep=False)
    if duplicate.any():
        sample = capital.loc[duplicate, ["day", "pool"]].iloc[0].to_dict()
        raise ValueError(f"capital panel has duplicate pool-day keys: {sample}")
    return capital.drop(columns="venue")


def _merge_capital_day(
    frame: pd.DataFrame,
    *,
    venue: str,
    day: str,
    columns: tuple[str, ...],
) -> pd.DataFrame:
    """Attach exact-day accounting capital without loading a venue-wide panel."""
    if frame.empty:
        return frame.reindex(columns=columns)
    panel = frame.copy()
    panel["pool"] = panel["pool"].str.lower()
    capital = _capital_day(venue, day)
    merged = panel.merge(
        capital[["day", "pool", *CAPITAL_COLUMNS]],
        on=["day", "pool"],
        how="left",
        validate="one_to_one",
    )
    return merged.reindex(columns=columns)


def _cache_path(cache_dir: Path, day: str) -> Path:
    return cache_dir / f"{day}.parquet"


def _validate_day_shard(
    path: Path,
    *,
    venue: str,
    day: str,
    columns: tuple[str, ...],
) -> int:
    """Validate one resumable shard without reading its wide payload."""
    if not path.is_file():
        raise FileNotFoundError(path)
    schema = pq.ParquetFile(path).schema_arrow
    names = tuple(schema.names)
    if names != columns:
        raise ValueError(
            f"{path.name}: schema mismatch; expected {list(columns)}, got {list(names)}"
        )
    expected = _expected_schema(columns)
    if not schema.equals(expected, check_metadata=False):
        raise ValueError(f"{path.name}: Arrow type/nullability contract mismatch")
    keys = pq.read_table(path, columns=list(UNIQUE_KEYS)).to_pandas()
    if keys.empty:
        return 0
    if keys[list(UNIQUE_KEYS)].isna().any().any():
        raise ValueError(f"{path.name}: null value in unique key")
    if set(keys["venue"].astype(str)) != {venue}:
        raise ValueError(f"{path.name}: contains the wrong venue")
    if set(keys["day"].astype(str)) != {day}:
        raise ValueError(f"{path.name}: contains the wrong day")
    if keys.duplicated(list(UNIQUE_KEYS)).any():
        raise ValueError(f"{path.name}: duplicate {UNIQUE_KEYS} keys")
    return len(keys)


def _valid_day_shard(
    path: Path,
    *,
    venue: str,
    day: str,
    columns: tuple[str, ...],
) -> bool:
    try:
        _validate_day_shard(path, venue=venue, day=day, columns=columns)
    except (FileNotFoundError, OSError, ValueError, pa.ArrowException):
        return False
    return True


def _missing_day_shards(
    days: list[str],
    cache_dir: Path,
    *,
    venue: str,
    columns: tuple[str, ...],
    force: bool = False,
) -> list[str]:
    """Return absent, corrupt, or schema-stale days for resumable rebuilding."""
    if force:
        return list(days)
    return [
        day
        for day in days
        if not _valid_day_shard(
            _cache_path(cache_dir, day), venue=venue, day=day, columns=columns
        )
    ]


def _write_day_shard(
    frame: pd.DataFrame,
    path: Path,
    *,
    venue: str,
    day: str,
    columns: tuple[str, ...],
) -> int:
    """Atomically install one complete shard after enforcing its schema and key."""
    missing = sorted(set(columns) - set(frame.columns))
    unexpected = sorted(set(frame.columns) - set(columns))
    if missing or unexpected:
        raise ValueError(
            f"{path.name}: producer schema differs; missing={missing}, unexpected={unexpected}"
        )
    ordered = frame.reindex(columns=columns)
    table = pa.Table.from_pandas(
        ordered,
        schema=_expected_schema(columns),
        preserve_index=False,
        safe=True,
    )
    with atomic_output(path) as temporary:
        pq.write_table(table, temporary, compression="snappy")
        rows = _validate_day_shard(
            temporary, venue=venue, day=day, columns=columns
        )
    return rows


def _day_input_bytes(family: str, venue: str, day: str) -> int:
    return state_partition_path(family, venue, day).stat().st_size


# ---------------------------------------------------------------------------
# Uniswap v2
# ---------------------------------------------------------------------------

def _v2_day(day: str) -> list[dict]:
    state = read_cp_partition("uniswap_v2", day)
    hours: dict[str, list] = defaultdict(list)
    meta: dict[str, tuple] = {}
    snapshots = state[state["record_type"].eq("snapshot")]
    for rec in snapshots.itertuples(index=False):
        pid = rec.pool
        if pid not in meta:
            meta[pid] = (rec.token0, rec.token1, rec.symbol0, rec.symbol1)
        hours[pid].append(
            (int(rec.period_start), _f(rec.reserve0), _f(rec.reserve1), _f(rec.value_usd))
        )

    mints: dict[str, int] = defaultdict(int)
    burns: dict[str, int] = defaultdict(int)
    liquidity = state[state["record_type"].eq("liquidity")]
    for rec in liquidity.itertuples(index=False):
        if rec.source_stream == "mints":
            mints[rec.pool] += 1
        elif rec.source_stream == "burns":
            burns[rec.pool] += 1

    out = []
    for pid, rows in hours.items():
        rows.sort()
        r0 = np.array([r[1] for r in rows], dtype=float)
        r1 = np.array([r[2] for r in rows], dtype=float)
        vol = float(np.nansum([r[3] for r in rows]))
        ok = (r0 > 0) & (r1 > 0) & np.isfinite(r0) & np.isfinite(r1)
        if ok.sum() == 0:
            continue
        price = r1[ok] / r0[ok]
        hh = np.array([r[0] for r in rows], dtype=np.int64)[ok] // 3600
        rv1, rv4, rvoc, mx = _rv_multiscale(hh, price)
        t0, t1, s0, s1 = meta[pid]
        out.append({
            "day": day, "venue": "uniswap_v2", "pool": pid,
            "token0": t0, "token1": t1, "sym0": s0, "sym1": s1,
            "n_hours": int(ok.sum()), "n_ret": int(max(0, ok.sum() - 1)),
            "volume_usd": vol,
            "reserve0": float(np.nanmean(r0[ok])), "reserve1": float(np.nanmean(r1[ok])),
            "rv": rv1, "rv_4h": rv4, "rv_oc": rvoc, "max_abs_ret": mx,
            "n_mint": mints.get(pid, 0), "n_burn": burns.get(pid, 0),
            "fee_rate": V2_FEE, "liquidity": float("nan"),
        })
    return out


# ---------------------------------------------------------------------------
# Uniswap v3
# ---------------------------------------------------------------------------

def _v3_day_state(
    day: str,
    keep: set[str] | None,
    *,
    summarize: bool,
) -> tuple[dict[str, dict], dict[str, tuple[int, int]], list[tuple[str, int, int, int]]]:
    """Read one partition into replay events and, when needed, a day summary."""
    acc: dict[str, dict] = {}
    state = read_tick_partition("uniswap_v3", day)
    if summarize:
        for rec in state[state["record_type"].eq("swap")].itertuples(index=False):
            pid = rec.pool
            if keep is not None and pid not in keep:
                continue
            a = acc.get(pid)
            if a is None:
                a = acc[pid] = {
                    "token0": rec.token0,
                    "token1": rec.token1,
                    "sym0": rec.symbol0,
                    "sym1": rec.symbol1,
                    "fee_pips": rec.fee_pips,
                    "vol": 0.0,
                    "n": 0,
                    "hp": {},
                    "ticks": [],
                    "w": [],
                }
            usd = _f(rec.value_usd)
            if math.isfinite(usd):
                a["vol"] += usd
            a["n"] += 1
            ts = int(rec.timestamp)
            sp = _f(rec.sqrt_price_x96)
            if math.isfinite(sp) and sp > 0:
                a["hp"][ts // 3600] = sp
            try:
                tick = int(rec.tick)
            except (TypeError, ValueError):
                tick = None
            if tick is not None:
                a["ticks"].append(tick)
                a["w"].append(abs(usd) if math.isfinite(usd) else 0.0)
    mints: dict[str, int] = defaultdict(int)
    burns: dict[str, int] = defaultdict(int)
    events: list[tuple[str, int, int, int]] = []
    for rec in state[state["record_type"].eq("liquidity")].itertuples(index=False):
        if keep is not None and rec.pool not in keep:
            continue
        if summarize:
            if rec.source_stream == "mints":
                mints[rec.pool] += 1
            elif rec.source_stream == "burns":
                burns[rec.pool] += 1
        try:
            amount = int(getattr(rec, "liquidity_delta"))
            lower = int(getattr(rec, "tick_lower"))
            upper = int(getattr(rec, "tick_upper"))
        except (AttributeError, TypeError, ValueError):
            continue
        if amount:
            events.append((rec.pool, lower, upper, amount))
    pools = set(mints) | set(burns)
    counts = {pool: (mints.get(pool, 0), burns.get(pool, 0)) for pool in pools}
    return acc, counts, events


def _v3_day_summary(
    day: str, keep: set[str] | None
) -> tuple[dict[str, dict], dict[str, tuple[int, int]]]:
    """Per-pool swaps and liquidity counts from one canonical partition read."""
    swaps, counts, _events = _v3_day_state(day, keep, summarize=True)
    return swaps, counts


def _v3_pool_universe(days: list[str], top_n: int, workers: int) -> set[str]:
    """Pools ranked by exact swap count over every canonical day."""
    counts: dict[str, int] = defaultdict(int)
    chunks = weighted_contiguous_chunks(
        days,
        [_day_input_bytes("tick", "uniswap_v3", day) for day in days],
        workers,
    )
    with interruptible_process_pool(workers) as ex:
        for chunk_counts in ex.map(_v3_count_chunk, chunks):
            for pool, count in chunk_counts.items():
                counts[pool] += count
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {k for k, _ in ranked[:top_n]}


def _v3_count_day(day: str) -> dict[str, int]:
    state = read_tick_partition("uniswap_v3", day)
    swaps = state[state["record_type"].eq("swap")]
    return swaps.groupby("pool").size().astype(int).to_dict()


def _v3_count_chunk(days: list[str]) -> dict[str, int]:
    """Reduce full-calendar swap counts inside one bounded worker result."""
    counts: dict[str, int] = defaultdict(int)
    for day in days:
        for pool, count in _v3_count_day(day).items():
            counts[pool] += count
    return dict(counts)


def _v3_tick_points_day(payload: tuple[str, set[str]]) -> dict[str, set[int]]:
    """Return only unique initialized ticks, never a day's full event payload."""
    day, keep = payload
    points: dict[str, set[int]] = defaultdict(set)
    state = read_tick_partition("uniswap_v3", day)
    for rec in state[state["record_type"].eq("liquidity")].itertuples(index=False):
        if rec.pool not in keep:
            continue
        try:
            lower = int(rec.tick_lower)
            upper = int(rec.tick_upper)
        except (TypeError, ValueError):
            continue
        points[rec.pool].update((lower, upper))
    return dict(points)


def _v3_tick_points_chunk(payload: tuple[list[str], set[str]]) -> dict[str, set[int]]:
    """Reduce a bounded day chunk before returning initialized ticks to the parent."""
    days, keep = payload
    points: dict[str, set[int]] = defaultdict(set)
    for day in days:
        for pool, ticks in _v3_tick_points_day((day, keep)).items():
            points[pool].update(ticks)
    return dict(points)


def _v3_tick_index(
    days: list[str], keep: set[str], workers: int
) -> dict[str, list[int]]:
    """Build the fixed compressed tick coordinates with bounded worker results."""
    pool_ticks: dict[str, set[int]] = defaultdict(set)
    chunks = weighted_contiguous_chunks(
        days,
        [_day_input_bytes("tick", "uniswap_v3", day) for day in days],
        workers,
    )
    payloads = [(chunk, keep) for chunk in chunks]
    with interruptible_process_pool(workers) as ex:
        scanned = 0
        for i, points in enumerate(ex.map(_v3_tick_points_chunk, payloads), 1):
            for pool, ticks in points.items():
                pool_ticks[pool].update(ticks)
            scanned += len(chunks[i - 1])
            print(
                f"  v3 tick scan [{i}/{len(chunks)}] days={scanned:,}/{len(days):,} "
                f"pools={len(pool_ticks):,}",
                flush=True,
            )
    return {pool: sorted(ticks) for pool, ticks in pool_ticks.items()}


class Fenwick:
    """Prefix sums over a fixed compressed tick index, with point updates.

    Active liquidity at a tick is the sum of every net liquidity delta at or
    below it, and both the deltas and the query tick change every day, so the
    naive rebuild is a full pass over a pool's tick set per pool-day. A binary
    indexed tree makes each of those logarithmic instead. Python integers hold
    the values because `liquidity` is uint128 and overflows int64.
    """

    __slots__ = ("n", "t")

    def __init__(self, n: int) -> None:
        self.n = n
        self.t = [0] * (n + 1)

    def add(self, i: int, v: int) -> None:
        i += 1
        while i <= self.n:
            self.t[i] += v
            i += i & (-i)

    def prefix(self, i: int) -> int:
        """Sum over compressed positions 0..i inclusive."""
        i += 1
        s = 0
        while i > 0:
            s += self.t[i]
            i -= i & (-i)
        return s


def _build_v2_chunk(payload: dict[str, object]) -> tuple[int, int]:
    """Build independent V2 day shards inside one bounded worker."""
    cache_dir = Path(str(payload["cache_dir"]))
    built = rows = 0
    for day in payload["days"]:
        frame = pd.DataFrame.from_records(_v2_day(str(day))).reindex(columns=V2_BASE_COLUMNS)
        frame = _merge_capital_day(
            frame,
            venue="uniswap_v2",
            day=str(day),
            columns=V2_COLUMNS,
        )
        rows += _write_day_shard(
            frame,
            _cache_path(cache_dir, str(day)),
            venue="uniswap_v2",
            day=str(day),
            columns=V2_COLUMNS,
        )
        built += 1
    return built, rows


def _build_v2_shards(
    days: list[str],
    cache_dir: Path,
    *,
    workers: int,
    force: bool,
) -> None:
    pending = _missing_day_shards(
        days,
        cache_dir,
        venue="uniswap_v2",
        columns=V2_COLUMNS,
        force=force,
    )
    if not pending:
        print(f"  v2 resume: all {len(days):,} day shards are valid", flush=True)
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks = weighted_contiguous_chunks(
        pending,
        [_day_input_bytes("constant_product", "uniswap_v2", day) for day in pending],
        workers,
    )
    payloads = [{"days": chunk, "cache_dir": str(cache_dir)} for chunk in chunks]
    print(
        f"  v2 building {len(pending):,}/{len(days):,} days in {len(chunks)} bounded chunks",
        flush=True,
    )
    built = rows = 0
    with interruptible_process_pool(workers) as ex:
        for i, (chunk_days, chunk_rows) in enumerate(ex.map(_build_v2_chunk, payloads), 1):
            built += chunk_days
            rows += chunk_rows
            print(
                f"  v2 chunk [{i}/{len(chunks)}] built={built:,} new_rows={rows:,}",
                flush=True,
            )


def _v3_replay_structures(
    tick_lists: dict[str, list[int]],
) -> tuple[dict[str, tuple[list[int], dict[int, int]]], dict[str, Fenwick]]:
    index = {
        pool: (ticks, {tick: position for position, tick in enumerate(ticks)})
        for pool, ticks in tick_lists.items()
    }
    trees = {pool: Fenwick(len(ticks)) for pool, ticks in tick_lists.items()}
    return index, trees


def _v3_day_frame(
    day: str,
    swaps: dict[str, dict],
    counts: dict[str, tuple[int, int]],
    index: dict[str, tuple[list[int], dict[int, int]]],
    trees: dict[str, Fenwick],
) -> pd.DataFrame:
    rows: list[dict] = []
    for pid, acc in swaps.items():
        if not acc["ticks"]:
            continue
        weights = np.array(acc["w"], dtype=float)
        observed_ticks = np.array(acc["ticks"], dtype=float)
        tick = int(
            np.average(observed_ticks, weights=weights)
            if weights.sum() > 0
            else np.mean(observed_ticks)
        )
        hourly_prices = sorted(acc["hp"].items())
        hours = np.array([hour for hour, _ in hourly_prices], dtype=np.int64)
        sqrt_prices = np.array([price for _, price in hourly_prices], dtype=float)
        rv1, rv4, rvoc, maximum = _rv_multiscale(hours, sqrt_prices, scale=2.0)
        try:
            fee = int(acc["fee_pips"])
        except (TypeError, ValueError):
            fee = derive_fee_tier(pid, acc["token0"], acc["token1"])
        liquidity = float("nan")
        if pid in index:
            initialized, _positions = index[pid]
            position = int(np.searchsorted(initialized, tick, side="right")) - 1
            liquidity = float(trees[pid].prefix(position)) if position >= 0 else 0.0
        n_mint, n_burn = counts.get(pid, (0, 0))
        rows.append(
            {
                "day": day,
                "venue": "uniswap_v3",
                "pool": pid,
                "token0": acc["token0"],
                "token1": acc["token1"],
                "sym0": acc["sym0"],
                "sym1": acc["sym1"],
                "n_hours": len(hourly_prices),
                "n_ret": max(0, len(hourly_prices) - 1),
                "volume_usd": acc["vol"],
                "n_swap": acc["n"],
                "reserve0": float("nan"),
                "reserve1": float("nan"),
                "rv": rv1,
                "rv_4h": rv4,
                "rv_oc": rvoc,
                "max_abs_ret": maximum,
                "n_mint": n_mint,
                "n_burn": n_burn,
                "fee_rate": (fee / 1e6) if fee else float("nan"),
                "tick": tick,
                "liquidity": liquidity,
                "sqrt_price_x96": (
                    float(np.median(sqrt_prices)) if sqrt_prices.size else float("nan")
                ),
            }
        )
    base = pd.DataFrame.from_records(rows).reindex(columns=V3_BASE_COLUMNS)
    return _merge_capital_day(
        base,
        venue="uniswap_v3",
        day=day,
        columns=V3_COLUMNS,
    )


def _replay_v3_chunk(payload: dict[str, object]) -> tuple[int, int]:
    """Replay a prefix plus one disjoint chunk; persist only requested days."""
    keep = set(payload["keep"])
    cache_dir = Path(str(payload["cache_dir"]))
    build_days = set(payload["build_days"])
    index, trees = _v3_replay_structures(payload["tick_lists"])
    built = rows = 0
    timeline = [*payload["warm_days"], *payload["chunk_days"]]
    for day_value in timeline:
        day = str(day_value)
        summarize = day in build_days
        swaps, counts, events = _v3_day_state(day, keep, summarize=summarize)
        for pool, lower, upper, delta in events:
            if pool not in index:
                continue
            _ticks, positions = index[pool]
            trees[pool].add(positions[lower], delta)
            trees[pool].add(positions[upper], -delta)
        if not summarize:
            continue
        frame = _v3_day_frame(day, swaps, counts, index, trees)
        rows += _write_day_shard(
            frame,
            _cache_path(cache_dir, day),
            venue="uniswap_v3",
            day=day,
            columns=V3_COLUMNS,
        )
        built += 1
    return built, rows


def _build_v3_shards(
    days: list[str],
    cache_dir: Path,
    *,
    top_n: int,
    workers: int,
    force: bool,
) -> None:
    pending = _missing_day_shards(
        days,
        cache_dir,
        venue="uniswap_v3",
        columns=V3_COLUMNS,
        force=force,
    )
    if not pending:
        print(f"  v3 resume: all {len(days):,} day shards are valid", flush=True)
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"  v3 ranking {top_n} pools over {len(days):,} days", flush=True)
    keep = _v3_pool_universe(days, top_n, workers)
    print(f"  v3 universe contains {len(keep):,} pools", flush=True)
    tick_lists = _v3_tick_index(days, keep, workers)
    print(f"  v3 fixed tick index contains {len(tick_lists):,} pools", flush=True)

    chunks = weighted_contiguous_chunks(
        days,
        [_day_input_bytes("tick", "uniswap_v3", day) for day in days],
        workers,
    )
    pending_set = set(pending)
    day_position = {day: position for position, day in enumerate(days)}
    payloads = []
    for chunk in chunks:
        build_days = [day for day in chunk if day in pending_set]
        if not build_days:
            continue
        payloads.append(
            {
                "warm_days": days[: day_position[chunk[0]]],
                "chunk_days": chunk,
                "build_days": build_days,
                "keep": keep,
                "tick_lists": tick_lists,
                "cache_dir": str(cache_dir),
            }
        )
    print(
        f"  v3 rebuilding {len(pending):,}/{len(days):,} days in {len(payloads)} stateful chunks",
        flush=True,
    )
    built = rows = 0
    with interruptible_process_pool(min(workers, len(payloads))) as ex:
        for i, (chunk_days, chunk_rows) in enumerate(ex.map(_replay_v3_chunk, payloads), 1):
            built += chunk_days
            rows += chunk_rows
            print(
                f"  v3 chunk [{i}/{len(payloads)}] built={built:,} new_rows={rows:,}",
                flush=True,
            )


def _generation_cache_dir(
    family: str,
    generation: str,
    *,
    top_n: int | None = None,
    root: Path = DAY_CACHE_ROOT,
) -> Path:
    suffix = f"top_{top_n}" if top_n is not None else "all_pools"
    return root / family / f"engine_{generation}" / suffix


def _clean_interrupted_shard_temps(cache_dir: Path) -> int:
    """Remove only orphaned atomic-write temporaries from an earlier killed worker."""
    removed = 0
    for path in cache_dir.glob(".*.parquet.*.tmp"):
        path.unlink()
        removed += 1
    return removed


def _require_generation_current(
    expected: str,
    *,
    code_sources: list[str],
    inputs: list[Path],
) -> None:
    """Abort before publication if any code or canonical input changed mid-run."""
    current = cache_key(code_sources, inputs=inputs)
    if current != expected:
        raise RuntimeError(
            f"rent-panel generation changed during the build: {expected} -> {current}"
        )


def _assemble_family(
    *,
    days: list[str],
    cache_dir: Path,
    venue: str,
    columns: tuple[str, ...],
    output: Path,
    code_sources: list[str],
    canonical_inputs: list[Path],
    generation: str,
) -> None:
    missing = _missing_day_shards(
        days,
        cache_dir,
        venue=venue,
        columns=columns,
    )
    if missing:
        preview = ", ".join(missing[:5])
        raise RuntimeError(
            f"cannot assemble {venue}: {len(missing):,} day shards are absent or invalid: {preview}"
        )

    def progress(index: int, total: int, rows: int) -> None:
        if index % 250 == 0 or index == total:
            print(f"  {venue} assembly [{index}/{total}] rows={rows:,}", flush=True)

    release_inputs = [*canonical_inputs, cache_dir]
    release_key = cache_key(code_sources, inputs=release_inputs)
    # Output and provenance are separate files. Removing the old sidecar first
    # makes an interruption fail closed: new panel bytes can never inherit a
    # still-current manifest from the prior top-N or generation.
    sidecar_path(output).unlink(missing_ok=True)
    result = assemble_parquet_shards(
        [_cache_path(cache_dir, day) for day in days],
        output,
        progress=progress,
        unique_keys=UNIQUE_KEYS,
    )
    if cache_key(code_sources, inputs=release_inputs) != release_key:
        raise RuntimeError(f"{venue} release inputs or code changed during assembly")
    stamp(
        output,
        code_sources=code_sources,
        inputs=release_inputs,
        rows=result.rows,
        notes=(
            f"generation {generation}; assembled {len(days)} validated day shards; "
            f"{result.shards} nonempty"
        ),
    )
    print(f"{venue} pool-days: {result.rows:,}", flush=True)


def build_v2(*, workers: int, force: bool) -> None:
    days = _days("constant_product", "uniswap_v2")
    if not days:
        raise RuntimeError("no canonical Uniswap V2 state days")
    inputs = [STATE_ROOT / "constant_product" / "uniswap_v2", POOL_CAPITAL_PANEL]
    generation = cache_key(V2_SHARD_CODE_SOURCES, inputs=inputs)
    cache_dir = _generation_cache_dir("v2", generation)
    _clean_interrupted_shard_temps(cache_dir)
    _build_v2_shards(days, cache_dir, workers=workers, force=force)
    _require_generation_current(
        generation,
        code_sources=V2_SHARD_CODE_SOURCES,
        inputs=inputs,
    )
    _assemble_family(
        days=days,
        cache_dir=cache_dir,
        venue="uniswap_v2",
        columns=V2_COLUMNS,
        output=PROC / "rent_incidence_v2_pool_day.parquet",
        code_sources=V2_OUTPUT_CODE_SOURCES,
        canonical_inputs=inputs,
        generation=generation,
    )


def build_v3(*, top_n: int, workers: int, force: bool) -> None:
    days = _days("tick", "uniswap_v3")
    if not days:
        raise RuntimeError("no canonical Uniswap V3 state days")
    inputs = [STATE_ROOT / "tick" / "uniswap_v3", POOL_CAPITAL_PANEL]
    generation = cache_key(V3_SHARD_CODE_SOURCES, inputs=inputs)
    cache_dir = _generation_cache_dir("v3", generation, top_n=top_n)
    _clean_interrupted_shard_temps(cache_dir)
    _build_v3_shards(
        days,
        cache_dir,
        top_n=top_n,
        workers=workers,
        force=force,
    )
    _require_generation_current(
        generation,
        code_sources=V3_SHARD_CODE_SOURCES,
        inputs=inputs,
    )
    _assemble_family(
        days=days,
        cache_dir=cache_dir,
        venue="uniswap_v3",
        columns=V3_COLUMNS,
        output=PROC / "rent_incidence_v3_pool_day.parquet",
        code_sources=V3_OUTPUT_CODE_SOURCES,
        canonical_inputs=inputs,
        generation=generation,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("which", choices=("v2",), nargs="?", default="v2")
    parser.add_argument("--workers", type=int, default=DEFAULT_RENT_WORKERS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    workers = bounded_workers(args.workers, maximum=MAX_RENT_WORKERS)
    require_node_d_release(market_state=True)
    require_current_artifacts([POOL_CAPITAL_PANEL], consumer="rent-incidence panel builder")
    build_v2(workers=workers, force=args.force)


if __name__ == "__main__":
    with exclusive_job(LOCK, job="rent-incidence analysis panels"):
        with exclusive_job(
            RAW_MARKET_DATA_LOCK,
            job="raw market-data fetch, enrichment, or canonical materialisation",
        ):
            with exclusive_job(MARKET_STATE_LOCK, job="canonical market-state build"):
                main()
