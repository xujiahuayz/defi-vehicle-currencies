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
local virtual depth is neither deposited capital nor a valid LVR scale. This
materializer has no V3 path; a future implementation must start from validated
event-replayed inventories and path-integrated LVR.

GAS. Mint and burn counts remain descriptive event counts. They are not a cost
measure. Provider gas enters only after each relevant transaction is joined to its
exact receipt and block header, assigned under a declared controller-level rule, and
then aggregated to the pool-day level.

Screens are applied in the analysis script, not here, so that the panel keeps
the rows a screen removes and the screen can be reported and varied.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.capital_contracts import CAPITAL_CURRENT_COLUMN, capital_contract
from ddvc.capital_release import CapitalRelease, resolve_capital_release
from ddvc.cp_state_stream import CPStateStreamSet, certified_cp_event_stream
from ddvc.liquidity import CAPITAL_COLUMN
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import (
    DATA_DIR,
    RAW_MARKET_DATA_LOCK,
)
from ddvc.provenance import cache_key
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_process_pool, staged_output
from ddvc.state_data import (
    CP_COLUMNS,
    RAW_ROOT,
)
from ddvc.tables import publish_staged_artifact
from ddvc.work_partition import weighted_contiguous_chunks
from ddvc.v2_event_completeness import V2EventSourceRelease, resolve_v2_event_source_release

PROC = DATA_DIR / "processed"
LOCK = PROC / ".rent_incidence_panels.lock"
DAY_CACHE_ROOT = PROC / "_rent_incidence_day_cache"

DEFAULT_RENT_WORKERS = 2
MAX_RENT_WORKERS = 4
UNIQUE_KEYS = ("venue", "day", "pool")

COMMON_SHARD_CODE_SOURCES = [
    "scripts/build_rent_incidence_panel.py",
    "src/ddvc/capital_contracts.py",
    "src/ddvc/cp_state_stream.py",
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
V2_OUTPUT_CODE_SOURCES = COMMON_OUTPUT_CODE_SOURCES

CAPITAL_COLUMNS = (
    "reported_capital_usd",
    "reported_capital_source",
    "reconstructed_capital_usd",
    CAPITAL_CURRENT_COLUMN,
    CAPITAL_COLUMN,
    "capital_reconciliation_ratio",
    "balance_value_ratio",
    "reserve_source",
    "reserve_state_timestamp",
    "reserve_validation_status",
    "capital_source",
    "price_source",
    "quantity_kind",
    "pool_family",
    "invariant_family",
    "state_generation",
    "capital_validation_status",
    "failure_reason",
    "capital_valid",
    "exact_lag_valid",
)
V2_BASE_COLUMNS = (
    "day", "venue", "pool", "token0", "token1", "sym0", "sym1",
    "n_hours", "n_ret", "volume_usd", "reserve0", "reserve1", "rv",
    "rv_4h", "rv_oc", "max_abs_ret", "n_mint", "n_burn", "fee_rate",
    "liquidity",
)
V2_COLUMNS = (*V2_BASE_COLUMNS, *CAPITAL_COLUMNS)


def _panel_schema(columns: tuple[str, ...]) -> pa.Schema:
    string_columns = {
        "day", "venue", "pool", "token0", "token1", "sym0", "sym1",
        "reported_capital_source", "reserve_source", "reserve_validation_status",
        "capital_source", "price_source", "quantity_kind",
        "pool_family", "invariant_family", "state_generation",
        "capital_validation_status", "failure_reason",
    }
    integer_columns = {
        "n_hours", "n_ret", "n_mint", "n_burn", "n_swap", "tick",
        "reserve_state_timestamp",
    }
    required_columns = {
        *UNIQUE_KEYS,
        "capital_source",
        "reserve_source",
        "reserve_validation_status",
        "quantity_kind",
        "pool_family",
        "invariant_family",
        "state_generation",
        "capital_validation_status",
        "capital_valid",
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
                if column in {"capital_valid", "exact_lag_valid"}
                else pa.float64(),
                nullable=column not in required_columns,
            )
            for column in columns
        ]
    )


