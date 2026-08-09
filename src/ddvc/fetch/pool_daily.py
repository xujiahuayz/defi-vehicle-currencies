"""Normalize provider pool-day capital records for canonical materialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source


@dataclass(frozen=True)
class PoolIdentity:
    """Immutable ordered token identity for one pool contract."""

    token0_address: str
    token0_symbol: str | None
    token1_address: str
    token1_symbol: str | None

@dataclass(frozen=True)
class PoolDailySchema:
    capital_field: str
    volume_field: str
    pool_container: str | None
    pool_id_field: str


POOL_DAILY_SCHEMAS: Mapping[str, PoolDailySchema] = {
    "uniswap_v2": PoolDailySchema("reserveUSD", "dailyVolumeUSD", None, "pairAddress"),
    "sushiswap_v2": PoolDailySchema("reserveUSD", "dailyVolumeUSD", None, "pairAddress"),
    "uniswap_v3": PoolDailySchema("tvlUSD", "volumeUSD", "pool", "id"),
    "uniswap_v4": PoolDailySchema("tvlUSD", "volumeUSD", "pool", "id"),
}

# Some legacy provider pool-day captures retained symbols but omitted addresses.
# A pool's ordered token addresses are immutable, so resolve them from a complete
# immutable event stream keyed by the exact pool contract. Never infer an address
# from a ticker. Other venues currently carry addresses on the pool-day row itself.
POOL_IDENTITY_STREAMS: Mapping[str, str] = {
    "uniswap_v2": "mints",
}

POOL_IDENTITY_STATIC_SNAPSHOTS: Mapping[str, str] = {
    "uniswap_v3": "uniswap_v3_pool_statics_20260630.jsonl.gz",
}


def expected_pool_daily_days(venue: str) -> tuple[str, ...]:
    """Exact research-calendar perimeter for one pool-day provider stream."""

    launch = get_source(venue).genesis.strftime("%Y%m%d")
    start = max(RESEARCH_SAMPLE_START, launch)
    return tuple(calendar_days(start, RESEARCH_SAMPLE_END))


def require_pool_daily_coverage(venue: str, files: list[Path]) -> None:
    """Reject a partial, duplicate, or out-of-perimeter raw pool-day source set."""

    expected = set(expected_pool_daily_days(venue))
    observed: list[str] = []
    prefix = f"{venue}_daily_"
    suffix = ".jsonl.gz"
    for path in files:
        name = path.name
        if not name.startswith(prefix) or not name.endswith(suffix):
            raise ValueError(f"unexpected {venue} pool-day filename: {name}")
        observed.append(name[len(prefix) : -len(suffix)])
    observed_set = set(observed)
    missing = sorted(expected - observed_set)
    unexpected = sorted(observed_set - expected)
    duplicates = len(observed) - len(observed_set)
    if missing or unexpected or duplicates:
        raise RuntimeError(
            f"{venue} pool-day coverage is incomplete; missing={len(missing)}, "
            f"unexpected={len(unexpected)}, duplicates={duplicates}, "
            f"first_missing={missing[0] if missing else 'none'}"
        )


def pool_identity_files(venue: str, raw_directory: Path) -> list[Path]:
    """Return the exact in-sample immutable identity perimeter for one venue."""

    static_name = POOL_IDENTITY_STATIC_SNAPSHOTS.get(venue)
    if static_name is not None:
        path = raw_directory / venue / static_name
        if not path.is_file():
            raise RuntimeError(f"{venue} pool-identity snapshot is missing: {path.name}")
        return [path]
    stream = POOL_IDENTITY_STREAMS.get(venue)
    if stream is None:
        return []
    directory = raw_directory / venue
    files = [directory / f"{venue}_{stream}_{day}.jsonl.gz" for day in expected_pool_daily_days(venue)]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(
            f"{venue} pool-identity coverage is incomplete; missing={len(missing)}, "
            f"first_missing={missing[0]}"
        )
    return files


def daily_pool_identity_perimeter(
    venue: str,
    files: list[Path],
) -> tuple[set[str], set[str]]:
    """Return all daily pools and those with at least one address-free row."""

    pools: set[str] = set()
    missing_identity: set[str] = set()
    for path in files:
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                normalized = pool_day_values(venue, record)
                if normalized is None:
                    continue
                pool = str(normalized["pool"])
                pools.add(pool)
                if not (
                    normalized["token0_address"]
                    and normalized["token1_address"]
                ):
                    missing_identity.add(pool)
    return pools, missing_identity


def pool_identity_values(record: Mapping[str, object]) -> tuple[str, PoolIdentity] | None:
    """Normalize a provider event's exact pool and ordered token identities."""

    container = record.get("pair") or record.get("pool") or record
    if not isinstance(container, Mapping):
        return None
    pool = str(container.get("id") or "").lower()
    token0_address, token0_symbol = _token_identity(record, container, "token0")
    token1_address, token1_symbol = _token_identity(record, container, "token1")
    if not pool or not token0_address or not token1_address:
        return None
    return pool, PoolIdentity(
        token0_address=token0_address,
        token0_symbol=token0_symbol,
        token1_address=token1_address,
        token1_symbol=token1_symbol,
    )