V2_SCHEMA = _panel_schema(V2_COLUMNS)


def _expected_schema(columns: tuple[str, ...]) -> pa.Schema:
    if columns == V2_COLUMNS:
        return V2_SCHEMA
    raise ValueError("unknown rent-panel schema contract")

V2_FEE = 0.003


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


def _capital_day(venue: str, day: str, capital_path: Path) -> pd.DataFrame:
    """Read only the accounting-capital partition needed by one output shard."""
    capital = pd.read_parquet(
        capital_path,
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
    capital_path: Path,
) -> pd.DataFrame:
    """Attach exact-day accounting capital without loading a venue-wide panel."""
    if frame.empty:
        return frame.reindex(columns=columns)
    panel = frame.copy()
    panel["pool"] = panel["pool"].str.lower()
    capital = _capital_day(venue, day, capital_path)
    merged = panel.merge(
        capital[["day", "pool", *CAPITAL_COLUMNS]],
        on=["day", "pool"],
        how="left",
        validate="one_to_one",
    )
    missing = merged["capital_source"].isna()
    if missing.any():
        contract = capital_contract(venue)
        merged.loc[missing, "reported_capital_source"] = "unavailable_missing_provider_pool_day"
        merged.loc[missing, "reserve_source"] = "unavailable_missing_provider_pool_day"
        merged.loc[missing, "reserve_validation_status"] = "unavailable_missing_provider_pool_day"
        merged.loc[missing, "capital_source"] = contract.capital_sources[0]
        merged.loc[missing, "price_source"] = "unavailable_missing_provider_pool_day"
        merged.loc[missing, "quantity_kind"] = "deposited_capital"
        merged.loc[missing, "pool_family"] = contract.pool_family
        merged.loc[missing, "invariant_family"] = contract.invariant_family
        merged.loc[missing, "state_generation"] = contract.state_generation
        merged.loc[missing, "capital_validation_status"] = "missing_pool_day_capital"
        merged.loc[missing, "failure_reason"] = "canonical state pool-day lacks provider capital"
        merged.loc[missing, "capital_valid"] = False
        merged.loc[missing, "exact_lag_valid"] = False
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


# ---------------------------------------------------------------------------
# Uniswap v2
# ---------------------------------------------------------------------------

def _v2_day(day: str, release: CPStateStreamSet) -> list[dict]:
    state = pd.DataFrame.from_records(release.read_day(day), columns=CP_COLUMNS)
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


def _build_v2_chunk(payload: dict[str, object]) -> tuple[int, int]:
    """Build independent V2 day shards inside one bounded worker."""
    cache_dir = Path(str(payload["cache_dir"]))
    release = payload["release"]
    if not isinstance(release, CPStateStreamSet) or release.kind != "event_stream":
        raise TypeError("V2 rent chunk requires a certified event-stream subset")
    capital_path = Path(str(payload["capital_path"]))
    built = rows = 0
    for day in payload["days"]:
        frame = pd.DataFrame.from_records(_v2_day(str(day), release)).reindex(columns=V2_BASE_COLUMNS)
        frame = _merge_capital_day(
            frame,
            venue="uniswap_v2",
            day=str(day),
            columns=V2_COLUMNS,
            capital_path=capital_path,
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
    release: CPStateStreamSet,
    capital_path: Path,
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
        [
            max(1, release.select_days((day,)).partitions[0].expected_rows)
            for day in pending
        ],
        workers,
    )
    payloads = [
        {
            "days": chunk,
            "cache_dir": str(cache_dir),
            "release": release.select_days(chunk),
            "capital_path": str(capital_path),
        }
        for chunk in chunks
    ]
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


def _generation_cache_dir(
    family: str,
    generation: str,
    *,
    root: Path = DAY_CACHE_ROOT,
) -> Path:
    return root / family / f"engine_{generation}"


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


def validate_v2_release_sources(
    state_release: CPStateStreamSet,
    event_source_release: V2EventSourceRelease,
    capital_release: CapitalRelease,
) -> None:
    """Reopen every selected pointer and reject a cross-generation install."""

    state_release.assert_current()
    reopened_event_source = resolve_v2_event_source_release(
        event_source_release.pointer_path
    )
    if reopened_event_source.generation_id != event_source_release.generation_id:
        raise RuntimeError("V2 event-source generation changed during rent build")
    reopened_capital = resolve_capital_release(capital_release.pointer_path)
    if reopened_capital.generation_id != capital_release.generation_id:
        raise RuntimeError("capital generation changed during rent build")


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
    release_identity: str | None = None,
    preinstall_validator: Callable[[Path], None] | None = None,
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
    with staged_output(output) as staged:
        result = assemble_parquet_shards(
            [_cache_path(cache_dir, day) for day in days],
            staged,
            progress=progress,
            unique_keys=UNIQUE_KEYS,
        )
        if cache_key(code_sources, inputs=release_inputs) != release_key:
            raise RuntimeError(f"{venue} release inputs or code changed during assembly")
        if preinstall_validator is not None:
            preinstall_validator(staged)
        notes = (
            f"generation {generation}; assembled {len(days)} validated day shards; "
            f"{result.shards} nonempty; {f'released-state identity {release_identity}; ' if release_identity else ''}resumable cache {cache_dir.name}"
        )
        publish_staged_artifact(
            staged,
            output,
            code_sources=code_sources,
            inputs=canonical_inputs,
            rows=result.rows,
            notes=notes,
            preinstall_validator=preinstall_validator,
        )
    print(f"{venue} pool-days: {result.rows:,}", flush=True)


def build_v2(
    *,
    workers: int,
    force: bool,
    capital_release: CapitalRelease | None = None,
    event_source_release: V2EventSourceRelease | None = None,
) -> None:
    selected_capital = capital_release or resolve_capital_release()
    reserve_authority = selected_capital.manifest["certified_reserve_stream"]["uniswap_v2"]
    days = [str(partition["day"]) for partition in reserve_authority["partitions"]]
    state_release = certified_cp_event_stream(
        "uniswap_v2",
        days,
        raw_root=RAW_ROOT,
    )
    selected_event_source = event_source_release or resolve_v2_event_source_release()
    capital_path = selected_capital.artifacts["pool"]
    if not days:
        raise RuntimeError("no certified Uniswap V2 event days")
    inputs = [
        *state_release.provenance_inputs,
        *selected_capital.lineage_paths,
        *selected_event_source.lineage_paths,
    ]
    generation = cache_key(V2_SHARD_CODE_SOURCES, inputs=inputs)
    cache_dir = _generation_cache_dir("v2", generation)
    _clean_interrupted_shard_temps(cache_dir)
    _build_v2_shards(days, cache_dir, release=state_release, capital_path=capital_path, workers=workers, force=force)
    _require_generation_current(
        generation,
        code_sources=V2_SHARD_CODE_SOURCES,
        inputs=inputs,
    )
    def validate_sources(_path: Path) -> None:
        validate_v2_release_sources(
            state_release, selected_event_source, selected_capital
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
        release_identity=state_release.content_identity_sha256,
        preinstall_validator=validate_sources,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("which", choices=("v2",), nargs="?", default="v2")
    parser.add_argument("--workers", type=int, default=DEFAULT_RENT_WORKERS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    workers = bounded_workers(args.workers, maximum=MAX_RENT_WORKERS)
    with exclusive_job(LOCK, job="rent-incidence analysis panels"):
        with exclusive_job(
            RAW_MARKET_DATA_LOCK,
            job="raw market-data fetch, enrichment, or canonical materialisation",
        ):
            capital_release = resolve_capital_release()
            event_source_release = resolve_v2_event_source_release()
            build_v2(
                workers=workers,
                force=args.force,
                capital_release=capital_release,
                event_source_release=event_source_release,
            )


if __name__ == "__main__":
    main()