def load_pool_identity_crosswalk(files: list[Path]) -> dict[str, PoolIdentity]:
    """Build one conflict-free pool-address crosswalk from immutable events."""

    identities: dict[str, PoolIdentity] = {}
    for path in files:
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                resolved = pool_identity_values(record)
                if resolved is None:
                    continue
                pool, identity = resolved
                prior = identities.get(pool)
                if prior is not None and (
                    prior.token0_address != identity.token0_address
                    or prior.token1_address != identity.token1_address
                ):
                    raise ValueError(f"conflicting immutable token identities for pool {pool}")
                if prior is None:
                    identities[pool] = identity
    return identities


def apply_pool_identity(
    row: dict[str, object],
    identities: Mapping[str, PoolIdentity],
) -> dict[str, object]:
    """Fill omitted addresses by pool contract and reject any contradiction."""

    identity = identities.get(str(row["pool"]).lower())
    if identity is None:
        return row
    observed = (row.get("token0_address"), row.get("token1_address"))
    expected = (identity.token0_address, identity.token1_address)
    if any(observed) and observed != expected:
        raise ValueError(
            f"pool {row['pool']} daily tokens {observed} conflict with immutable identity {expected}"
        )
    return {
        **row,
        "token0_address": identity.token0_address,
        "token0_symbol": row.get("token0_symbol") or identity.token0_symbol,
        "token1_address": identity.token1_address,
        "token1_symbol": row.get("token1_symbol") or identity.token1_symbol,
    }


def finite_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if np.isfinite(parsed) else float("nan")


def _token_identity(
    record: Mapping[str, object],
    container: Mapping[str, object],
    side: str,
) -> tuple[str | None, str | None]:
    """Resolve a token contract and symbol from either provider record shape."""

    token = container.get(side) or record.get(side) or {}
    if not isinstance(token, Mapping):
        return None, None
    address = str(token.get("id") or "").lower()
    symbol = str(token.get("symbol") or "")
    return address or None, symbol or None


def pool_day_values(venue: str, record: Mapping[str, object]) -> dict[str, object] | None:
    """Normalize one supported raw daily record without changing its semantics."""

    spec = POOL_DAILY_SCHEMAS[venue]
    container = record.get(spec.pool_container, {}) if spec.pool_container else record
    if not isinstance(container, Mapping):
        return None
    pool = str(container.get(spec.pool_id_field) or record.get("id") or "").lower()
    if not pool:
        return None
    token0_address, token0_symbol = _token_identity(record, container, "token0")
    token1_address, token1_symbol = _token_identity(record, container, "token1")
    return {
        "pool": pool,
        "token0_address": token0_address,
        "token0_symbol": token0_symbol,
        "token1_address": token1_address,
        "token1_symbol": token1_symbol,
        "reported_capital_usd": finite_float(record.get(spec.capital_field)),
        "reported_volume_usd": finite_float(record.get(spec.volume_field)),
        "reported_fees_usd": finite_float(record.get("feesUSD")),
        "capital_source": f"{venue}.{spec.capital_field}",
    }


def read_pool_day_values(
    venue: str,
    raw_directory: Path,
    *,
    keep: set[str] | None = None,
) -> pd.DataFrame:
    """Read a venue's raw daily snapshots into one harmonized capital frame."""

    rows: list[dict[str, object]] = []
    pattern = f"{venue}_daily_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].jsonl.gz"
    for path in sorted(raw_directory.glob(pattern)):
        stamp = path.name.removesuffix(".jsonl.gz").rsplit("_", 1)[-1]
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                normalized = pool_day_values(venue, record)
                if normalized is None or (keep is not None and normalized["pool"] not in keep):
                    continue
                normalized["day"] = stamp
                rows.append(normalized)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    if result.duplicated(["day", "pool"]).any():
        raise ValueError(f"duplicate {venue} pool-day capital records")
    return result.sort_values(["pool", "day"]).reset_index(drop=True)
